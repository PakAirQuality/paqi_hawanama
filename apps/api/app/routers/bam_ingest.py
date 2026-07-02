"""BAM push-ingest router.

Public HTTPS endpoint that SFL's central system POSTs BAM reference-monitor
readings to. Guarded by our own bearer token (verify_bam_token), an optional
source-IP allowlist, best-effort rate limiting and strict payload validation.
Only mounted when BAM_ROLE=true (its own Cloud Run service, hawanama-bam), so
it is never exposed on the main public app.
"""

import logging
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_database
from app.core.security import verify_bam_token
from app.services.ingestion.bam_service import (
    ensure_bam_provider,
    evaluate_bam_qc,
    pm25_to_aqi_us,
    upsert_bam_reading,
    upsert_bam_station,
    wind_dir_to_deg,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Known BAM devices → fixed location. Unknown device_ids are rejected (422) so we
# never write readings against an unregistered / mislocated station.
DEVICE_REGISTRY: Dict[str, Dict[str, object]] = {
    "bam1006": {"name": "BAM 1006 (Karachi)", "lat": 24.837633, "lon": 67.103668},
}


def _sanity(v, lo, hi, name):
    """Wide guard: reject only non-finite / absurd magnitudes that would corrupt the
    DB. Plausibility (sentinels, out-of-physical-range) is handled downstream by QC
    so the reading is still stored and flagged, not rejected."""
    if v is None:
        return v
    if not math.isfinite(v):
        raise ValueError(f"{name} not finite")
    if not (lo <= v <= hi):
        raise ValueError(f"{name} grossly out of range")
    return v


class BamData(BaseModel):
    """Sensor payload (mirrors the MQTT message body)."""
    flow: Optional[float] = None
    pm25: Optional[float] = None
    humidity: Optional[float] = None
    temperature: Optional[float] = None
    pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_dir: Optional[str] = None

    @field_validator("pm25")
    @classmethod
    def _g_pm25(cls, v):
        return _sanity(v, -1000, 100000, "pm25")

    @field_validator("humidity")
    @classmethod
    def _g_humidity(cls, v):
        return _sanity(v, -100, 1000, "humidity")

    @field_validator("temperature")
    @classmethod
    def _g_temperature(cls, v):
        return _sanity(v, -150, 200, "temperature")

    @field_validator("pressure")
    @classmethod
    def _g_pressure(cls, v):
        # kPa (~99.8 at sea level); wide guard, QC flags pressure_oor beyond 50–120.
        return _sanity(v, 0, 5000, "pressure")

    @field_validator("wind_speed")
    @classmethod
    def _g_wind_speed(cls, v):
        return _sanity(v, -10, 1000, "wind_speed")


class BamReadingIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    timestamp: Optional[datetime] = None
    event_id: Optional[str] = Field(None, max_length=128)
    source: Optional[str] = Field(None, max_length=64)
    topic: Optional[str] = Field(None, max_length=128)
    data: BamData


# ---- Best-effort per-instance rate limiting (safeguard, not a hard guarantee;
# Cloud Run runs multiple instances so this is per-instance). -----------------
_REQUEST_LOG: Dict[str, Deque[float]] = defaultdict(deque)


def _ts_from_event_id(event_id: Optional[str]) -> Optional[datetime]:
    """Parse the nanosecond-epoch timestamp SFL/Telegraf embeds as the last segment of
    event_id (e.g. 'bam1006-20260702T135321-1782982401080169600' → …:21.513 UTC).

    This recovers sub-second precision that the second-resolution `timestamp` field drops,
    so two readings in the same clock second get distinct `ts_utc` and neither is lost to
    the (scope_type, scope_key, ts_utc) upsert. Returns None if not parseable.
    """
    if not event_id:
        return None
    tail = event_id.rsplit("-", 1)[-1]
    if not tail.isdigit():
        return None
    try:
        ns = int(tail)
    except ValueError:
        return None
    # Nanoseconds since epoch for the 2000s are ~1e18 (19 digits); guard the range.
    if not (10**18 <= ns < 10**19):
        return None
    try:
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_bam_ip_allowlist(request: Request) -> None:
    """No-op unless BAM_ALLOWED_IPS is configured; else 403 for non-listed IPs."""
    allow = settings.BAM_ALLOWED_IPS
    if not allow:
        return
    allowed = {ip.strip() for ip in allow.split(",") if ip.strip()}
    if _client_ip(request) not in allowed:
        raise HTTPException(status_code=403, detail="Source IP not allowed")


async def bam_rate_limit(request: Request) -> None:
    limit = settings.BAM_RATE_LIMIT_PER_MIN
    if not limit or limit <= 0:
        return
    now = time.time()
    ip = _client_ip(request)
    log = _REQUEST_LOG[ip]
    while log and now - log[0] > 60:
        log.popleft()
    if len(log) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    log.append(now)


@router.post(
    "/readings",
    dependencies=[
        Depends(verify_bam_token),
        Depends(enforce_bam_ip_allowlist),
        Depends(bam_rate_limit),
    ],
)
async def ingest_bam_reading(
    payload: BamReadingIn,
    db: AsyncSession = Depends(get_database),
):
    """Receive one BAM reading and upsert it into the readings table."""
    device = DEVICE_REGISTRY.get(payload.device_id)
    if device is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown device_id '{payload.device_id}'",
        )

    # Timestamp resolution: SFL's `timestamp` field is only second-resolution, so two
    # readings in the same second would collide on the (scope_key, ts_utc) key and one
    # would be lost. event_id carries a nanosecond timestamp — prefer it (when it agrees
    # with the payload second) to keep sub-second precision and capture every reading.
    ts_payload = payload.timestamp
    if ts_payload is not None and ts_payload.tzinfo is None:
        ts_payload = ts_payload.replace(tzinfo=timezone.utc)
    ts_event = _ts_from_event_id(payload.event_id)

    if ts_event is not None and (
        ts_payload is None or abs((ts_event - ts_payload).total_seconds()) < 5
    ):
        ts_utc = ts_event.astimezone(timezone.utc)          # sub-second → no collisions
    elif ts_payload is not None:
        ts_utc = ts_payload.astimezone(timezone.utc)
    else:
        ts_utc = datetime.now(timezone.utc)

    d = payload.data

    # BAM reports pressure in kPa (confirmed with SFL); the DB column is hPa.
    pressure_hpa = round(d.pressure * 10, 2) if d.pressure is not None else None

    # Per-reading QC — accept + flag rather than reject, so bad data is recorded and
    # gated at display, and the QC page can surface faults (see bam_service.evaluate_bam_qc).
    qc_state, qc_flags, qc_detail = evaluate_bam_qc(
        pm25=d.pm25, humidity=d.humidity, temperature=d.temperature,
        pressure_kpa=d.pressure, wind_speed=d.wind_speed, flow=d.flow,
    )

    try:
        provider_id = await ensure_bam_provider(db)
        station_id = await upsert_bam_station(
            db,
            provider_id=provider_id,
            source_station_id=payload.device_id,
            name=str(device["name"]),
            lat=float(device["lat"]),
            lon=float(device["lon"]),
        )
        await upsert_bam_reading(
            db,
            station_id=station_id,
            ts_utc=ts_utc,
            pm25=d.pm25,
            temp_c=d.temperature,
            humidity=d.humidity,
            pressure_hpa=pressure_hpa,
            wind_speed_ms=d.wind_speed,
            wind_dir_deg=wind_dir_to_deg(d.wind_dir),
            aqi_us=pm25_to_aqi_us(d.pm25),
            qc_state=qc_state,
            qc_flags=qc_flags,
            raw={
                "provider": "bam",
                "device_id": payload.device_id,
                "event_id": payload.event_id,
                "topic": payload.topic,
                "flow": d.flow,
                "wind_dir": d.wind_dir,
                "pressure_raw": d.pressure,
                "qc": {"state": qc_state, "flags": qc_flags, "detail": qc_detail},
                "v": "bam_push_v2",
            },
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("BAM ingest failed for %s: %s", payload.device_id, e)
        raise HTTPException(status_code=500, detail="Failed to store BAM reading")

    return {
        "success": True,
        "message": "BAM reading received",
        "station_id": station_id,
        "ts_utc": ts_utc.isoformat(),
        "qc_state": qc_state,
        "qc_flags": qc_flags,
    }
