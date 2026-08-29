"""
Analyst Desk API endpoints for PM2.5 operational forecasting.

Serves pre-computed forecast outputs (forecast, watchlist, summary JSONs)
from GCS and computes derived views for the analyst dashboard:
  - Daily overview with national risk statistics
  - Station-level forecasts with risk labels
  - Ranked watchlists for analyst triage
  - City and province summary aggregations
  - Single-station detail views

All heavy computation (risk classification, watchlist generation, city
aggregation) happens in the forecast pipeline. This router reads the
results and shapes them for the frontend.
"""

import csv
import io
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

FORECASTS_BUCKET = settings.OPS_FORECASTS_BUCKET or "paqi-forecasts-hawanama-data"


# ── Risk band thresholds for normalization ────────────────────────────────

_PM25_BANDS = [
    (35, "good"),
    (75, "moderate"),
    (150, "unhealthy"),
    (250, "very_unhealthy"),
]


def _classify_band(pm25: float | None) -> str:
    if pm25 is None:
        return "unknown"
    for threshold, band in _PM25_BANDS:
        if pm25 <= threshold:
            return band
    return "severe"


def _normalize_forecast(data: dict) -> dict:
    """Normalize forecast JSON so downstream consumers get consistent fields.

    Fixes:
    - city → city_name (old forecasts use 'city')
    - Computes risk_band from pm25_forecast if missing
    - Adds default episode_state, confidence, priority if missing
    """
    for entry in data.get("forecasts", []):
        # Normalize city field
        if not entry.get("city_name") and entry.get("city"):
            entry["city_name"] = entry["city"]

        # Compute risk_band from pm25_forecast if missing
        if not entry.get("risk_band"):
            entry["risk_band"] = _classify_band(entry.get("pm25_forecast"))

        # Defaults for decision-support fields
        if not entry.get("episode_state"):
            entry["episode_state"] = "stable"
        if not entry.get("confidence"):
            entry["confidence"] = "medium"
        if not entry.get("priority"):
            band = entry.get("risk_band", "unknown")
            if band in ("severe", "very_unhealthy"):
                entry["priority"] = "escalate"
            elif band == "unhealthy":
                entry["priority"] = "review"
            else:
                entry["priority"] = "monitor"

    return data


# ── GCS helpers (same pattern as ops_pipeline.py) ────────────────────────

def _require_gcs():
    try:
        from google.cloud import storage
        return storage
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail="GCS operations require 'google-cloud-storage' installed.",
        ) from e


def _gcs_client():
    storage = _require_gcs()
    return storage.Client()


