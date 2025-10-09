"""
Readings data repository
Handles bulk operations for readings data in TimescaleDB
"""

import logging
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def upsert_readings_bulk(session: AsyncSession, rows: List[Dict[str, Any]]) -> int:
    """
    Bulk upsert readings data with conflict resolution
    
    Args:
        session: Database session
        rows: List of reading row dictionaries
    
    Returns:
        Number of rows processed
    """
    if not rows:
        return 0
    
    try:
        query = text("""
            INSERT INTO readings (
                scope_type, scope_key, ts_utc,
                aqi_us, aqi_cn, main_us, main_cn,
                pm25, pm10, o3, no2, so2, co,
                units_pm25, units_pm10, units_o3, units_no2, units_so2, units_co,
                temp_c, humidity, pressure_hpa, wind_speed_ms, wind_dir_deg,
                weather_icon, heatindex_c, dewpoint_c, visibility_km, uv_index, pop_pct,
                qc_state, qc_flags, source, raw
            )
            VALUES (
                :scope_type, :scope_key, :ts_utc,
                :aqi_us, :aqi_cn, :main_us, :main_cn,
                :pm25, :pm10, :o3, :no2, :so2, :co,
                :units_pm25, :units_pm10, :units_o3, :units_no2, :units_so2, :units_co,
                :temp_c, :humidity, :pressure_hpa, :wind_speed_ms, :wind_dir_deg,
                :weather_icon, :heatindex_c, :dewpoint_c, :visibility_km, :uv_index, :pop_pct,
                :qc_state, :qc_flags, :source, :raw
            )
            ON CONFLICT (scope_type, scope_key, ts_utc) 
            DO UPDATE SET 
                -- Only update if source data is newer (DB wins on conflicts for backfill)
                aqi_us = CASE WHEN readings.source = 'airvisual' THEN readings.aqi_us ELSE EXCLUDED.aqi_us END,
                aqi_cn = CASE WHEN readings.source = 'airvisual' THEN readings.aqi_cn ELSE EXCLUDED.aqi_cn END,
                main_us = CASE WHEN readings.source = 'airvisual' THEN readings.main_us ELSE EXCLUDED.main_us END,
                main_cn = CASE WHEN readings.source = 'airvisual' THEN readings.main_cn ELSE EXCLUDED.main_cn END,
                pm25 = CASE WHEN readings.source = 'airvisual' THEN readings.pm25 ELSE EXCLUDED.pm25 END,
                pm10 = CASE WHEN readings.source = 'airvisual' THEN readings.pm10 ELSE EXCLUDED.pm10 END,
                o3 = CASE WHEN readings.source = 'airvisual' THEN readings.o3 ELSE EXCLUDED.o3 END,
                no2 = CASE WHEN readings.source = 'airvisual' THEN readings.no2 ELSE EXCLUDED.no2 END,
                so2 = CASE WHEN readings.source = 'airvisual' THEN readings.so2 ELSE EXCLUDED.so2 END,
                co = CASE WHEN readings.source = 'airvisual' THEN readings.co ELSE EXCLUDED.co END,
                units_pm25 = CASE WHEN readings.source = 'airvisual' THEN readings.units_pm25 ELSE EXCLUDED.units_pm25 END,
                units_pm10 = CASE WHEN readings.source = 'airvisual' THEN readings.units_pm10 ELSE EXCLUDED.units_pm10 END,
                units_o3 = CASE WHEN readings.source = 'airvisual' THEN readings.units_o3 ELSE EXCLUDED.units_o3 END,
                units_no2 = CASE WHEN readings.source = 'airvisual' THEN readings.units_no2 ELSE EXCLUDED.units_no2 END,
                units_so2 = CASE WHEN readings.source = 'airvisual' THEN readings.units_so2 ELSE EXCLUDED.units_so2 END,
                units_co = CASE WHEN readings.source = 'airvisual' THEN readings.units_co ELSE EXCLUDED.units_co END,
                temp_c = CASE WHEN readings.source = 'airvisual' THEN readings.temp_c ELSE EXCLUDED.temp_c END,
                humidity = CASE WHEN readings.source = 'airvisual' THEN readings.humidity ELSE EXCLUDED.humidity END,
                pressure_hpa = CASE WHEN readings.source = 'airvisual' THEN readings.pressure_hpa ELSE EXCLUDED.pressure_hpa END,
                wind_speed_ms = CASE WHEN readings.source = 'airvisual' THEN readings.wind_speed_ms ELSE EXCLUDED.wind_speed_ms END,
                wind_dir_deg = CASE WHEN readings.source = 'airvisual' THEN readings.wind_dir_deg ELSE EXCLUDED.wind_dir_deg END,
                weather_icon = CASE WHEN readings.source = 'airvisual' THEN readings.weather_icon ELSE EXCLUDED.weather_icon END,
                heatindex_c = CASE WHEN readings.source = 'airvisual' THEN readings.heatindex_c ELSE EXCLUDED.heatindex_c END,
                dewpoint_c = CASE WHEN readings.source = 'airvisual' THEN readings.dewpoint_c ELSE EXCLUDED.dewpoint_c END,
                visibility_km = CASE WHEN readings.source = 'airvisual' THEN readings.visibility_km ELSE EXCLUDED.visibility_km END,
                uv_index = CASE WHEN readings.source = 'airvisual' THEN readings.uv_index ELSE EXCLUDED.uv_index END,
                pop_pct = CASE WHEN readings.source = 'airvisual' THEN readings.pop_pct ELSE EXCLUDED.pop_pct END,
                qc_state = EXCLUDED.qc_state,
                qc_flags = EXCLUDED.qc_flags,
                raw = EXCLUDED.raw
        """)
        
        # Ensure all rows have required keys with defaults
        processed_rows = []
        for row in rows:
            processed_row = {
                # Required fields
                "scope_type": row.get("scope_type"),
                "scope_key": row.get("scope_key"),
                "ts_utc": row.get("ts_utc"),
                # AQI fields
                "aqi_us": row.get("aqi_us"),
                "aqi_cn": row.get("aqi_cn"),
                "main_us": row.get("main_us"),
                "main_cn": row.get("main_cn"),
                # Pollutant concentrations
                "pm25": row.get("pm25"),
                "pm10": row.get("pm10"),
                "o3": row.get("o3"),
                "no2": row.get("no2"),
                "so2": row.get("so2"),
                "co": row.get("co"),
                # Units
                "units_pm25": row.get("units_pm25"),
                "units_pm10": row.get("units_pm10"),
                "units_o3": row.get("units_o3"),
                "units_no2": row.get("units_no2"),
                "units_so2": row.get("units_so2"),
                "units_co": row.get("units_co"),
                # Weather fields
                "temp_c": row.get("temp_c"),
                "humidity": row.get("humidity"),
                "pressure_hpa": row.get("pressure_hpa"),
                "wind_speed_ms": row.get("wind_speed_ms"),
                "wind_dir_deg": row.get("wind_dir_deg"),
                "weather_icon": row.get("weather_icon"),
                "heatindex_c": row.get("heatindex_c"),
                "dewpoint_c": row.get("dewpoint_c"),
                "visibility_km": row.get("visibility_km"),
                "uv_index": row.get("uv_index"),
                "pop_pct": row.get("pop_pct"),
                # QC and metadata
                "qc_state": row.get("qc_state", "OK"),
                "qc_flags": row.get("qc_flags"),
                "source": row.get("source", "airvisual"),
                "raw": row.get("raw")
            }
            processed_rows.append(processed_row)
        
        await session.execute(query, processed_rows)
        
        logger.debug(f"Bulk upserted {len(processed_rows)} reading rows")
        return len(processed_rows)
        
    except Exception as error:
        logger.error(f"Bulk upsert readings failed: {error}")
        raise error


