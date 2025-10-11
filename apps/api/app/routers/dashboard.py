"""
Dashboard API Router - provides dashboard endpoints for frontend
"""

import logging
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_database)):
    """Get dashboard statistics"""
    try:
        # Get comprehensive dashboard stats
        result = await db.execute(text("""
            WITH station_stats AS (
                SELECT 
                    COUNT(*) as total_stations,
                    COUNT(CASE WHEN s.active = true THEN 1 END) as active_stations
                FROM stations s
            ),
            latest_readings AS (
                SELECT 
                    AVG(r.pm25) as avg_pm25,
                    MAX(r.ts_utc) as last_update,
                    COUNT(CASE WHEN r.ts_utc > NOW() - INTERVAL '6 hours' THEN 1 END) as recent_readings,
                    AVG(r.aqi_us) as avg_aqi
                FROM readings r 
                WHERE r.scope_type = 'station' 
                AND r.pm25 IS NOT NULL 
                AND r.ts_utc > NOW() - INTERVAL '24 hours'
            ),
            top_cities AS (
                SELECT 
                    r.scope_key,
                    AVG(r.aqi_us) as avg_aqi
                FROM readings r 
                WHERE r.scope_type = 'city' 
                AND r.aqi_us IS NOT NULL 
                AND r.ts_utc > NOW() - INTERVAL '24 hours'
                GROUP BY r.scope_key
                ORDER BY avg_aqi DESC
                LIMIT 5
            ),
            reading_counts AS (
                SELECT 
                    COUNT(CASE WHEN scope_type = 'city' THEN 1 END) as city_readings,
                    COUNT(CASE WHEN scope_type = 'station' THEN 1 END) as station_readings,
                    COUNT(*) as total_readings
                FROM readings
            )
            SELECT 
                ss.total_stations,
                ss.active_stations,
                lr.avg_pm25,
                lr.last_update,
                lr.avg_aqi,
                rc.city_readings,
                rc.station_readings,
                rc.total_readings,
                (SELECT COUNT(*) FROM cities) as total_cities
            FROM station_stats ss, latest_readings lr, reading_counts rc
        """))
        
        row = result.fetchone()
        if not row:
            return {"error": "No data available"}
            
        # Get top cities separately (try last 7 days if no data in last 24 hours)
        cities_result = await db.execute(text("""
            SELECT 
                r.scope_key,
                AVG(r.aqi_us) as avg_aqi
            FROM readings r 
            WHERE r.scope_type = 'city' 
            AND r.aqi_us IS NOT NULL 
            AND r.ts_utc > NOW() - INTERVAL '7 days'
            GROUP BY r.scope_key
            ORDER BY avg_aqi DESC
            LIMIT 5
        """))
        
        cities_rows = cities_result.fetchall()
        top_cities = []
        for city_row in cities_rows:
            # Extract city name from scope_key (format: country|state|city)
            city_parts = city_row.scope_key.split('|')
            city_name = city_parts[-1].title() if len(city_parts) > 0 else city_row.scope_key
            top_cities.append({
                "name": city_name,
                "aqi": float(city_row.avg_aqi)
            })
        
        # Determine AQI color category
        avg_aqi = float(row.avg_aqi) if row.avg_aqi else 0
        if avg_aqi <= 50:
            aqi_color = 'green'
        elif avg_aqi <= 100:
            aqi_color = 'yellow' 
        elif avg_aqi <= 150:
            aqi_color = 'orange'
        elif avg_aqi <= 200:
            aqi_color = 'red'
        else:
            aqi_color = 'purple'
            
        # Format last update (convert UTC to Pakistan time UTC+5)
        last_update = None
        if row.last_update:
            from datetime import datetime, timezone, timedelta
            # Convert UTC to Pakistan time (UTC+5)
            pkr_timezone = timezone(timedelta(hours=5))
            pkr_time = row.last_update.replace(tzinfo=timezone.utc).astimezone(pkr_timezone)
            last_update = pkr_time.strftime("%H:%M PKT")
        
        return {
            "total_stations": row.total_stations or 0,
            "active_stations": row.active_stations or 0,
            "avg_pm25": round(float(row.avg_pm25), 1) if row.avg_pm25 else None,
            "aqi_color": aqi_color,
            "last_update": last_update or "No data",
            "top_cities": top_cities,
            "city_readings": row.city_readings or 0,
            "station_readings": row.station_readings or 0, 
            "total_readings": row.total_readings or 0,
            "total_cities": row.total_cities or 0
        }
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/debug")
async def get_debug_info(db: AsyncSession = Depends(get_database)):
    """Get debug information"""
    try:
        # Get latest readings
        city_result = await db.execute(text("""
            SELECT scope_key, ts_utc, pm25, aqi_us, ingested_at 
            FROM readings 
            WHERE scope_type = 'city' 
            ORDER BY ingested_at DESC 
            LIMIT 5
        """))
        
        station_result = await db.execute(text("""
            SELECT scope_key, ts_utc, pm25, aqi_us, ingested_at 
            FROM readings 
            WHERE scope_type = 'station' 
            ORDER BY ingested_at DESC 
            LIMIT 5
        """))
        
        city_rows = city_result.fetchall()
        station_rows = station_result.fetchall()
        
        return {
            "latest_city_readings": [dict(row._mapping) for row in city_rows],
            "latest_station_readings": [dict(row._mapping) for row in station_rows],
            "timestamp": "2025-09-26T00:30:00Z"
        }
        
    except Exception as e:
        logger.error(f"Error getting debug info: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations")
