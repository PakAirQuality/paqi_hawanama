"""
History API Router - provides historical air quality data
"""

import logging
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
async def station_history(
    station_id: int = Path(..., description="Numeric station ID", example=1),
    hours: int = Query(24, description="Number of hours to include (1–168)"),
    db: AsyncSession = Depends(get_database),
):
    # Validate hours parameter
    if hours < 1 or hours > 168:  # Max 1 week
        raise HTTPException(status_code=400, detail="Hours must be between 1 and 168")
    
    try:
        # Get station by numeric index using same pattern as dashboard endpoints
        station_lookup = await db.execute(text("""
            SELECT station_id, name 
            FROM stations 
            WHERE active = true 
            ORDER BY name
        """))
        
        stations_list = station_lookup.fetchall()
        
        # Find the station at the given index (station_id - 1, since IDs are 1-based)
        if station_id < 1 or station_id > len(stations_list):
            raise HTTPException(status_code=404, detail="Station not found")
        
        target_station = stations_list[station_id - 1]  # Convert to 0-based index
        hash_station_id = target_station.station_id
        
        # Get historical PM2.5 readings using the same pattern as dashboard endpoints
        history_result = await db.execute(text("""
            WITH hour_series AS (
                SELECT generate_series(
                    date_trunc('hour', NOW() - INTERVAL '%s hours'),
                    date_trunc('hour', NOW()),
                    INTERVAL '1 hour'
                ) AS hour_utc
            )
            SELECT 
                hs.hour_utc + INTERVAL '5 hours' AS hour_pk,
                r.pm25,
                r.aqi_us,
                :station_name AS station_name,
                :station_id AS station_id
            FROM hour_series hs
            LEFT JOIN readings r ON (
                date_trunc('hour', r.ts_utc) = hs.hour_utc
                AND r.scope_key = :hash_station_id 
                AND r.scope_type = 'station'
            )
            ORDER BY hs.hour_utc ASC
        """ % hours), {"hash_station_id": hash_station_id, "station_name": target_station.name, "station_id": station_id})
        
        history_rows = history_result.fetchall()
        
        return [
            {
                "timestamp_pk": row.hour_pk.strftime('%Y-%m-%dT%H:%M:%S+05:00'),
                "pm25": float(row.pm25) if row.pm25 is not None else None,
                "aqi": float(row.aqi_us) if row.aqi_us is not None else None,
                "station_name": row.station_name,
                "station_id": row.station_id
            }
            for row in history_rows
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station PM2.5 history for station {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


############## CITY AVERAGES API ############## 


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
            "Abbottabad","Bahawalpur","Bhopalwala","Chak Jhumra","Daska Kalan",
            "Dera Ismail Khan","Eminabad","Faisalabad","Gujranwala","Haripur",
            "Hundal","Hyderabad","Islamabad","Jhang","Jhelum","Kahna Nau",
            "Karachi","Kasur","Khairpur Mir's","Kharan","Khurrianwala",
            "Kot Malik Barkhurdar","Kotli Loharan","Kotri","Ladhewala Waraich",
            "Lahore","Lodhran","Malam Jabba","Malir Cantonment","Mandi Bahauddin",
            "Mirpur Khas","Multan","Murree","Pasrur","Pattoki","Peshawar",
            "Pindi Bhattian","Qadirpur Ran","Quetta","Rahim Yar Khan","Raiwind",
            "Rawalpindi","Rojhan","Sambrial","Sheikhupura","Sialkot","Skardu","Sukkur"
        ]
    ),
    hours: int = Query(24, description="Number of hours to include (1–168)"),
    db: AsyncSession = Depends(get_database),
):
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="Hours must be between 1 and 168")

    try:
        # 1) Build the hour series
        # 2) For each station & hour, pick ONE value (latest within that hour)
        # 3) Average those per-hour station values across stations (equal weight)
        history_result = await db.execute(text("""
            WITH bounds AS (
                SELECT
                    date_trunc('hour', NOW())                                AS cur_hr_utc,
                    -- We want exactly `:hours` bins ending at cur_hr_utc
                    date_trunc('hour', NOW()) - make_interval(hours => :hours - 1) AS min_hr_utc
            ),
            hour_series AS (
                -- Exact hour buckets we will return (UTC)
                SELECT generate_series(
                    (SELECT min_hr_utc FROM bounds),
                    (SELECT cur_hr_utc FROM bounds),
                    INTERVAL '1 hour'
                ) AS hour_utc
            ),
            city_stations AS (
                -- Use the same key format as readings.scope_key; cast to text to be robust
                SELECT s.station_id::text AS scope_key
                FROM stations s
                JOIN cities c ON s.city_id = c.id
                WHERE s.active = TRUE
                AND LOWER(c.name) = LOWER(:city_name)
            ),
            station_hourly AS (
                -- For each (hour_bin, station), latest reading within [hour_bin, hour_bin+1h)
                SELECT
                    hs.hour_utc,
                    r.scope_key::text AS scope_key,
                    r.pm25,
                    row_number() OVER (
                        PARTITION BY hs.hour_utc, r.scope_key
                        ORDER BY r.ts_utc DESC
                    ) AS rn
                FROM hour_series hs
                JOIN city_stations cs ON TRUE
                JOIN readings r
                ON r.scope_type = 'station'
                AND r.scope_key::text = cs.scope_key
                AND r.ts_utc >= hs.hour_utc
                AND r.ts_utc <  hs.hour_utc + INTERVAL '1 hour'
            ),
            city_hourly AS (
                SELECT
                    sh.hour_utc,
                    AVG(sh.pm25)              AS avg_pm25,
                    COUNT(*) FILTER (WHERE sh.rn = 1) AS stations_used
                FROM station_hourly sh
                WHERE sh.rn = 1
                GROUP BY sh.hour_utc
            )
            SELECT
                hs.hour_utc,
                hs.hour_utc + INTERVAL '5 hours' AS hour_pk,  -- PKT display
                ch.avg_pm25,
                ch.stations_used
            FROM hour_series hs
            LEFT JOIN city_hourly ch USING (hour_utc)
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
                avg_pm25 = None
                avg_aqi = None
                health_message = None
                category = None
            
            result.append({
                "timestamp_pk": row.hour_pk.strftime('%Y-%m-%dT%H:%M:%S+05:00'),
                "avg_pm25": avg_pm25,
                "avg_aqi": avg_aqi,
                "category": category,
                "health_message": health_message,
                "stations_used": int(row.stations_used) if row.stations_used is not None else 0
            })
        
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting city average history for %s: %s", city, e)
        raise HTTPException(status_code=500, detail="Internal server error")

