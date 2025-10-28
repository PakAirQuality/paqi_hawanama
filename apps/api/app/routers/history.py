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



@router.get("/stations/{station_id}/history")
async def get_station_history_data(
    station_id: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_database)
):
    """Get historical data for a specific station using numeric station ID"""
    try:
        # Get station by numeric index using same pattern as current endpoint  
        station_lookup = await db.execute(text("""
            SELECT station_id, name 
            FROM stations 
            WHERE active = true 
            ORDER BY name
        """))
        
        stations_list = station_lookup.fetchall()
        
        # Find the station at the given index
        if station_id < 1 or station_id > len(stations_list):
            raise HTTPException(status_code=404, detail="Station not found")
        
        target_station = stations_list[station_id - 1]  # Convert to 0-based index
        hash_station_id = target_station.station_id
        
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
                AND r.scope_key = :hash_station_id 
                AND r.scope_type = 'station'
            )
            ORDER BY hs.hour_utc ASC
        """ % hours), {"hash_station_id": hash_station_id})
        
        history_rows = history_result.fetchall()
        history_data = [
            {
                "timestamp_utc": row.hour_utc.isoformat() + "Z",
                "timestamp_pk": row.hour_pk.strftime('%Y-%m-%dT%H:%M:%S+05:00'),
                "timestamp": row.hour_utc.isoformat() + "Z",  # Keep for backward compatibility
                "aqi_us": int(row.aqi_us) if row.aqi_us is not None else None
            }
            for row in history_rows
        ]
        
        return history_data
        
    except Exception as e:
        logger.error(f"Error getting station history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stations/{station_id}/history/pm25")
async def get_station_history_pm25_data(
    station_id: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_database)
):
    """Get historical PM2.5 concentration data for a specific station using numeric station ID
    
    Args:
        station_id: The numeric station ID
        hours: Number of hours of history to fetch (default: 24)
        
    Returns:
        List of historical PM2.5 readings with timestamp and pm25 value
        
    Note:
        This endpoint follows the same safe pattern as the AQI history endpoint,
        using parameterized queries and proper error handling.
    """
    try:
        # Get station by numeric index using same pattern as other endpoints
        station_lookup = await db.execute(text("""
            SELECT station_id, name 
            FROM stations 
            WHERE active = true 
            ORDER BY name
        """))
        
        stations_list = station_lookup.fetchall()
        
        # Find the station at the given index
        if station_id < 1 or station_id > len(stations_list):
            raise HTTPException(status_code=404, detail="Station not found")
        
        target_station = stations_list[station_id - 1]  # Convert to 0-based index
        hash_station_id = target_station.station_id
        
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
                AND r.scope_key = :hash_station_id 
                AND r.scope_type = 'station'
            )
            ORDER BY hs.hour_utc ASC
        """ % hours), {"hash_station_id": hash_station_id})
        
        history_rows = history_result.fetchall()
        history_data = [
            {
                "timestamp_utc": row.hour_utc.isoformat() + "Z",
                "timestamp_pk": row.hour_pk.strftime('%Y-%m-%dT%H:%M:%S+05:00'),
                "timestamp": row.hour_utc.isoformat() + "Z",  # Keep for backward compatibility
                "pm25": float(row.pm25) if row.pm25 is not None else None
            }
            for row in history_rows
        ]
        
        return history_data
        
    except Exception as e:
        logger.error(f"Error getting station PM2.5 history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


