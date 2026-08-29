"""
Forecasts data repository
Handles bulk operations for forecast data
"""

import logging
from typing import List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def upsert_forecasts_bulk(session: AsyncSession, rows: List[Dict[str, Any]]) -> int:
    """
    Bulk upsert forecast data with conflict resolution
    
    Args:
        session: Database session
        rows: List of forecast row dictionaries
    
    Returns:
        Number of rows processed
    """
    if not rows:
        return 0
    
    try:
        # Check if forecasts table exists, if not create a simple version
        await _ensure_forecasts_table(session)
        
        query = text("""
            INSERT INTO forecasts (
                scope_type, scope_key, ts_utc, forecast_type, forecast_horizon_hours,
                aqi_us, aqi_cn, pm25, pm10, o3, no2, so2, co,
                temp_c, temp_min_c, temp_max_c, humidity, pressure_hpa,
                wind_speed_ms, wind_dir_deg, weather_icon, pop_pct,
                source, raw, created_at
            )
            VALUES (
                :scope_type, :scope_key, :ts_utc, :forecast_type, :forecast_horizon_hours,
                :aqi_us, :aqi_cn, :pm25, :pm10, :o3, :no2, :so2, :co,
                :temp_c, :temp_min_c, :temp_max_c, :humidity, :pressure_hpa,
                :wind_speed_ms, :wind_dir_deg, :weather_icon, :pop_pct,
                :source, :raw, :created_at
            )
            ON CONFLICT (scope_type, scope_key, ts_utc, forecast_type) 
            DO UPDATE SET 
                forecast_horizon_hours = EXCLUDED.forecast_horizon_hours,
                aqi_us = EXCLUDED.aqi_us,
                aqi_cn = EXCLUDED.aqi_cn,
                pm25 = EXCLUDED.pm25,
                pm10 = EXCLUDED.pm10,
                o3 = EXCLUDED.o3,
                no2 = EXCLUDED.no2,
                so2 = EXCLUDED.so2,
                co = EXCLUDED.co,
                temp_c = EXCLUDED.temp_c,
                temp_min_c = EXCLUDED.temp_min_c,
                temp_max_c = EXCLUDED.temp_max_c,
                humidity = EXCLUDED.humidity,
                pressure_hpa = EXCLUDED.pressure_hpa,
                wind_speed_ms = EXCLUDED.wind_speed_ms,
                wind_dir_deg = EXCLUDED.wind_dir_deg,
                weather_icon = EXCLUDED.weather_icon,
                pop_pct = EXCLUDED.pop_pct,
                raw = EXCLUDED.raw,
                created_at = EXCLUDED.created_at
        """)
        
        # Ensure all rows have required keys with defaults
        processed_rows = []
        created_at = datetime.now(timezone.utc)
        
        for row in rows:
            processed_row = {
                # Required fields
                "scope_type": row.get("scope_type"),
                "scope_key": row.get("scope_key"),
                "ts_utc": row.get("ts_utc"),
                "forecast_type": row.get("forecast_type"),
                "forecast_horizon_hours": row.get("forecast_horizon_hours", 0),
                # Pollution forecast
                "aqi_us": row.get("aqi_us"),
                "aqi_cn": row.get("aqi_cn"),
                "pm25": row.get("pm25"),
                "pm10": row.get("pm10"),
                "o3": row.get("o3"),
                "no2": row.get("no2"),
                "so2": row.get("so2"),
                "co": row.get("co"),
                # Weather forecast
                "temp_c": row.get("temp_c"),
                "temp_min_c": row.get("temp_min_c"),
                "temp_max_c": row.get("temp_max_c"),
                "humidity": row.get("humidity"),
                "pressure_hpa": row.get("pressure_hpa"),
                "wind_speed_ms": row.get("wind_speed_ms"),
                "wind_dir_deg": row.get("wind_dir_deg"),
                "weather_icon": row.get("weather_icon"),
                "pop_pct": row.get("pop_pct"),
                # Metadata
                "source": row.get("source", "airvisual"),
                "raw": row.get("raw"),
                "created_at": row.get("created_at", created_at)
            }
            processed_rows.append(processed_row)
        
        await session.execute(query, processed_rows)
        
        logger.debug(f"Bulk upserted {len(processed_rows)} forecast rows")
        return len(processed_rows)
        
    except Exception as error:
        logger.error(f"Bulk upsert forecasts failed: {error}")
        raise error


