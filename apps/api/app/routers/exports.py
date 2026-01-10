"""
CSV Export Endpoints for Historical Data

Provides CSV export functionality for:
- All station-level readings
- All city-level readings

These endpoints return streaming CSV responses for bulk data download.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam
from app.core.database import get_database
from app.core.security import verify_tasks_token
from typing import Optional
import logging
import io
import csv
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

router = APIRouter()

# Export limits and constants
MAX_DAYS_BACK = 3650  # Allow up to ~10 years of data
MAX_EXPORT_ROWS_DEFAULT_DEFAULT = 500_000  # Default row limit
MAX_EXPORT_ROWS_DEFAULT_HARD_CAP = 5_000_000  # Hard safety cap for debugging
DEFAULT_DAYS_BACK = 1  # Swagger-friendly default
PM25_MAX_DAYS = 3650  # Allow full historical data for PM2.5

STREAM_FLUSH_EVERY_ROWS = 500  # yield every N rows (tune: 200–2000)
CSV_ENCODING = "utf-8"

# Pollutant configuration
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

def parse_date_yyyy_mm_dd(date_str: str) -> datetime:
    """Parse YYYY-MM-DD date string to UTC datetime at start of day"""
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

def _split_multi(values: Optional[list[str]]) -> list[str]:
    """
    FastAPI list params can arrive as:
      ?station_id=A&station_id=B  -> ["A","B"]
    but also people pass:
      ?station_id=A,B             -> ["A,B"]
    This normalizes both.
    """
    if not values:
        return []
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        parts = [p.strip() for p in v.split(",") if p.strip()]
        out.extend(parts)
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
      None -> legacy mode (pm25 only, current behavior)
      "all" -> all supported pollutants
      "pm25,pm10,no2" -> subset
    Accept aliases like carbon_monoxide, pm2.5.
    """
    if parameters is None:
        return ["pm25"]  # legacy default (matches your current export)
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
                detail=f"Invalid parameters entry '{item}'. Allowed: all,{','.join(sorted(ALLOWED_POLLUTANTS))} (aliases: pm2.5, carbon_monoxide)."
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

def build_pollutant_selects(selected: list[str], aggregated: bool) -> tuple[list[str], list[str]]:
    """
    Returns (select_sql_fragments, csv_header_columns) for pollutant values + unit columns.
    Column labels are stable.
    """
    col_map = {
        "pm25": ("pm25", "units_pm25", "pm25_ugm3", "pm25_units"),
        "pm10": ("pm10", "units_pm10", "pm10_ugm3", "pm10_units"),
        "no2":  ("no2",  "units_no2",  "no2",      "no2_units"),
        "so2":  ("so2",  "units_so2",  "so2",      "so2_units"),
        "co":   ("co",   "units_co",   "co",       "co_units"),
        "o3":   ("o3",   "units_o3",   "o3",       "o3_units"),
    }

    selects: list[str] = []
    headers: list[str] = []
    for key in selected:
        val_col, unit_col, out_val, out_unit = col_map[key]

        if aggregated:
            selects.append(f"AVG(r.{val_col}) AS {out_val}")
            selects.append(f"MAX(r.{unit_col}) AS {out_unit}")
        else:
            selects.append(f"r.{val_col} AS {out_val}")
            selects.append(f"r.{unit_col} AS {out_unit}")

        headers.append(out_val)
        headers.append(out_unit)

    return selects, headers

