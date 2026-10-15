#!/usr/bin/env python3
"""
Public API endpoints with API key authentication.

Exposes:
  - GET /api/v1/public/locations
  - GET /api/v1/public/measurements

Requirements:
  - API key authentication required
  - Only data from January 1, 2025 onwards is accessible
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Literal

from fastapi import APIRouter, HTTPException, Query, Depends, Header, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database
from app.core.config import settings
from app.services.ingestion.bam_service import pm25_to_aqi_us

# How this network should appear to OpenAQ
NETWORK_NAME = "PAQI"
ORGANIZATION = "South Asia Air Quality Initiative (PAQI)"
PROVIDER_LABEL = "PAQI"
HARDWARE_TYPE = "IQAIR Airvisual Outdoor"

# How to identify the 210 PAQI stations in your DB
PROVIDER_DISPLAY_NAME = "Airvisual/PAQI"

# Date cutoff - only data from this date onwards is accessible
DATA_CUTOFF_DATE = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Rate limiting (per API key, falling back to client IP)
# ---------------------------------------------------------------------

def _rate_limit_key(request: Request) -> str:
    """Rate-limit bucket: the API key if present, else the client IP."""
    return request.headers.get("x-api-key") or get_remote_address(request)


# Shared limiter instance; registered on the app in main.py.
# Best-effort per-instance on Cloud Run (multiple instances don't share state);
# REDIS_URL-backed storage can be added later if partner traffic grows.
limiter = Limiter(key_func=_rate_limit_key)
PUBLIC_RATE_LIMIT = f"{settings.RATE_LIMIT_PER_MINUTE}/minute"

# Get API secret from settings
PUBLIC_API_SECRET = settings.PUBLIC_API_SECRET


def _load_partner_keys() -> dict:
    """
    Build the {api_key: partner_name} map from settings.

    Sources:
      - PARTNER_API_KEYS: JSON object mapping key -> partner name (preferred).
      - PUBLIC_API_SECRET: legacy single shared key, kept for backward compat
        and labelled "legacy".
    """
    keys: dict = {}
    raw = settings.PARTNER_API_KEYS
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                keys.update({str(k): str(v) for k, v in parsed.items()})
            else:
                logging.warning("PARTNER_API_KEYS is not a JSON object — ignoring")
        except json.JSONDecodeError:
            logging.warning("PARTNER_API_KEYS is not valid JSON — ignoring")
    if PUBLIC_API_SECRET:
        keys.setdefault(PUBLIC_API_SECRET, "legacy")
    return keys


PARTNER_KEYS = _load_partner_keys()
if not PARTNER_KEYS:
    logging.warning(
        "No public API keys configured (PARTNER_API_KEYS / PUBLIC_API_SECRET) — "
        "public API endpoints will reject all requests"
    )


# ---------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------

def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """
    Verify the X-API-Key header against the configured partner keys using
    constant-time comparison, and return the resolved partner name.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header."
        )

    if not PARTNER_KEYS:
        # Deliberately indistinguishable from a bad key: don't reveal
        # server-side configuration state to anonymous callers.
        raise HTTPException(
            status_code=401,
            detail="Invalid API key."
        )

    # Constant-time compare against every known key so a mismatch does not
    # leak timing about which (if any) key it was close to.
    matched_partner: Optional[str] = None
    for known_key, partner in PARTNER_KEYS.items():
        if secrets.compare_digest(x_api_key, known_key):
            matched_partner = partner

    if matched_partner is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key."
        )

    logger.info("public_api_request partner=%s", matched_partner)
    return matched_partner


# ---------------------------------------------------------------------
# Pydantic models (same as openaq_network.py)
# ---------------------------------------------------------------------

class OpenAQLocation(BaseModel):
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
    country: str
    provider: str              # "PAQI"
    network: str               # "PAQI AirVisual Network"


class OpenAQMeasurementsResponse(BaseModel):
    meta: dict
    results: List[OpenAQMeasurement]


class CurrentStation(BaseModel):
    location_id: str
    location: str              # station name
    city: Optional[str]
    country: str               # ISO-2, e.g. "PK"
    lat: float
    lon: float
    aqi_us: Optional[int]      # US AQI computed from PM2.5 (EPA breakpoints)
    aqi_category: str          # Good / Moderate / Unhealthy … (US EPA bands)
    pm25: Optional[float]      # µg/m³
    pm10: Optional[float]      # µg/m³ (not reported by this network — currently always null)
    datetime: str              # ISO-8601 UTC of the reading
    distance_km: Optional[float] = None  # only set for lat/lon lookups


class CurrentResponse(BaseModel):
    meta: dict
    results: List[CurrentStation]


# US EPA AQI category bands (mirrors punjab_epa.py:_aqi_category).
AQI_CATEGORIES = [
    (0, 50,   "Good"),
    (51, 100, "Moderate"),
    (101, 150, "Unhealthy for Sensitive Groups"),
    (151, 200, "Unhealthy"),
    (201, 300, "Very Unhealthy"),
    (301, 500, "Hazardous"),
]


