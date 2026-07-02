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

# ---- QC thresholds (reuse the values from exports_publish._apply_hourly_qc) ----
PM25_ABS_MAX = 1000.0                    # hard ceiling; above → INVALID
PM25_SENTINELS = {999.0, 1000.0, -1.0}   # known cap / error codes from LCS/BAM feeds
FLOW_TARGET_LPM = 16.7                    # BAM-1020 nominal sample flow (L/min)
FLOW_TOL_FRAC = 0.10                      # ±10% → flow_oor (mass measurement suspect)
HIGH_RH_PCT = 90.0                        # above → PM may over-read (informational)
# Physical sanity bounds for the met channels (out-of-range → informational flag).
TEMP_MIN_C, TEMP_MAX_C = -60.0, 80.0
PRESSURE_MIN_KPA, PRESSURE_MAX_KPA = 50.0, 120.0
WIND_MIN_MS, WIND_MAX_MS = 0.0, 150.0
HUMIDITY_MIN, HUMIDITY_MAX = 0.0, 100.0


def evaluate_bam_qc(
    *, pm25: Optional[float], humidity: Optional[float], temperature: Optional[float],
    pressure_kpa: Optional[float], wind_speed: Optional[float], flow: Optional[float],
):
    """Classify a single BAM reading.

    Returns (qc_state, qc_flags, detail):
      - qc_state 'INVALID'  → PM2.5 itself is untrustworthy (missing/sentinel/out-of-range).
      - qc_state 'SUSPECT'  → instrument health compromises the reading (flow out of tolerance).
      - qc_state 'OK'       → usable; qc_flags may still carry informational notes (e.g. high_rh).
    Only OK readings are shown on the public map (see dashboard.get_stations_for_map).
    """
    flags: list[str] = []
    detail: Dict[str, Any] = {}
    invalid = False
    suspect = False

    # --- PM2.5 (drives INVALID — the only thing that hides a reading from the public map) ---
    if pm25 is None:
        invalid = True
        flags.append("pm25_missing")
    elif float(pm25) in PM25_SENTINELS:
        invalid = True
        flags.append("pm25_sentinel")
        detail["pm25_sentinel"] = pm25
    elif pm25 < 0 or pm25 > PM25_ABS_MAX:
        invalid = True
        flags.append("pm25_oor")
        detail["pm25_oor"] = {"value": pm25, "max": PM25_ABS_MAX}

    # NOTE: flow is NOT judged per-reading — the correct flow target/units for this device
    # are unconfirmed (observed avg ≈ 11 L/min, not the BAM-1020 nominal 16.7). Flow health
    # is surfaced as an informational signal on the QC page instead of hiding readings.

    # --- Informational flags (do NOT hide the reading) ---
    if humidity is not None:
        if humidity > HIGH_RH_PCT:
            flags.append("high_rh")
            detail["high_rh"] = humidity
        if humidity < HUMIDITY_MIN or humidity > HUMIDITY_MAX:
            flags.append("humidity_oor")
    if temperature is not None and (temperature < TEMP_MIN_C or temperature > TEMP_MAX_C):
        flags.append("temp_oor")
    if pressure_kpa is not None and (pressure_kpa < PRESSURE_MIN_KPA or pressure_kpa > PRESSURE_MAX_KPA):
        flags.append("pressure_oor")
    if wind_speed is not None and (wind_speed < WIND_MIN_MS or wind_speed > WIND_MAX_MS):
        flags.append("wind_oor")

    qc_state = "INVALID" if invalid else ("SUSPECT" if suspect else "OK")
    return qc_state, flags, detail


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
    qc_state: str = "OK", qc_flags: Optional[list] = None,
):
    # Pass the flags as a Python list (asyncpg encodes list -> text[] from the column
    # context); empty -> NULL to keep OK rows clean. The bind's type is inferred from the
    # qc_flags column, so no explicit CAST (a CAST would mis-infer the param as text[]).
    qc_flags_param = qc_flags if qc_flags else None
    await db.execute(text("""
        INSERT INTO readings (
          scope_type, scope_key, ts_utc,
          pm25, temp_c, humidity, pressure_hpa,
          wind_speed_ms, wind_dir_deg, aqi_us,
          qc_state, qc_flags, raw, source, ingested_at
        )
        VALUES (
          'station', :scope_key, :ts_utc,
          :pm25, :temp_c, :humidity, :pressure_hpa,
          :wind_speed_ms, :wind_dir_deg, :aqi_us,
          :qc_state, :qc_flags, CAST(:raw AS jsonb), 'bam', now()
        )
        ON CONFLICT (scope_type, scope_key, ts_utc) DO UPDATE
        SET pm25=EXCLUDED.pm25, temp_c=EXCLUDED.temp_c, humidity=EXCLUDED.humidity,
            pressure_hpa=EXCLUDED.pressure_hpa, wind_speed_ms=EXCLUDED.wind_speed_ms,
            wind_dir_deg=EXCLUDED.wind_dir_deg, aqi_us=EXCLUDED.aqi_us,
            qc_state=EXCLUDED.qc_state, qc_flags=EXCLUDED.qc_flags,
            raw = COALESCE(readings.raw, '{}'::jsonb) || EXCLUDED.raw,
            source='bam'
    """), dict(
        scope_key=station_id, ts_utc=ts_utc,
        pm25=pm25, temp_c=temp_c, humidity=humidity, pressure_hpa=pressure_hpa,
        wind_speed_ms=wind_speed_ms, wind_dir_deg=wind_dir_deg, aqi_us=aqi_us,
        qc_state=qc_state, qc_flags=qc_flags_param,
        raw=json.dumps(raw),
    ))
    await db.commit()