def _gcs_read_json(blob_path: str) -> Dict[str, Any]:
    """Read and parse a JSON file from the forecasts bucket."""
    try:
        client = _gcs_client()
        blob = client.bucket(FORECASTS_BUCKET).blob(blob_path)
        if not blob.exists(client):
            raise HTTPException(
                status_code=404,
                detail="Forecast data not found for the requested date.",
            )
        raw = blob.download_as_text()
        return json.loads(raw)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GCS read failed: {blob_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read forecast data.")


def _gcs_blob_exists(blob_path: str) -> bool:
    try:
        client = _gcs_client()
        return client.bucket(FORECASTS_BUCKET).blob(blob_path).exists(client)
    except Exception:
        return False


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _date_str(d: str) -> str:
    """Normalise date string to YYYYMMDD for GCS file naming."""
    if not _DATE_RE.match(d):
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format.")
    return d.replace("-", "")


# ── Available dates ──────────────────────────────────────────────────────

@router.get(
    "/dates",
    summary="List available forecast dates",
    description="Returns dates for which forecast data exists in GCS.",
)
async def list_dates(
    limit: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    try:
        client = _gcs_client()
        bucket = client.bucket(FORECASTS_BUCKET)
        blobs = bucket.list_blobs(prefix="forecasts/forecast_", delimiter="/")
        blob_list = list(blobs)

        dates = set()
        for b in blob_list:
            name = b.name
            if name.endswith(".json") and "forecast_" in name:
                # forecasts/forecast_20260307.json → 2026-03-07
                try:
                    ds = name.split("forecast_")[1].split(".")[0]
                    dates.add(f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}")
                except (IndexError, ValueError):
                    continue

        sorted_dates = sorted(dates, reverse=True)[:limit]
        return {"dates": sorted_dates, "count": len(sorted_dates)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list forecast dates: {e}")
        raise HTTPException(status_code=500, detail="Failed to list forecast dates.")


# ── Overview ─────────────────────────────────────────────────────────────

@router.get(
    "/overview",
    summary="Daily forecast overview",
    description="National-level summary statistics for the analyst dashboard.",
)
async def get_overview(
    date: str = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
) -> Dict[str, Any]:
    # Load forecast
    forecast = _load_forecast(date)
    entries = forecast.get("forecasts", [])

    if not entries:
        return {"init_date": forecast.get("init_date"), "empty": True}

    d1 = [e for e in entries if e.get("lead_days") == 1]
    all_horizons = sorted(set(e.get("lead_days", 0) for e in entries))

    # National D+1 stats
    band_counts = {}
    priority_counts = {}
    confidence_counts = {}
    n_ramp = 0

    for e in d1:
        band = e.get("risk_band", "unknown")
        band_counts[band] = band_counts.get(band, 0) + 1
        pri = e.get("priority", "unknown")
        priority_counts[pri] = priority_counts.get(pri, 0) + 1
        conf = e.get("confidence", "unknown")
        confidence_counts[conf] = confidence_counts.get(conf, 0) + 1
        if e.get("ramp_detected"):
            n_ramp += 1

    d1_forecasts = [e["pm25_forecast"] for e in d1 if e.get("pm25_forecast") is not None]
    d1_q90s = [e["pm25_q90"] for e in d1 if e.get("pm25_q90") is not None]

    # Load summary for city-level context
    summary = _load_summary_safe(date or forecast.get("init_date"))
    n_cities_unhealthy = 0
    n_cities_worsening = 0
    if summary:
        for city in summary.get("city_summaries", []):
            d1h = city.get("horizons", {}).get("D+1", {})
            if d1h.get("worst_band") in ("unhealthy", "very_unhealthy", "severe"):
                n_cities_unhealthy += 1
            if city.get("trend") == "worsening":
                n_cities_worsening += 1

    # Load watchlist summary
    watchlist = _load_watchlist_safe(date or forecast.get("init_date"))
    watchlist_counts = {}
    if watchlist:
        for name, wl_entries in watchlist.get("watchlists", {}).items():
            if wl_entries:
                watchlist_counts[name] = len(wl_entries)

    return {
        "init_date": forecast.get("init_date"),
        "generated_at": forecast.get("generated_at"),
        "n_stations": forecast.get("n_stations", 0),
        "n_rows": forecast.get("n_rows", 0),
        "horizons": all_horizons,
        "d1_stats": {
            "n_stations": len(d1),
            "mean_forecast": round(sum(d1_forecasts) / len(d1_forecasts), 1) if d1_forecasts else None,
            "median_forecast": round(sorted(d1_forecasts)[len(d1_forecasts) // 2], 1) if d1_forecasts else None,
            "max_forecast": round(max(d1_forecasts), 1) if d1_forecasts else None,
            "max_q90": round(max(d1_q90s), 1) if d1_q90s else None,
            "band_counts": band_counts,
            "priority_counts": priority_counts,
            "confidence_counts": confidence_counts,
            "n_ramp": n_ramp,
        },
        "cities_unhealthy": n_cities_unhealthy,
        "cities_worsening": n_cities_worsening,
        "watchlist_counts": watchlist_counts,
        "data_quality": forecast.get("data_quality", {}),
    }


# ── Forecasts (station-level) ────────────────────────────────────────────

@router.get(
    "/forecasts",
    summary="Station-level forecasts",
    description="Full forecast grid, optionally filtered by horizon, city, priority, or band.",
)
async def get_forecasts(
    date: str = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
    horizon: Optional[int] = Query(None, description="Filter to specific lead_days (1, 2, or 3)."),
    city: Optional[str] = Query(None, description="Filter to a specific city."),
    priority: Optional[str] = Query(None, description="Filter by priority (monitor, review, escalate)."),
    band: Optional[str] = Query(None, description="Filter by risk_band."),
    limit: int = Query(2000, ge=1, le=5000),
) -> Dict[str, Any]:
    forecast = _load_forecast(date)
    entries = forecast.get("forecasts", [])

    # Apply filters
    if horizon is not None:
        entries = [e for e in entries if e.get("lead_days") == horizon]
    if city:
        entries = [e for e in entries if e.get("city_name", "").lower() == city.lower()]
    if priority:
        entries = [e for e in entries if e.get("priority") == priority]
    if band:
        entries = [e for e in entries if e.get("risk_band") == band]

    return {
        "init_date": forecast.get("init_date"),
        "generated_at": forecast.get("generated_at"),
        "n_stations": forecast.get("n_stations", 0),
        "n_rows": forecast.get("n_rows", 0),
        "horizons": sorted(set(e.get("lead_days", 0) for e in forecast.get("forecasts", []))),
        "data_quality": forecast.get("data_quality", {}),
        "watchlist_summary": forecast.get("watchlist_summary", {}),
        "total": len(entries),
        "forecasts": entries[:limit],
    }


# ── Watchlists ───────────────────────────────────────────────────────────

@router.get(
    "/watchlists",
    summary="All watchlists",
    description="Ranked triage watchlists for analyst review.",
)
async def get_watchlists(
    date: str = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
    list_name: Optional[str] = Query(None, description="Return a single watchlist by name."),
) -> Dict[str, Any]:
    init_date = date or _resolve_latest_date()
    ds = _date_str(init_date)

    blob_path = f"forecasts/watchlist_{ds}.json"
    data = _gcs_read_json(blob_path)

    watchlists = data.get("watchlists", {})

    if list_name:
        if list_name not in watchlists:
            raise HTTPException(status_code=404, detail=f"Watchlist '{list_name}' not found.")
        return {
            "init_date": data.get("init_date"),
            "watchlist": list_name,
            "entries": watchlists[list_name],
            "count": len(watchlists[list_name]),
        }

    # Return all with counts
    summary = {name: len(entries) for name, entries in watchlists.items()}
    return {
        "init_date": data.get("init_date"),
        "generated_at": data.get("generated_at"),
        "watchlist_counts": summary,
        "watchlists": watchlists,
    }


# ── City / Province summaries ────────────────────────────────────────────

@router.get(
    "/summaries",
    summary="City and province summaries",
    description="Group-level forecast aggregations with trend indicators.",
)
async def get_summaries(
    date: str = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
    level: str = Query("all", description="Aggregation level: 'all', 'city', or 'province'."),
    city: Optional[str] = Query(None, description="Return a single city by name."),
) -> Dict[str, Any]:
    init_date = date or _resolve_latest_date()
    ds = _date_str(init_date)

    blob_path = f"forecasts/summary_{ds}.json"
    data = _gcs_read_json(blob_path)

    if city:
        city_summaries = data.get("city_summaries", [])
        match = [s for s in city_summaries if s.get("name", "").lower() == city.lower()]
        if not match:
            raise HTTPException(status_code=404, detail=f"City '{city}' not found in summaries.")
        return {
            "init_date": data.get("init_date"),
            "summary": match[0],
        }

    if level == "all":
        # Return both city and province summaries
        return {
            "init_date": data.get("init_date"),
            "generated_at": data.get("generated_at"),
            "city_summaries": data.get("city_summaries", []),
            "province_summaries": data.get("province_summaries", []),
        }

    key = "province_summaries" if level == "province" else "city_summaries"
    summaries = data.get(key, [])

    return {
        "init_date": data.get("init_date"),
        "generated_at": data.get("generated_at"),
        "level": level,
        "count": len(summaries),
        "summaries": summaries,
    }


# ── Station detail ───────────────────────────────────────────────────────

@router.get(
    "/station/{sensor_id}",
    summary="Single station detail",
    description="All horizons for a single station, with risk labels and source flags.",
)
async def get_station_detail(
    sensor_id: int,
    date: str = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
) -> Dict[str, Any]:
    forecast = _load_forecast(date)
    entries = forecast.get("forecasts", [])

    station_rows = [e for e in entries if e.get("sensor_id") == sensor_id]
    if not station_rows:
        raise HTTPException(status_code=404, detail=f"Station {sensor_id} not found in forecast.")

    station_rows.sort(key=lambda e: e.get("lead_days", 0))
    meta = station_rows[0]

    # Compute spread and trajectory
    horizons = []
    for row in station_rows:
        med = row.get("pm25_forecast")
        q75 = row.get("pm25_q75")
        q90 = row.get("pm25_q90")
        horizons.append({
            "lead_days": row.get("lead_days"),
            "target_date": row.get("target_date"),
            "pm25_forecast": med,
            "pm25_q75": q75,
            "pm25_q90": q90,
            "spread": round(q90 - med, 1) if q90 is not None and med is not None else None,
            "risk_band": row.get("risk_band"),
            "episode_state": row.get("episode_state"),
            "confidence": row.get("confidence"),
            "priority": row.get("priority"),
            "ramp_detected": row.get("ramp_detected", False),
        })

    # Trajectory trend
    forecasts = [h["pm25_forecast"] for h in horizons if h["pm25_forecast"] is not None]
    if len(forecasts) >= 2:
        delta = forecasts[-1] - forecasts[0]
        trend = "worsening" if delta > 10 else "improving" if delta < -10 else "stable"
    else:
        delta = 0
        trend = "insufficient_data"

    return {
        "init_date": forecast.get("init_date"),
        "sensor_id": sensor_id,
        "station_name": meta.get("station_name", ""),
        "city_name": meta.get("city_name", ""),
        "state_name": meta.get("state_name", ""),
        "latitude": meta.get("latitude"),
        "longitude": meta.get("longitude"),
        "source_ifs": meta.get("source_ifs", False),
        "source_cams": meta.get("source_cams", False),
        "source_geos_cf": meta.get("source_geos_cf", False),
        "mos_applied": meta.get("mos_applied", False),
        "horizons": horizons,
        "trend": trend,
        "trend_delta": round(delta, 1),
    }


# ── Active fires (FIRMS) ─────────────────────────────────────────────────

@router.get(
    "/fires",
    summary="Active fire detections",
    description="VIIRS fire detections as GeoJSON for map overlay. Falls back to previous day if data not yet available.",
)
async def get_fires(
    date: str = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
) -> Dict[str, Any]:
    init_date = date or _resolve_latest_date()
    ds = _date_str(init_date)

    # Try requested date, then fall back up to 2 days (FIRMS ~12h latency)
    raw: Optional[str] = None
    used_date = init_date
    for offset in range(3):
        d = datetime.strptime(init_date, "%Y-%m-%d") - timedelta(days=offset)
        trial_ds = d.strftime("%Y%m%d")
        raw = _gcs_read_text(f"hindcast/firms/firms_{trial_ds}.csv")
        if raw and raw.strip():
            used_date = d.strftime("%Y-%m-%d")
            break

    if not raw or not raw.strip():
        return {
            "type": "FeatureCollection",
            "date": used_date,
            "features": [],
        }

    # Parse CSV → GeoJSON features
    features: List[Dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        try:
            frp = float(row.get("frp", 0))
        except (ValueError, TypeError):
            frp = 0.0
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "frp": round(frp, 1),
                "confidence": row.get("confidence", ""),
                "satellite": row.get("satellite", ""),
                "acq_date": row.get("acq_date", used_date),
            },
        })

    return {
        "type": "FeatureCollection",
        "date": used_date,
        "features": features,
    }


# ── Internal helpers ─────────────────────────────────────────────────────

def _resolve_latest_date() -> str:
    """Get the init_date from the latest.json pointer."""
    try:
        latest = _gcs_read_json("forecasts/latest.json")
        return latest.get("init_date", "")
    except Exception:
        # Fallback: try today and yesterday
        for offset in range(0, 3):
            d = (datetime.utcnow() - timedelta(days=offset)).strftime("%Y-%m-%d")
            ds = d.replace("-", "")
            if _gcs_blob_exists(f"forecasts/forecast_{ds}.json"):
                return d
        raise HTTPException(status_code=404, detail="No forecast data found.")


def _load_forecast(date_str: Optional[str] = None) -> Dict[str, Any]:
    """Load forecast JSON from GCS. Falls back to latest.json.

    Always normalizes fields (city→city_name, risk_band defaults, etc.)
    so downstream consumers get consistent data regardless of pipeline version.
    """
    if date_str:
        ds = _date_str(date_str)
        raw = _gcs_read_json(f"forecasts/forecast_{ds}.json")
    else:
        raw = _gcs_read_json("forecasts/latest.json")
    return _normalize_forecast(raw)


def _load_watchlist_safe(date_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load watchlist JSON, returning None on failure."""
    if not date_str:
        return None
    try:
        ds = _date_str(date_str)
        return _gcs_read_json(f"forecasts/watchlist_{ds}.json")
    except Exception:
        return None


def _load_summary_safe(date_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load summary JSON, returning None on failure."""
    if not date_str:
        return None
    try:
        ds = _date_str(date_str)
        return _gcs_read_json(f"forecasts/summary_{ds}.json")
    except Exception:
        return None


def _load_drift_report(date_str: str) -> Optional[Dict[str, Any]]:
    """Load drift report JSON for a given date, returning None on failure."""
    try:
        ds = _date_str(date_str)
        key = f"monitoring/drift/drift_{ds}.json"
        return _gcs_read_json(key)
    except Exception:
        return None


def _load_driver_summary_safe(date_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load driver summary JSON, returning None on failure."""
    if not date_str:
        return None
    try:
        ds = _date_str(date_str)
        return _gcs_read_json(f"forecasts/driver_summary_{ds}.json")
    except Exception:
        return None


def _load_firms_nrt_safe() -> Optional[Dict[str, Any]]:
    """Load latest FIRMS NRT fire scores, returning None on failure."""
    try:
        return _gcs_read_json("forecasts/firms_nrt_latest.json")
    except Exception:
        return None


def _gcs_read_text(blob_path: str) -> Optional[str]:
    """Read raw text from a GCS blob, returning None if not found."""
    try:
        client = _gcs_client()
        blob = client.bucket(FORECASTS_BUCKET).blob(blob_path)
        if not blob.exists(client):
            return None
        return blob.download_as_text()
    except Exception as e:
        logger.warning(f"GCS text read failed: {blob_path}: {e}")
        return None


def _load_trajectory_safe(city_name: str, date_str: str) -> Optional[Dict[str, Any]]:
    """Load cached HYSPLIT trajectory summary for a city, returning None on failure."""
    city_key = city_name.lower().replace(" ", "_").replace("'", "")
    ds = date_str.replace("-", "")
    try:
        return _gcs_read_json(f"forecasts/trajectories/traj_{city_key}_{ds}.json")
    except Exception:
        return None
