"""
Parquet Publishing Endpoints for GCS

Publishes station readings (hourly and daily) as Parquet files to GCS.

Datasets:
- Hourly:  gs://<bucket>/raw/station_hourly/date=YYYY-MM-DD/
- Daily:   gs://<bucket>/raw/station_daily/date=YYYY-MM-DD/
- Latest:  gs://<bucket>/raw/station_readings_hourly_latest.parquet
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam
from app.core.database import get_database
from app.core.security import verify_tasks_token

from typing import Optional, Any
import logging
import uuid
import time
import os
import tempfile
import json
from datetime import datetime, timedelta, timezone, date

logger = logging.getLogger(__name__)
router = APIRouter()

# -----------------------------
# Export limits / constants
# -----------------------------
MAX_DAYS_BACK = 3650  # ~10 years
MAX_EXPORT_ROWS_HARD_CAP = 5_000_000

# Parquet batching (controls memory)
PARQUET_BATCH_ROWS = 50_000  # write row-groups around this size

# Default GCS "latest file" target (override via env)
DEFAULT_GCS_BUCKET = os.getenv("GCS_EXPORT_BUCKET", "paqi-raw-hawanama-data").strip()
DEFAULT_GCS_OBJECT = os.getenv(
    "GCS_EXPORT_OBJECT",
    "raw/station_readings_hourly_latest.parquet"
).strip()

# Default GCS prefixes for hourly and daily datasets
DEFAULT_HOURLY_PREFIX = "raw/station_hourly"
DEFAULT_DAILY_PREFIX = "raw/station_daily"

# QA Parameters for daily aggregation
DEFAULT_MIN_HOURS = 18  # Minimum hours per day for "complete" flag
DEFAULT_MIN_PUBLISH_HOURS = 6  # Don't publish station-day at all below this
DEFAULT_LOW_THRESHOLD = 2.0  # µg/m³ - suspiciously low PM2.5

# --- Hourly QC thresholds ---
PM25_ABS_MAX = 1000.0  # µg/m³ hard ceiling (anything above is invalid)
PM25_SENTINELS = {999.0, 1000.0, -1.0}  # known cap / error codes from LCS feeds
AQI_US_MIN, AQI_US_MAX = 0, 500

# Spike / stuck-sensor detection
PM25_MAX_DELTA_1H = 250.0  # µg/m³ jump in 1 hour (isolated spike threshold)
PM25_SPIKE_RETURN_TOL = 1.0  # µg/m³ tolerance for "returns to baseline" (AVG → floats)
PM25_FLATLINE_HOURS = 18  # consecutive identical-value hours to mark as stuck

# -----------------------------
# Pollutants (hourly aggregation only)
# -----------------------------
ALLOWED_POLLUTANTS = {"pm25", "pm10", "no2", "so2", "co", "o3"}
POLLUTANT_ALIASES = {
    "pm2.5": "pm25",
    "pm2_5": "pm25",
    "pm_2_5": "pm25",
    "carbon_monoxide": "co",
    "carbon-monoxide": "co",
    "monoxide": "co",
    "co": "co",
}

# -----------------------------
# Helpers
# -----------------------------
def _require_pyarrow():
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
        return pa, pq
    except Exception as e:
        raise HTTPException(
            status_code=501,
            detail="Parquet export requires 'pyarrow' installed in the API environment.",
        ) from e


def _require_pyarrow_dataset():
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
        import pyarrow.dataset as ds  # type: ignore
        import pyarrow.compute as pc  # type: ignore
        return pa, pq, ds, pc
    except Exception as e:
        raise HTTPException(
            status_code=501,
            detail="Daily aggregation requires 'pyarrow' with dataset support.",
        ) from e


def _require_pandas():
    try:
        import pandas as pd  # type: ignore
        import numpy as np  # type: ignore
        return pd, np
    except Exception as e:
        raise HTTPException(
            status_code=501,
            detail="Daily aggregation requires 'pandas' and 'numpy'.",
        ) from e


def _require_gcs():
    try:
        from google.cloud import storage  # type: ignore
        return storage
    except Exception as e:
        raise HTTPException(
            status_code=501,
            detail="GCS publish requires 'google-cloud-storage' installed in the API environment.",
        ) from e


def parse_date_yyyy_mm_dd(date_str: str) -> datetime:
    """Parse YYYY-MM-DD date string to UTC datetime at start of day."""
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def validate_and_compute_time_range(
    days_back: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[datetime, datetime]:
    """
    Returns (start_ts, end_ts) where end_ts is an exclusive upper bound.
    """
    if start_date and end_date:
        try:
            start_ts = parse_date_yyyy_mm_dd(start_date)
            end_ts = parse_date_yyyy_mm_dd(end_date) + timedelta(days=1)  # exclusive

            if start_ts >= end_ts:
                raise HTTPException(status_code=400, detail="start_date must be before end_date")

            days = (end_ts - start_ts).days
            if days > 365:
                logger.warning(f"Large explicit date range requested: {days} days")

            return start_ts, end_ts
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # days_back mode
    if days_back is None:
        days_back = MAX_DAYS_BACK
    if days_back < 1:
        raise HTTPException(status_code=400, detail="days_back must be >= 1")
    if days_back > MAX_DAYS_BACK:
        logger.warning(f"days_back={days_back} exceeds max; clamping to {MAX_DAYS_BACK}")
        days_back = MAX_DAYS_BACK

    now = datetime.now(timezone.utc)
    return now - timedelta(days=days_back), now


def _split_multi(values: Optional[list[str]]) -> list[str]:
    """
    Normalizes:
      ?x=A&x=B  -> ["A","B"]
      ?x=A,B    -> ["A,B"]
    into: ["A","B"]
    """
    if not values:
        return []
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        out.extend([p.strip() for p in v.split(",") if p.strip()])

    # de-dup preserving order
    seen = set()
    dedup = []
    for x in out:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def parse_parameters_param(parameters: Optional[str]) -> list[str]:
    """
    parameters:
      None -> default ("pm25" only)
      "all" -> all supported
      "pm25,pm10,no2" -> subset
    Supports aliases (pm2.5, carbon_monoxide, etc.)
    """
    if parameters is None:
        return ["pm25"]

    p = parameters.strip().lower()
    if p == "all":
        return ["pm25", "pm10", "no2", "so2", "co", "o3"]

    items = [x.strip().lower() for x in p.split(",") if x.strip()]
    normalized: list[str] = []
    for item in items:
        item = POLLUTANT_ALIASES.get(item, item)
        if item not in ALLOWED_POLLUTANTS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid parameters entry '{item}'. Allowed: all,"
                    f"{','.join(sorted(ALLOWED_POLLUTANTS))} (aliases: pm2.5, carbon_monoxide)."
                ),
            )
        normalized.append(item)

    # de-dup preserving order
    seen = set()
    out = []
    for x in normalized:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_pollutant_selects_hourly(selected: list[str]) -> tuple[list[str], list[str]]:
    """
    Returns (select_sql_fragments, output_column_names) for hourly-aggregated pollutant values (NO UNITS).
    """
    # (value_col, output_value_alias)
    col_map = {
        "pm25": ("pm25", "pm25_ugm3"),
        "pm10": ("pm10", "pm10_ugm3"),
        "no2":  ("no2",  "no2"),
        "so2":  ("so2",  "so2"),
        "co":   ("co",   "co"),
        "o3":   ("o3",   "o3"),
    }

    selects: list[str] = []
    headers: list[str] = []

    for key in selected:
        val_col, out_val = col_map[key]
        selects.append(f"AVG(r.{val_col}) AS {out_val}")
        headers.append(out_val)

    return selects, headers


def _daterange_days(start_ts: datetime, end_ts: datetime) -> list[date]:
    """Generate list of dates between start_ts and end_ts (inclusive)."""
    start_d = start_ts.date()
    end_d = (end_ts - timedelta(microseconds=1)).date()
    out = []
    cur = start_d
    while cur <= end_d:
        out.append(cur)
        cur = cur + timedelta(days=1)
    return out


def _day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """Return (start, end) datetime bounds for a given date in UTC."""
    s = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return s, s + timedelta(days=1)


def _build_all_stations_hourly_query(
    pollutant_selects: list[str],
    province: Optional[str],
    city: Optional[str],
    station_ids: list[str],
    provider_codes: list[str],
) -> tuple[Any, dict[str, Any]]:
    """
    Build a single optimized query that returns hourly aggregated readings
    for ALL stations in a time range, with station metadata joined.

    This replaces the N+1 query pattern (one query per station) with a single
    efficient query that uses the database's ability to join and aggregate.

    Note: No LIMIT clause - date bounds + indexes provide safety. Callers should
    detect truncation if they impose row limits.
    """
    bucket_expr = "time_bucket('1 hour', r.ts_utc, 'UTC')"

    # Build pollutant selects
    pollutant_sql = ",\n            ".join(pollutant_selects)

    # Build WHERE clauses for station filters
    where_clauses = ["r.scope_type = 'station'", "r.ts_utc >= :start_ts", "r.ts_utc < :end_ts"]
    params: dict[str, Any] = {}

    if province:
        where_clauses.append("LOWER(COALESCE(st.name, '')) = LOWER(:province)")
        params["province"] = province
    if city:
        where_clauses.append("LOWER(COALESCE(c.name, '')) = LOWER(:city)")
        params["city"] = city
    if station_ids:
        where_clauses.append("s.station_id IN :station_ids")
        params["station_ids"] = station_ids
    if provider_codes:
        where_clauses.append("LOWER(COALESCE(p.code, '')) IN :provider_codes")
        params["provider_codes"] = provider_codes

    where_sql = " AND ".join(where_clauses)

    # Single query: join + aggregate by station_id and hour bucket only
    # Metadata columns use FIRST_VALUE or are derived from station_id grouping
    sql = f"""
        SELECT
            s.station_id,
            s.name AS station_name,
            s.lat AS latitude,
            s.lon AS longitude,
            c.name AS city_name,
            st.name AS state_name,
            co.name AS country_name,
            p.display_name AS provider_name,
            {bucket_expr} AS timestamp_utc,
            AVG(r.aqi_us) AS aqi_us,
            {pollutant_sql}
        FROM readings r
        JOIN stations s ON r.scope_key = s.station_id
        LEFT JOIN providers p ON s.provider_id = p.id
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN states st ON c.state_id = st.id
        LEFT JOIN countries co ON st.country_id = co.id
        WHERE {where_sql}
        GROUP BY
            s.station_id,
            s.name,
            s.lat,
            s.lon,
            c.name,
            st.name,
            co.name,
            p.display_name,
            {bucket_expr}
        ORDER BY s.station_id, {bucket_expr} ASC
    """

    q = text(sql)

    # Bind expanding parameters
    if station_ids:
        q = q.bindparams(bindparam("station_ids", expanding=True))
    if provider_codes:
        q = q.bindparams(bindparam("provider_codes", expanding=True))

    return q, params


# --------------------------------------------------------------------------------------
# Daily Aggregation Pipeline Functions
# --------------------------------------------------------------------------------------
def read_hourly_partition_from_gcs(
    target_date: date,
    bucket_name: str,
    hourly_prefix: str,
) -> Optional[Any]:
    """
    Read hourly partition for a specific date from GCS.
    Returns pyarrow.Table or None if partition doesn't exist.
    """
    pa, pq, ds, pc = _require_pyarrow_dataset()
    storage = _require_gcs()

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Check if partition exists (look for _SUCCESS marker)
    partition_dir = f"{hourly_prefix}/date={target_date.isoformat()}"
    success_blob = f"{partition_dir}/_SUCCESS.json"

    if not bucket.blob(success_blob).exists(client):
        logger.warning(f"Hourly partition not found: {partition_dir}")
        return None

    try:
        # Read using pyarrow dataset
        gcs_path = f"gs://{bucket_name}/{partition_dir}"
        dataset = ds.dataset(gcs_path, format="parquet")
        table = dataset.to_table()

        logger.info(f"Read {len(table)} hourly rows from {gcs_path}")
        return table

    except Exception as e:
        logger.error(f"Error reading hourly partition {partition_dir}: {e}")
        return None


def _apply_hourly_qc(df, pd, np) -> tuple[Any, dict]:
    """
    Hour-level QC on the raw hourly DataFrame (single day, all stations).

    Mutates pollutant columns in-place (invalid hours → NaN) so that
    downstream aggregation only uses QC-passed values.

    Returns (df, qc_stats) where qc_stats counts removals by cause.
    """
    qc = {
        "pm25_sentinel": 0,
        "pm25_bounds": 0,
        "pm25_spike": 0,
        "pm25_flatline": 0,
        "aqi_bounds": 0,
    }

    # --- AQI sanity ---
    if "aqi_us" in df.columns:
        df["aqi_us"] = pd.to_numeric(df["aqi_us"], errors="coerce")
        bad_aqi = (df["aqi_us"] < AQI_US_MIN) | (df["aqi_us"] > AQI_US_MAX)
        qc["aqi_bounds"] = int(bad_aqi.sum())
        df.loc[bad_aqi, "aqi_us"] = np.nan

    # --- PM2.5 ---
    if "pm25_ugm3" in df.columns:
        df["pm25_ugm3"] = pd.to_numeric(df["pm25_ugm3"], errors="coerce")

        # Sentinels / cap values (999, 1000, -1)
        is_sentinel = df["pm25_ugm3"].isin(PM25_SENTINELS)
        qc["pm25_sentinel"] = int(is_sentinel.sum())
        df.loc[is_sentinel, "pm25_ugm3"] = np.nan

        # Physical bounds: 0 ≤ pm25 ≤ 1000
        out_of_bounds = (df["pm25_ugm3"] < 0) | (df["pm25_ugm3"] > PM25_ABS_MAX)
        qc["pm25_bounds"] = int(out_of_bounds.sum())
        df.loc[out_of_bounds, "pm25_ugm3"] = np.nan

        # Spike filter: isolated 1-hour spike or 2-hour plateau that returns
        df = df.sort_values(["station_id", "timestamp_utc"])
        pm = df["pm25_ugm3"]
        prev_pm = df.groupby("station_id")["pm25_ugm3"].shift(1)
        next_pm = df.groupby("station_id")["pm25_ugm3"].shift(-1)
        prev2_pm = df.groupby("station_id")["pm25_ugm3"].shift(2)

        # 1-hour spike: big jump from prev AND returns next hour
        spike_1h = (
            pm.notna()
            & prev_pm.notna()
            & next_pm.notna()
            & ((pm - prev_pm).abs() > PM25_MAX_DELTA_1H)
            & ((next_pm - prev_pm).abs() <= PM25_SPIKE_RETURN_TOL)
        )
        df.loc[spike_1h, "pm25_ugm3"] = np.nan

        # 2-hour spike plateau: two consecutive elevated hours, then returns
        spike_2h = (
            pm.notna()
            & prev_pm.notna()
            & prev2_pm.notna()
            & next_pm.notna()
            & ((prev_pm - prev2_pm).abs() > PM25_MAX_DELTA_1H)
            & ((pm - prev2_pm).abs() > PM25_MAX_DELTA_1H)
            & ((next_pm - prev2_pm).abs() <= PM25_SPIKE_RETURN_TOL)
        )
        # nullify both the current and previous spike hour
        df.loc[spike_2h, "pm25_ugm3"] = np.nan
        spike_2h_prev = spike_2h.groupby(df["station_id"]).shift(-1).fillna(False)
        df.loc[spike_2h_prev, "pm25_ugm3"] = np.nan

        qc["pm25_spike"] = int(spike_1h.sum()) + int(spike_2h.sum()) + int(spike_2h_prev.sum())

        # Flatline / stuck sensor: ≥N consecutive hours with identical value
        # (run-length on values, not deltas, so 18 identical hours = 18 flagged)
        pm = df["pm25_ugm3"]
        sid = df["station_id"].astype(str)

        new_seg = (
            (sid != sid.shift(1))
            | pm.isna()
            | pm.shift(1).isna()
            | (pm != pm.shift(1))
        )
        seg_id = new_seg.cumsum()
        seg_len = df.groupby(seg_id)["pm25_ugm3"].transform("size")

        stuck = pm.notna() & (seg_len >= PM25_FLATLINE_HOURS)
        qc["pm25_flatline"] = int(stuck.sum())
        df.loc[stuck, "pm25_ugm3"] = np.nan

    return df, qc


def aggregate_hourly_to_daily(
    hourly_table: Any,
    target_date: date,
    min_hours: int = DEFAULT_MIN_HOURS,
    apply_qc: bool = True,
) -> tuple[Any, dict]:
    """
    Aggregate hourly data to daily with QA filters.

    Returns:
        (daily_table, stats_dict)
    """
    pa, pq, ds, pc = _require_pyarrow_dataset()
    pd, np = _require_pandas()

    # Convert to pandas for aggregation
    df = hourly_table.to_pandas()

    if df.empty:
        logger.warning(f"Empty hourly table for {target_date}")
        empty_table = pa.table({})
        return empty_table, {"rows_in": 0, "rows_out": 0, "stations": 0}

    rows_in = len(df)

    # Ensure required columns exist
    if "timestamp_utc" not in df.columns:
        raise ValueError("Hourly table missing 'timestamp_utc' column")
    if "station_id" not in df.columns:
        raise ValueError("Hourly table missing 'station_id' column")

    # Parse timestamp
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce")
    df = df[df["timestamp_utc"].notna()].copy()

    # ---- Hour-level QC (before aggregation) ----
    hourly_qc_stats = {}
    if apply_qc:
        df, hourly_qc_stats = _apply_hourly_qc(df, pd, np)
        total_flagged = sum(hourly_qc_stats.values())
        if total_flagged > 0:
            logger.info(f"Hourly QC for {target_date}: {total_flagged} values nullified {hourly_qc_stats}")

    # Group by station_id only (stable key)
    group_cols = ["station_id"]

    # Metadata columns to take first value per station
    meta_cols = ["station_name", "latitude", "longitude", "city_name", "state_name", "country_name", "provider_name"]
    meta_cols = [col for col in meta_cols if col in df.columns]

    # Pollutant columns to aggregate
    pollutant_cols = []
    for col in ["pm25_ugm3", "pm10_ugm3", "no2", "so2", "co", "o3"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            pollutant_cols.append(col)

    if not pollutant_cols:
        logger.warning(f"No pollutant columns found for {target_date}")

    # Build aggregation dict
    agg_dict = {}

    # AQI aggregation
    if "aqi_us" in df.columns:
        agg_dict["aqi_us_mean"] = ("aqi_us", "mean")
        agg_dict["aqi_us_max"] = ("aqi_us", "max")

    for pol in pollutant_cols:
        agg_dict[f"{pol}_mean"] = (pol, "mean")
        agg_dict[f"{pol}_median"] = (pol, "median")
        agg_dict[f"{pol}_p95"] = (pol, lambda x: np.percentile(x.dropna(), 95) if len(x.dropna()) > 0 else np.nan)
        agg_dict[f"{pol}_valid_hours"] = (pol, lambda x: x.notna().sum())

    # Aggregate by station_id only
    daily = df.groupby(group_cols, dropna=False).agg(**agg_dict).reset_index()

    # Add metadata columns (take first value per station_id)
    for col in meta_cols:
        if col not in daily.columns:
            daily[col] = df.groupby(group_cols, dropna=False)[col].first().values

    # Add date column
    daily["date"] = target_date

    # Compute completeness flags per pollutant
    for pol in pollutant_cols:
        valid_hours_col = f"{pol}_valid_hours"
        flag_col = f"{pol}_complete"
        if valid_hours_col in daily.columns:
            daily[flag_col] = (daily[valid_hours_col] >= min_hours).astype("int8")

    stations_before_qc = len(daily)

    # ---- Day-level QC (after aggregation) ----
    if apply_qc:
        # 1. Drop station-days with suspiciously low PM2.5 (complete days only)
        if "pm25_ugm3_mean" in daily.columns:
            pm25_complete = daily.get("pm25_ugm3_complete", pd.Series([1] * len(daily)))
            suspicious_low = (
                (daily["pm25_ugm3_mean"] < DEFAULT_LOW_THRESHOLD)
                & (pm25_complete == 1)
            )
            n_low = int(suspicious_low.sum())
            if n_low > 0:
                logger.info(f"Dropped {n_low} station-days: PM2.5 mean < {DEFAULT_LOW_THRESHOLD} µg/m³")
                daily = daily[~suspicious_low].copy()

        # 2. Drop station-days with too few usable hours to be meaningful
        if "pm25_ugm3_valid_hours" in daily.columns:
            too_few = daily["pm25_ugm3_valid_hours"] < DEFAULT_MIN_PUBLISH_HOURS
            n_sparse = int(too_few.sum())
            if n_sparse > 0:
                logger.info(f"Dropped {n_sparse} station-days: < {DEFAULT_MIN_PUBLISH_HOURS} valid PM2.5 hours")
                daily = daily[~too_few].copy()

    stations_after_qc = len(daily)
    rows_out = len(daily)

    # Convert back to PyArrow Table
    daily_table = pa.Table.from_pandas(daily, preserve_index=False)

    stats = {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "stations_before_qc": stations_before_qc,
        "stations_after_qc": stations_after_qc,
        "stations_flagged": stations_before_qc - stations_after_qc,
        "hourly_qc": hourly_qc_stats,
    }

    return daily_table, stats


def upload_daily_partition_to_gcs(
    target_date: date,
    daily_table: Any,
    bucket_name: str,
    daily_prefix: str,
    run_id: str,
    stats: Optional[dict] = None,
    min_hours: int = DEFAULT_MIN_HOURS,
    apply_qc: bool = True,
) -> dict:
    """
    Upload daily aggregated table to GCS partition and write success marker.

    Returns dict with upload details.
    """
    pa, pq, ds, pc = _require_pyarrow_dataset()
    storage = _require_gcs()

    if len(daily_table) == 0:
        logger.warning(f"Skipping upload for {target_date}: empty table")
        return {"uploaded": False, "reason": "empty_table"}

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    partition_dir = f"{daily_prefix}/date={target_date.isoformat()}"
    parquet_file = f"{partition_dir}/station_daily_{run_id}.parquet"
    success_file = f"{partition_dir}/_SUCCESS.json"

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
        pq.write_table(daily_table, tmp_path, compression="snappy")

    try:
        # Upload parquet
        blob = bucket.blob(parquet_file)
        blob.upload_from_filename(tmp_path)

        # Write success marker with full QC provenance
        success_data = {
            "date": target_date.isoformat(),
            "rows": len(daily_table),
            "uri": f"gs://{bucket_name}/{parquet_file}",
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "qc": {
                "apply_qc": apply_qc,
                "thresholds": {
                    "min_hours": min_hours,
                    "min_publish_hours": DEFAULT_MIN_PUBLISH_HOURS,
                    "low_threshold_ugm3": DEFAULT_LOW_THRESHOLD,
                    "pm25_abs_max_ugm3": PM25_ABS_MAX,
                    "pm25_sentinels": sorted(PM25_SENTINELS),
                    "pm25_max_delta_1h_ugm3": PM25_MAX_DELTA_1H,
                    "pm25_spike_return_tol_ugm3": PM25_SPIKE_RETURN_TOL,
                    "pm25_flatline_hours": PM25_FLATLINE_HOURS,
                    "aqi_us_range": [AQI_US_MIN, AQI_US_MAX],
                },
                "stats": stats or {},
            },
        }

        success_blob = bucket.blob(success_file)
        success_blob.upload_from_string(
            json.dumps(success_data, indent=2),
            content_type="application/json"
        )

        # Write lightweight stations.json for fast API serving (same data as training labels)
        try:
            df = daily_table.to_pandas()
            pm25_col = "pm25_ugm3_mean" if "pm25_ugm3_mean" in df.columns else None
            lat_col = next((c for c in ["latitude", "lat"] if c in df.columns), None)
            lon_col = next((c for c in ["longitude", "lon"] if c in df.columns), None)
            hours_col = "pm25_ugm3_valid_hours" if "pm25_ugm3_valid_hours" in df.columns else None

            if pm25_col and lat_col and lon_col:
                valid = df.dropna(subset=[pm25_col, lat_col, lon_col])
                if hours_col:
                    valid = valid[valid[hours_col] >= DEFAULT_MIN_PUBLISH_HOURS]

                station_records = []
                for _, row in valid.iterrows():
                    station_records.append({
                        "name": str(row.get("station_name", "")),
                        "city": str(row.get("city_name", "")),
                        "lat": round(float(row[lat_col]), 5),
                        "lon": round(float(row[lon_col]), 5),
                        "pm25": round(float(row[pm25_col]), 1),
                        "valid_hours": int(row[hours_col]) if hours_col and not pd.isna(row.get(hours_col)) else None,
                        "complete": bool(row.get("pm25_ugm3_complete", 0)),
                    })

                stations_json = {
                    "date": target_date.isoformat(),
                    "stations": station_records,
                    "count": len(station_records),
                }
                stations_blob = bucket.blob(f"{partition_dir}/stations.json")
                stations_blob.upload_from_string(
                    json.dumps(stations_json),
                    content_type="application/json"
                )
                logger.info(f"Wrote stations.json: {len(station_records)} stations")
        except Exception as e:
            logger.warning(f"Failed to write stations.json for {target_date}: {e}")

        logger.info(f"Uploaded daily partition: {parquet_file}")

        return {
            "uploaded": True,
            "date": target_date.isoformat(),
            "rows": len(daily_table),
            "uri": f"gs://{bucket_name}/{parquet_file}",
        }

    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# --------------------------------------------------------------------------------------
# Publish "latest" Parquet to GCS (single object, rewritten daily)
# --------------------------------------------------------------------------------------
@router.post("/station-readings-hourly-parquet")
async def publish_station_readings_hourly_parquet_to_gcs(
    request: Request,
    db: AsyncSession = Depends(get_database),

    # Default: publish "everything" unless you override
    days_back: Optional[int] = Query(
        MAX_DAYS_BACK,
        description=f"Days of history to include (default: {MAX_DAYS_BACK} i.e. ~10 years)",
    ),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),

    # filters (optional)
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    station_id: Optional[list[str]] = Query(None),
    provider: Optional[list[str]] = Query(None),

    # content selection
    parameters: Optional[str] = Query(
        "all",
        description="Pollutants to include in the published parquet. Default: all",
    ),

    # safety
    max_rows: Optional[int] = Query(None),

    # GCS target (optional overrides)
    gcs_bucket: Optional[str] = Query(None, description="Override bucket (else env GCS_EXPORT_BUCKET)"),
    gcs_object: Optional[str] = Query(None, description="Override object key (else env GCS_EXPORT_OBJECT)"),

    _: bool = Depends(verify_tasks_token),
):
    """
    Builds a single hourly Parquet file and uploads it to GCS, overwriting the target object.

    Intended to be called by a daily automation (Cloud Scheduler / Cron / GitHub Action / etc.).
    """
    request_id = uuid.uuid4().hex[:12]
    client_ip = getattr(getattr(request, "client", None), "host", None) or "unknown"
    t0 = time.perf_counter()

    bucket = (gcs_bucket or DEFAULT_GCS_BUCKET).strip()
    obj = (gcs_object or DEFAULT_GCS_OBJECT).strip()
    if not bucket:
        raise HTTPException(status_code=500, detail="GCS_EXPORT_BUCKET is not set (and no gcs_bucket provided).")
    if not obj:
        raise HTTPException(status_code=500, detail="GCS_EXPORT_OBJECT is empty (and no gcs_object provided).")

    # Use the same export function by calling the GET handler logic internally would be messy;
    # instead we re-run the key steps here (station list + per-station query + parquet writer).
    start_ts, end_ts = validate_and_compute_time_range(days_back=days_back, start_date=start_date, end_date=end_date)

    effective_max_rows = max_rows if max_rows is not None else MAX_EXPORT_ROWS_HARD_CAP
    if effective_max_rows < 1:
        raise HTTPException(status_code=400, detail="max_rows must be >= 1")
    if effective_max_rows > MAX_EXPORT_ROWS_HARD_CAP:
        effective_max_rows = MAX_EXPORT_ROWS_HARD_CAP

    station_ids = _split_multi(station_id)
    provider_codes = [p.strip().lower() for p in _split_multi(provider)]
    selected_pollutants = parse_parameters_param(parameters)
    pollutant_selects, pollutant_headers = build_pollutant_selects_hourly(selected_pollutants)

    logger.info(
        f"[{request_id}] PUBLISH START client={client_ip} "
        f"gcs=gs://{bucket}/{obj} range={start_ts.isoformat()}→{end_ts.isoformat()} "
        f"province={province or 'ALL'} city={city or 'ALL'} "
        f"stations={'ALL' if not station_ids else len(station_ids)} providers={provider_codes or 'ALL'} "
        f"pollutants={','.join(selected_pollutants)} max_rows={effective_max_rows}"
    )

    # Build optimized single query for all stations (replaces N+1 pattern)
    all_stations_query, base_params = _build_all_stations_hourly_query(
        pollutant_selects=pollutant_selects,
        province=province,
        city=city,
        station_ids=station_ids,
        provider_codes=provider_codes,
    )

    pa, pq = _require_pyarrow()

    # Arrow schema
    fields = [
        pa.field("station_id", pa.string()),
        pa.field("station_name", pa.string()),
        pa.field("latitude", pa.float64()),
        pa.field("longitude", pa.float64()),
        pa.field("city_name", pa.string()),
        pa.field("state_name", pa.string()),
        pa.field("country_name", pa.string()),
        pa.field("timestamp_utc", pa.timestamp("ms", tz="UTC")),
        pa.field("aqi_us", pa.int32()),
        pa.field("provider_name", pa.string()),
    ]
    for pcol in pollutant_headers:
        fields.append(pa.field(pcol, pa.float64()))
    schema = pa.schema(fields)

    fd, tmp_path = tempfile.mkstemp(prefix="hawanama_publish_", suffix=".parquet")
    os.close(fd)

    total_rows = 0
    batch_rows: list[dict[str, Any]] = []
    writer = None
    truncated = False

    try:
        writer = pq.ParquetWriter(
            tmp_path,
            schema=schema,
            compression="snappy",
            use_dictionary=True,
        )

        # Single optimized query for ALL stations (no LIMIT in query - we enforce here)
        query_params = {
            **base_params,
            "start_ts": start_ts,
            "end_ts": end_ts,
        }

        # Use injected db session
        result = await db.stream(all_stations_query, query_params)

        async for row in result:
            # Check if we've hit the hard cap
            if total_rows >= effective_max_rows:
                truncated = True
                logger.warning(f"[{request_id}] Hit max_rows limit ({effective_max_rows}), truncating")
                break

            rec: dict[str, Any] = {
                "station_id": str(row.station_id) if row.station_id else "",
                "station_name": row.station_name or "",
                "latitude": float(row.latitude) if row.latitude is not None else None,
                "longitude": float(row.longitude) if row.longitude is not None else None,
                "city_name": row.city_name or "",
                "state_name": row.state_name or "",
                "country_name": row.country_name or "",
                "timestamp_utc": row.timestamp_utc,
                "aqi_us": None if row.aqi_us is None else int(round(row.aqi_us)),
                "provider_name": row.provider_name or "",
            }
            for col in pollutant_headers:
                v = getattr(row, col, None)
                rec[col] = None if v is None else float(v)
            batch_rows.append(rec)

            total_rows += 1

            if len(batch_rows) >= PARQUET_BATCH_ROWS:
                table = pa.Table.from_pylist(batch_rows, schema=schema)
                writer.write_table(table)
                batch_rows.clear()

        if batch_rows:
            table = pa.Table.from_pylist(batch_rows, schema=schema)
            writer.write_table(table)
            batch_rows.clear()

    except Exception as e:
        logger.error(f"[{request_id}] Failed building parquet: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to publish parquet") from e
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass

    # Fail if truncated - don't upload partial data
    if truncated:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Export truncated at {effective_max_rows} rows. Use date filters to reduce scope."
        )

    # Upload to GCS
    storage = _require_gcs()
    try:
        t_up0 = time.perf_counter()
        client = storage.Client()
        b = client.bucket(bucket)
        blob = b.blob(obj)

        # Optional: encourage clients to revalidate
        blob.cache_control = "no-cache"

        blob.upload_from_filename(tmp_path, content_type="application/octet-stream")
        dt_up = time.perf_counter() - t_up0
    except Exception as e:
        logger.error(f"[{request_id}] GCS upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Parquet built but GCS upload failed") from e
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    dt_all = time.perf_counter() - t0
    gs_uri = f"gs://{bucket}/{obj}"

    logger.info(
        f"[{request_id}] PUBLISH DONE rows={total_rows:,} upload_dt={dt_up:.2f}s total_dt={dt_all:.2f}s uri={gs_uri}"
    )

    return JSONResponse(
        {
            "ok": True,
            "request_id": request_id,
            "gs_uri": gs_uri,
            "rows": total_rows,
            "range": {"start_ts": start_ts.isoformat(), "end_ts": end_ts.isoformat()},
            "pollutants": selected_pollutants,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


# --------------------------------------------------------------------------------------
# Partitioned Parquet Publisher (date-partitioned dataset on GCS)
# --------------------------------------------------------------------------------------
@router.post("/station-readings-hourly-parquet-partitioned")
async def publish_station_readings_hourly_parquet_partitioned_to_gcs(
    request: Request,
    db: AsyncSession = Depends(get_database),

    # Choose a date range OR a default "yesterday" run
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    days_back: int = Query(1, description="If start_date/end_date not given, publish last N complete days (default 1)"),

    # filters (optional)
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    station_id: Optional[list[str]] = Query(None),
    provider: Optional[list[str]] = Query(None),

    parameters: Optional[str] = Query("all"),
    max_rows: Optional[int] = Query(None),

    # GCS target base
    gcs_bucket: Optional[str] = Query(None),
    gcs_prefix: str = Query(DEFAULT_HOURLY_PREFIX, description="Dataset prefix for hourly partitions"),
    overwrite: bool = Query(False, description="If false, skip dates that already have _SUCCESS.json"),

    _: bool = Depends(verify_tasks_token),
):
    """
    Writes a partitioned Parquet dataset:
      gs://<bucket>/<prefix>/date=YYYY-MM-DD/part-<runid>.parquet
      gs://<bucket>/<prefix>/date=YYYY-MM-DD/_SUCCESS.json
    """
    request_id = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()

    bucket = (gcs_bucket or DEFAULT_GCS_BUCKET).strip()
    prefix = gcs_prefix.strip().strip("/")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing GCS bucket")

    # --- compute range ---
    if start_date and end_date:
        start_ts = parse_date_yyyy_mm_dd(start_date)
        end_ts = parse_date_yyyy_mm_dd(end_date) + timedelta(days=1)  # exclusive
    else:
        # publish last N complete days (end at today's 00:00 UTC)
        today0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end_ts = today0
        start_ts = end_ts - timedelta(days=days_back)

    # safety rows
    effective_max_rows = max_rows if max_rows is not None else MAX_EXPORT_ROWS_HARD_CAP
    if effective_max_rows > MAX_EXPORT_ROWS_HARD_CAP:
        effective_max_rows = MAX_EXPORT_ROWS_HARD_CAP
    if effective_max_rows < 1:
        raise HTTPException(status_code=400, detail="max_rows must be >= 1")

    # filters
    station_ids = _split_multi(station_id)
    provider_codes = [p.strip().lower() for p in _split_multi(provider)]
    selected_pollutants = parse_parameters_param(parameters)
    pollutant_selects, pollutant_headers = build_pollutant_selects_hourly(selected_pollutants)

    logger.info(
        f"[{request_id}] PARTITIONED PUBLISH START bucket=gs://{bucket}/{prefix} "
        f"range={start_ts.isoformat()}→{end_ts.isoformat()} overwrite={overwrite}"
    )

    # Build optimized single query for all stations (replaces N+1 pattern)
    all_stations_query, base_params = _build_all_stations_hourly_query(
        pollutant_selects=pollutant_selects,
        province=province,
        city=city,
        station_ids=station_ids,
        provider_codes=provider_codes,
    )

    pa, pq = _require_pyarrow()
    storage = _require_gcs()
    gcs_client = storage.Client()
    bkt = gcs_client.bucket(bucket)

    # Arrow schema
    fields = [
        pa.field("station_id", pa.string()),
        pa.field("station_name", pa.string()),
        pa.field("latitude", pa.float64()),
        pa.field("longitude", pa.float64()),
        pa.field("city_name", pa.string()),
        pa.field("state_name", pa.string()),
        pa.field("country_name", pa.string()),
        pa.field("timestamp_utc", pa.timestamp("ms", tz="UTC")),
        pa.field("aqi_us", pa.int32()),
        pa.field("provider_name", pa.string()),
    ]
    for pcol in pollutant_headers:
        fields.append(pa.field(pcol, pa.float64()))
    schema = pa.schema(fields)

    days = _daterange_days(start_ts, end_ts)

    published = []
    skipped = []
    errors = []

    for d in days:
        day_start, day_end = _day_bounds_utc(d)
        part_dir = f"{prefix}/date={d.isoformat()}"
        success_obj = f"{part_dir}/_SUCCESS.json"

        if not overwrite and bkt.blob(success_obj).exists(gcs_client):
            skipped.append(d.isoformat())
            continue

        run_id = uuid.uuid4().hex[:8]
        part_obj = f"{part_dir}/part-{run_id}.parquet"

        fd, tmp_path = tempfile.mkstemp(prefix=f"hawanama_part_{d.isoformat()}_", suffix=".parquet")
        os.close(fd)

        total_rows = 0
        batch_rows: list[dict[str, Any]] = []
        writer = None
        truncated = False

        try:
            writer = pq.ParquetWriter(tmp_path, schema=schema, compression="snappy", use_dictionary=True)

            # Single optimized query for ALL stations for this day (no LIMIT in query)
            query_params = {
                **base_params,
                "start_ts": max(start_ts, day_start),
                "end_ts": min(end_ts, day_end),
            }

            # Use injected db session
            result = await db.stream(all_stations_query, query_params)

            async for row in result:
                # Check if we've hit the hard cap
                if total_rows >= effective_max_rows:
                    truncated = True
                    logger.warning(f"[{request_id}] Date {d.isoformat()} hit max_rows limit ({effective_max_rows})")
                    break

                rec = {
                    "station_id": str(row.station_id) if row.station_id else "",
                    "station_name": row.station_name or "",
                    "latitude": float(row.latitude) if row.latitude is not None else None,
                    "longitude": float(row.longitude) if row.longitude is not None else None,
                    "city_name": row.city_name or "",
                    "state_name": row.state_name or "",
                    "country_name": row.country_name or "",
                    "timestamp_utc": row.timestamp_utc,
                    "aqi_us": None if row.aqi_us is None else int(round(row.aqi_us)),
                    "provider_name": row.provider_name or "",
                }
                for col in pollutant_headers:
                    v = getattr(row, col, None)
                    rec[col] = None if v is None else float(v)

                batch_rows.append(rec)
                total_rows += 1

                if len(batch_rows) >= PARQUET_BATCH_ROWS:
                    writer.write_table(pa.Table.from_pylist(batch_rows, schema=schema))
                    batch_rows.clear()

            if batch_rows:
                writer.write_table(pa.Table.from_pylist(batch_rows, schema=schema))
                batch_rows.clear()

            writer.close()
            writer = None

            # If truncated, fail this day - don't upload partial data
            if truncated:
                errors.append({
                    "date": d.isoformat(),
                    "error": f"truncated_at_{effective_max_rows}_rows"
                })
                continue

            # upload parquet
            blob = bkt.blob(part_obj)
            blob.cache_control = "no-cache"
            blob.upload_from_filename(tmp_path, content_type="application/octet-stream")

            # success marker last
            success_payload = {
                "date": d.isoformat(),
                "ok": True,
                "rows": total_rows,
                "parquet": f"gs://{bucket}/{part_obj}",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "run_id": run_id,
                "range": {"start_ts": max(start_ts, day_start).isoformat(), "end_ts": min(end_ts, day_end).isoformat()},
                "pollutants": selected_pollutants,
            }

            with tempfile.NamedTemporaryFile(
                mode="w", prefix=f"hawanama_success_{d.isoformat()}_", suffix=".json",
                delete=False, encoding="utf-8",
            ) as f:
                tmp_success = f.name
                json.dump(success_payload, f)
                f.write("\n")
            bkt.blob(success_obj).upload_from_filename(tmp_success, content_type="application/json")
            os.unlink(tmp_success)

            published.append({"date": d.isoformat(), "rows": total_rows, "uri": f"gs://{bucket}/{part_obj}"})

        except Exception as e:
            logger.error(f"[{request_id}] Failed date={d.isoformat()}: {e}", exc_info=True)
            errors.append({"date": d.isoformat(), "error": str(e)})
        finally:
            try:
                if writer is not None:
                    writer.close()
            except Exception:
                pass
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    dt_all = time.perf_counter() - t0
    return JSONResponse(
        {
            "ok": len(errors) == 0,
            "request_id": request_id,
            "bucket": bucket,
            "prefix": prefix,
            "published": published,
            "skipped": skipped,
            "errors": errors,
            "elapsed_s": round(dt_all, 3),
        }
    )


# --------------------------------------------------------------------------------------
# Daily Aggregation Pipeline (reads hourly GCS partitions → writes daily GCS partitions)
# --------------------------------------------------------------------------------------
@router.post("/station-daily/parquet")
async def publish_station_daily_parquet(
    request: Request,
    date: Optional[str] = Query(None, description="Single date YYYY-MM-DD"),
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD (for range)"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD (for range)"),
    overwrite: bool = Query(False, description="Overwrite existing partitions"),
    only_missing: bool = Query(True, description="Skip dates with existing _SUCCESS markers"),
    min_hours: int = Query(DEFAULT_MIN_HOURS, description="Minimum hours for complete day"),
    apply_qc: bool = Query(True, description="Apply station anomaly QA filters"),
    gcs_bucket: Optional[str] = Query(None, description="Override GCS bucket"),
    hourly_prefix: Optional[str] = Query(None, description="Override hourly prefix"),
    daily_prefix: Optional[str] = Query(None, description="Override daily prefix"),
    _: bool = Depends(verify_tasks_token),
):
    """
    Aggregate hourly station readings to daily with QA filters.

    Pipeline:
    1. Reads: gs://<bucket>/<hourly_prefix>/date=YYYY-MM-DD/ (hourly Parquet partitions)
    2. Aggregates: Daily means, medians, P95, valid hours, completeness flags
    3. Applies QA: Filters out stations with suspiciously low readings
    4. Writes: gs://<bucket>/<daily_prefix>/date=YYYY-MM-DD/station_daily_*.parquet
    5. Marks: gs://<bucket>/<daily_prefix>/date=YYYY-MM-DD/_SUCCESS.json

    Supports:
    - Single date: ?date=2024-01-15
    - Date range: ?start_date=2024-01-01&end_date=2024-01-31
    - Skip existing: ?only_missing=true (default)
    - Overwrite: ?overwrite=true
    - QA control: ?apply_qc=true (default), ?min_hours=18 (default)
    """
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex[:8]

    # Validate inputs
    bucket_name = gcs_bucket or DEFAULT_GCS_BUCKET
    hourly_pfx = hourly_prefix or DEFAULT_HOURLY_PREFIX
    daily_pfx = daily_prefix or DEFAULT_DAILY_PREFIX

    # Determine date range
    dates_to_process = []

    if date:
        # Single date mode
        try:
            target_date = parse_date_yyyy_mm_dd(date).date()
            dates_to_process = [target_date]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {date}")

    elif start_date and end_date:
        # Range mode
        try:
            start_d = parse_date_yyyy_mm_dd(start_date).date()
            end_d = parse_date_yyyy_mm_dd(end_date).date()

            if start_d > end_d:
                raise HTTPException(status_code=400, detail="start_date must be <= end_date")

            # Generate date range
            cur = start_d
            while cur <= end_d:
                dates_to_process.append(cur)
                cur = cur + timedelta(days=1)

        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'date' or 'start_date' + 'end_date'"
        )

    if not dates_to_process:
        raise HTTPException(status_code=400, detail="No dates to process")

    logger.info(
        f"[{run_id}] DAILY AGGREGATION START bucket=gs://{bucket_name} "
        f"hourly={hourly_pfx} daily={daily_pfx} dates={len(dates_to_process)} "
        f"overwrite={overwrite} only_missing={only_missing} min_hours={min_hours} apply_qc={apply_qc}"
    )

    # Initialize GCS client
    storage = _require_gcs()
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Process each date
    published = []
    skipped = []
    errors = []

    for target_date in dates_to_process:
        try:
            # Check if already exists
            success_path = f"{daily_pfx}/date={target_date.isoformat()}/_SUCCESS.json"

            if only_missing and not overwrite:
                if bucket.blob(success_path).exists(client):
                    logger.info(f"Skipping {target_date}: already exists")
                    skipped.append(target_date.isoformat())
                    continue

            # Read hourly partition
            hourly_table = read_hourly_partition_from_gcs(target_date, bucket_name, hourly_pfx)

            if hourly_table is None:
                logger.warning(f"No hourly data for {target_date}")
                errors.append({
                    "date": target_date.isoformat(),
                    "error": "missing_hourly_partition"
                })
                continue

            # Aggregate to daily
            daily_table, stats = aggregate_hourly_to_daily(
                hourly_table,
                target_date,
                min_hours=min_hours,
                apply_qc=apply_qc,
            )

            if len(daily_table) == 0:
                logger.warning(f"Empty daily table for {target_date}")
                errors.append({
                    "date": target_date.isoformat(),
                    "error": "empty_after_aggregation"
                })
                continue

            # Upload
            upload_result = upload_daily_partition_to_gcs(
                target_date,
                daily_table,
                bucket_name,
                daily_pfx,
                run_id,
                stats=stats,
                min_hours=min_hours,
                apply_qc=apply_qc,
            )

            if upload_result["uploaded"]:
                published.append({
                    "date": target_date.isoformat(),
                    "rows": upload_result["rows"],
                    "uri": upload_result["uri"],
                    "stats": stats,
                })

        except Exception as e:
            logger.error(f"[{run_id}] Error processing {target_date}: {e}", exc_info=True)
            errors.append({
                "date": target_date.isoformat(),
                "error": str(e)
            })

    elapsed = time.perf_counter() - t0

    logger.info(
        f"[{run_id}] DAILY AGGREGATION DONE published={len(published)} skipped={len(skipped)} "
        f"errors={len(errors)} elapsed={elapsed:.2f}s"
    )

    return JSONResponse({
        "ok": len(errors) == 0,
        "request_id": run_id,
        "bucket": bucket_name,
        "hourly_prefix": hourly_pfx,
        "daily_prefix": daily_pfx,
        "published": published,
        "skipped": skipped,
        "errors": errors,
        "elapsed_s": round(elapsed, 3),
    })
