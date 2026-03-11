"""
HISTORY API Router - provides HISTORY endpoints 
"""

import logging
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Path, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_database
from app.utils.normalization import pm25_to_aqi, get_aqi_label, get_aqi_category

logger = logging.getLogger(__name__)

router = APIRouter()



@router.get(
    "/stations/{station_id}/history",
    summary="Get historical PM2.5 data for a station", 
    description="Get hourly historical PM2.5 data for a specific monitoring station using numeric ID"
)
async def get_station_history_data(
    station_id: int = Path(..., description="Numeric station ID", example=1),
    hours: int = Query(24, description="Number of hours to include (1–168)"),
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
        
        # Clamp hours to valid range
        hours = max(1, min(hours, 168))

        # Generate complete hourly time series with local timezone
        history_result = await db.execute(text("""
            WITH RECURSIVE hour_series AS (
                SELECT
                    date_trunc('hour', NOW() - make_interval(hours => :hours)) + INTERVAL '1 hour' AS hour_utc
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
        """), {"hash_station_id": hash_station_id, "hours": hours})
        
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


@router.get(
    "/stations/{station_id}/history/pm25",
    summary="Get historical PM2.5 data for a station",
    description="Get hourly historical PM2.5 concentration data for a specific monitoring station using numeric ID"
)
async def get_station_history_pm25_data(
    station_id: int = Path(..., description="Numeric station ID", example=1),
    hours: int = Query(24, description="Number of hours to include (1–168)"),
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
        
        # Clamp hours to valid range
        hours = max(1, min(hours, 168))

        # Generate complete hourly time series with local timezone
        history_result = await db.execute(text("""
            WITH RECURSIVE hour_series AS (
                SELECT
                    date_trunc('hour', NOW() - make_interval(hours => :hours)) + INTERVAL '1 hour' AS hour_utc
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
        """), {"hash_station_id": hash_station_id, "hours": hours})
        
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


@router.get(
    "/cities/{city}/average/history",
    summary="Hourly city-average AQI & PM2.5 history",
    description="Get hourly historical city-wide average PM2.5 and AQI data"
)
async def city_average_history(
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
        ],
    ),
    hours: int = Query(24, description="Number of hours to include (1–168)"),
    db: AsyncSession = Depends(get_database),
):
    """Fetch hourly averaged PM2.5 and AQI data across all stations in a city."""
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="Hours must be between 1 and 168")

    try:
        # NOTE: We end at the last fully-completed hour (UTC), so no leading null from the current partial hour.
        history_result = await db.execute(text("""
            WITH end_hr AS (
                SELECT date_trunc('hour', NOW()) - INTERVAL '1 hour' AS end_hr_utc
            ),
            hour_series AS (
                SELECT generate_series(
                           (SELECT end_hr_utc FROM end_hr) - ((:hours - 1) * INTERVAL '1 hour'),
                           (SELECT end_hr_utc FROM end_hr),
                           INTERVAL '1 hour'
                       ) AS hour_utc
            ),
            city_stations AS (
                SELECT s.station_id::text AS scope_key
                FROM stations s
                JOIN cities c ON c.id = s.city_id
                WHERE s.active = TRUE
                  AND c.active = TRUE
                  AND LOWER(c.name) = LOWER(:city_name)
            ),
            per_station_hour AS (
                -- For each hour and station in the city, take the latest reading within [hour, hour+1h)
                SELECT
                    hs.hour_utc,
                    cs.scope_key,
                    r_latest.pm25
                FROM hour_series hs
                JOIN city_stations cs ON TRUE
                LEFT JOIN LATERAL (
                    SELECT r.pm25
                    FROM readings r
                    WHERE r.scope_type = 'station'
                      AND r.scope_key = cs.scope_key
                      AND r.ts_utc >= hs.hour_utc
                      AND r.ts_utc <  hs.hour_utc + INTERVAL '1 hour'
                    -- Optional QC gate:
                    --  AND r.qc_state = 'OK'
                    ORDER BY r.ts_utc DESC
                    LIMIT 1
                ) AS r_latest ON TRUE
            ),
            city_hourly AS (
                SELECT
                    psh.hour_utc,
                    AVG(psh.pm25) AS avg_pm25,
                    COUNT(psh.pm25) AS stations_used  -- counts only stations with a reading that hour
                FROM per_station_hour psh
                GROUP BY psh.hour_utc
            )
            SELECT
                hs.hour_utc,
                hs.hour_utc + INTERVAL '5 hours' AS hour_pk,
                ch.avg_pm25,
                COALESCE(ch.stations_used, 0) AS stations_used
            FROM hour_series hs
            LEFT JOIN city_hourly ch ON ch.hour_utc = hs.hour_utc
            ORDER BY hs.hour_utc ASC;
        """), {"city_name": city, "hours": hours})

        rows = history_result.fetchall()

        if not rows:
            city_check = await db.execute(
                text("SELECT 1 FROM cities WHERE LOWER(name) = LOWER(:city_name)"),
                {"city_name": city}
            )
            if not city_check.fetchone():
                raise HTTPException(status_code=404, detail="City not found")

        result = []
        for row in rows:
            if row.avg_pm25 is not None:
                avg_pm25 = float(row.avg_pm25)
                avg_aqi = pm25_to_aqi(avg_pm25)
                health_message = get_aqi_label(avg_aqi)
                category = get_aqi_category(avg_aqi)
            else:
                avg_pm25 = avg_aqi = health_message = category = None

            result.append({
                "timestamp_pk": row.hour_pk.strftime('%Y-%m-%dT%H:%M:%S+05:00'),
                "avg_pm25": avg_pm25,
                "avg_aqi": avg_aqi,
                "category": category,
                "health_message": health_message,
                "stations_used": int(row.stations_used) if row.stations_used is not None else 0,
            })

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting city average history for %s: %s", city, e)
        raise HTTPException(status_code=500, detail="Internal server error")


# Force rebuild 1761682600# Timestamp: 1761684140