async def get_stations_for_map(db: AsyncSession = Depends(get_database)):
    """Get stations data for map display"""
    try:
        # Get stations with latest readings - only get most recent reading per station
        result = await db.execute(text("""
            WITH latest_readings AS (
                SELECT DISTINCT ON (scope_key) 
                    scope_key, pm25, aqi_us, temp_c, humidity, pressure_hpa, wind_speed_ms, wind_dir_deg, ts_utc
                FROM readings
                WHERE scope_type = 'station' 
                AND ts_utc > NOW() - INTERVAL '48 hours'
                ORDER BY scope_key, ts_utc DESC
            )
            SELECT 
                s.station_id,
                s.name,
                s.lat as latitude,
                s.lon as longitude,
                c.name as city_name,
                lr.pm25,
                lr.aqi_us,
                lr.temp_c as temp,
                lr.humidity as hum,
                lr.pressure_hpa,
                lr.wind_speed_ms,
                lr.wind_dir_deg,
                lr.ts_utc as last_reading,
                'OK' as qc_state,
                CASE 
                    WHEN lr.aqi_us <= 50 THEN 'good'
                    WHEN lr.aqi_us <= 100 THEN 'moderate' 
                    WHEN lr.aqi_us <= 150 THEN 'unhealthy_sensitive'
                    WHEN lr.aqi_us <= 200 THEN 'unhealthy'
                    WHEN lr.aqi_us <= 300 THEN 'very_unhealthy'
                    ELSE 'hazardous'
                END as aqi_category
            FROM stations s
            LEFT JOIN cities c ON s.city_id = c.id
            LEFT JOIN latest_readings lr ON s.station_id = lr.scope_key
            WHERE s.active = true
            ORDER BY s.name
        """))
        
        stations_rows = result.fetchall()
        stations_list = []
        for i, row in enumerate(stations_rows):
            station_data = {
                "id": i + 1,  # Use sequential numeric ID for frontend
                "station_id": row.station_id,  # Keep original hash ID
                "name": row.name,
                "latitude": float(row.latitude) if row.latitude else 0,
                "longitude": float(row.longitude) if row.longitude else 0,
                "city": row.city_name,  # Add city name for boundary filtering
                "source_id": 1,  # Default source ID (AirVisual)
                "pm25": float(row.pm25) if row.pm25 else None,
                "aqi_raw": int(row.aqi_us) if row.aqi_us else None,  # Frontend expects aqi_raw
                "temp": float(row.temp) if row.temp else None,
                "hum": float(row.hum) if row.hum else None,
                "qc_state": row.qc_state,
                "aqi_category": row.aqi_category if row.aqi_us else None,
                "last_reading": row.last_reading.isoformat() if row.last_reading else None
            }
            stations_list.append(station_data)
        
        return {"stations": stations_list}
        
    except Exception as e:
        logger.error(f"Error getting stations: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")



@router.get("/stations/{station_numeric_id}/current")
async def get_station_current_data(
    station_numeric_id: int,
    db: AsyncSession = Depends(get_database)
):
    """Get current data for a specific station using numeric ID from stations list"""
    try:
        # First get station details by numeric position using the same query as stations list
        stations_result = await db.execute(text("""
            WITH latest_readings AS (
                SELECT DISTINCT ON (scope_key) 
                    scope_key, pm25, aqi_us, temp_c, humidity, pressure_hpa, wind_speed_ms, wind_dir_deg, ts_utc
                FROM readings
                WHERE scope_type = 'station' 
                AND ts_utc > NOW() - INTERVAL '48 hours'
                ORDER BY scope_key, ts_utc DESC
            )
            SELECT 
                s.station_id, s.name, s.lat, s.lon,
                lr.pm25, lr.aqi_us, lr.temp_c, lr.humidity, lr.pressure_hpa, lr.wind_speed_ms, lr.wind_dir_deg, lr.ts_utc
            FROM stations s
            LEFT JOIN latest_readings lr ON s.station_id = lr.scope_key
            WHERE s.active = true
            ORDER BY s.name
            LIMIT 1 OFFSET :offset
        """), {"offset": station_numeric_id - 1})
        
        station_row = stations_result.fetchone()
        if not station_row:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Determine main pollutant (simplified - use PM2.5 for now)
        main_pollutant = "PM2.5"
        main_value = float(station_row.pm25) if station_row.pm25 else 0
        
        return {
            "station_id": str(station_numeric_id),
            "name": station_row.name,
            "aqi_us": int(station_row.aqi_us) if station_row.aqi_us else 0,
            "main_pollutant": main_pollutant,
            "main_value": main_value,
            "main_units": "µg/m³",
            "temp_c": float(station_row.temp_c) if station_row.temp_c else None,
            "humidity": float(station_row.humidity) if station_row.humidity else None,
            "wind_speed_kmh": float(station_row.wind_speed_ms * 3.6) if station_row.wind_speed_ms else None,  # Convert m/s to km/h
            "wind_direction": float(station_row.wind_dir_deg) if station_row.wind_dir_deg else None,
            "pressure_mbar": float(station_row.pressure_hpa) if station_row.pressure_hpa else None,   # hPa = mbar  
            "last_update": station_row.ts_utc.isoformat() if station_row.ts_utc else None
        }
        
    except Exception as e:
        logger.error(f"Error getting station current data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations/{station_numeric_id}/history")
