"""
CSV + Parquet Export Endpoints for Historical Data (Hourly)

Provides export functionality for:
- Station-level readings (MULTIFUNCTIONAL, hourly-only, station-by-station for CSV)
- City-level readings (legacy CSV)
- Publish a *single* hourly Parquet file to GCS (daily refresh pattern)

Key decisions (per your latest direction):
- We assume data_type is ONLY hourly (no raw/daily).
- Stakeholders can still download CSV via the API.
- "Canonical shared artifact" is a single Parquet object on GCS, rewritten daily:
    gs://<bucket>/exports/station_readings_hourly_latest.parquet

Notes:
- Parquet cannot be truly "streamed" to the client like CSV because it needs a footer.
  So for `format=parquet`, we write to a temp file incrementally (batch-by-batch),
  then stream the finished file to the client (or upload to GCS).
- For "append last day" into the same Parquet file: Parquet is not append-friendly on
  object storage in a safe way. The simplest robust approach is "rewrite latest file daily".
  (If you later want true append, switch to a partitioned dataset layout.)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam
from app.core.database import get_database, SessionLocal
from app.core.security import verify_tasks_token

from typing import Optional, Iterable, Any
import logging
import io
import csv
import uuid
import time
import os
import tempfile
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
router = APIRouter()

# -----------------------------
# Export limits / constants
# -----------------------------
MAX_DAYS_BACK = 3650  # ~10 years
DEFAULT_DAYS_BACK = 1

MAX_EXPORT_ROWS_DEFAULT = 500_000
MAX_EXPORT_ROWS_HARD_CAP = 5_000_000

STREAM_FLUSH_EVERY_ROWS = 500  # yield every N rows (tune: 200–2000)
CSV_ENCODING = "utf-8"

# Parquet batching (controls memory)
PARQUET_BATCH_ROWS = 50_000  # write row-groups around this size

# Default GCS "latest file" target (override via env)
DEFAULT_GCS_BUCKET = os.getenv("GCS_EXPORT_BUCKET", "paqi-raw-hawanama-data").strip()
DEFAULT_GCS_OBJECT = os.getenv(
    "GCS_EXPORT_OBJECT",
    "raw/station_readings_hourly_latest.parquet"
).strip()

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
        days_back = DEFAULT_DAYS_BACK
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


def _iter_file_bytes(path: str, chunk_size: int = 1024 * 1024) -> Iterable[bytes]:
    """
    Streams a local file in chunks. Safe for large files.
    """
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


# -----------------------------
# Core station list + per-station hourly query builders
# -----------------------------
def _build_station_list_query(
    province: Optional[str],
    city: Optional[str],
    station_ids: list[str],
    provider_codes: list[str],
):
    where_station = ["1=1"]  # allow all stations unless filtered
    if province:
        where_station.append("LOWER(COALESCE(st.name,'')) = LOWER(:province)")
    if city:
        where_station.append("LOWER(COALESCE(c.name,'')) = LOWER(:city)")
    if station_ids:
        where_station.append("s.station_id IN :station_ids")
    if provider_codes:
        where_station.append("LOWER(COALESCE(p.code,'')) IN :provider_codes")

    station_where_sql = " AND ".join(where_station)

    stations_sql = f"""
        SELECT
            s.station_id,
            COALESCE(s.name, 'Unknown Station') AS station_name,
            COALESCE(s.lat, 0) AS latitude,
            COALESCE(s.lon, 0) AS longitude,
            COALESCE(c.name, 'Unknown City') AS city_name,
            COALESCE(st.name, 'Unknown State') AS state_name,
            COALESCE(co.name, 'Unknown Country') AS country_name,
            COALESCE(p.code, 'unknown') AS provider_code,
            COALESCE(p.display_name, 'Unknown Provider') AS provider_name
        FROM stations s
        LEFT JOIN providers p ON s.provider_id = p.id
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN states st ON c.state_id = st.id
        LEFT JOIN countries co ON st.country_id = co.id
        WHERE {station_where_sql}
        ORDER BY COALESCE(s.name, 'Unknown Station'), s.station_id
    """
    q = text(stations_sql)

    if station_ids:
        q = q.bindparams(bindparam("station_ids", expanding=True))
    if provider_codes:
        q = q.bindparams(bindparam("provider_codes", expanding=True))

    params: dict[str, Any] = {}
    if province:
        params["province"] = province
    if city:
        params["city"] = city
    if station_ids:
        params["station_ids"] = station_ids
    if provider_codes:
        params["provider_codes"] = provider_codes

    return q, params


def _build_station_hourly_query(pollutant_selects: list[str]):
    bucket_expr = "time_bucket('1 hour', r.ts_utc, 'UTC')"

    readings_selects = [
        f"{bucket_expr} AS timestamp_utc",
        "AVG(r.aqi_us) AS aqi_us",
    ] + pollutant_selects

    readings_select_sql = ",\n            ".join(readings_selects)

    station_hourly_sql = f"""
        SELECT
            {readings_select_sql}
        FROM readings r
        WHERE r.scope_type = 'station'
            AND r.scope_key = :station_id
            AND r.ts_utc >= :start_ts
            AND r.ts_utc < :end_ts
        GROUP BY {bucket_expr}
        ORDER BY {bucket_expr} ASC
        LIMIT :limit_rows
    """
    return text(station_hourly_sql)


# --------------------------------------------------------------------------------------
# Station export: CSV (streamed station-by-station) OR Parquet (built to temp file)
# --------------------------------------------------------------------------------------
@router.get("/station-readings-csv")
async def export_station_readings_hourly(
    request: Request,
    db: AsyncSession = Depends(get_database),

    # --- time range ---
    days_back: Optional[int] = Query(
        DEFAULT_DAYS_BACK,
        description=f"Number of days back from now (default: {DEFAULT_DAYS_BACK}, max: {MAX_DAYS_BACK})",
    ),
    start_date: Optional[str] = Query(
        None, description="Start date in YYYY-MM-DD format (overrides days_back)", example="2024-01-01"
    ),
    end_date: Optional[str] = Query(
        None, description="End date in YYYY-MM-DD format (requires start_date)", example="2024-12-31"
    ),

    # --- filters ---
    province: Optional[str] = Query(None, description="Filter stations by province/state name (e.g., Punjab)"),
    city: Optional[str] = Query(None, description="Filter stations by city name (e.g., Lahore)"),
    station_id: Optional[list[str]] = Query(
        None,
        description="Filter by station_id. Can repeat (?station_id=A&station_id=B) or comma-separate (?station_id=A,B).",
    ),
    provider: Optional[list[str]] = Query(
        None,
        description="Filter by provider code(s) (providers.code). Can repeat or comma-separate.",
    ),

    # --- selection / mode ---
    parameters: Optional[str] = Query(
        None,
        description="Pollutants to include: 'all' or comma-separated (pm25,pm10,no2,so2,co,o3). Aliases: pm2.5, carbon_monoxide.",
    ),
    data_type: str = Query(
        "hourly",
        description="Currently only hourly is supported.",
        pattern="^(hourly)$",
    ),
    format: str = Query(
        "csv",
        description="Output format: csv or parquet",
        pattern="^(csv|parquet)$",
    ),

    # --- safety ---
    max_rows: Optional[int] = Query(
        None,
        description=f"Optional safety cap on rows (default: {MAX_EXPORT_ROWS_DEFAULT}, hard cap: {MAX_EXPORT_ROWS_HARD_CAP})",
    ),

    _: bool = Depends(verify_tasks_token),
):
    """
    Multifunctional station readings export (hourly-only).

    - format=csv:
        * True streaming station-by-station: rows for each station are contiguous.
    - format=parquet:
        * Writes Parquet incrementally to a temp file (batch-by-batch), then streams file to client.
        * (Parquet is not footer-streamable in a clean way.)
    """
    request_id = uuid.uuid4().hex[:12]
    client_ip = getattr(getattr(request, "client", None), "host", None) or "unknown"
    t0 = time.perf_counter()

    # 1) Time range
    start_ts, end_ts = validate_and_compute_time_range(days_back=days_back, start_date=start_date, end_date=end_date)

    # 2) max_rows safety
    effective_max_rows = max_rows if max_rows is not None else MAX_EXPORT_ROWS_DEFAULT
    if effective_max_rows < 1:
        raise HTTPException(status_code=400, detail="max_rows must be >= 1")
    if effective_max_rows > MAX_EXPORT_ROWS_HARD_CAP:
        logger.warning(f"[{request_id}] max_rows={effective_max_rows} exceeds hard cap; clamping to {MAX_EXPORT_ROWS_HARD_CAP}")
        effective_max_rows = MAX_EXPORT_ROWS_HARD_CAP

    # 3) Normalize filters
    station_ids = _split_multi(station_id)
    provider_codes = [p.strip().lower() for p in _split_multi(provider)]

    # 4) Pollutants
    selected_pollutants = parse_parameters_param(parameters)
    pollutant_selects, pollutant_headers = build_pollutant_selects_hourly(selected_pollutants)

    # 5) Log request summary
    logger.info(
        f"[{request_id}] EXPORT START client={client_ip} format={format} "
        f"range={start_ts.isoformat()}→{end_ts.isoformat()} "
        f"days={(end_ts - start_ts).days} "
        f"province={province or 'ALL'} city={city or 'ALL'} "
        f"station_ids={'ALL' if not station_ids else len(station_ids)} "
        f"providers={provider_codes or 'ALL'} "
        f"pollutants={','.join(selected_pollutants)} "
        f"max_rows={effective_max_rows}"
    )

    # 6) Fetch station list
    stations_query, stations_params = _build_station_list_query(
        province=province, city=city, station_ids=station_ids, provider_codes=provider_codes
    )

    try:
        t_st = time.perf_counter()
        res = await db.execute(stations_query, stations_params)
        stations = res.fetchall()
        dt_st = time.perf_counter() - t_st
        logger.info(f"[{request_id}] Stations matched={len(stations)} (lookup {dt_st:.3f}s)")
    except Exception as e:
        logger.error(f"[{request_id}] Failed to fetch station list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export station readings")

    station_id_map = {row.station_id: i + 1 for i, row in enumerate(stations)}

    # Common header/columns
    columns = [
        "id",
        "station_name",
        "latitude",
        "longitude",
        "city_name",
        "state_name",
        "country_name",
        "timestamp_utc",
        "aqi_us",
        "provider_name",
    ] + pollutant_headers

    station_hourly_query = _build_station_hourly_query(pollutant_selects)

    # ---------------------------
    # CSV streaming path
    # ---------------------------
    async def _generate_csv_bytes():
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(columns)
        yield output.getvalue().encode(CSV_ENCODING)
        output.seek(0)
        output.truncate(0)

        if not stations:
            logger.warning(f"[{request_id}] No stations matched; returning header-only CSV")
            return

        total_rows = 0
        t_stream0 = time.perf_counter()

        for idx, s in enumerate(stations, start=1):
            if await request.is_disconnected():
                logger.warning(f"[{request_id}] Client disconnected; stopping export (rows={total_rows:,})")
                break

            remaining = effective_max_rows - total_rows
            if remaining <= 0:
                logger.warning(f"[{request_id}] Hit max_rows={effective_max_rows:,}; stopping export early")
                break

            numeric_id = station_id_map.get(s.station_id, 0)
            station_label = f"{s.station_name} ({s.station_id})"
            t_station0 = time.perf_counter()
            station_rows = 0

            logger.info(f"[{request_id}] Station {idx}/{len(stations)} START {station_label} remaining_rows={remaining:,}")

            async with SessionLocal() as station_session:
                try:
                    result = await station_session.stream(
                        station_hourly_query,
                        {
                            "station_id": s.station_id.strip() if s.station_id else s.station_id,
                            "start_ts": start_ts,
                            "end_ts": end_ts,
                            "limit_rows": remaining,
                        },
                    )

                    async for row in result:
                        if await request.is_disconnected():
                            logger.warning(f"[{request_id}] Client disconnected mid-station; stopping export (rows={total_rows:,})")
                            break

                        base_row = [
                            numeric_id,
                            s.station_name or "",
                            s.latitude or "",
                            s.longitude or "",
                            s.city_name or "",
                            s.state_name or "",
                            s.country_name or "",
                            row.timestamp_utc.isoformat() if row.timestamp_utc else "",
                            "" if row.aqi_us is None else int(round(row.aqi_us)),
                            s.provider_name or "",
                        ]

                        dyn = []
                        for col in pollutant_headers:
                            v = getattr(row, col, None)
                            dyn.append("" if v is None else v)

                        writer.writerow(base_row + dyn)

                        station_rows += 1
                        total_rows += 1

                        if total_rows % STREAM_FLUSH_EVERY_ROWS == 0:
                            yield output.getvalue().encode(CSV_ENCODING)
                            output.seek(0)
                            output.truncate(0)

                    # station boundary flush
                    if output.tell() > 0:
                        yield output.getvalue().encode(CSV_ENCODING)
                        output.seek(0)
                        output.truncate(0)

                    dt_station = time.perf_counter() - t_station0
                    logger.info(
                        f"[{request_id}] Station {idx}/{len(stations)} DONE {station_label} "
                        f"rows={station_rows:,} dt={dt_station:.2f}s total_rows={total_rows:,}"
                    )

                except Exception as e:
                    logger.error(
                        f"[{request_id}] Error exporting station {station_label}: {e} "
                        f"(total_rows_so_far={total_rows:,})",
                        exc_info=True,
                    )
                    yield f"# Export error for station {s.station_id}: {str(e)}\n".encode(CSV_ENCODING)

        dt_total = time.perf_counter() - t_stream0
        dt_all = time.perf_counter() - t0
        rate = (total_rows / dt_total) if dt_total > 0 else 0.0

        logger.info(
            f"[{request_id}] EXPORT DONE format=csv rows={total_rows:,} stations={len(stations)} "
            f"stream_dt={dt_total:.2f}s total_dt={dt_all:.2f}s rate={rate:.0f} rows/s"
        )

    # ---------------------------
    # Parquet path (build then stream)
    # ---------------------------
    async def _build_parquet_to_tempfile() -> str:
        pa, pq = _require_pyarrow()

        if not stations:
            raise HTTPException(status_code=404, detail="No stations matched your filters; nothing to export.")

        # Arrow schema (stable types)
        fields = [
            pa.field("id", pa.int64()),
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

        fd, tmp_path = tempfile.mkstemp(prefix="hawanama_export_", suffix=".parquet")
        os.close(fd)

        total_rows = 0
        batch_rows: list[dict[str, Any]] = []
        t_stream0 = time.perf_counter()

        writer = None
        try:
            writer = pq.ParquetWriter(
                tmp_path,
                schema=schema,
                compression="snappy",  # widely compatible (change to "zstd" if you want more compression)
                use_dictionary=True,
            )

            for idx, s in enumerate(stations, start=1):
                if await request.is_disconnected():
                    logger.warning(f"[{request_id}] Client disconnected; abort parquet build (rows={total_rows:,})")
                    break

                remaining = effective_max_rows - total_rows
                if remaining <= 0:
                    logger.warning(f"[{request_id}] Hit max_rows={effective_max_rows:,}; stopping parquet build early")
                    break

                numeric_id = station_id_map.get(s.station_id, 0)
                station_label = f"{s.station_name} ({s.station_id})"
                t_station0 = time.perf_counter()
                station_rows = 0

                logger.info(f"[{request_id}] [parquet] Station {idx}/{len(stations)} START {station_label}")

                async with SessionLocal() as station_session:
                    result = await station_session.stream(
                        station_hourly_query,
                        {
                            "station_id": s.station_id.strip() if s.station_id else s.station_id,
                            "start_ts": start_ts,
                            "end_ts": end_ts,
                            "limit_rows": remaining,
                        },
                    )

                    async for row in result:
                        # materialize record
                        rec: dict[str, Any] = {
                            "id": int(numeric_id),
                            "station_name": s.station_name or "",
                            "latitude": float(s.latitude) if s.latitude is not None else None,
                            "longitude": float(s.longitude) if s.longitude is not None else None,
                            "city_name": s.city_name or "",
                            "state_name": s.state_name or "",
                            "country_name": s.country_name or "",
                            "timestamp_utc": row.timestamp_utc,  # tz-aware datetime OK
                            "aqi_us": None if row.aqi_us is None else int(round(row.aqi_us)),
                            "provider_name": s.provider_name or "",
                        }
                        for col in pollutant_headers:
                            v = getattr(row, col, None)
                            rec[col] = None if v is None else float(v)
                        batch_rows.append(rec)

                        station_rows += 1
                        total_rows += 1

                        if len(batch_rows) >= PARQUET_BATCH_ROWS:
                            table = pa.Table.from_pylist(batch_rows, schema=schema)
                            writer.write_table(table)
                            batch_rows.clear()

                    dt_station = time.perf_counter() - t_station0
                    logger.info(
                        f"[{request_id}] [parquet] Station {idx}/{len(stations)} DONE {station_label} "
                        f"rows={station_rows:,} dt={dt_station:.2f}s total_rows={total_rows:,}"
                    )

            # flush final batch
            if batch_rows:
                table = pa.Table.from_pylist(batch_rows, schema=schema)
                writer.write_table(table)
                batch_rows.clear()

            dt_total = time.perf_counter() - t_stream0
            dt_all = time.perf_counter() - t0
            rate = (total_rows / dt_total) if dt_total > 0 else 0.0
            logger.info(
                f"[{request_id}] EXPORT DONE format=parquet rows={total_rows:,} stations={len(stations)} "
                f"build_dt={dt_total:.2f}s total_dt={dt_all:.2f}s rate={rate:.0f} rows/s path={tmp_path}"
            )
            return tmp_path

        except Exception as e:
            logger.error(f"[{request_id}] Parquet build failed: {e}", exc_info=True)
            # cleanup
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail="Failed to build Parquet export") from e

        finally:
            if writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass

    # ---------------
    # Return response
    # ---------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_range = f"{start_ts.strftime('%Y%m%d')}_to_{end_ts.strftime('%Y%m%d')}"
    base_name = f"hawanama_station_readings_hourly_{date_range}_{timestamp}"

    if format == "csv":
        filename = f"{base_name}.csv"
        return StreamingResponse(
            _generate_csv_bytes(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Export-Request-Id": request_id,
            },
        )

    # parquet
    tmp_path = await _build_parquet_to_tempfile()
    filename = f"{base_name}.parquet"

    def _stream_and_cleanup():
        try:
            yield from _iter_file_bytes(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return StreamingResponse(
        _stream_and_cleanup(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Export-Request-Id": request_id,
        },
    )


# --------------------------------------------------------------------------------------
# Legacy endpoints below (CSV only, maintained for backwards compatibility)
# --------------------------------------------------------------------------------------
@router.get("/city-readings-csv")
async def export_city_readings_csv(
    request: Request,
    db: AsyncSession = Depends(get_database),
    days_back: Optional[int] = Query(
        DEFAULT_DAYS_BACK,
        description=f"Number of days back from now (default: {DEFAULT_DAYS_BACK}, max: {MAX_DAYS_BACK})",
    ),
    _: bool = Depends(verify_tasks_token),
):
    """
    Export all city-level readings as CSV (legacy).
    """
    start_ts, end_ts = validate_and_compute_time_range(days_back=days_back)
    logger.info(f"Exporting city readings CSV from {start_ts} to {end_ts}")

    query = text(
        """
        SELECT
            r.scope_key,
            (STRING_TO_ARRAY(r.scope_key, '|'))[3] as city_name,
            (STRING_TO_ARRAY(r.scope_key, '|'))[2] as state_name,
            (STRING_TO_ARRAY(r.scope_key, '|'))[1] as country_name,
            r.ts_utc as timestamp_utc,
            r.pm25,
            r.temp_c as temperature_celsius,
            r.humidity as humidity_percent,
            r.pressure_hpa as pressure_hpa,
            r.wind_speed_ms as wind_speed_ms,
            r.wind_dir_deg as wind_direction_degrees,
            r.heatindex_c as heat_index_celsius,
            r.weather_icon,
            r.qc_state,
            r.source,
            r.units_pm25
        FROM readings r
        WHERE r.scope_type = 'city'
            AND r.ts_utc >= :start_ts
            AND r.ts_utc < :end_ts
        ORDER BY r.scope_key, r.ts_utc ASC
        LIMIT :max_rows
        """
    )

    params = {"start_ts": start_ts, "end_ts": end_ts, "max_rows": MAX_EXPORT_ROWS_DEFAULT}

    async def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)

        header = [
            "scope_key",
            "city_name",
            "state_name",
            "country_name",
            "timestamp_utc",
            "pm25_ugm3",
            "temperature_celsius",
            "humidity_percent",
            "pressure_hpa",
            "wind_speed_ms",
            "wind_direction_degrees",
            "heat_index_celsius",
            "weather_icon",
            "qc_state",
            "source",
            "pm25_units",
        ]
        writer.writerow(header)
        yield output.getvalue().encode(CSV_ENCODING)
        output.seek(0)
        output.truncate(0)

        try:
            result = await db.stream(query, params)
            async for row in result:
                if await request.is_disconnected():
                    logger.warning("Client disconnected during city export; stopping early")
                    break

                writer.writerow(
                    [
                        row.scope_key or "",
                        row.city_name or "",
                        row.state_name or "",
                        row.country_name or "",
                        row.timestamp_utc.isoformat() if row.timestamp_utc else "",
                        "" if row.pm25 is None else row.pm25,
                        "" if row.temperature_celsius is None else row.temperature_celsius,
                        "" if row.humidity_percent is None else row.humidity_percent,
                        "" if row.pressure_hpa is None else row.pressure_hpa,
                        "" if row.wind_speed_ms is None else row.wind_speed_ms,
                        "" if row.wind_direction_degrees is None else row.wind_direction_degrees,
                        "" if row.heat_index_celsius is None else row.heat_index_celsius,
                        row.weather_icon or "",
                        row.qc_state or "",
                        row.source or "",
                        row.units_pm25 or "",
                    ]
                )

                if output.tell() > 0:
                    yield output.getvalue().encode(CSV_ENCODING)
                    output.seek(0)
                    output.truncate(0)

        except Exception as e:
            logger.error(f"Error exporting city readings CSV: {e}", exc_info=True)
            yield f"# Export error: {str(e)}\n".encode(CSV_ENCODING)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_range = f"{start_ts.strftime('%Y%m%d')}_to_{end_ts.strftime('%Y%m%d')}"
    filename = f"hawanama_city_readings_{date_range}_{timestamp}.csv"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/station-readings-by-city-csv/{city}")
async def export_station_readings_by_city_csv(
    request: Request,
    city: str = Path(..., description="City name", example="Lahore"),
    db: AsyncSession = Depends(get_database),
    days_back: Optional[int] = Query(DEFAULT_DAYS_BACK),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    _: bool = Depends(verify_tasks_token),
):
    """
    Legacy: station readings for a specific city as CSV (raw-ish).
    Prefer using /station-readings-csv with city=... now.
    """
    start_ts, end_ts = validate_and_compute_time_range(days_back=days_back, start_date=start_date, end_date=end_date)

    query = text(
        """
        SELECT
            r.scope_key as station_id,
            COALESCE(s.name, 'Unknown Station') as station_name,
            COALESCE(s.lat, 0) as latitude,
            COALESCE(s.lon, 0) as longitude,
            COALESCE(c.name, 'Unknown City') as city_name,
            COALESCE(st.name, 'Unknown State') as state_name,
            COALESCE(co.name, 'Unknown Country') as country_name,
            r.ts_utc as timestamp_utc,
            r.pm25,
            r.aqi_us,
            r.aqi_cn,
            r.main_us,
            r.main_cn,
            r.temp_c as temperature_celsius,
            r.humidity as humidity_percent,
            r.pressure_hpa,
            r.wind_speed_ms,
            r.wind_dir_deg as wind_direction_degrees,
            r.heatindex_c as heat_index_celsius,
            r.weather_icon,
            r.qc_state,
            COALESCE(p.code, r.source) as provider_code,
            COALESCE(p.display_name, r.source) as provider_name,
            r.units_pm25
        FROM readings r
        LEFT JOIN stations s ON r.scope_key = s.station_id
        LEFT JOIN providers p ON s.provider_id = p.id
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN states st ON c.state_id = st.id
        LEFT JOIN countries co ON st.country_id = co.id
        WHERE r.scope_type = 'station'
            AND LOWER(COALESCE(c.name, '')) = LOWER(:city_name)
            AND r.ts_utc >= :start_ts
            AND r.ts_utc < :end_ts
        ORDER BY r.scope_key, r.ts_utc ASC
        LIMIT :max_rows
        """
    )

    params = {
        "city_name": city,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "max_rows": MAX_EXPORT_ROWS_DEFAULT,
    }

    async def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)

        header = [
            "station_id",
            "station_name",
            "latitude",
            "longitude",
            "city_name",
            "state_name",
            "country_name",
            "timestamp_utc",
            "pm25_ugm3",
            "aqi_us",
            "aqi_cn",
            "main_pollutant_us",
            "main_pollutant_cn",
            "temperature_celsius",
            "humidity_percent",
            "pressure_hpa",
            "wind_speed_ms",
            "wind_direction_degrees",
            "heat_index_celsius",
            "weather_icon",
            "qc_state",
            "provider_code",
            "provider_name",
            "pm25_units",
        ]
        writer.writerow(header)
        yield output.getvalue().encode(CSV_ENCODING)
        output.seek(0)
        output.truncate(0)

        try:
            result = await db.stream(query, params)
            async for row in result:
                if await request.is_disconnected():
                    logger.warning("Client disconnected during city station export; stopping early")
                    break

                writer.writerow(
                    [
                        row.station_id or "",
                        row.station_name or "",
                        row.latitude or "",
                        row.longitude or "",
                        row.city_name or "",
                        row.state_name or "",
                        row.country_name or "",
                        row.timestamp_utc.isoformat() if row.timestamp_utc else "",
                        "" if row.pm25 is None else row.pm25,
                        "" if row.aqi_us is None else row.aqi_us,
                        "" if row.aqi_cn is None else row.aqi_cn,
                        row.main_us or "",
                        row.main_cn or "",
                        "" if row.temperature_celsius is None else row.temperature_celsius,
                        "" if row.humidity_percent is None else row.humidity_percent,
                        "" if row.pressure_hpa is None else row.pressure_hpa,
                        "" if row.wind_speed_ms is None else row.wind_speed_ms,
                        "" if row.wind_direction_degrees is None else row.wind_direction_degrees,
                        "" if row.heat_index_celsius is None else row.heat_index_celsius,
                        row.weather_icon or "",
                        row.qc_state or "",
                        row.provider_code or "",
                        row.provider_name or "",
                        row.units_pm25 or "",
                    ]
                )

                if output.tell() > 0:
                    yield output.getvalue().encode(CSV_ENCODING)
                    output.seek(0)
                    output.truncate(0)

        except Exception as e:
            logger.error(f"Error exporting station readings by city CSV: {e}", exc_info=True)
            yield f"# Export error: {str(e)}\n".encode(CSV_ENCODING)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_range = f"{start_ts.strftime('%Y%m%d')}_to_{end_ts.strftime('%Y%m%d')}"
    safe_city_name = "".join(c for c in city if c.isalnum() or c in (" ", "-", "_")).rstrip().replace(" ", "_")
    filename = f"hawanama_station_readings_{safe_city_name}_{date_range}_{timestamp}.csv"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
