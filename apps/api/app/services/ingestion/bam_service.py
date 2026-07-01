"""BAM (SFL reference monitor) push-ingest service.

Mirrors the Punjab EPA ingestion pattern (see epa_service.py): resolve a
provider, upsert a station, upsert a reading — all as raw-SQL upserts into the
existing schema. No DDL. BAM readings arrive one-at-a-time over HTTPS from
SFL's MQTT→HTTP bridge rather than being polled.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Pakistan country id (same value epa_service uses for its stations).
COUNTRY_ID_PK = 1
DEFAULT_TZ = "Asia/Karachi"

# 16-point compass → degrees, for the string wind_dir the BAM sends (e.g. "W").
WIND_DIR_DEG = {
    "N": 0, "NNE": 23, "NE": 45, "ENE": 68,
    "E": 90, "ESE": 113, "SE": 135, "SSE": 158,
    "S": 180, "SSW": 203, "SW": 225, "WSW": 248,
    "W": 270, "WNW": 293, "NW": 315, "NNW": 338,
}

# EPA 2024 PM2.5 breakpoints (µg/m³) → US AQI, matching punjab_epa.py.
PM25_BPTS = [
    (0.0, 9.0, 0, 50),
    (9.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 125.4, 151, 200),
    (125.5, 225.4, 201, 300),
    (225.5, 500.4, 301, 500),
]


def station_id_for_bam(device_id: str) -> str:
    """Deterministic, DB-safe station id (char(16)) derived from the device id."""
    digest = hashlib.sha256(f"bam:{device_id}".encode()).hexdigest()
    return f"bam_{digest[:12]}"


def wind_dir_to_deg(wind_dir: Optional[str]) -> Optional[int]:
    if not wind_dir:
        return None
    return WIND_DIR_DEG.get(wind_dir.strip().upper())


def pm25_to_aqi_us(pm25: Optional[float]) -> Optional[int]:
    """US AQI from a single PM2.5 concentration (µg/m³), EPA piecewise-linear."""
    if pm25 is None:
        return None
    # EPA truncates PM2.5 to 1 decimal before mapping.
    c = int(float(pm25) * 10) / 10.0
    for lo, hi, ilo, ihi in PM25_BPTS:
        if lo <= c <= hi:
            return round((ihi - ilo) / (hi - lo) * (c - lo) + ilo)
    return None


async def ensure_bam_provider(db: AsyncSession) -> int:
    """SELECT-first (avoids burning the SMALLSERIAL providers_id_seq) then INSERT."""
    result = await db.execute(text("SELECT id FROM providers WHERE code='bam'"))
    pid = result.scalar()
    if pid is None:
        result = await db.execute(text("""
            INSERT INTO providers (code, display_name, active)
            VALUES ('bam', 'SFL BAM Network', true)
            RETURNING id
        """))
        pid = result.scalar_one()
        await db.commit()
    return int(pid)


async def upsert_bam_station(
    db: AsyncSession, *, provider_id: int, source_station_id: str,
    name: str, lat: float, lon: float, tz: str = DEFAULT_TZ,
) -> str:
    station_id = station_id_for_bam(source_station_id)
    await db.execute(text("""
        INSERT INTO stations (
          station_id, country_id, name, lat, lon,
          provider_id, source_station_id, timezone, monitor_type, active
        )
        VALUES (
          :station_id, :country_id, :name, :lat, :lon,
          :provider_id, :source_station_id, :tz, 'BAM', true
        )
        ON CONFLICT (provider_id, source_station_id) DO UPDATE
        SET name=EXCLUDED.name, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
            monitor_type='BAM', active=true, station_id=EXCLUDED.station_id
    """), dict(
        station_id=station_id, country_id=COUNTRY_ID_PK, name=name,
        lat=lat, lon=lon, provider_id=provider_id,
        source_station_id=source_station_id, tz=tz,
    ))
    await db.commit()
    return station_id


async def upsert_bam_reading(
    db: AsyncSession, *, station_id: str, ts_utc: datetime,
    pm25: Any, temp_c: Any, humidity: Any, pressure_hpa: Any,
    wind_speed_ms: Any, wind_dir_deg: Any, aqi_us: Any, raw: Dict[str, Any],
):
    await db.execute(text("""
        INSERT INTO readings (
          scope_type, scope_key, ts_utc,
          pm25, temp_c, humidity, pressure_hpa,
          wind_speed_ms, wind_dir_deg, aqi_us,
          raw, source, ingested_at
        )
        VALUES (
          'station', :scope_key, :ts_utc,
          :pm25, :temp_c, :humidity, :pressure_hpa,
          :wind_speed_ms, :wind_dir_deg, :aqi_us,
          CAST(:raw AS jsonb), 'bam', now()
        )
        ON CONFLICT (scope_type, scope_key, ts_utc) DO UPDATE
        SET pm25=EXCLUDED.pm25, temp_c=EXCLUDED.temp_c, humidity=EXCLUDED.humidity,
            pressure_hpa=EXCLUDED.pressure_hpa, wind_speed_ms=EXCLUDED.wind_speed_ms,
            wind_dir_deg=EXCLUDED.wind_dir_deg, aqi_us=EXCLUDED.aqi_us,
            raw = COALESCE(readings.raw, '{}'::jsonb) || EXCLUDED.raw,
            source='bam'
    """), dict(
        scope_key=station_id, ts_utc=ts_utc,
        pm25=pm25, temp_c=temp_c, humidity=humidity, pressure_hpa=pressure_hpa,
        wind_speed_ms=wind_speed_ms, wind_dir_deg=wind_dir_deg, aqi_us=aqi_us,
        raw=json.dumps(raw),
    ))
    await db.commit()
