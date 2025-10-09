from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Optional, Dict, Any
from app.core.database import get_database
from datetime import datetime

router = APIRouter()

@router.get("/")
async def get_cities(
    db: AsyncSession = Depends(get_database),
    limit: Optional[int] = Query(50, description="Maximum number of cities to return")
):
    """Get all cities with their station counts and latest AQI data"""
    
    query = text("""
        SELECT 
            s.meta_json->>'iqair_city' as city_name,
            s.meta_json->>'iqair_state' as state,
            COUNT(DISTINCT s.id) as station_count,
            AVG(ST_X(s.geom)) as avg_longitude,
            AVG(ST_Y(s.geom)) as avg_latitude,
            -- Get latest AQI data from stations_vt view
            AVG(sv.aqi_raw) as avg_aqi,
            COUNT(CASE WHEN sv.aqi_raw IS NOT NULL THEN 1 END) as active_stations,
            MAX(sv.last_reading) as latest_update
        FROM stations s
        LEFT JOIN stations_vt sv ON s.id = sv.id
        WHERE s.meta_json->>'iqair_city' IS NOT NULL
        GROUP BY s.meta_json->>'iqair_city', s.meta_json->>'iqair_state'
        HAVING COUNT(DISTINCT s.id) > 0
        ORDER BY avg_aqi DESC NULLS LAST, station_count DESC
        LIMIT :limit
    """)
    
    result = await db.execute(query, {'limit': limit})
    cities_data = result.fetchall()
    
    cities = []
    for row in cities_data:
        # Calculate AQI category
        avg_aqi = int(row.avg_aqi) if row.avg_aqi else None
        aqi_category = "No Data"
        aqi_color = "gray"
        
        if avg_aqi is not None:
            if avg_aqi <= 50:
                aqi_category = "Good"
                aqi_color = "green"
            elif avg_aqi <= 100:
                aqi_category = "Moderate"
                aqi_color = "yellow"
            elif avg_aqi <= 150:
                aqi_category = "Unhealthy for Sensitive Groups"
                aqi_color = "orange"
            elif avg_aqi <= 200:
                aqi_category = "Unhealthy"
                aqi_color = "red"
            elif avg_aqi <= 300:
                aqi_category = "Very Unhealthy"
                aqi_color = "purple"
            else:
                aqi_category = "Hazardous"
                aqi_color = "maroon"
        
        # Calculate time since last update
        last_update_str = "No recent data"
        if row.latest_update:
            time_diff = datetime.utcnow() - row.latest_update.replace(tzinfo=None)
            if time_diff.total_seconds() < 3600:  # Less than 1 hour
                minutes = int(time_diff.total_seconds() / 60)
                last_update_str = f"{minutes} min ago"
            elif time_diff.total_seconds() < 86400:  # Less than 1 day
                hours = int(time_diff.total_seconds() / 3600)
                last_update_str = f"{hours}h ago"
            else:
                days = int(time_diff.total_seconds() / 86400)
                last_update_str = f"{days}d ago"
        
        city_data = {
            "city_name": row.city_name,
            "state": row.state,
            "station_count": row.station_count,
            "active_stations": row.active_stations,
            "avg_longitude": float(row.avg_longitude) if row.avg_longitude else None,
            "avg_latitude": float(row.avg_latitude) if row.avg_latitude else None,
            "avg_aqi": avg_aqi,
            "aqi_category": aqi_category,
            "aqi_color": aqi_color,
            "last_update": last_update_str,
            "slug": row.city_name.lower().replace(' ', '-').replace(',', '') if row.city_name else None
        }
        cities.append(city_data)
    
    return {
        "cities": cities,
        "count": len(cities)
    }