def validate_and_compute_time_range(
    days_back: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> tuple[datetime, datetime]:
    """
    Validate inputs and compute start_ts/end_ts for queries.
    Returns (start_ts, end_ts) where end_ts is exclusive upper bound.
    """
    if start_date and end_date:
        # Use explicit date range, ignore days_back
        try:
            start_ts = parse_date_yyyy_mm_dd(start_date)
            end_ts = parse_date_yyyy_mm_dd(end_date) + timedelta(days=1)  # exclusive upper bound
            
            if start_ts >= end_ts:
                raise HTTPException(status_code=400, detail="start_date must be before end_date")
                
            # Optional: Log large date ranges for monitoring
            if (end_ts - start_ts).days > 365:
                logger.warning(f"Large date range requested: {(end_ts - start_ts).days} days")
                
            return start_ts, end_ts
            
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        # Use days_back approach
        if days_back is None:
            days_back = DEFAULT_DAYS_BACK
        if days_back < 1:
            raise HTTPException(status_code=400, detail="days_back must be >= 1")
        if days_back > MAX_DAYS_BACK:
            logger.warning(f"Large days_back requested: {days_back}, allowing up to {MAX_DAYS_BACK}")
            days_back = MAX_DAYS_BACK  # Clamp to maximum
            
        now = datetime.now(timezone.utc)
        start_ts = now - timedelta(days=days_back)
        end_ts = now
        
        return start_ts, end_ts

@router.get("/station-readings-csv")
async def export_station_readings_csv(
    request: Request,
    db: AsyncSession = Depends(get_database),

    # --- time range ---
    days_back: Optional[int] = Query(
        DEFAULT_DAYS_BACK,
        description=f"Number of days back from now (default: {DEFAULT_DAYS_BACK}, max: {MAX_DAYS_BACK})"
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
        description="Filter by station_id. Can repeat (?station_id=A&station_id=B) or comma-separate (?station_id=A,B)."
    ),
    provider: Optional[list[str]] = Query(
        None,
        description="Filter by provider code(s) (providers.code). Can repeat or comma-separate."
    ),

    # --- selection / mode ---
    parameters: Optional[str] = Query(
        None,
        description="Pollutants to include: 'all' or comma-separated (pm25,pm10,no2,so2,co,o3). Aliases: pm2.5, carbon_monoxide."
    ),
    data_type: str = Query(
        "raw",
        description="Data type / resolution: raw | hourly | daily",
        pattern="^(raw|hourly|daily)$",
    ),

    # --- safety ---
    max_rows: Optional[int] = Query(
        None,
        description=f"Optional safety cap on rows (default: {MAX_EXPORT_ROWS_DEFAULT_DEFAULT}, hard cap: {MAX_EXPORT_ROWS_DEFAULT_HARD_CAP})"
    ),

    _: bool = Depends(verify_tasks_token)
):
    """
    Multifunctional station readings CSV export (streaming).

    **Authentication Required**: This endpoint requires a valid API token via Authorization header.

    Returns a streaming CSV file with station readings including:
    - Station information (ID, name, location)
    - Air quality data (PM2.5, PM10, AQI, etc.)
    - Meteorological data (temperature, humidity, pressure, wind)
    - Quality control flags and timestamps

    **Filters:**
    - province: Filter by province/state (e.g., "Punjab")
    - city: Filter by city name (e.g., "Lahore")
    - station_id: Filter by specific station(s)
    - provider: Filter by data provider code

    **Parameters:**
    - parameters: Select pollutants - "all" or "pm25,pm10,no2,so2,co,o3"
    - data_type: raw (individual readings) | hourly (1-hour averages) | daily (daily averages)
    - days_back: Number of days of historical data (default: 1, max: 3650)
    - start_date/end_date: Explicit date range (YYYY-MM-DD format)

    **Usage Examples:**
    ```bash
    # All stations, all pollutants, daily averages for last 30 days
    curl -H "Authorization: Bearer TOKEN" \
         "https://hawanama.org/api/v1/exports/station-readings-csv?parameters=all&data_type=daily&days_back=30"

    # Lahore stations, PM2.5 only, hourly data
    curl -H "Authorization: Bearer TOKEN" \
         "https://hawanama.org/api/v1/exports/station-readings-csv?city=Lahore&parameters=pm25&data_type=hourly"

    # Specific date range, Punjab province
    curl -H "Authorization: Bearer TOKEN" \
         "https://hawanama.org/api/v1/exports/station-readings-csv?province=Punjab&start_date=2024-01-01&end_date=2024-01-31"
    ```

    **Backwards-compatible defaults:**
    - If you don't pass parameters/data_type/province/city/station_id/provider,
      it behaves like the legacy endpoint (pm25 + existing fields, raw data).
    """

    # 1) Time range
    start_ts, end_ts = validate_and_compute_time_range(
        days_back=days_back,
        start_date=start_date,
        end_date=end_date
    )

    # 2) max_rows safety
    effective_max_rows = max_rows if max_rows is not None else MAX_EXPORT_ROWS_DEFAULT_DEFAULT
    if effective_max_rows < 1:
        raise HTTPException(status_code=400, detail="max_rows must be >= 1")
    if effective_max_rows > MAX_EXPORT_ROWS_DEFAULT_HARD_CAP:
        logger.warning(f"max_rows={effective_max_rows} exceeds hard cap; clamping to {MAX_EXPORT_ROWS_DEFAULT_HARD_CAP}")
        effective_max_rows = MAX_EXPORT_ROWS_DEFAULT_HARD_CAP

    # 3) Normalize filters
    station_ids = _split_multi(station_id)
    provider_codes = [p.strip().lower() for p in _split_multi(provider)]

    # 4) Parse pollutants
    selected_pollutants = parse_parameters_param(parameters)

    # 5) Decide aggregation mode
    aggregated = data_type in ("hourly", "daily")
    if data_type == "hourly":
        bucket_expr = "time_bucket('1 hour', r.ts_utc, 'UTC')"
    elif data_type == "daily":
        bucket_expr = "time_bucket('1 day', r.ts_utc, 'UTC')"
    else:
        bucket_expr = "r.ts_utc"

    # 6) Build station filter SQL (re-used in both queries)
    where_station = ["s.active = true"]
    params: dict = {"start_ts": start_ts, "end_ts": end_ts, "max_rows": effective_max_rows}

    if province:
        where_station.append("LOWER(COALESCE(st.name,'')) = LOWER(:province)")
        params["province"] = province

    if city:
        where_station.append("LOWER(COALESCE(c.name,'')) = LOWER(:city)")
        params["city"] = city

    # station_id list
    # (use expanding bindparam if present)
    station_bind = None
    if station_ids:
        where_station.append("s.station_id IN :station_ids")
        params["station_ids"] = station_ids
        station_bind = bindparam("station_ids", expanding=True)

    # provider filter
    provider_bind = None
    if provider_codes:
        # filter by providers.code, with fallback to readings.source for safety
        where_station.append("(LOWER(COALESCE(p.code,'')) IN :provider_codes)")
        params["provider_codes"] = provider_codes
        provider_bind = bindparam("provider_codes", expanding=True)

    station_where_sql = " AND ".join(where_station)

    logger.info(
        f"Export station CSV [{data_type}] {start_ts} → {end_ts} "
        f"pollutants={selected_pollutants} province={province} city={city} "
        f"station_ids={len(station_ids)} providers={provider_codes} max_rows={effective_max_rows}"
    )

    # 7) Build station_id -> numeric_id mapping (ONLY for the filtered station set)
    stations_query_sql = f"""
        SELECT
            s.station_id,
            COALESCE(s.name, 'Unknown Station') AS station_name
        FROM stations s
        LEFT JOIN providers p ON s.provider_id = p.id
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN states st ON c.state_id = st.id
        WHERE {station_where_sql}
        ORDER BY COALESCE(s.name, 'Unknown Station'), s.station_id
    """
    stations_query = text(stations_query_sql)
    if station_bind:
        stations_query = stations_query.bindparams(station_bind)
    if provider_bind:
        stations_query = stations_query.bindparams(provider_bind)

    try:
        stations_res = await db.execute(stations_query, params)
        stations = stations_res.fetchall()
        station_id_map = {row.station_id: i + 1 for i, row in enumerate(stations)}
        logger.info(f"Station map size: {len(station_id_map)} stations")
    except Exception as e:
        logger.error(f"Failed to build station_id_map: {e}")
        raise HTTPException(status_code=500, detail="Failed to export station readings")

    # 8) Build SELECT list dynamically (pollutants + units)
    pollutant_selects, pollutant_headers = build_pollutant_selects(selected_pollutants, aggregated=aggregated)

    # Legacy: you currently always export these (keep them stable)
    if aggregated:
        # For aggregated, numeric fields become AVG; categorical fields become NULL (or you can add mode() later)
        extra_selects = [
            f"{bucket_expr} AS timestamp_utc",
            "AVG(r.aqi_us) AS aqi_us",
            "AVG(r.aqi_cn) AS aqi_cn",
            "NULL::text AS main_us",
            "NULL::text AS main_cn",
            "AVG(r.temp_c) AS temperature_celsius",
            "AVG(r.humidity) AS humidity_percent",
            "AVG(r.pressure_hpa) AS pressure_hpa",
            "AVG(r.wind_speed_ms) AS wind_speed_ms",
            "AVG(r.wind_dir_deg) AS wind_direction_degrees",
            "AVG(r.heatindex_c) AS heat_index_celsius",
            "NULL::text AS weather_icon",
            "NULL::text AS qc_state",
            # counts
            "COUNT(*) AS sample_count",
            "COUNT(*) FILTER (WHERE r.qc_state = 'OK') AS qc_ok_count",
        ]
    else:
        extra_selects = [
            f"{bucket_expr} AS timestamp_utc",
            "r.aqi_us AS aqi_us",
            "r.aqi_cn AS aqi_cn",
            "r.main_us AS main_us",
            "r.main_cn AS main_cn",
            "r.temp_c AS temperature_celsius",
            "r.humidity AS humidity_percent",
            "r.pressure_hpa AS pressure_hpa",
            "r.wind_speed_ms AS wind_speed_ms",
            "r.wind_dir_deg AS wind_direction_degrees",
            "r.heatindex_c AS heat_index_celsius",
            "r.weather_icon AS weather_icon",
            "r.qc_state AS qc_state",
        ]

    base_selects = [
        "r.scope_key AS station_id",
        "COALESCE(s.name, 'Unknown Station') AS station_name",
        "COALESCE(s.lat, 0) AS latitude",
        "COALESCE(s.lon, 0) AS longitude",
        "COALESCE(c.name, 'Unknown City') AS city_name",
        "COALESCE(st.name, 'Unknown State') AS state_name",
        "COALESCE(co.name, 'Unknown Country') AS country_name",
        "COALESCE(p.code, r.source) AS provider_code",
        "COALESCE(p.display_name, r.source) AS provider_name",
    ]

    select_sql = ",\n            ".join(base_selects + extra_selects + pollutant_selects)

    # 9) Build WHERE for readings (same station filters + time)
    where_readings = [
        "r.scope_type = 'station'",
        "r.ts_utc >= :start_ts",
        "r.ts_utc < :end_ts",
        "s.active = true",
    ]
    if province:
        where_readings.append("LOWER(COALESCE(st.name,'')) = LOWER(:province)")
    if city:
        where_readings.append("LOWER(COALESCE(c.name,'')) = LOWER(:city)")
    if station_ids:
        where_readings.append("s.station_id IN :station_ids")
    if provider_codes:
        where_readings.append("(LOWER(COALESCE(p.code, r.source, '')) IN :provider_codes OR LOWER(COALESCE(r.source,'')) IN :provider_codes)")

    where_readings_sql = " AND ".join(where_readings)

    # 10) GROUP BY if aggregated
    if aggregated:
        group_by = f"""
            GROUP BY
                r.scope_key,
                s.name, s.lat, s.lon,
                c.name, st.name, co.name,
                p.code, p.display_name,
                {bucket_expr}
        """
        order_by = f"ORDER BY {bucket_expr} ASC, r.scope_key ASC"
    else:
        group_by = ""
        order_by = "ORDER BY r.ts_utc ASC, r.scope_key ASC"

    readings_query_sql = f"""
        SELECT
            {select_sql}
        FROM readings r
        LEFT JOIN stations s ON r.scope_key = s.station_id
        LEFT JOIN providers p ON s.provider_id = p.id
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN states st ON c.state_id = st.id
        LEFT JOIN countries co ON st.country_id = co.id
        WHERE {where_readings_sql}
        {group_by}
        {order_by}
        LIMIT :max_rows
    """
    readings_query = text(readings_query_sql)
    if station_bind:
        readings_query = readings_query.bindparams(station_bind)
    if provider_bind:
        readings_query = readings_query.bindparams(provider_bind)

    # 11) CSV header (keep your legacy columns + dynamic pollutants)
    header = [
        "id", "station_name", "latitude", "longitude",
        "city_name", "state_name", "country_name", "timestamp_utc",
        "aqi_us", "aqi_cn", "main_pollutant_us", "main_pollutant_cn",
        "temperature_celsius", "humidity_percent", "pressure_hpa",
        "wind_speed_ms", "wind_direction_degrees", "heat_index_celsius",
        "weather_icon", "qc_state",
        "provider_code", "provider_name",
    ]
    if aggregated:
        header += ["sample_count", "qc_ok_count"]
    header += pollutant_headers

    async def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(header)
        yield output.getvalue().encode(CSV_ENCODING)
        output.seek(0)
        output.truncate(0)

        row_count = 0

        try:
            result = await db.stream(readings_query, params)

            async for row in result:
                if await request.is_disconnected():
                    logger.warning("Client disconnected during export; stopping stream early")
                    break

                numeric_id = station_id_map.get(row.station_id, 0)

                base_row = [
                    numeric_id,
                    row.station_name or "",
                    row.latitude or "",
                    row.longitude or "",
                    row.city_name or "",
                    row.state_name or "",
                    row.country_name or "",
                    row.timestamp_utc.isoformat() if row.timestamp_utc else "",
                    row.aqi_us if row.aqi_us is not None else "",
                    row.aqi_cn if row.aqi_cn is not None else "",
                    row.main_us or "",
                    row.main_cn or "",
                    row.temperature_celsius if row.temperature_celsius is not None else "",
                    row.humidity_percent if row.humidity_percent is not None else "",
                    row.pressure_hpa if row.pressure_hpa is not None else "",
                    row.wind_speed_ms if row.wind_speed_ms is not None else "",
                    row.wind_direction_degrees if row.wind_direction_degrees is not None else "",
                    row.heat_index_celsius if row.heat_index_celsius is not None else "",
                    row.weather_icon or "",
                    row.qc_state or "",
                    row.provider_code or "",
                    row.provider_name or "",
                ]

                if aggregated:
                    base_row += [
                        row.sample_count if row.sample_count is not None else "",
                        row.qc_ok_count if row.qc_ok_count is not None else "",
                    ]

                # dynamic pollutants
                dyn = []
                for col in pollutant_headers:
                    v = getattr(row, col, None)
                    dyn.append("" if v is None else v)

                writer.writerow(base_row + dyn)

                row_count += 1
                if row_count % STREAM_FLUSH_EVERY_ROWS == 0:
                    yield output.getvalue().encode(CSV_ENCODING)
                    output.seek(0)
                    output.truncate(0)

            if output.tell() > 0:
                yield output.getvalue().encode(CSV_ENCODING)

            logger.info(f"Export completed: streamed {row_count} rows (max_rows={effective_max_rows})")

        except Exception as e:
            logger.error(f"Error during streaming export: {e}")
            yield f"# Export error: {str(e)}\n".encode(CSV_ENCODING)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_range = f"{start_ts.strftime('%Y%m%d')}_to_{end_ts.strftime('%Y%m%d')}"
    filename = f"hawanama_station_readings_{data_type}_{date_range}_{timestamp}.csv"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/city-readings-csv")
async def export_city_readings_csv(
    request: Request,
    db: AsyncSession = Depends(get_database),
    days_back: Optional[int] = Query(DEFAULT_DAYS_BACK, description=f"Number of days back from now (default: {DEFAULT_DAYS_BACK}, max: {MAX_DAYS_BACK})"),
    _: bool = Depends(verify_tasks_token)
):
    """
    Export all city-level readings as CSV.
    
    Returns a streaming CSV file with all city readings including:
    - City information (name, state, country)
    - Aggregated air quality data (PM2.5, AQI, etc.)
    - Meteorological data (temperature, humidity, pressure, wind)
    - Quality control flags and timestamps
    
    Parameters:
    - days_back: Number of days of historical data to include (default: 1, max: 3650)
    """
    # Compute time range with validation
    start_ts, end_ts = validate_and_compute_time_range(days_back=days_back)
    
    logger.info(f"Exporting city readings CSV from {start_ts} to {end_ts}")
    
    # Query to get all city readings with city metadata - fully parameterized
    query = text("""
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
    """)
    
    params = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "max_rows": MAX_EXPORT_ROWS_DEFAULT,
    }
    
    try:
        result = await db.execute(query, params)
        
        # Create CSV content generator
        def generate_csv():
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write filtered header (removed pm10, o3, no2, so2, co, aqi_us, aqi_cn, main_pollutant columns)
            header = [
                'scope_key', 'city_name', 'state_name', 'country_name', 'timestamp_utc',
                'pm25_ugm3', 'temperature_celsius', 'humidity_percent', 'pressure_hpa',
                'wind_speed_ms', 'wind_direction_degrees', 'heat_index_celsius',
                'weather_icon', 'qc_state', 'source', 'pm25_units'
            ]
            writer.writerow(header)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            
            # Write filtered data rows (removed pm10, o3, no2, so2, co, aqi_us, aqi_cn, main_pollutant columns)
            for row in result:
                data_row = [
                    row.scope_key or '',
                    row.city_name or '',
                    row.state_name or '',
                    row.country_name or '',
                    row.timestamp_utc.isoformat() if row.timestamp_utc else '',
                    row.pm25 or '',
                    row.temperature_celsius or '',
                    row.humidity_percent or '',
                    row.pressure_hpa or '',
                    row.wind_speed_ms or '',
                    row.wind_direction_degrees or '',
                    row.heat_index_celsius or '',
                    row.weather_icon or '',
                    row.qc_state or '',
                    row.source or '',
                    row.units_pm25 or ''
                ]
                writer.writerow(data_row)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
        
        # Generate filename with timestamp and actual date range
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        date_range = f"{start_ts.strftime('%Y%m%d')}_to_{end_ts.strftime('%Y%m%d')}"
        filename = f"hawanama_city_readings_{date_range}_{timestamp}.csv"
        
        # Return streaming response
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error exporting city readings CSV: {e}")
        raise HTTPException(status_code=500, detail="Failed to export city readings")