async def get_latest_readings_by_scope(session: AsyncSession, scope_keys: List[str], limit: int = 24) -> List[Dict[str, Any]]:
    """
    Get latest readings for multiple scopes
    
    Args:
        session: Database session
        scope_keys: List of scope keys to fetch
        limit: Number of latest readings per scope
    
    Returns:
        List of reading rows
    """
    if not scope_keys:
        return []
    
    try:
        # Create parameterized IN clause
        placeholders = ','.join([f':scope_{i}' for i in range(len(scope_keys))])
        params = {f'scope_{i}': scope_key for i, scope_key in enumerate(scope_keys)}
        params['limit'] = limit
        
        query = text(f"""
            WITH latest_per_scope AS (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY scope_key ORDER BY ts_utc DESC) as rn
                FROM readings
                WHERE scope_key IN ({placeholders})
                  AND qc_state = 'OK'
            )
            SELECT scope_type, scope_key, ts_utc, aqi_us, aqi_cn, pm25, pm10, temp_c, source
            FROM latest_per_scope
            WHERE rn <= :limit
            ORDER BY scope_key, ts_utc DESC
        """)
        
        result = await session.execute(query, params)
        readings = [dict(row._mapping) for row in result.fetchall()]
        
        logger.debug(f"Retrieved {len(readings)} latest readings for {len(scope_keys)} scopes")
        return readings
        
    except Exception as error:
        logger.error(f"Failed to get latest readings by scope: {error}")
        return []


async def get_reading_gaps(session: AsyncSession, scope_key: str, hours_back: int = 48) -> List[Dict[str, Any]]:
    """
    Identify gaps in hourly readings for a scope
    
    Args:
        session: Database session  
        scope_key: Scope to check for gaps
        hours_back: Hours to look back for gaps
    
    Returns:
        List of gap periods (start_hour, end_hour)
    """
    try:
        query = text("""
            WITH hour_series AS (
                SELECT generate_series(
                    date_trunc('hour', NOW() - INTERVAL ':hours_back hours'),
                    date_trunc('hour', NOW()),
                    INTERVAL '1 hour'
                ) AS hour_ts
            ),
            existing_readings AS (
                SELECT date_trunc('hour', ts_utc) as hour_ts
                FROM readings
                WHERE scope_key = :scope_key
                  AND ts_utc >= NOW() - INTERVAL ':hours_back hours'
                GROUP BY date_trunc('hour', ts_utc)
            ),
            gaps AS (
                SELECT h.hour_ts
                FROM hour_series h
                LEFT JOIN existing_readings e ON h.hour_ts = e.hour_ts
                WHERE e.hour_ts IS NULL
            )
            SELECT hour_ts as gap_hour
            FROM gaps
            ORDER BY hour_ts
        """)
        
        result = await session.execute(query, {
            "scope_key": scope_key,
            "hours_back": hours_back
        })
        
        gaps = [dict(row._mapping) for row in result.fetchall()]
        logger.debug(f"Found {len(gaps)} hour gaps for {scope_key}")
        return gaps
        
    except Exception as error:
        logger.error(f"Failed to find reading gaps for {scope_key}: {error}")
        return []