def _aqi_category(aqi: Optional[int]) -> str:
    if aqi is None:
        return "Unknown"
    for lo, hi, name in AQI_CATEGORIES:
        if lo <= aqi <= hi:
            return name
    return "Beyond Index"


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


def _enforce_date_cutoff(dt_from: Optional[datetime], dt_to: Optional[datetime]):
    """Enforce that queried date range is not before January 1, 2025."""
    # Reject any request trying to access data before cutoff
    if dt_from is not None and dt_from < DATA_CUTOFF_DATE:
        raise HTTPException(
            status_code=403,
            detail=f"Access to data before {DATA_CUTOFF_DATE.strftime('%Y-%m-%d')} is not permitted."
        )
    
    if dt_to is not None and dt_to < DATA_CUTOFF_DATE:
        raise HTTPException(
            status_code=403,
            detail=f"Access to data before {DATA_CUTOFF_DATE.strftime('%Y-%m-%d')} is not permitted."
        )
    
    # If no date range specified, default to cutoff date
    if dt_from is None:
        dt_from = DATA_CUTOFF_DATE
    
    return dt_from, dt_to


# Pollutants to export and their units.
POLLUTANTS = [
    ("pm25", "µg/m³"),
    ("pm10", "µg/m³"),
    ("no2", "ppb"),
    ("so2", "ppb"),
    ("o3",  "ppb"),
    ("co",  "ppm"),
]


router = APIRouter(prefix="/public", tags=["public"])


# ---------------------------------------------------------------------
# /api/v1/public/locations
# ---------------------------------------------------------------------

