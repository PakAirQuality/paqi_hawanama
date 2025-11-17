from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Dict, Any
from app.core.database import get_database
from datetime import datetime

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_database)) -> Dict[str, Any]:
    """Get dashboard statistics for homepage overview"""
    
    # Get stations with recent data (last 24 hours)
    stats_query = text("""
        SELECT 
            COUNT(DISTINCT s.id) as total_stations,
            COUNT(DISTINCT CASE WHEN r.aqi_raw IS NOT NULL THEN s.id END) as active_stations,
            ROUND(AVG(r.aqi_raw)) as avg_aqi,
            MAX(r.ts) as latest_update,
            COUNT(CASE WHEN r.aqi_raw <= 50 THEN 1 END) as good_count,
            COUNT(CASE WHEN r.aqi_raw > 50 AND r.aqi_raw <= 100 THEN 1 END) as moderate_count,
            COUNT(CASE WHEN r.aqi_raw > 100 AND r.aqi_raw <= 150 THEN 1 END) as unhealthy_sensitive_count,
            COUNT(CASE WHEN r.aqi_raw > 150 AND r.aqi_raw <= 200 THEN 1 END) as unhealthy_count,
            COUNT(CASE WHEN r.aqi_raw > 200 AND r.aqi_raw <= 300 THEN 1 END) as very_unhealthy_count,
            COUNT(CASE WHEN r.aqi_raw > 300 THEN 1 END) as hazardous_count
        FROM stations s
        LEFT JOIN LATERAL (
            SELECT aqi_raw, ts
            FROM readings r_sub
            WHERE r_sub.station_id = s.id
            AND r_sub.ts >= NOW() - INTERVAL '24 hours'
            ORDER BY r_sub.ts DESC
            LIMIT 1
        ) r ON true
        JOIN monitor_sources ms ON s.source_id = ms.id
        WHERE ms.type = 'iqair'  -- IQAir stations only
    """)
    
    result = await db.execute(stats_query)
    stats = result.fetchone()
    
    # Get top cities with highest AQI
    top_cities_query = text("""
        SELECT s.name, r.aqi_raw
        FROM stations s
        JOIN LATERAL (
            SELECT aqi_raw
            FROM readings r_sub
            WHERE r_sub.station_id = s.id
            AND r_sub.ts >= NOW() - INTERVAL '24 hours'
            ORDER BY r_sub.ts DESC
            LIMIT 1
        ) r ON true
        WHERE r.aqi_raw IS NOT NULL
        ORDER BY r.aqi_raw DESC
        LIMIT 5
    """)
    
    cities_result = await db.execute(top_cities_query)
    top_cities = [{"name": row.name, "aqi": row.aqi_raw} for row in cities_result.fetchall()]
    
    # Calculate AQI category based on average
    avg_aqi = int(stats.avg_aqi) if stats.avg_aqi else 0
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
    if stats.latest_update:
        time_diff = datetime.utcnow() - stats.latest_update.replace(tzinfo=None)
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
        "total_stations": stats.total_stations,
        "active_stations": stats.active_stations,
        "avg_aqi": avg_aqi,
        "aqi_category": aqi_category,
        "aqi_color": aqi_color,
        "last_update": last_update_str,
        "top_cities": top_cities,
        "distribution": {
            "good": stats.good_count,
            "moderate": stats.moderate_count,
            "unhealthy_sensitive": stats.unhealthy_sensitive_count,
            "unhealthy": stats.unhealthy_count,
            "very_unhealthy": stats.very_unhealthy_count,
            "hazardous": stats.hazardous_count
        }
    }