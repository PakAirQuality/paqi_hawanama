"""
CSV Export Endpoints for Historical Data

Provides CSV export functionality for:
- All station-level readings
- All city-level readings

These endpoints return streaming CSV responses for bulk data download.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_database
from typing import Optional
import logging
import io
import csv
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/station-readings-csv")
async def export_station_readings_csv(
    db: AsyncSession = Depends(get_database),
    days_back: Optional[int] = Query(30, description="Number of days back from now to include (default: 30, max: 365)")
):
    """
    Export all station-level readings as CSV.
    
    Returns a streaming CSV file with all station readings including:
    - Station information (ID, name, location)
    - Air quality data (PM2.5, PM10, AQI, etc.)
    - Meteorological data (temperature, humidity, pressure, wind)
    - Quality control flags and timestamps
    
    Parameters:
    - days_back: Number of days of historical data to include (default: 30, max: 365)
    """
    # Validate input
    if days_back and (days_back < 1 or days_back > 365):
        raise HTTPException(status_code=400, detail="days_back must be between 1 and 365")
    
    if days_back is None:
        days_back = 30
    
    logger.info(f"Exporting station readings CSV for last {days_back} days")
    
    # Station readings export with metadata from JOINs
    query = f"""
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
        r.source,
        r.units_pm25
    FROM readings r
    LEFT JOIN stations s ON r.scope_key = s.station_id
    LEFT JOIN cities c ON s.city_id = c.id
    LEFT JOIN states st ON c.state_id = st.id
    LEFT JOIN countries co ON st.country_id = co.id
    WHERE r.scope_type = 'station'
        AND r.ts_utc >= CURRENT_TIMESTAMP - INTERVAL '{days_back} days'
    ORDER BY r.scope_key, r.ts_utc ASC
    LIMIT 50000
    """
    
    try:
        result = await db.execute(text(query))
        
        # Create CSV content generator
        def generate_csv():
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write filtered header (removed pm10, o3, no2, so2, co columns)
            header = [
                'station_id', 'station_name', 'latitude', 'longitude',
                'city_name', 'state_name', 'country_name', 'timestamp_utc',
                'pm25_ugm3', 'aqi_us', 'aqi_cn', 'main_pollutant_us', 'main_pollutant_cn',
                'temperature_celsius', 'humidity_percent', 'pressure_hpa',
                'wind_speed_ms', 'wind_direction_degrees', 'heat_index_celsius',
                'weather_icon', 'qc_state', 'source', 'pm25_units'
            ]
            writer.writerow(header)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            
            # Write filtered data rows (removed pm10, o3, no2, so2, co columns)
            for row in result:
                data_row = [
                    row.station_id or '',
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
                    row.source or '',
                    row.units_pm25 or ''
                ]
                writer.writerow(data_row)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"hawanama_station_readings_{days_back}days_{timestamp}.csv"
        
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
    db: AsyncSession = Depends(get_database),
    days_back: Optional[int] = Query(30, description="Number of days back from now to include (default: 30, max: 365)")
):
    """
    Export all city-level readings as CSV.
    
    Returns a streaming CSV file with all city readings including:
    - City information (name, state, country)
    - Aggregated air quality data (PM2.5, AQI, etc.)
    - Meteorological data (temperature, humidity, pressure, wind)
    - Quality control flags and timestamps
    
    Parameters:
    - days_back: Number of days of historical data to include (default: 30, max: 365)
    """
    # Validate input
    if days_back and (days_back < 1 or days_back > 365):
        raise HTTPException(status_code=400, detail="days_back must be between 1 and 365")
    
    if days_back is None:
        days_back = 30
    
    logger.info(f"Exporting city readings CSV for last {days_back} days")
    
    # Query to get all city readings with city metadata (filtered columns)
    query = f"""
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
        AND r.ts_utc >= CURRENT_TIMESTAMP - INTERVAL '{days_back} days'
    ORDER BY r.scope_key, r.ts_utc ASC
    """
    
    try:
        result = await db.execute(text(query))
        
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
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"hawanama_city_readings_{days_back}days_{timestamp}.csv"
        
        # Return streaming response
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error exporting city readings CSV: {e}")
        raise HTTPException(status_code=500, detail="Failed to export city readings")