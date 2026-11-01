"""QA-filtered station daily PM2.5 for one Pakistan day.

One loader behind the map's station layer (/ops/pipeline/stations/daily), the daily brief
and the copilot's hotspots, so all three rank and average the same numbers: per-station
daily means of hourly PM2.5 with spike/flatline QA and a minimum-valid-hours threshold
(the labels the model trains on).
"""

import json
import logging
import os
import shutil
import tempfile
from typing import Any, Dict, Optional

from app.services.geo_utils import point_in_pakistan

logger = logging.getLogger(__name__)

RAW_DATA_BUCKET = "paqi-raw-hawanama-data"
# The pre-computed stations.json is already filtered at this threshold.
DEFAULT_MIN_HOURS = 6


def load_station_daily(
    obs_date: str,
    country: Optional[str] = None,
    min_hours: int = DEFAULT_MIN_HOURS,
) -> Optional[Dict[str, Any]]:
    """Return ``{"date", "stations", "count", ...}`` for ``obs_date``, or None if the day
    has not been aggregated yet (today, or a gap).

    Fast path: the pre-computed ``stations.json``; fallback: the station_daily parquets.
    ``country="Pakistan"`` keeps stations inside the national boundary.
    """
    from google.cloud import storage

    filter_pakistan = bool(country) and country.lower() == "pakistan"
    bucket = storage.Client().bucket(RAW_DATA_BUCKET)

    # ── Fast path: pre-computed stations.json ──
    json_blob = bucket.blob(f"raw/station_daily/date={obs_date}/stations.json")
    if json_blob.exists():
        data = json.loads(json_blob.download_as_text())
        stations = data.get("stations", [])
        if min_hours > DEFAULT_MIN_HOURS:
            stations = [s for s in stations if (s.get("valid_hours") or 0) >= min_hours]
        if filter_pakistan:
            stations = [s for s in stations if point_in_pakistan(s.get("lat") or 0, s.get("lon") or 0)]
        data["stations"] = stations
        data["count"] = len(stations)
        return data

    # ── Slow fallback: parse parquets ──
    prefix = f"raw/station_daily/date={obs_date}"
    parquet_blobs = [b for b in bucket.list_blobs(prefix=prefix) if b.name.endswith(".parquet")]
    if not parquet_blobs:
        return None

    import pandas as pd

    tmp_dir = tempfile.mkdtemp()
    try:
        dfs = []
        for blob in parquet_blobs:
            tmp_path = os.path.join(tmp_dir, os.path.basename(blob.name))
            blob.download_to_filename(tmp_path)
            dfs.append(pd.read_parquet(tmp_path))
        df = pd.concat(dfs, ignore_index=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if filter_pakistan:
        if "country_name" in df.columns:
            df = df[df["country_name"].str.lower() == "pakistan"]
        else:
            # Fallback to boundary polygon if no country column
            df = df[df.apply(
                lambda r: point_in_pakistan(
                    float(r.get("latitude") or r.get("lat") or 0),
                    float(r.get("longitude") or r.get("lon") or 0),
                ), axis=1
            )]

    hours_col = "pm25_ugm3_valid_hours" if "pm25_ugm3_valid_hours" in df.columns else None
    if hours_col:
        df = df[df[hours_col] >= min_hours]

    pm25_col = "pm25_ugm3_mean" if "pm25_ugm3_mean" in df.columns else "pm25_daily_mean"
    lat_col = next((c for c in ["latitude", "lat"] if c in df.columns), None)
    lon_col = next((c for c in ["longitude", "lon"] if c in df.columns), None)
    if pm25_col not in df.columns or lat_col is None or lon_col is None:
        raise ValueError(f"Unexpected station_daily parquet schema for {obs_date}")

    df = df.dropna(subset=[pm25_col, lat_col, lon_col])
    stations = []
    for _, row in df.iterrows():
        stations.append({
            "station_id": str(row.get("station_id", "")).strip(),
            "name": str(row.get("station_name", "")),
            "city": str(row.get("city_name", "")),
            "lat": round(float(row[lat_col]), 5),
            "lon": round(float(row[lon_col]), 5),
            "pm25": round(float(row[pm25_col]), 1),
            "valid_hours": int(row[hours_col]) if hours_col and pd.notna(row.get(hours_col)) else None,
            "complete": bool(row.get("pm25_ugm3_complete", 0)),
        })
    return {"date": obs_date, "stations": stations, "count": len(stations)}
