#!/usr/bin/env python3
"""
OpenAQ export for the PAQI network.

Exposes:
  - GET /openaq/locations
  - GET /openaq/measurements

Membership is explicit: stations with metadata_json.export.openaq = true
(db_schema/oneoff/2026-10_export_membership.sql), never a provider display
name. Hardware comes from stations.metadata_json.hardware when attested
(otherwise "unknown"); units come from readings.units_* (otherwise "unknown").
Anything that originated from OpenAQ is excluded so imported data is never
exported back. Measurements page by a (ts_utc, scope_key) keyset cursor so
tied timestamps are never lost or duplicated.
"""

from datetime import datetime, timezone
from typing import List, Optional, Literal

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database
from app.ingestion.export_membership import (CURSOR_WHERE, KEYSET_ORDER, MEMBERSHIP_WHERE, POLLUTANT_PARAMS,
                                             READINGS_NOT_OPENAQ, decode_cursor, hardware_label, next_cursor,
                                             unit_or_unknown)

# How this network should appear to OpenAQ
NETWORK_NAME = "PAQI"
ORGANIZATION = "South Asia Air Quality Initiative (PAQI)"
PROVIDER_LABEL = "PAQI"


# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------

class OpenAQLocation(BaseModel):
    location_id: str           # station_id
    location: str              # station name
    city: Optional[str]
    country: Optional[str]      # ISO-2 when known; a country row without iso2 must not break the export
    lat: float
    lon: float
    timezone: Optional[str]
    provider: str              # "PAQI"
    network: str               # "PAQI"
    hardware: Optional[str]    # attested hardware or "unknown"


class OpenAQLocationsResponse(BaseModel):
    meta: dict
    results: List[OpenAQLocation]


class OpenAQMeasurement(BaseModel):
    location_id: str
    location: str
    parameter: Literal["pm25", "pm10", "no2", "so2", "o3", "co"]
    value: float
    unit: str
    datetime: str
    lat: float
    lon: float
    city: Optional[str]
    country: Optional[str]      # ISO-2 when known; a country row without iso2 must not break the export
    provider: str              # "PAQI"
    network: str               # "PAQI"


class OpenAQMeasurementsResponse(BaseModel):
    meta: dict
    results: List[OpenAQMeasurement]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _parse_iso8601_optional(value: Optional[str]) -> Optional[datetime]:
    """Parse an optional ISO-8601 string (with or without trailing Z)."""
    if not value:
        return None
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {value}") from exc


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sid(raw) -> str:
    return raw.strip() if isinstance(raw, str) else raw


router = APIRouter(prefix="/openaq", tags=["OpenAQ"])


# ---------------------------------------------------------------------
# /openaq/locations
# ---------------------------------------------------------------------

LOCATIONS_SQL = f"""
    SELECT
      s.station_id,
      s.name AS station_name,
      c.name AS city_name,
      co.iso2 AS country_code,
      s.lat,
      s.lon,
      COALESCE(s.timezone, 'Asia/Karachi') AS timezone,
      s.metadata_json
    FROM stations s
    JOIN providers p   ON s.provider_id = p.id
    LEFT JOIN cities c ON c.id = s.city_id
    JOIN countries co  ON co.id = s.country_id
    WHERE {MEMBERSHIP_WHERE}
      AND s.active = TRUE
    ORDER BY s.station_id
"""


@router.get("/locations", response_model=OpenAQLocationsResponse)
async def list_locations(db: AsyncSession = Depends(get_database)):
    """List the stations marked for export (metadata_json.export.openaq = true)."""
    rows = (await db.execute(text(LOCATIONS_SQL))).mappings().all()
    locations = [
        OpenAQLocation(
            location_id=_sid(row["station_id"]),
            location=row["station_name"],
            city=row["city_name"],
            country=row["country_code"],
            lat=row["lat"],
            lon=row["lon"],
            timezone=row["timezone"],
            provider=PROVIDER_LABEL,
            network=NETWORK_NAME,
            hardware=hardware_label(row["metadata_json"]),
        )
        for row in rows
    ]
    return OpenAQLocationsResponse(
        meta={"provider": PROVIDER_LABEL, "network": NETWORK_NAME, "organization": ORGANIZATION,
              "generated": _now_z(), "count": len(locations)},
        results=locations,
    )


# ---------------------------------------------------------------------
# /openaq/measurements
# ---------------------------------------------------------------------

MEASUREMENTS_SQL = f"""
    SELECT
      r.ts_utc,
      r.scope_key,
      r.pm25, r.pm10, r.no2, r.so2, r.o3, r.co,
      r.units_pm25, r.units_pm10, r.units_no2, r.units_so2, r.units_o3, r.units_co,
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
    WHERE {MEMBERSHIP_WHERE}
      {READINGS_NOT_OPENAQ}
"""


@router.get("/measurements", response_model=OpenAQMeasurementsResponse)
async def list_measurements(
    db: AsyncSession = Depends(get_database),
    datetime_from: Optional[str] = Query(None, description="ISO-8601 start time (inclusive), e.g. 2025-11-13T00:00:00Z"),
    datetime_to: Optional[str] = Query(None, description="ISO-8601 end time (exclusive), e.g. 2025-11-14T00:00:00Z"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of DB rows per page (each row flattens to ≤ 6 measurements)."),
    cursor: Optional[str] = Query(None, description="Opaque keyset cursor from meta.next_cursor of the previous page."),
):
    """
    Measurements for exported stations, one object per (station, timestamp, pollutant).
    Page with `cursor` (meta.next_cursor); pages are ordered by (ts_utc DESC, station DESC)
    so stations sharing a timestamp are never lost at a page boundary.
    """
    dt_from = _parse_iso8601_optional(datetime_from)
    dt_to = _parse_iso8601_optional(datetime_to)
    after = decode_cursor(cursor)

    sql = MEASUREMENTS_SQL
    params: dict = {"limit": limit}
    if dt_from is not None:
        sql += " AND r.ts_utc >= :dt_from"
        params["dt_from"] = dt_from
    if dt_to is not None:
        sql += " AND r.ts_utc < :dt_to"
        params["dt_to"] = dt_to
    if after is not None:
        sql += CURSOR_WHERE
        params["c_ts"], params["c_key"] = after
    sql += KEYSET_ORDER

    rows = (await db.execute(text(sql), params)).mappings().all()

    measurements: List[OpenAQMeasurement] = []
    for row in rows:
        ts_utc: datetime = row["ts_utc"]
        ts_iso = ts_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        station_id = _sid(row["station_id"])
        for param in POLLUTANT_PARAMS:
            val = row.get(param)
            if val is None:
                continue
            measurements.append(OpenAQMeasurement(
                location_id=station_id, location=row["station_name"], parameter=param,  # type: ignore[arg-type]
                value=float(val), unit=unit_or_unknown(row, param), datetime=ts_iso,
                lat=row["lat"], lon=row["lon"], city=row["city_name"], country=row["country_code"],
                provider=PROVIDER_LABEL, network=NETWORK_NAME,
            ))

    return OpenAQMeasurementsResponse(
        meta={
            "provider": PROVIDER_LABEL, "network": NETWORK_NAME, "organization": ORGANIZATION,
            "generated": _now_z(), "rows_from_db": len(rows), "measurements": len(measurements),
            "limit": limit, "next_cursor": next_cursor(rows, limit),
        },
        results=measurements,
    )
