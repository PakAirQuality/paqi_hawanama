"""
Hourly nowcast (+3/+6/+12/+24 h) read routes.

The Operational_Forecasting ``nowcast`` Cloud Run job runs every 3 h and
publishes ``nowcast/nowcast_{YYYYMMDDTHH}Z.json`` plus ``nowcast/latest.json``
to the forecasts bucket. Each file carries one entry per station of the
forecast universe with four lead values (``pm25``/``q75``/``q90`` per lead,
null when ``basis == "prior"``) and a ``basis`` of ``model`` (own
observations), ``neighbours`` (inverse-distance estimate from nearby
reporting stations) or ``prior`` (nothing usable nearby).

These routes read the published JSON; nothing is computed here. Public,
read-only, like the analyst-desk forecast routes.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.routers.analyst_desk import FORECASTS_BUCKET, _gcs_client, _gcs_read_json

logger = logging.getLogger(__name__)
router = APIRouter()

LATEST_BLOB = "nowcast/latest.json"
RUN_RE = re.compile(r"^nowcast/nowcast_(\d{8}T\d{2})Z\.json$")
CACHE_TTL_S = 60.0

_cache: Dict[str, Any] = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def _latest(force: bool = False) -> Dict[str, Any]:
    """latest.json with a 60 s in-process cache; 404 when not published yet."""
    now = time.monotonic()
    with _cache_lock:
        if not force and _cache["data"] is not None and now - _cache["at"] < CACHE_TTL_S:
            return _cache["data"]
    try:
        data = _gcs_read_json(LATEST_BLOB)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="No nowcast has been published yet.")
        raise
    with _cache_lock:
        _cache["at"], _cache["data"] = time.monotonic(), data
    return data


def _matches(entry: Dict[str, Any], station_id: str) -> bool:
    sid = station_id.strip()
    if str(entry.get("station_id") or "").strip() == sid:
        return True
    members = entry.get("member_station_ids") or []
    if any(str(m).strip() == sid for m in members):
        return True
    return sid.isdigit() and entry.get("sensor_id") is not None and int(sid) == int(entry["sensor_id"])


def _summary(data: Dict[str, Any]) -> Dict[str, Any]:
    dq = data.get("data_quality") or {}
    return {
        "init_time": data.get("init_time"),
        "generated_at": data.get("generated_at"),
        "model_tag": data.get("model_tag"),
        "leads": data.get("leads"),
        "n_stations": data.get("n_stations"),
        "n_forecastable": dq.get("n_forecastable"),
        "forecastable_fraction": dq.get("forecastable_fraction"),
        "basis_counts": dq.get("basis_counts"),
        "source_ifs": dq.get("source_ifs"),
        "met_run": dq.get("met_run"),
        "newest_obs_utc": dq.get("newest_obs_utc"),
        "duration_s": dq.get("duration_s"),
    }


@router.get("/latest", summary="Latest hourly nowcast for every station")
async def get_latest(
    city: Optional[str] = Query(None, description="Keep only stations in this city (case-insensitive)"),
    refresh: bool = Query(False, description="Bypass the 60 s cache"),
) -> Dict[str, Any]:
    data = _latest(force=refresh)
    if city:
        want = city.strip().lower()
        stations = [s for s in data.get("stations", []) if str(s.get("city") or "").strip().lower() == want]
        data = {**data, "stations": stations, "n_stations": len(stations), "city": city}
    return data


@router.get("/station/{station_id}", summary="One station's nowcast")
async def get_station(station_id: str) -> Dict[str, Any]:
    data = _latest()
    entry = next((s for s in data.get("stations", []) if _matches(s, station_id)), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="No nowcast for this station in the latest cycle.")
    return {"init_time": data.get("init_time"), "generated_at": data.get("generated_at"),
            "model_tag": data.get("model_tag"), "leads": data.get("leads"), "station": entry}


@router.get("/runs", summary="Recent nowcast cycles")
async def list_runs(limit: int = Query(24, ge=1, le=200)) -> Dict[str, Any]:
    try:
        client = _gcs_client()
        blobs = client.bucket(FORECASTS_BUCKET).list_blobs(prefix="nowcast/nowcast_")
        names = sorted((b.name for b in blobs if RUN_RE.match(b.name)), reverse=True)[:limit]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GCS list failed for nowcast runs: {e}")
        raise HTTPException(status_code=500, detail="Failed to list nowcast runs.")
    runs: List[Dict[str, Any]] = []
    for name in names:
        stamp = RUN_RE.match(name).group(1)  # YYYYMMDDTHH
        init = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:00:00Z"
        row: Dict[str, Any] = {"blob": name, "init_time": init}
        try:
            row.update(_summary(_gcs_read_json(name)))
        except HTTPException:
            row["error"] = "unreadable"
        runs.append(row)
    return {"runs": runs, "count": len(runs)}