@router.get("/station-readings-by-city-csv/{city}")
async def export_station_readings_by_city_csv(
    request: Request,
    city: str = Path(
        ...,
        description="Select city from dropdown list",
        example="Lahore",
        enum=[
            "Abbottabad", "Bahawalpur", "Bhopalwala", "Chak Jhumra", "Daska Kalan", 
            "Dera Ismail Khan", "Eminabad", "Faisalabad", "Gujranwala", "Haripur", 
            "Hundal", "Hyderabad", "Islamabad", "Jhang", "Jhelum", "Kahna Nau", 
            "Karachi", "Kasur", "Khairpur Mir's", "Kharan", "Khurrianwala", 
            "Kot Malik Barkhurdar", "Kotli Loharan", "Kotri", "Ladhewala Waraich", 
            "Lahore", "Lodhran", "Malam Jabba", "Malir Cantonment", "Mandi Bahauddin", 
            "Mirpur Khas", "Multan", "Murree", "Pasrur", "Pattoki", "Peshawar", 
            "Pindi Bhattian", "Qadirpur Ran", "Quetta", "Rahim Yar Khan", "Raiwind", 
            "Rawalpindi", "Rojhan", "Sambrial", "Sheikhupura", "Sialkot", "Skardu", "Sukkur"
        ]
    ),
    db: AsyncSession = Depends(get_database),
    days_back: Optional[int] = Query(DEFAULT_DAYS_BACK, description=f"Number of days back from now (default: {DEFAULT_DAYS_BACK}, max: {MAX_DAYS_BACK})"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format (overrides days_back)", example="2024-01-01"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format (requires start_date)", example="2024-12-31"),
    _: bool = Depends(verify_tasks_token)
):
    """
    Export station-level readings for a specific city as CSV.
    
    Returns a streaming CSV file with all station readings within the specified city including:
    - Station information (ID, name, location)
    - Air quality data (PM2.5, PM10, AQI, etc.)
    - Meteorological data (temperature, humidity, pressure, wind)
    - Quality control flags and timestamps
    
    Parameters:
    - city: Name of the city to filter stations (required, selected from dropdown)
    - days_back: Number of days of historical data to include (default: 1, max: 3650)
    - start_date: Start date in YYYY-MM-DD format (overrides days_back if provided)
    - end_date: End date in YYYY-MM-DD format (requires start_date)
    """
    # Compute time range with validation
    start_ts, end_ts = validate_and_compute_time_range(
        days_back=days_back, 
        start_date=start_date, 
        end_date=end_date
    )
    
    logger.info(f"Exporting station readings CSV for city '{city}' from {start_ts} to {end_ts}")
    
    # Station readings export filtered by city name - fully parameterized with provider info
    query = text("""
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
        AND s.active = true
    ORDER BY r.scope_key, r.ts_utc ASC
    LIMIT :max_rows
    """)
    
    params = {
        "city_name": city,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "max_rows": MAX_EXPORT_ROWS_DEFAULT,
    }
    
    try:
        result = await db.execute(query, params)
        
        # Check if any results were found
        rows = result.fetchall()
        if not rows:
            raise HTTPException(
                status_code=404, 
                detail=f"No station data found for city '{city}' in the specified time period"
            )
        
        # Create station_id to numeric_id mapping like dashboard API does
        unique_stations = {}
        for row in rows:
            if row.station_id not in unique_stations:
                unique_stations[row.station_id] = {
                    'name': row.station_name,
                    'station_id': row.station_id
                }
        
        # Sort stations by name and assign numeric IDs
        sorted_stations = sorted(unique_stations.items(), key=lambda x: x[1]['name'])
        station_id_map = {}
        for i, (station_id, station_info) in enumerate(sorted_stations):
            station_id_map[station_id] = i + 1  # 1-based indexing like dashboard
        
        # Create CSV content generator
        def generate_csv():
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header with provider information
            header = [
                'id', 'station_name', 'latitude', 'longitude',
                'city_name', 'state_name', 'country_name', 'timestamp_utc',
                'pm25_ugm3', 'aqi_us', 'aqi_cn', 'main_pollutant_us', 'main_pollutant_cn',
                'temperature_celsius', 'humidity_percent', 'pressure_hpa',
                'wind_speed_ms', 'wind_direction_degrees', 'heat_index_celsius',
                'weather_icon', 'qc_state', 'provider_code', 'provider_name', 'pm25_units'
            ]
            writer.writerow(header)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            
            # Write data rows with numeric station IDs and provider info
            for row in rows:
                numeric_id = station_id_map.get(row.station_id, 0)
                data_row = [
                    numeric_id,  # Use numeric ID instead of hex station_id
                    row.station_name or '',
                    row.latitude or '',
                    row.longitude or '',
                    row.city_name or '',
                    row.state_name or '',
                    row.country_name or '',
                    row.timestamp_utc.isoformat() if row.timestamp_utc else '',
                    row.pm25 or '',
                    row.aqi_us or '',
                    row.aqi_cn or '',
                    row.main_us or '',
                    row.main_cn or '',
                    row.temperature_celsius or '',
                    row.humidity_percent or '',
                    row.pressure_hpa or '',
                    row.wind_speed_ms or '',
                    row.wind_direction_degrees or '',
                    row.heat_index_celsius or '',
                    row.weather_icon or '',
                    row.qc_state or '',
                    row.provider_code or '',
                    row.provider_name or '',
                    row.units_pm25 or ''
                ]
                writer.writerow(data_row)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
        
        # Generate filename with timestamp and city name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_city_name = "".join(c for c in city if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_city_name = safe_city_name.replace(' ', '_')
        
        if start_date and end_date:
            filename = f"hawanama_station_readings_{safe_city_name}_{start_date}_to_{end_date}_{timestamp}.csv"
        else:
            filename = f"hawanama_station_readings_{safe_city_name}_{days_back}days_{timestamp}.csv"
        
        # Return streaming response
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting station readings by city CSV: {e}")
        raise HTTPException(status_code=500, detail="Failed to export station readings by city")


