#!/usr/bin/env python3
"""
NASA Database export for the PAQI AirVisual network.

Exposes:
  - GET /NasaDatabase/locations
  - GET /NasaDatabase/measurements

Assumptions:
  - The 210 PAQI network stations are exactly those with
      providers.display_name = 'Airvisual/PAQI'
    (change PROVIDER_DISPLAY_NAME below if needed).
  - readings.scope_type = 'station' and readings.scope_key = stations.station_id
    for station-level time-series.
"""

import secrets
from datetime import datetime
from typing import List, Optional, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_database


# ---------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------

async def verify_api_key(x_api_key: str = Header(..., description="API key for NASA Database access")):
    """Validate the X-API-Key header against the configured NASA_API_KEY."""
    if not settings.NASA_API_KEY:
        raise HTTPException(status_code=503, detail="NASA API key not configured on server")
    if not secrets.compare_digest(x_api_key, settings.NASA_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")


# How this network should appear to NASA Database
NETWORK_NAME = "PAQI AirVisual Network"
ORGANIZATION = "Pakistan Air Quality Initiative (PAQI)"
PROVIDER_LABEL = "PAQI"
HARDWARE_TYPE = "IQAir"

# How to identify the 210 PAQI stations in your DB
PROVIDER_DISPLAY_NAME = "Airvisual/PAQI"


# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------

class NasaLocation(BaseModel):
    location_id: str           # station_id
    location: str              # station name
    city: Optional[str]
    country: str               # ISO-2, e.g. "PK"
    lat: float
    lon: float
    timezone: Optional[str]
    provider: str              # "PAQI"
    network: str               # "PAQI AirVisual Network"
    hardware: Optional[str]    # "IQAir"


class NasaLocationsResponse(BaseModel):
    meta: dict
    results: List[NasaLocation]


class NasaMeasurement(BaseModel):
    location_id: str
    location: str
    parameter: Literal["pm25", "pm10", "no2", "so2", "o3", "co"]
    value: float
    unit: str
    datetime: str
    lat: float
    lon: float
    city: Optional[str]
    country: str
    provider: str              # "PAQI"
    network: str               # "PAQI AirVisual Network"


class NasaMeasurementsResponse(BaseModel):
    meta: dict
    results: List[NasaMeasurement]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _parse_iso8601_optional(value: Optional[str]) -> Optional[datetime]:
    """Parse an optional ISO-8601 string (with or without trailing Z)."""
    if not value:
        return None
    # Accept both "...Z" and "+00:00" etc.
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {value}") from exc


# Pollutants to export and their units.
POLLUTANTS = [
    ("pm25", "µg/m³"),
    ("pm10", "µg/m³"),
    ("no2", "ppb"),
    ("so2", "ppb"),
    ("o3",  "ppb"),
    ("co",  "ppm"),
]


router = APIRouter(prefix="/NasaDatabase", tags=["NasaDatabase"], dependencies=[Depends(verify_api_key)])


# ---------------------------------------------------------------------
# /NasaDatabase/locations
# ---------------------------------------------------------------------

@router.get("/locations", response_model=NasaLocationsResponse)
async def list_locations(db: AsyncSession = Depends(get_database)):
    """
    List all locations in the PAQI AirVisual Network (210 IQAir devices).
    Filters strictly to provider display_name = 'Airvisual/PAQI'.
    """
    sql = text(
        """
        SELECT
          s.station_id,
          s.name AS station_name,
          c.name AS city_name,
          co.iso2 AS country_code,
          s.lat,
          s.lon,
          COALESCE(s.timezone, 'Asia/Karachi') AS timezone
        FROM stations s
        JOIN providers p   ON s.provider_id = p.id
        LEFT JOIN cities c ON c.id = s.city_id
        JOIN countries co  ON co.id = s.country_id
        WHERE p.display_name = :provider_display_name
          AND s.active = TRUE
        ORDER BY s.station_id;
        """
    )

    result = await db.execute(sql, {"provider_display_name": PROVIDER_DISPLAY_NAME})
    rows = result.mappings().all()

    locations = [
        NasaLocation(
            location_id=row["station_id"].strip() if isinstance(row["station_id"], str) else row["station_id"],
            location=row["station_name"],
            city=row["city_name"],
            country=row["country_code"],
            lat=row["lat"],
            lon=row["lon"],
            timezone=row["timezone"],
            provider=PROVIDER_LABEL,
            network=NETWORK_NAME,
            hardware=HARDWARE_TYPE,
        )
        for row in rows
    ]

    return NasaLocationsResponse(
        meta={
            "provider": PROVIDER_LABEL,
            "network": NETWORK_NAME,
            "organization": ORGANIZATION,
            "generated": datetime.utcnow().isoformat() + "Z",
            "count": len(locations),
        },
        results=locations,
    )


# ---------------------------------------------------------------------
# /NasaDatabase/measurements
# ---------------------------------------------------------------------

@router.get("/measurements", response_model=NasaMeasurementsResponse)
async def list_measurements(
    db: AsyncSession = Depends(get_database),
    datetime_from: Optional[str] = Query(
        None,
        description="ISO-8601 start time (inclusive), e.g. 2025-11-13T00:00:00Z",
    ),
    datetime_to: Optional[str] = Query(
        None,
        description="ISO-8601 end time (exclusive), e.g. 2025-11-14T00:00:00Z",
    ),
    limit: int = Query(
        1000,
        ge=1,
        le=10000,
        description="Maximum number of rows to fetch from DB before flattening.",
    ),
):
    """
    List measurements for all PAQI AirVisual stations (flattened per pollutant).

    Note:
    - Filters to provider display_name = 'Airvisual/PAQI'.
    - Returns one JSON object per (station, timestamp, pollutant).
    - Use datetime_from / datetime_to to page through time.
    """
    dt_from = _parse_iso8601_optional(datetime_from)
    dt_to = _parse_iso8601_optional(datetime_to)

    sql = """
        SELECT
          r.ts_utc,
          r.pm25, r.pm10, r.no2, r.so2, r.o3, r.co,
          s.station_id,
          s.name      AS station_name,
          s.lat,
          s.lon,
          c.name      AS city_name,
          co.iso2     AS country_code
        FROM readings r
        JOIN stations s    ON r.scope_type = 'station'
                          AND r.scope_key  = s.station_id
        JOIN providers p   ON s.provider_id = p.id
        LEFT JOIN cities c ON c.id = s.city_id
        JOIN countries co  ON co.id = s.country_id
        WHERE p.display_name = :provider_display_name
    """

    params = {"provider_display_name": PROVIDER_DISPLAY_NAME}

    if dt_from is not None:
        sql += " AND r.ts_utc >= :dt_from"
        params["dt_from"] = dt_from
    if dt_to is not None:
        sql += " AND r.ts_utc < :dt_to"
        params["dt_to"] = dt_to

    sql += " ORDER BY r.ts_utc DESC LIMIT :limit"
    params["limit"] = limit

    result = await db.execute(text(sql), params)
    rows = result.mappings().all()

    measurements: List[NasaMeasurement] = []

    for row in rows:
        ts_utc: datetime = row["ts_utc"]
        ts_iso = ts_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")

        station_id_raw = row["station_id"]
        station_id = station_id_raw.strip() if isinstance(station_id_raw, str) else station_id_raw

        for param, unit in POLLUTANTS:
            val = row.get(param)
            if val is None:
                continue
            measurements.append(
                NasaMeasurement(
                    location_id=station_id,
                    location=row["station_name"],
                    parameter=param,   # type: ignore[arg-type]
                    value=float(val),
                    unit=unit,
                    datetime=ts_iso,
                    lat=row["lat"],
                    lon=row["lon"],
                    city=row["city_name"],
                    country=row["country_code"],
                    provider=PROVIDER_LABEL,
                    network=NETWORK_NAME,
                )
            )

    return NasaMeasurementsResponse(
        meta={
            "provider": PROVIDER_LABEL,
            "network": NETWORK_NAME,
            "organization": ORGANIZATION,
            "generated": datetime.utcnow().isoformat() + "Z",
            "rows_from_db": len(rows),
            "measurements": len(measurements),
        },
        results=measurements,
    )