async def get_latest_forecasts_by_scope(session: AsyncSession, scope_keys: List[str], forecast_type: str = "hourly") -> List[Dict[str, Any]]:
    """
    Get latest forecasts for multiple scopes
    
    Args:
        session: Database session
        scope_keys: List of scope keys to fetch
        forecast_type: Type of forecast ("hourly" or "daily")
    
    Returns:
        List of forecast rows
    """
    if not scope_keys:
        return []
    
    try:
        # Create parameterized IN clause
        placeholders = ','.join([f':scope_{i}' for i in range(len(scope_keys))])
        params = {f'scope_{i}': scope_key for i, scope_key in enumerate(scope_keys)}
        params['forecast_type'] = forecast_type
        
        query = text(f"""
            WITH latest_forecasts AS (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY scope_key ORDER BY created_at DESC, ts_utc ASC) as rn
                FROM forecasts
                WHERE scope_key IN ({placeholders})
                  AND forecast_type = :forecast_type
                  AND ts_utc >= NOW()  -- Only future forecasts
            )
            SELECT scope_type, scope_key, ts_utc, forecast_type, forecast_horizon_hours,
                   aqi_us, aqi_cn, pm25, pm10, temp_c, weather_icon, created_at
            FROM latest_forecasts
            WHERE rn <= 24  -- Limit per scope
            ORDER BY scope_key, ts_utc ASC
        """)
        
        result = await session.execute(query, params)
        forecasts = [dict(row._mapping) for row in result.fetchall()]
        
        logger.debug(f"Retrieved {len(forecasts)} latest {forecast_type} forecasts for {len(scope_keys)} scopes")
        return forecasts
        
    except Exception as error:
        logger.error(f"Failed to get latest forecasts by scope: {error}")
        return []


async def cleanup_old_forecasts(session: AsyncSession, days_to_keep: int = 7) -> int:
    """
    Clean up old forecast data to prevent table bloat
    
    Args:
        session: Database session
        days_to_keep: Number of days of forecasts to keep
    
    Returns:
        Number of rows deleted
    """
    try:
        query = text("""
            DELETE FROM forecasts
            WHERE created_at < NOW() - INTERVAL ':days days'
               OR ts_utc < NOW() - INTERVAL '1 day'  -- Remove past forecasts
        """)
        
        result = await session.execute(query, {"days": days_to_keep})
        deleted_count = result.rowcount
        
        logger.info(f"Cleaned up {deleted_count} old forecast rows")
        return deleted_count
        
    except Exception as error:
        logger.error(f"Failed to cleanup old forecasts: {error}")
        return 0


async def _ensure_forecasts_table(session: AsyncSession):
    """
    Ensure forecasts table exists, create if not
    This is a temporary helper until proper migrations are in place
    """
    try:
        # Check if table exists
        check_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'forecasts'
            );
        """)
        
        result = await session.execute(check_query)
        table_exists = result.scalar()
        
        if not table_exists:
            logger.info("Creating forecasts table")
            
            create_query = text("""
                CREATE TABLE IF NOT EXISTS forecasts (
                    scope_type TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    ts_utc TIMESTAMP WITH TIME ZONE NOT NULL,
                    forecast_type TEXT NOT NULL,
                    forecast_horizon_hours INTEGER,
                    
                    -- Pollution forecasts
                    aqi_us SMALLINT,
                    aqi_cn SMALLINT,
                    pm25 DOUBLE PRECISION,
                    pm10 DOUBLE PRECISION,
                    o3 DOUBLE PRECISION,
                    no2 DOUBLE PRECISION,
                    so2 DOUBLE PRECISION,
                    co DOUBLE PRECISION,
                    
                    -- Weather forecasts
                    temp_c DOUBLE PRECISION,
                    temp_min_c DOUBLE PRECISION,
                    temp_max_c DOUBLE PRECISION,
                    humidity DOUBLE PRECISION,
                    pressure_hpa DOUBLE PRECISION,
                    wind_speed_ms DOUBLE PRECISION,
                    wind_dir_deg INTEGER,
                    weather_icon TEXT,
                    pop_pct SMALLINT,
                    
                    -- Metadata
                    source TEXT NOT NULL DEFAULT 'airvisual',
                    raw JSONB,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    
                    PRIMARY KEY (scope_type, scope_key, ts_utc, forecast_type)
                );
                
                CREATE INDEX IF NOT EXISTS idx_forecasts_scope_recent 
                ON forecasts (scope_key, created_at DESC) 
                WHERE ts_utc >= NOW();
                
                CREATE INDEX IF NOT EXISTS idx_forecasts_cleanup 
                ON forecasts (created_at DESC);
            """)
            
            await session.execute(create_query)
            logger.info("Forecasts table created successfully")
        
    except Exception as error:
        logger.warning(f"Could not ensure forecasts table: {error}")
        # Don't raise - let the upsert fail if needed