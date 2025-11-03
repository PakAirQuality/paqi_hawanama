from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_database
from typing import List, Optional
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/cities")
async def get_cities(
    limit: Optional[int] = None,
    db: AsyncSession = Depends(get_database)
):
    """Get list of all cities with station data"""
    try:
        # Get cities with station counts and latest data
        query = """
        WITH city_stats AS (
            SELECT 
                c.id,
                c.name as city_name,
                c.state_id,
                c.country_id,
                s2.name as state_name,
                c2.name as country_name,
                COUNT(s.station_id) as station_count,
                AVG(latest.pm25) as avg_pm25,
                AVG(latest.aqi_us) as avg_aqi,
                MAX(latest.ts_utc) as last_update
            FROM cities c
            LEFT JOIN states s2 ON c.state_id = s2.id
            LEFT JOIN countries c2 ON c.country_id = c2.id
            LEFT JOIN stations s ON c.id = s.city_id AND s.active = true
            LEFT JOIN LATERAL (
                SELECT pm25, aqi_us, ts_utc
                FROM readings r
                WHERE r.scope_key = s.station_id
                    AND r.scope_type = 'station'
                    AND r.ts_utc > NOW() - INTERVAL '24 HOUR'
                ORDER BY r.ts_utc DESC
                LIMIT 1
            ) latest ON true
            WHERE c.id IN (
                SELECT DISTINCT city_id 
                FROM stations 
                WHERE active = true AND city_id IS NOT NULL
            )
            GROUP BY c.id, c.name, c.state_id, c.country_id, s2.name, c2.name
            HAVING COUNT(s.station_id) > 0
            ORDER BY avg_aqi DESC NULLS LAST, station_count DESC
        )
        SELECT * FROM city_stats
        """ + (f"LIMIT {limit}" if limit else "")
        
        result = await db.execute(text(query))
        cities = result.fetchall()
        
        cities_list = []
        for city in cities:
            # Determine AQI category
            aqi_category = 'good'
            if city.avg_aqi:
                if city.avg_aqi <= 50:
                    aqi_category = 'good'
                elif city.avg_aqi <= 100:
                    aqi_category = 'moderate'
                elif city.avg_aqi <= 150:
                    aqi_category = 'unhealthy_sensitive'
                elif city.avg_aqi <= 200:
                    aqi_category = 'unhealthy'
                elif city.avg_aqi <= 300:
                    aqi_category = 'very_unhealthy'
                else:
                    aqi_category = 'hazardous'
            
            cities_list.append({
                "id": city.id,
                "name": city.city_name,
                "slug": city.city_name.lower().replace(' ', '-').replace(',', ''),
                "state": city.state_name,
                "country": city.country_name,
                "station_count": city.station_count,
                "avg_pm25": round(city.avg_pm25, 1) if city.avg_pm25 else None,
                "avg_aqi": round(city.avg_aqi, 1) if city.avg_aqi else None,
                "aqi_category": aqi_category,
                "last_update": city.last_update.isoformat() if city.last_update else None
            })
        
        return {"cities": cities_list, "count": len(cities_list)}
        
    except Exception as e:
        logger.error(f"Error getting cities: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/cities/{city_slug}")
