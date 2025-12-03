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
from sqlalchemy import text
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
MAX_EXPORT_ROWS = 500_000  # Increased row limit for larger exports
DEFAULT_DAYS_BACK = 1  # Swagger-friendly default
PM25_MAX_DAYS = 3650  # Allow full historical data for PM2.5

def parse_date_yyyy_mm_dd(date_str: str) -> datetime:
    """Parse YYYY-MM-DD date string to UTC datetime at start of day"""
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

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
    days_back: Optional[int] = Query(DEFAULT_DAYS_BACK, description=f"Number of days back from now (default: {DEFAULT_DAYS_BACK}, max: {MAX_DAYS_BACK})"),
    _: bool = Depends(verify_tasks_token)
):
    """
    Export all station-level readings as CSV.
    
    **Authentication Required**: This endpoint requires a valid API token via Authorization header.
    
    Returns a streaming CSV file with all station readings including:
    - Station information (ID, name, location)
    - Air quality data (PM2.5, PM10, AQI, etc.)
    - Meteorological data (temperature, humidity, pressure, wind)
    - Quality control flags and timestamps
    
    Parameters:
    - days_back: Number of days of historical data to include (default: 1, max: 3650)
    
    **Usage:**
    ```bash
    curl -H "Authorization: Bearer YOUR_API_TOKEN" \
         "https://hawanama.org/api/v1/exports/station-readings-csv?days_back=7"
    ```
    """
    # Compute time range with validation
    start_ts, end_ts = validate_and_compute_time_range(days_back=days_back)
    
    logger.info(f"Exporting station readings CSV from {start_ts} to {end_ts}")
    
    # Station readings export with metadata from JOINs - fully parameterized
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
        AND r.ts_utc >= :start_ts
        AND r.ts_utc < :end_ts
        AND s.active = true
    ORDER BY r.scope_key, r.ts_utc ASC
    LIMIT :max_rows
    """)
    
    params = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "max_rows": MAX_EXPORT_ROWS,
    }
    
    try:
        result = await db.execute(query, params)
        rows = result.fetchall()
        
        # Create station_id to numeric_id mapping like dashboard API does
        # Get unique stations and sort by name to create consistent mapping
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
            
            # Write filtered header with provider information
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
            
            # Write filtered data rows with numeric station IDs and provider info
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
        
        # Generate filename with timestamp and actual date range
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        date_range = f"{start_ts.strftime('%Y%m%d')}_to_{end_ts.strftime('%Y%m%d')}"
        filename = f"hawanama_station_readings_{date_range}_{timestamp}.csv"
        
        # Return streaming response
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error exporting station readings CSV: {e}")
        raise HTTPException(status_code=500, detail="Failed to export station readings")


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
        "max_rows": MAX_EXPORT_ROWS,
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
        "max_rows": MAX_EXPORT_ROWS,
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
                'max_rows': MAX_EXPORT_ROWS
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