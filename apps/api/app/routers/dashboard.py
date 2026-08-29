"""
Dashboard API Router - provides dashboard endpoints for frontend
"""

import logging
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_database)):
    """Get dashboard statistics"""
    try:
        result = await db.execute(text("""
            WITH station_stats AS (
                SELECT 
                    COUNT(*) as total_stations,
                    COUNT(CASE WHEN s.active = true THEN 1 END) as active_stations
                FROM stations s
                LEFT JOIN providers p ON s.provider_id = p.id
                WHERE COALESCE(p.code, '') != 'punjab'
            ),
            latest_readings AS (
                SELECT 
                    AVG(r.pm25) as avg_pm25,
                    MAX(r.ts_utc) as last_update,
                    COUNT(CASE WHEN r.ts_utc > NOW() - INTERVAL '6 hours' THEN 1 END) as recent_readings,
                    AVG(r.aqi_us) as avg_aqi
                FROM readings r 
                WHERE r.scope_type = 'station' 
                AND r.source != 'punjab'
                AND r.pm25 IS NOT NULL 
                AND r.ts_utc > NOW() - INTERVAL '24 hours'
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
            
        # Get top cities (last 7 days)
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
            city_parts = city_row.scope_key.split('|')
            city_name = city_parts[-1].title() if len(city_parts) > 0 else city_row.scope_key
            top_cities.append({
                "name": city_name,
                "aqi": float(city_row.avg_aqi)
            })
        
        # AQI color
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
            
        # Last update in PKT
        last_update = None
        if row.last_update:
            from datetime import timezone, timedelta
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


@router.get("/stations")
async def get_stations_for_map(db: AsyncSession = Depends(get_database)):
    """Get stations with latest readings for map display (hash-based IDs)"""
    try:
        result = await db.execute(text("""
            WITH latest_readings AS (
                SELECT DISTINCT ON (scope_key) 
                    scope_key, pm25, aqi_us, temp_c, humidity, pressure_hpa,
                    wind_speed_ms, wind_dir_deg, ts_utc, qc_state
                FROM readings
                WHERE scope_type = 'station'
                  AND ts_utc > NOW() - INTERVAL '48 hours'
                  -- QC gate: hide only readings we explicitly flagged bad (BAM). Legacy
                  -- providers use other qc_state values ('raw', 'OK', NULL) and must all
                  -- pass — so we EXCLUDE the bad states rather than allow-list 'OK'.
                  AND (qc_state IS NULL OR qc_state NOT IN ('INVALID', 'SUSPECT'))
                ORDER BY scope_key, ts_utc DESC
            )
            SELECT
                s.station_id,
                s.name,
                s.lat AS latitude,
                s.lon AS longitude,
                c.name AS city_name,
                lr.pm25,
                lr.aqi_us,
                lr.temp_c AS temp,
                lr.humidity AS hum,
                lr.pressure_hpa,
                lr.wind_speed_ms,
                lr.wind_dir_deg,
                lr.ts_utc AS last_reading,
                COALESCE(lr.qc_state, 'OK') AS qc_state,
                CASE 
                    WHEN lr.aqi_us <= 50 THEN 'good'
                    WHEN lr.aqi_us <= 100 THEN 'moderate'
                    WHEN lr.aqi_us <= 150 THEN 'unhealthy_sensitive'
                    WHEN lr.aqi_us <= 200 THEN 'unhealthy'
                    WHEN lr.aqi_us <= 300 THEN 'very_unhealthy'
                    ELSE 'hazardous'
                END AS aqi_category
            FROM stations s
            LEFT JOIN cities c ON s.city_id = c.id
            LEFT JOIN latest_readings lr ON s.station_id = lr.scope_key
            LEFT JOIN providers p ON s.provider_id = p.id
            WHERE s.active = true
              AND COALESCE(p.code, '') != 'punjab'
            ORDER BY s.name
        """))
        
        stations_rows = result.fetchall()
        stations_list = []
        for row in stations_rows:
            station_data = {
                # <-- hash ID becomes the public API ID
                "id": row.station_id,
                "name": row.name,
                "latitude": float(row.latitude) if row.latitude is not None else 0.0,
                "longitude": float(row.longitude) if row.longitude is not None else 0.0,
                "city": row.city_name,
                "source_id": 1,  # keep if frontend expects this
                "pm25": float(row.pm25) if row.pm25 is not None else None,
                "aqi_raw": int(row.aqi_us) if row.aqi_us is not None else None,
                "temp": float(row.temp) if row.temp is not None else None,
                "hum": float(row.hum) if row.hum is not None else None,
                "qc_state": row.qc_state,
                "aqi_category": row.aqi_category if row.aqi_us is not None else None,
                "last_reading": row.last_reading.isoformat() if row.last_reading else None,
            }
            stations_list.append(station_data)
        
        return JSONResponse(
            {"stations": stations_list},
            headers={"Cache-Control": "public, max-age=60, s-maxage=120, stale-while-revalidate=300"},
        )

    except Exception as e:
        logger.error(f"Error getting stations: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations/{station_id}/current")
async def get_station_current_data(
    station_id: str,
    db: AsyncSession = Depends(get_database)
):
    """Get current data for a specific station using hash station_id"""
    try:
        # Verify station exists and is not Punjab EPA
        station_result = await db.execute(text("""
            SELECT s.station_id, s.name, s.lat, s.lon
            FROM stations s
            LEFT JOIN providers p ON s.provider_id = p.id
            WHERE s.station_id = :station_id
              AND s.active = true
              AND COALESCE(p.code, '') != 'punjab'
        """), {"station_id": station_id})
        
        target_station = station_result.fetchone()
        if not target_station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Get latest reading for this station
        latest_reading = await db.execute(text("""
            WITH latest_readings AS (
                SELECT DISTINCT ON (scope_key)
                    scope_key, pm25, aqi_us, temp_c, humidity, pressure_hpa,
                    wind_speed_ms, wind_dir_deg, ts_utc
                FROM readings
                WHERE scope_type = 'station'
                  AND scope_key = :station_id
                  AND ts_utc > NOW() - INTERVAL '48 hours'
                  -- QC gate: hide implausible readings from the public current view.
                  AND (qc_state IS NULL OR qc_state NOT IN ('INVALID', 'SUSPECT'))
                ORDER BY scope_key, ts_utc DESC
            )
            SELECT * FROM latest_readings
        """), {"station_id": station_id})
        
        reading_row = latest_reading.fetchone()
        
        # Main pollutant
        main_pollutant = "PM2.5"
        main_value = float(reading_row.pm25) if reading_row and reading_row.pm25 is not None else 0.0
        aqi_value = int(reading_row.aqi_us) if reading_row and reading_row.aqi_us is not None else 0
        
        return {
            "station_id": station_id,  # hash ID as string
            "name": target_station.name,
            "aqi_us": aqi_value,
            "main_pollutant": main_pollutant,
            "main_value": main_value,
            "main_units": "µg/m³",
            "temp_c": float(reading_row.temp_c) if reading_row and reading_row.temp_c is not None else None,
            "humidity": float(reading_row.humidity) if reading_row and reading_row.humidity is not None else None,
            "wind_speed_kmh": float(reading_row.wind_speed_ms * 3.6) if reading_row and reading_row.wind_speed_ms is not None else None,
            "wind_direction": float(reading_row.wind_dir_deg) if reading_row and reading_row.wind_dir_deg is not None else None,
            "pressure_mbar": float(reading_row.pressure_hpa) if reading_row and reading_row.pressure_hpa is not None else None,
            "last_update": reading_row.ts_utc.isoformat() if reading_row and reading_row.ts_utc is not None else None,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station current data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations/{station_id}/history")
async def get_station_history_data(
    station_id: str,
    hours: int = 24,
    db: AsyncSession = Depends(get_database)
):
    """Get historical AQI data for a specific station using hash station_id"""
    try:
        # Verify station exists / is allowed
        station_result = await db.execute(text("""
            SELECT s.station_id, s.name
            FROM stations s
            LEFT JOIN providers p ON s.provider_id = p.id
            WHERE s.station_id = :station_id
              AND s.active = true
              AND COALESCE(p.code, '') != 'punjab'
        """), {"station_id": station_id})
        
        target_station = station_result.fetchone()
        if not target_station:
            raise HTTPException(status_code=404, detail="Station not found")
        
        # Validate hours parameter
        if not isinstance(hours, int) or hours < 1 or hours > 168:
            raise HTTPException(status_code=400, detail="Invalid hours parameter (1-168)")
            
        from datetime import datetime, timedelta
        start_time = datetime.now() - timedelta(hours=hours)
        
        history_result = await db.execute(text("""
            SELECT 
                date_trunc('hour', r.ts_utc) AS hour_utc,
                date_trunc('hour', r.ts_utc) + INTERVAL '5 hours' AS hour_pk,
                r.aqi_us
            FROM readings r 
            WHERE r.scope_key = :station_id 
                AND r.scope_type = 'station'
                AND r.ts_utc >= :start_time
                AND r.ts_utc <= NOW()
            ORDER BY r.ts_utc ASC
        """), {"station_id": station_id, "start_time": start_time})
        
        history_rows = history_result.fetchall()
        history_data = [
            {
                "timestamp_utc": row.hour_utc.isoformat() + "Z",
                "timestamp_pk": row.hour_pk.strftime('%Y-%m-%dT%H:%M:%S+05:00'),
                "timestamp": row.hour_utc.isoformat() + "Z",  # backward compat
                "aqi_us": int(row.aqi_us) if row.aqi_us is not None else None,
            }
            for row in history_rows
        ]
        
        return history_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations/{station_id}/history/pm25")
async def get_station_history_pm25_data(
    station_id: str,
    hours: int = 24,
    date: str = None,
    all_providers: bool = False,
    db: AsyncSession = Depends(get_database)
):
    """Get historical PM2.5 concentration data for a specific station using hash station_id.

    If `date` is provided (YYYY-MM-DD), returns hourly data for that specific day (00:00-23:59 UTC).
    Otherwise returns the last `hours` hours from now.
    If `all_providers` is true, includes all providers (including Punjab EPA).
    """
    try:
        # Verify station exists / is allowed
        provider_filter = "" if all_providers else "AND COALESCE(p.code, '') != 'punjab'"
        station_result = await db.execute(text(f"""
            SELECT s.station_id, s.name
            FROM stations s
            LEFT JOIN providers p ON s.provider_id = p.id
            WHERE s.station_id = :station_id
              AND s.active = true
              {provider_filter}
        """), {"station_id": station_id})

        target_station = station_result.fetchone()
        if not target_station:
            raise HTTPException(status_code=404, detail="Station not found")

        from datetime import datetime, timedelta

        if date:
            # Date-specific query: full day in UTC
            try:
                day = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
            start_time = day
            end_time = day + timedelta(days=1)
        else:
            # Validate hours parameter
            if not isinstance(hours, int) or hours < 1 or hours > 168:
                raise HTTPException(status_code=400, detail="Invalid hours parameter (1-168)")
            start_time = datetime.now() - timedelta(hours=hours)
            end_time = datetime.now()

        history_result = await db.execute(text("""
            SELECT
                date_trunc('hour', r.ts_utc) AS hour_utc,
                date_trunc('hour', r.ts_utc) + INTERVAL '5 hours' AS hour_pk,
                r.pm25
            FROM readings r
            WHERE r.scope_key = :station_id
                AND r.scope_type = 'station'
                AND r.ts_utc >= :start_time
                AND r.ts_utc <= :end_time
            ORDER BY r.ts_utc ASC
        """), {"station_id": station_id, "start_time": start_time, "end_time": end_time})
        
        history_rows = history_result.fetchall()
        history_data = [
            {
                "timestamp_utc": row.hour_utc.isoformat() + "Z",
                "timestamp_pk": row.hour_pk.strftime('%Y-%m-%dT%H:%M:%S+05:00'),
                "timestamp": row.hour_utc.isoformat() + "Z",
                "pm25": float(row.pm25) if row.pm25 is not None else None,
            }
            for row in history_rows
        ]
        
        return history_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station PM2.5 history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations/{station_id}/history/pm25/daily")
async def get_station_daily_pm25_data(
    station_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_database),
):
    """Get daily-aggregated PM2.5 data for a station (for 30d/90d/yearly views)."""
    try:
        # Verify station exists / is allowed
        station_result = await db.execute(text("""
            SELECT s.station_id, s.name
            FROM stations s
            LEFT JOIN providers p ON s.provider_id = p.id
            WHERE s.station_id = :station_id
              AND s.active = true
              AND COALESCE(p.code, '') != 'punjab'
        """), {"station_id": station_id})

        target_station = station_result.fetchone()
        if not target_station:
            raise HTTPException(status_code=404, detail="Station not found")

        if not isinstance(days, int) or days < 1 or days > 365:
            raise HTTPException(status_code=400, detail="Invalid days parameter (1-365)")

        from datetime import datetime, timedelta
        start_time = datetime.now() - timedelta(days=days)

        history_result = await db.execute(text("""
            SELECT
                date_trunc('day', r.ts_utc + INTERVAL '5 hours') AS day_pk,
                AVG(r.pm25) AS pm25_mean,
                MIN(r.pm25) AS pm25_min,
                MAX(r.pm25) AS pm25_max,
                COUNT(*) AS n_readings
            FROM readings r
            WHERE r.scope_key = :station_id
                AND r.scope_type = 'station'
                AND r.ts_utc >= :start_time
                AND r.ts_utc <= NOW()
                AND r.pm25 IS NOT NULL
            GROUP BY day_pk
            ORDER BY day_pk ASC
        """), {"station_id": station_id, "start_time": start_time})

        history_rows = history_result.fetchall()
        # Return same shape as hourly endpoint (pm25 = daily mean)
        history_data = [
            {
                "timestamp_utc": row.day_pk.strftime('%Y-%m-%dT00:00:00Z'),
                "timestamp_pk": row.day_pk.strftime('%Y-%m-%dT05:00:00+05:00'),
                "pm25": round(float(row.pm25_mean), 1) if row.pm25_mean is not None else None,
                "pm25_min": round(float(row.pm25_min), 1) if row.pm25_min is not None else None,
                "pm25_max": round(float(row.pm25_max), 1) if row.pm25_max is not None else None,
            }
            for row in history_rows
        ]

        return history_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station daily PM2.5 history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")