@router.get("/station-readings-by-city-pm25-csv/{city}")
async def export_station_readings_by_city_pm25_csv(
    request: Request,
    city: str = Path(
        ...,
        description="Select city from dropdown list",
        example="Lahore",
        enum=[
            "Abbottabad", "Bahawalpur", "Bhopalwala", "Chak Jhumra", "Daska Kalan", 
            "Dera Ismail Khan", "Eminabad", "Faisalabad", "Gujranwala", "Haripur", 
            "Hundal", "Hyderabad", "Islamabad", "Jhang", "Jhelum", "Kahna Nau", 
            "Karachi", "Kasur", "Khairpur Mir's", "Kharan", "Khurrianwala", 
            "Kot Malik Barkhurdar", "Kotli Loharan", "Kotri", "Ladhewala Waraich", 
            "Lahore", "Lodhran", "Malam Jabba", "Malir Cantonment", "Mandi Bahauddin", 
            "Mirpur Khas", "Multan", "Murree", "Pasrur", "Pattoki", "Peshawar", 
            "Pindi Bhattian", "Qadirpur Ran", "Quetta", "Rahim Yar Khan", "Raiwind", 
            "Rawalpindi", "Rojhan", "Sambrial", "Sheikhupura", "Sialkot", "Skardu", "Sukkur"
        ]
    ),
    db: AsyncSession = Depends(get_database),
    days_back: Optional[int] = Query(DEFAULT_DAYS_BACK, description=f"Number of days back from now (default: {DEFAULT_DAYS_BACK}, max: {MAX_DAYS_BACK})"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format (overrides days_back)", example="2024-01-01"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format (requires start_date)", example="2024-12-31"),
    _: bool = Depends(verify_tasks_token)
):
    """
    Export PM2.5-only station readings for a specific city as CSV.
    
    Returns a streamlined CSV file with only PM2.5 data for all stations within the specified city:
    - Station information (ID, name, location)
    - PM2.5 concentration only
    - Basic timestamps and quality control flags
    
    This is a lightweight version optimized specifically for PM2.5 analysis.
    
    Parameters:
    - city: Name of the city to filter stations (required, selected from dropdown)
    - days_back: Number of days of historical data to include (default: 1, max: 3650)
    - start_date: Start date in YYYY-MM-DD format (overrides days_back if provided)
    - end_date: End date in YYYY-MM-DD format (overrides days_back if provided)
    """
    # Compute time range with validation
    start_ts, end_ts = validate_and_compute_time_range(
        days_back=days_back, 
        start_date=start_date, 
        end_date=end_date
    )
    
    logger.info(f"Exporting PM2.5-only station readings CSV for city '{city}' from {start_ts} to {end_ts}")
    
    # Get stations in the city first - fully parameterized with provider info
    stations_query = text("""
    SELECT s.station_id, s.name, s.lat, s.lon, c.name as city_name,
           COALESCE(p.code, 'unknown') as provider_code,
           COALESCE(p.display_name, 'Unknown Provider') as provider_name
    FROM stations s
    LEFT JOIN cities c ON s.city_id = c.id
    LEFT JOIN providers p ON s.provider_id = p.id
    WHERE LOWER(COALESCE(c.name, '')) = LOWER(:city_name)
        AND s.active = true
    ORDER BY s.name
    """)
    
    # PM2.5 readings with complete time series - fully parameterized
    readings_query = text("""
    SELECT 
        r.scope_key as station_id,
        r.ts_utc as timestamp_utc,
        r.pm25,
        r.qc_state,
        r.source
    FROM readings r
    WHERE r.scope_key = :station_id 
        AND r.scope_type = 'station'
        AND r.ts_utc >= :start_ts
        AND r.ts_utc < :end_ts
    ORDER BY r.ts_utc ASC
    LIMIT :max_rows
    """)
    
    try:
        # Get stations in the city
        stations_result = await db.execute(stations_query, {'city_name': city})
        stations = stations_result.fetchall()
        
        if not stations:
            raise HTTPException(
                status_code=404, 
                detail=f"No stations found for city '{city}'"
            )
        
        # Create station_id to numeric_id mapping
        station_id_map = {}
        station_info = {}
        for i, station in enumerate(stations):
            station_id_map[station.station_id] = i + 1  # 1-based indexing like dashboard
            station_info[station.station_id] = {
                'name': station.name,
                'lat': station.lat,
                'lon': station.lon,
                'city_name': station.city_name,
                'provider_code': station.provider_code,
                'provider_name': station.provider_name
            }
        
        # Get all readings data for all stations
        all_readings = []
        for station in stations:
            readings_params = {
                'station_id': station.station_id,
                'start_ts': start_ts,
                'end_ts': end_ts,
                'max_rows': MAX_EXPORT_ROWS_DEFAULT
            }
            readings_result = await db.execute(readings_query, readings_params)
            readings = readings_result.fetchall()
            
            numeric_id = station_id_map[station.station_id]
            info = station_info[station.station_id]
            
            for reading in readings:
                all_readings.append({
                    'numeric_id': numeric_id,
                    'name': info['name'],
                    'lat': info['lat'],
                    'lon': info['lon'],
                    'city_name': info['city_name'],
                    'provider_code': info['provider_code'],
                    'provider_name': info['provider_name'],
                    'timestamp_utc': reading.timestamp_utc,
                    'pm25': reading.pm25,
                    'qc_state': reading.qc_state,
                    'source': reading.source
                })
        
        # Create CSV content generator
        def generate_csv():
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write minimal header focused only on PM2.5 with provider info
            header = [
                'id', 'station_name', 'latitude', 'longitude',
                'city_name', 'timestamp_utc', 'timestamp_pk', 'pm25_ugm3', 
                'provider_code', 'provider_name', 'qc_state'
            ]
            writer.writerow(header)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            
            # Write data rows with complete time series (including nulls)
            for reading_data in all_readings:
                # Calculate Pakistan time (UTC+5)
                timestamp_utc = reading_data['timestamp_utc']
                timestamp_pk = None
                if timestamp_utc:
                    from datetime import timedelta
                    timestamp_pk = timestamp_utc + timedelta(hours=5)
                
                data_row = [
                    reading_data['numeric_id'],
                    reading_data['name'] or '',
                    reading_data['lat'] or '',
                    reading_data['lon'] or '',
                    reading_data['city_name'] or '',
                    timestamp_utc.isoformat() if timestamp_utc else '',
                    timestamp_pk.isoformat() if timestamp_pk else '',
                    'null' if reading_data['pm25'] is None else float(reading_data['pm25']),
                    reading_data['provider_code'] or '',
                    reading_data['provider_name'] or '',
                    reading_data['qc_state'] or ''
                ]
                writer.writerow(data_row)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
        
        # Generate filename with timestamp and city name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_city_name = "".join(c for c in city if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_city_name = safe_city_name.replace(' ', '_')
        
        date_range = f"{start_ts.strftime('%Y%m%d')}_to_{end_ts.strftime('%Y%m%d')}"
        filename = f"hawanama_station_pm25_{safe_city_name}_{date_range}_{timestamp}.csv"
        
        # Return streaming response
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting PM2.5 station readings by city CSV: {e}")
        raise HTTPException(status_code=500, detail="Failed to export PM2.5 station readings by city")