async def get_city(
    city_slug: str = Path(
        ...,
        description="Select city from dropdown list",
        example="lahore",
        enum=[
            "abbottabad", "bahawalpur", "bhopalwala", "chak-jhumra", "daska-kalan", 
            "dera-ismail-khan", "eminabad", "faisalabad", "gujranwala", "haripur", 
            "hundal", "hyderabad", "islamabad", "jhang", "jhelum", "kahna-nau", 
            "karachi", "kasur", "khairpur-mirs", "kharan", "khurrianwala", 
            "kot-malik-barkhurdar", "kotli-loharan", "kotri", "ladhewala-waraich", 
            "lahore", "lodhran", "malam-jabba", "malir-cantonment", "mandi-bahauddin", 
            "mirpur-khas", "multan", "murree", "pasrur", "pattoki", "peshawar", 
            "pindi-bhattian", "qadirpur-ran", "quetta", "rahim-yar-khan", "raiwind", 
            "rawalpindi", "rojhan", "sambrial", "sheikhupura", "sialkot", "skardu", "sukkur"
        ]
    ),
    db: AsyncSession = Depends(get_database)
):
    """Get detailed city information with stations and aggregated data"""
    try:
        # Convert slug back to city name (basic approach)
        city_name = city_slug.replace('-', ' ').title()
        
        # Get city details with stations
        city_query = """
        WITH city_data AS (
            SELECT 
                c.id,
                c.name as city_name,
                s2.name as state_name,
                c2.name as country_name,
                COUNT(s.station_id) as station_count
            FROM cities c
            LEFT JOIN states s2 ON c.state_id = s2.id
            LEFT JOIN countries c2 ON c.country_id = c2.id
            LEFT JOIN stations s ON c.id = s.city_id AND s.active = true
            WHERE LOWER(c.name) = LOWER(:city_name)
               OR LOWER(c.name) = LOWER(:city_slug)
            GROUP BY c.id, c.name, s2.name, c2.name
        )
        SELECT * FROM city_data
        """
        
        city_result = await db.execute(text(city_query), {
            "city_name": city_name,
            "city_slug": city_slug.replace('-', ' ')
        })
        city_data = city_result.fetchone()
        
        if not city_data:
            raise HTTPException(status_code=404, detail="City not found")
        
        # Get city-level meteorological data (separate from station data)
        city_scope_key = f"pakistan|{city_data.state_name.lower()}|{city_data.city_name.lower()}"
        city_weather_query = """
        SELECT 
            temp_c,
            humidity,
            pressure_hpa,
            wind_speed_ms,
            wind_dir_deg,
            heatindex_c,
            ts_utc,
            pm25,
            aqi_us
        FROM readings r
        WHERE r.scope_type = 'city'
            AND LOWER(r.scope_key) = LOWER(:scope_key)
            AND r.ts_utc > NOW() - INTERVAL '6 HOUR'
        ORDER BY r.ts_utc DESC
        LIMIT 1
        """
        
        city_weather_result = await db.execute(text(city_weather_query), {"scope_key": city_scope_key})
        city_weather = city_weather_result.fetchone()
        
        if city_weather:
            pass
        
        # Get stations in this city with latest readings
        stations_query = """
        WITH latest_readings AS (
            SELECT DISTINCT ON (s.station_id)
                s.station_id,
                s.name,
                s.lat,
                s.lon,
                r.pm25,
                r.aqi_us,
                r.temp_c,
                r.humidity,
                r.pressure_hpa,
                r.wind_speed_ms,
                r.wind_dir_deg,
                r.ts_utc,
                EXTRACT(EPOCH FROM (NOW() - r.ts_utc)) / 3600 as hours_since_update
            FROM stations s
            LEFT JOIN readings r ON s.station_id = r.scope_key 
                AND r.scope_type = 'station'
                AND r.ts_utc > NOW() - INTERVAL '48 HOUR'
            WHERE s.city_id = :city_id AND s.active = true
            ORDER BY s.station_id, r.ts_utc DESC
        )
        SELECT * FROM latest_readings ORDER BY name
        """
        
        stations_result = await db.execute(text(stations_query), {"city_id": city_data.id})
        stations = stations_result.fetchall()
        
        
        # Calculate AQI distribution
        distribution = {
            'good': 0,
            'moderate': 0, 
            'unhealthy_sensitive': 0,
            'unhealthy': 0,
            'very_unhealthy': 0,
            'hazardous': 0
        }
        
        total_aqi = 0
        valid_readings = 0
        aqi_values = []
        latest_update = None
        
        stations_list = []
        for station in stations:
            station_data = {
                "id": station.station_id,  # Use hash ID (original behavior)
                "name": station.name,
                "latitude": float(station.lat) if station.lat else None,
                "longitude": float(station.lon) if station.lon else None,
                "latest_pm25": float(station.pm25) if station.pm25 else None,
                "latest_aqi": int(station.aqi_us) if station.aqi_us else None,
                "temp_c": float(station.temp_c) if station.temp_c else None,
                "humidity": float(station.humidity) if station.humidity else None,
                "pressure_hpa": float(station.pressure_hpa) if station.pressure_hpa else None,
                "wind_speed_ms": float(station.wind_speed_ms) if station.wind_speed_ms else None,
                "wind_direction": float(station.wind_dir_deg) if station.wind_dir_deg else None,
                "hours_since_update": float(station.hours_since_update) if station.hours_since_update else None,
                "last_reading": station.ts_utc.isoformat() if station.ts_utc else None
            }
            
            # Calculate AQI category
            if station.aqi_us:
                aqi_val = int(station.aqi_us)
                aqi_values.append(aqi_val)
                total_aqi += aqi_val
                valid_readings += 1
                
                if aqi_val <= 50:
                    distribution['good'] += 1
                    station_data['aqi_category'] = 'good'
                elif aqi_val <= 100:
                    distribution['moderate'] += 1
                    station_data['aqi_category'] = 'moderate'
                elif aqi_val <= 150:
                    distribution['unhealthy_sensitive'] += 1
                    station_data['aqi_category'] = 'unhealthy_sensitive'
                elif aqi_val <= 200:
                    distribution['unhealthy'] += 1
                    station_data['aqi_category'] = 'unhealthy'
                elif aqi_val <= 300:
                    distribution['very_unhealthy'] += 1
                    station_data['aqi_category'] = 'very_unhealthy'
                else:
                    distribution['hazardous'] += 1
                    station_data['aqi_category'] = 'hazardous'
            
            # Track latest update
            if station.ts_utc and (not latest_update or station.ts_utc > latest_update):
                latest_update = station.ts_utc
            
            stations_list.append(station_data)
        
        # Calculate city-level statistics
        avg_aqi = round(total_aqi / valid_readings) if valid_readings > 0 else None
        min_aqi = min(aqi_values) if aqi_values else None
        max_aqi = max(aqi_values) if aqi_values else None
        
        # Determine overall city AQI category
        city_aqi_category = 'good'
        if avg_aqi:
            if avg_aqi <= 50:
                city_aqi_category = 'good'
            elif avg_aqi <= 100:
                city_aqi_category = 'moderate'
            elif avg_aqi <= 150:
                city_aqi_category = 'unhealthy_sensitive'
            elif avg_aqi <= 200:
                city_aqi_category = 'unhealthy'
            elif avg_aqi <= 300:
                city_aqi_category = 'very_unhealthy'
            else:
                city_aqi_category = 'hazardous'
        
        # Prepare city-level weather data
        city_weather_data = None
        if city_weather:
            city_weather_data = {
                "temperature": float(city_weather.temp_c) if city_weather.temp_c else None,
                "humidity": float(city_weather.humidity) if city_weather.humidity else None,
                "pressure": float(city_weather.pressure_hpa) if city_weather.pressure_hpa else None,
                "wind_speed": float(city_weather.wind_speed_ms) if city_weather.wind_speed_ms else None,
                "wind_direction": float(city_weather.wind_dir_deg) if city_weather.wind_dir_deg else None,
                "heat_index": float(city_weather.heatindex_c) if city_weather.heatindex_c else None,
                "last_update": city_weather.ts_utc.isoformat() if city_weather.ts_utc else None
            }
        
        return {
            "id": city_data.id,
            "city_name": city_data.city_name,
            "state": city_data.state_name,
            "country": city_data.country_name,
            "slug": city_slug,
            "station_count": len(stations_list),
            "active_stations": len([s for s in stations_list if s['latest_aqi'] is not None]),
            "avg_aqi": avg_aqi,
            "min_aqi": min_aqi,
            "max_aqi": max_aqi,
            "aqi_category": city_aqi_category,
            "distribution": distribution,
            "last_update": latest_update.isoformat() if latest_update else None,
            "weather": city_weather_data,
            "stations": stations_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting city {city_slug}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/cities/{city_slug}/historical")
async def get_city_historical(
    city_slug: str = Path(
        ...,
        description="Select city from dropdown list",
        example="lahore",
        enum=[
            "abbottabad", "bahawalpur", "bhopalwala", "chak-jhumra", "daska-kalan", 
            "dera-ismail-khan", "eminabad", "faisalabad", "gujranwala", "haripur", 
            "hundal", "hyderabad", "islamabad", "jhang", "jhelum", "kahna-nau", 
            "karachi", "kasur", "khairpur-mirs", "kharan", "khurrianwala", 
            "kot-malik-barkhurdar", "kotli-loharan", "kotri", "ladhewala-waraich", 
            "lahore", "lodhran", "malam-jabba", "malir-cantonment", "mandi-bahauddin", 
            "mirpur-khas", "multan", "murree", "pasrur", "pattoki", "peshawar", 
            "pindi-bhattian", "qadirpur-ran", "quetta", "rahim-yar-khan", "raiwind", 
            "rawalpindi", "rojhan", "sambrial", "sheikhupura", "sialkot", "skardu", "sukkur"
        ]
    ),
    hours: int = 24,
    db: AsyncSession = Depends(get_database)
):
    """Get historical AQI data for a city (hourly averages)"""
    try:
        # Convert slug back to city name
        city_name = city_slug.replace('-', ' ').title()
        
        # Get city details to construct scope key
        city_query = """
        SELECT c.id, c.name as city_name, s.name as state_name
        FROM cities c
        LEFT JOIN states s ON c.state_id = s.id 
        WHERE LOWER(c.name) = LOWER(:city_name) 
           OR LOWER(c.name) = LOWER(:city_slug)
        """
        
        city_result = await db.execute(text(city_query), {
            "city_name": city_name,
            "city_slug": city_slug.replace('-', ' ')
        })
        city_data = city_result.fetchone()
        
        if not city_data:
            raise HTTPException(status_code=404, detail="City not found")
        
        # Construct city scope key
        city_scope_key = f"pakistan|{city_data.state_name.lower()}|{city_data.city_name.lower()}"
        
        # Get city-level historical readings (not station aggregation)
        historical_query = """
        SELECT 
            DATE_TRUNC('hour', r.ts_utc) as hour,
            r.pm25 as avg_pm25,
            r.aqi_us as avg_aqi,
            r.temp_c as avg_temp,
            r.humidity as avg_humidity,
            r.pressure_hpa as avg_pressure,
            r.wind_speed_ms as avg_wind_speed,
            r.wind_dir_deg as avg_wind_direction,
            r.heatindex_c as avg_heat_index,
            1 as station_count
        FROM readings r
        WHERE r.scope_type = 'city'
            AND LOWER(r.scope_key) = LOWER(:scope_key)
            AND r.ts_utc >= NOW() - INTERVAL '1 HOUR' * :hours
        ORDER BY hour
        """
        
        result = await db.execute(text(historical_query), {
            "scope_key": city_scope_key,
            "hours": hours
        })
        historical_data = result.fetchall()
        
        readings = []
        for row in historical_data:
            # Determine AQI category
            aqi_category = 'good'
            if row.avg_aqi:
                if row.avg_aqi <= 50:
                    aqi_category = 'good'
                elif row.avg_aqi <= 100:
                    aqi_category = 'moderate'
                elif row.avg_aqi <= 150:
                    aqi_category = 'unhealthy_sensitive'
                elif row.avg_aqi <= 200:
                    aqi_category = 'unhealthy'
                elif row.avg_aqi <= 300:
                    aqi_category = 'very_unhealthy'
                else:
                    aqi_category = 'hazardous'
            
            readings.append({
                "timestamp": row.hour.isoformat(),
                "avg_pm25": round(row.avg_pm25, 1) if row.avg_pm25 else None,
                "avg_aqi": round(row.avg_aqi, 1) if row.avg_aqi else None,
                "avg_temp": round(row.avg_temp, 1) if row.avg_temp else None,
                "avg_humidity": round(row.avg_humidity, 1) if row.avg_humidity else None,
                "avg_pressure": round(row.avg_pressure, 1) if row.avg_pressure else None,
                "avg_wind_speed": round(row.avg_wind_speed, 1) if row.avg_wind_speed else None,
                "avg_wind_direction": round(row.avg_wind_direction, 1) if row.avg_wind_direction else None,
                "avg_heat_index": round(row.avg_heat_index, 1) if row.avg_heat_index else None,
                "station_count": row.station_count,
                "aqi_category": aqi_category
            })
        
        return {
            "city_slug": city_slug,
            "hours": hours,
            "readings": readings,
            "count": len(readings)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting historical data for city {city_slug}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