@router.get("/{city_slug}")
async def get_city_details(
    city_slug: str,
    db: AsyncSession = Depends(get_database)
):
    """Get detailed information for a specific city"""
    
    # Convert slug back to city name (approximate match)
    city_name_query = text("""
        SELECT DISTINCT s.meta_json->>'iqair_city' as city_name
        FROM stations s
        WHERE LOWER(REPLACE(REPLACE(s.meta_json->>'iqair_city', ' ', '-'), ',', '')) = :city_slug
        LIMIT 1
    """)
    
    city_result = await db.execute(city_name_query, {'city_slug': city_slug})
    city_row = city_result.fetchone()
    
    if not city_row:
        raise HTTPException(status_code=404, detail="City not found")
    
    city_name = city_row.city_name
    
    # Get city overview
    overview_query = text("""
        SELECT 
            s.meta_json->>'iqair_city' as city_name,
            s.meta_json->>'iqair_state' as state,
            COUNT(DISTINCT s.id) as total_stations,
            COUNT(CASE WHEN sv.aqi_raw IS NOT NULL THEN 1 END) as active_stations,
            AVG(ST_X(s.geom)) as avg_longitude,
            AVG(ST_Y(s.geom)) as avg_latitude,
            AVG(sv.aqi_raw) as avg_aqi,
            MIN(sv.aqi_raw) as min_aqi,
            MAX(sv.aqi_raw) as max_aqi,
            MAX(sv.last_reading) as latest_update,
            -- AQI distribution
            COUNT(CASE WHEN sv.aqi_category = 'good' THEN 1 END) as good_count,
            COUNT(CASE WHEN sv.aqi_category = 'moderate' THEN 1 END) as moderate_count,
            COUNT(CASE WHEN sv.aqi_category = 'unhealthy_sensitive' THEN 1 END) as unhealthy_sensitive_count,
            COUNT(CASE WHEN sv.aqi_category = 'unhealthy' THEN 1 END) as unhealthy_count,
            COUNT(CASE WHEN sv.aqi_category = 'very_unhealthy' THEN 1 END) as very_unhealthy_count,
            COUNT(CASE WHEN sv.aqi_category = 'hazardous' THEN 1 END) as hazardous_count
        FROM stations s
        LEFT JOIN stations_vt sv ON s.id = sv.id
        WHERE s.meta_json->>'iqair_city' = :city_name
        GROUP BY s.meta_json->>'iqair_city', s.meta_json->>'iqair_state'
    """)
    
    overview_result = await db.execute(overview_query, {'city_name': city_name})
    overview = overview_result.fetchone()
    
    # Get individual stations in the city
    stations_query = text("""
        SELECT 
            s.id,
            s.name,
            s.external_id,
            ST_X(s.geom) as longitude,
            ST_Y(s.geom) as latitude,
            sv.aqi_raw,
            sv.pm25,
            sv.pm10,
            sv.temp,
            sv.hum,
            sv.qc_state,
            sv.last_reading,
            sv.aqi_category,
            sv.qc_flag,
            sv.hours_since_update
        FROM stations s
        LEFT JOIN stations_vt sv ON s.id = sv.id
        WHERE s.meta_json->>'iqair_city' = :city_name
        ORDER BY sv.aqi_raw DESC NULLS LAST, s.name
    """)
    
    stations_result = await db.execute(stations_query, {'city_name': city_name})
    stations_data = stations_result.fetchall()
    
    stations = []
    for row in stations_data:
        station = {
            "id": row.id,
            "name": row.name,
            "external_id": row.external_id,
            "longitude": float(row.longitude) if row.longitude else None,
            "latitude": float(row.latitude) if row.latitude else None,
            "aqi_raw": row.aqi_raw,
            "pm25": row.pm25,
            "pm10": row.pm10,
            "temp": row.temp,
            "hum": row.hum,
            "qc_state": row.qc_state,
            "last_reading": row.last_reading.isoformat() if row.last_reading else None,
            "aqi_category": row.aqi_category,
            "qc_flag": row.qc_flag,
            "hours_since_update": float(row.hours_since_update) if row.hours_since_update else None
        }
        stations.append(station)
    
    # Calculate overall AQI category for city
    avg_aqi = int(overview.avg_aqi) if overview.avg_aqi else None
    aqi_category = "No Data"
    aqi_color = "gray"
    
    if avg_aqi is not None:
        if avg_aqi <= 50:
            aqi_category = "Good"
            aqi_color = "green"
        elif avg_aqi <= 100:
            aqi_category = "Moderate"
            aqi_color = "yellow"
        elif avg_aqi <= 150:
            aqi_category = "Unhealthy for Sensitive Groups"
            aqi_color = "orange"
        elif avg_aqi <= 200:
            aqi_category = "Unhealthy"
            aqi_color = "red"
        elif avg_aqi <= 300:
            aqi_category = "Very Unhealthy"
            aqi_color = "purple"
        else:
            aqi_category = "Hazardous"
            aqi_color = "maroon"
    
    # Calculate time since last update
    last_update_str = "No recent data"
    if overview.latest_update:
        time_diff = datetime.utcnow() - overview.latest_update.replace(tzinfo=None)
        if time_diff.total_seconds() < 3600:  # Less than 1 hour
            minutes = int(time_diff.total_seconds() / 60)
            last_update_str = f"{minutes} min ago"
        elif time_diff.total_seconds() < 86400:  # Less than 1 day
            hours = int(time_diff.total_seconds() / 3600)
            last_update_str = f"{hours}h ago"
        else:
            days = int(time_diff.total_seconds() / 86400)
            last_update_str = f"{days}d ago"
    
    return {
        "city_name": overview.city_name,
        "state": overview.state,
        "slug": city_slug,
        "total_stations": overview.total_stations,
        "active_stations": overview.active_stations,
        "avg_longitude": float(overview.avg_longitude) if overview.avg_longitude else None,
        "avg_latitude": float(overview.avg_latitude) if overview.avg_latitude else None,
        "avg_aqi": avg_aqi,
        "min_aqi": int(overview.min_aqi) if overview.min_aqi else None,
        "max_aqi": int(overview.max_aqi) if overview.max_aqi else None,
        "aqi_category": aqi_category,
        "aqi_color": aqi_color,
        "last_update": last_update_str,
        "distribution": {
            "good": overview.good_count or 0,
            "moderate": overview.moderate_count or 0,
            "unhealthy_sensitive": overview.unhealthy_sensitive_count or 0,
            "unhealthy": overview.unhealthy_count or 0,
            "very_unhealthy": overview.very_unhealthy_count or 0,
            "hazardous": overview.hazardous_count or 0
        },
        "stations": stations
    }