@router.get("/locations", response_model=OpenAQLocationsResponse)
@limiter.limit(PUBLIC_RATE_LIMIT)
async def list_locations(
    request: Request,
    db: AsyncSession = Depends(get_database),
    partner: str = Depends(verify_api_key)
):
    """
    List all locations in the PAQI AirVisual Network (210 IQAir devices).
    Requires API key authentication.
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
        OpenAQLocation(
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

    return OpenAQLocationsResponse(
        meta={
            "provider": PROVIDER_LABEL,
            "network": NETWORK_NAME,
            "organization": ORGANIZATION,
            "generated": datetime.utcnow().isoformat() + "Z",
            "count": len(locations),
            "data_available_from": DATA_CUTOFF_DATE.strftime('%Y-%m-%d'),
        },
        results=locations,
    )


# ---------------------------------------------------------------------
# /api/v1/public/measurements
# ---------------------------------------------------------------------

@router.get("/measurements", response_model=OpenAQMeasurementsResponse)
@limiter.limit(PUBLIC_RATE_LIMIT)
async def list_measurements(
    request: Request,
    db: AsyncSession = Depends(get_database),
    partner: str = Depends(verify_api_key),
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
    Requires API key authentication.
    Only returns data from January 1, 2025 onwards.

    Note:
    - Filters to provider display_name = 'Airvisual/PAQI'.
    - Returns one JSON object per (station, timestamp, pollutant).
    - Use datetime_from / datetime_to to page through time.
    """
    dt_from = _parse_iso8601_optional(datetime_from)
    dt_to = _parse_iso8601_optional(datetime_to)
    
    # Enforce date cutoff
    dt_from, dt_to = _enforce_date_cutoff(dt_from, dt_to)

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
          AND r.ts_utc >= :cutoff_date
    """

    params = {
        "provider_display_name": PROVIDER_DISPLAY_NAME,
        "cutoff_date": DATA_CUTOFF_DATE
    }

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

    measurements: List[OpenAQMeasurement] = []

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
                OpenAQMeasurement(
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

    return OpenAQMeasurementsResponse(
        meta={
            "provider": PROVIDER_LABEL,
            "network": NETWORK_NAME,
            "organization": ORGANIZATION,
            "generated": datetime.utcnow().isoformat() + "Z",
            "rows_from_db": len(rows),
            "measurements": len(measurements),
            "data_available_from": DATA_CUTOFF_DATE.strftime('%Y-%m-%d'),
        },
        results=measurements,
    )


# ---------------------------------------------------------------------
# /api/v1/public/current
# ---------------------------------------------------------------------

@router.get("/current", response_model=CurrentResponse)
@limiter.limit(PUBLIC_RATE_LIMIT)
async def current_conditions(
    request: Request,
    db: AsyncSession = Depends(get_database),
    partner: str = Depends(verify_api_key),
    city: Optional[str] = Query(
        None,
        description="Filter to a single city by name (case-insensitive), e.g. Lahore.",
        example="Lahore",
    ),
    lat: Optional[float] = Query(
        None, ge=-90, le=90,
        description="Latitude for a nearest-station lookup. Requires lon.",
        example=31.5204,
    ),
    lon: Optional[float] = Query(
        None, ge=-180, le=180,
        description="Longitude for a nearest-station lookup. Requires lat.",
        example=74.3587,
    ),
    radius_km: float = Query(
        25.0, ge=1.0, le=300.0,
        description="Search radius in km for lat/lon lookups.",
        example=25.0,
    ),
    limit: int = Query(
        100, ge=1, le=1000,
        description="Max stations to return (applies to nearest lookups).",
    ),
):
    """
    Latest current conditions for PAQI AirVisual stations, with a **computed
    US AQI** value and category alongside PM2.5 / PM10.

    Requires an `X-API-Key` header. Three lookup modes:

    - `?city=Lahore` — all active stations in a city.
    - `?lat=31.52&lon=74.36&radius_km=25` — nearest stations within a radius.
    - no filter — every active PAQI station.

    Each result carries `aqi_us`, `aqi_category`, `pm25`, `pm10`, `lat`, `lon`,
    `city`, and the reading `datetime` (UTC). Use `/api/v1/meta/cities` for the
    list of valid city names.
    """
    if (lat is None) != (lon is None):
        raise HTTPException(
            status_code=400,
            detail="Both lat and lon are required for a coordinate lookup.",
        )

    # Latest PM2.5-bearing reading per active PAQI station.
    # - Time floor (24h) keeps "current" honest and lets TimescaleDB
    #   chunk-prune the scan instead of walking each station's full history.
    # - pm25 IS NOT NULL skips placeholder/weather-only rows so we return a
    #   usable reading (this network stores pm25; pm10/gases are not populated).
    base_sql = """
        WITH latest AS (
          SELECT DISTINCT ON (s.station_id)
            s.station_id,
            s.name    AS station_name,
            c.name    AS city_name,
            co.iso2   AS country_code,
            s.lat,
            s.lon,
            r.ts_utc,
            r.pm25,
            r.pm10
          FROM stations s
          JOIN providers p   ON s.provider_id = p.id
          LEFT JOIN cities c ON c.id = s.city_id
          JOIN countries co  ON co.id = s.country_id
          JOIN readings r    ON r.scope_type = 'station'
                            AND r.scope_key  = s.station_id
          WHERE p.display_name = :provider_display_name
            AND s.active = TRUE
            AND r.ts_utc >= NOW() - INTERVAL '24 hours'
            AND r.pm25 IS NOT NULL
          ORDER BY s.station_id, r.ts_utc DESC
        )
    """

    params: dict = {"provider_display_name": PROVIDER_DISPLAY_NAME}

    if lat is not None and lon is not None:
        # Haversine distance in km; filter by radius, order nearest-first.
        distance_expr = (
            "6371 * acos(least(1, greatest(-1, "
            "cos(radians(:lat)) * cos(radians(lat)) * cos(radians(lon) - radians(:lon)) "
            "+ sin(radians(:lat)) * sin(radians(lat)))))"
        )
        # Wrap so the haversine is evaluated once per row, not twice.
        sql = base_sql + f"""
            SELECT * FROM (
              SELECT *, {distance_expr} AS distance_km
              FROM latest
            ) with_distance
            WHERE distance_km <= :radius_km
            ORDER BY distance_km ASC
            LIMIT :limit
        """
        params.update({"lat": lat, "lon": lon, "radius_km": radius_km, "limit": limit})
    elif city is not None:
        sql = base_sql + """
            SELECT *, NULL AS distance_km
            FROM latest
            WHERE city_name ILIKE :city
            ORDER BY station_name
        """
        params["city"] = city
    else:
        sql = base_sql + """
            SELECT *, NULL AS distance_km
            FROM latest
            ORDER BY station_name
        """

    result = await db.execute(text(sql), params)
    rows = result.mappings().all()

    stations: List[CurrentStation] = []
    for row in rows:
        ts_utc: datetime = row["ts_utc"]
        ts_iso = ts_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")

        station_id_raw = row["station_id"]
        station_id = station_id_raw.strip() if isinstance(station_id_raw, str) else station_id_raw

        pm25_val = float(row["pm25"]) if row["pm25"] is not None else None
        aqi_val = pm25_to_aqi_us(pm25_val)
        dist = row["distance_km"]

        stations.append(
            CurrentStation(
                location_id=station_id,
                location=row["station_name"],
                city=row["city_name"],
                country=row["country_code"],
                lat=row["lat"],
                lon=row["lon"],
                aqi_us=aqi_val,
                aqi_category=_aqi_category(aqi_val),
                pm25=pm25_val,
                pm10=float(row["pm10"]) if row["pm10"] is not None else None,
                datetime=ts_iso,
                distance_km=round(float(dist), 2) if dist is not None else None,
            )
        )

    return CurrentResponse(
        meta={
            "provider": PROVIDER_LABEL,
            "network": NETWORK_NAME,
            "organization": ORGANIZATION,
            "generated": datetime.utcnow().isoformat() + "Z",
            "count": len(stations),
            "aqi_standard": "US EPA",
        },
        results=stations,
    )