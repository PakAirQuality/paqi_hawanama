"""BAM push-ingest router.

Public HTTPS endpoint that SFL's central system POSTs BAM reference-monitor
readings to. Guarded by our own bearer token (verify_bam_token), an optional
source-IP allowlist, best-effort rate limiting and strict payload validation.
Only mounted when BAM_ROLE=true (its own Cloud Run service, hawanama-bam), so
it is never exposed on the main public app.
"""

import logging
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
    def _check_pm25(cls, v):
        if v is not None and not (0 <= v <= 2000):
            raise ValueError("pm25 out of range")
        return v

    @field_validator("humidity")
    @classmethod
    def _check_humidity(cls, v):
        if v is not None and not (0 <= v <= 100):
            raise ValueError("humidity out of range")
        return v

    @field_validator("temperature")
    @classmethod
    def _check_temperature(cls, v):
        if v is not None and not (-60 <= v <= 80):
            raise ValueError("temperature out of range")
        return v

    @field_validator("pressure")
    @classmethod
    def _check_pressure(cls, v):
        # BAM reports pressure in kPa (confirmed with SFL); ~99.8 at sea level.
        if v is not None and not (50 <= v <= 120):
            raise ValueError("pressure out of range")
        return v

    @field_validator("wind_speed")
    @classmethod
    def _check_wind_speed(cls, v):
        if v is not None and not (0 <= v <= 150):
            raise ValueError("wind_speed out of range")
        return v


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

    # Timestamp: use the sender's if provided (normalised to UTC), else now.
    ts = payload.timestamp or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_utc = ts.astimezone(timezone.utc)

    d = payload.data

    # BAM reports pressure in kPa (confirmed with SFL); the DB column is hPa.
    pressure_hpa = round(d.pressure * 10, 2) if d.pressure is not None else None

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
            raw={
                "provider": "bam",
                "device_id": payload.device_id,
                "event_id": payload.event_id,
                "topic": payload.topic,
                "flow": d.flow,
                "wind_dir": d.wind_dir,
                "pressure_raw": d.pressure,
                "v": "bam_push_v1",
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
    }