@router.get("/{city_slug}/historical")
async def get_city_historical_data(
    city_slug: str,
    db: AsyncSession = Depends(get_database),
    hours: Optional[int] = Query(24, description="Number of hours of historical data to return")
):
    """Get historical AQI data for a city"""
    
    # Convert slug back to city name
    city_name_query = text("""
        SELECT DISTINCT s.meta_json->>'iqair_city' as city_name
        FROM stations s
        WHERE LOWER(REPLACE(REPLACE(s.meta_json->>'iqair_city', ' ', '-'), ',', '')) = :city_slug
        LIMIT 1
    """)
    
    city_result = await db.execute(city_name_query, {'city_slug': city_slug})
    city_row = city_result.fetchone()
    
    if not city_row:
        raise HTTPException(status_code=404, detail="City not found")
    
    city_name = city_row.city_name
    
    # Get hourly aggregated data for the city
    historical_query = text("""
        SELECT 
            date_trunc('hour', rm.ts) as hour,
            AVG(rm.aqi_raw) as avg_aqi,
            AVG(rm.pm25) as avg_pm25,
            AVG(rm.pm10) as avg_pm10,
            AVG(rm.temp) as avg_temp,
            AVG(rm.hum) as avg_hum,
            COUNT(DISTINCT rm.station_id) as reporting_stations
        FROM readings_minute rm
        JOIN stations s ON rm.station_id = s.id
        WHERE s.meta_json->>'iqair_city' = :city_name
        AND rm.ts >= NOW() - INTERVAL '1 hour' * :hours
        AND rm.aqi_raw IS NOT NULL
        GROUP BY date_trunc('hour', rm.ts)
        ORDER BY hour ASC
    """)
    
    historical_result = await db.execute(historical_query, {
        'city_name': city_name,
        'hours': hours
    })
    historical_data = historical_result.fetchall()
    
    readings = []
    for row in historical_data:
        reading = {
            "timestamp": row.hour.isoformat(),
            "avg_aqi": round(row.avg_aqi, 1) if row.avg_aqi else None,
            "avg_pm25": round(row.avg_pm25, 1) if row.avg_pm25 else None,
            "avg_pm10": round(row.avg_pm10, 1) if row.avg_pm10 else None,
            "avg_temp": round(row.avg_temp, 1) if row.avg_temp else None,
            "avg_hum": round(row.avg_hum, 1) if row.avg_hum else None,
            "reporting_stations": row.reporting_stations
        }
        readings.append(reading)
    
    return {
        "city_name": city_name,
        "slug": city_slug,
        "hours_requested": hours,
        "readings_count": len(readings),
        "readings": readings
    }