async def get_station_history_data(
    station_numeric_id: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_database)
):
    """Get historical data for a specific station using numeric ID"""
    try:
        # First get the station_id hash from numeric position
        station_lookup = await db.execute(text("""
            SELECT station_id 
            FROM stations 
            WHERE active = true 
            ORDER BY name 
            LIMIT 1 OFFSET :offset
        """), {"offset": station_numeric_id - 1})
        
        station_row = station_lookup.fetchone()
        if not station_row:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Generate complete hourly time series with Pakistan timezone
        history_result = await db.execute(text("""
            WITH RECURSIVE hour_series AS (
                SELECT 
                    date_trunc('hour', NOW() - INTERVAL '%s hours') + INTERVAL '1 hour' AS hour_utc
                UNION ALL
                SELECT 
                    hour_utc + INTERVAL '1 hour'
                FROM hour_series
                WHERE hour_utc < date_trunc('hour', NOW())
            )
            SELECT 
                hs.hour_utc,
                hs.hour_utc + INTERVAL '5 hours' AS hour_pk,
                r.aqi_us
            FROM hour_series hs
            LEFT JOIN readings r ON (
                date_trunc('hour', r.ts_utc) = hs.hour_utc
                AND r.scope_key = :station_id 
                AND r.scope_type = 'station'
            )
            ORDER BY hs.hour_utc ASC
        """ % hours), {"station_id": station_row.station_id})
        
        history_rows = history_result.fetchall()
        history_data = [
            {
                "timestamp_utc": row.hour_utc.isoformat() + "Z",
                "timestamp_pk": row.hour_pk.isoformat() + "+05:00",
                "timestamp": row.hour_utc.isoformat() + "Z",  # Keep for backward compatibility
                "aqi_us": int(row.aqi_us) if row.aqi_us is not None else None
            }
            for row in history_rows
        ]
        
        return history_data
        
    except Exception as e:
        logger.error(f"Error getting station history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations/{station_numeric_id}/history/pm25")
async def get_station_history_pm25_data(
    station_numeric_id: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_database)
):
    """Get historical PM2.5 concentration data for a specific station using numeric ID
    
    Args:
        station_numeric_id: The numeric ID of the station (from stations list)
        hours: Number of hours of history to fetch (default: 24)
        
    Returns:
        List of historical PM2.5 readings with timestamp and pm25 value
        
    Note:
        This endpoint follows the same safe pattern as the AQI history endpoint,
        using parameterized queries and proper error handling.
    """
    try:
        # First get the station_id hash from numeric position
        station_lookup = await db.execute(text("""
            SELECT station_id 
            FROM stations 
            WHERE active = true 
            ORDER BY name 
            LIMIT 1 OFFSET :offset
        """), {"offset": station_numeric_id - 1})
        
        station_row = station_lookup.fetchone()
        if not station_row:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Generate complete hourly time series with Pakistan timezone
        history_result = await db.execute(text("""
            WITH RECURSIVE hour_series AS (
                SELECT 
                    date_trunc('hour', NOW() - INTERVAL '%s hours') + INTERVAL '1 hour' AS hour_utc
                UNION ALL
                SELECT 
                    hour_utc + INTERVAL '1 hour'
                FROM hour_series
                WHERE hour_utc < date_trunc('hour', NOW())
            )
            SELECT 
                hs.hour_utc,
                hs.hour_utc + INTERVAL '5 hours' AS hour_pk,
                r.pm25
            FROM hour_series hs
            LEFT JOIN readings r ON (
                date_trunc('hour', r.ts_utc) = hs.hour_utc
                AND r.scope_key = :station_id 
                AND r.scope_type = 'station'
            )
            ORDER BY hs.hour_utc ASC
        """ % hours), {"station_id": station_row.station_id})
        
        history_rows = history_result.fetchall()
        history_data = [
            {
                "timestamp_utc": row.hour_utc.isoformat() + "Z",
                "timestamp_pk": row.hour_pk.isoformat() + "+05:00",
                "timestamp": row.hour_utc.isoformat() + "Z",  # Keep for backward compatibility
                "pm25": float(row.pm25) if row.pm25 is not None else None
            }
            for row in history_rows
        ]
        
        return history_data
        
    except Exception as e:
        logger.error(f"Error getting station PM2.5 history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


