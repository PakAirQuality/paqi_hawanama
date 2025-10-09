from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_database
from datetime import datetime
from typing import Dict, Any
import psutil
import os

router = APIRouter()

@router.get("/")
async def health_check(db: AsyncSession = Depends(get_database)) -> Dict[str, Any]:
    """Comprehensive health check for the API"""
    health_data = {
        "status": "ok",
        "service": "hawanama-api",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "environment": os.getenv("ENVIRONMENT", "development")
    }
    
    # Database health check
    try:
        result = await db.execute(text("SELECT 1"))
        
        # Check data freshness using new schema
        freshness_query = text("""
            SELECT 
                (SELECT COUNT(*) FROM stations) as total_stations,
                COUNT(DISTINCT scope_key) as active_stations_24h,
                MAX(ts_utc) as latest_reading,
                AVG(pm25) as avg_pm25
            FROM readings 
            WHERE ts_utc >= NOW() - INTERVAL '24 hours'
                AND scope_type = 'station'
        """)
        
        freshness_result = await db.execute(freshness_query)
        stats = dict(freshness_result.fetchone()._mapping)
        
        health_data["database"] = {
            "status": "connected",
            "latest_reading": stats["latest_reading"].isoformat() + "Z" if stats["latest_reading"] else None,
            "active_stations_24h": stats["active_stations_24h"],
            "avg_pm25_24h": float(stats["avg_pm25"]) if stats["avg_pm25"] else None
        }
        
    except Exception as e:
        health_data["status"] = "degraded"
        health_data["database"] = {
            "status": "error",
            "error": str(e)
        }
    
    # System metrics
    try:
        health_data["system"] = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
    except Exception:
        # If psutil is not available, skip system metrics
        pass
    
    return health_data

@router.get("/db")
async def health_check_db(db: AsyncSession = Depends(get_database)):
    """Detailed database health check"""
    try:
        # Basic connection test
        await db.execute(text("SELECT 1"))
        
        # Database statistics using new schema
        stats_query = text("""
            SELECT 
                (SELECT COUNT(*) FROM stations) as total_stations,
                (SELECT COUNT(*) FROM readings WHERE ts_utc >= NOW() - INTERVAL '1 hour') as readings_last_hour,
                (SELECT COUNT(*) FROM readings WHERE ts_utc >= NOW() - INTERVAL '24 hours') as readings_last_24h,
                (SELECT MAX(ts_utc) FROM readings) as latest_reading,
                (SELECT pg_size_pretty(pg_database_size(current_database()))) as database_size
        """)
        
        result = await db.execute(stats_query)
        stats = dict(result.fetchone()._mapping)
        
        return {
            "status": "ok", 
            "database": "connected",
            "statistics": {
                "total_stations": stats["total_stations"],
                "readings_last_hour": stats["readings_last_hour"],
                "readings_last_24h": stats["readings_last_24h"],
                "latest_reading": stats["latest_reading"].isoformat() + "Z" if stats["latest_reading"] else None,
                "database_size": stats["database_size"]
            }
        }
    except Exception as e:
        return {"status": "error", "database": str(e)}

@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_database)) -> Dict[str, Any]:
    """Get detailed API metrics"""
    try:
        metrics_query = text("""
            SELECT 
                (SELECT COUNT(*) FROM stations) as total_stations,
                COUNT(DISTINCT CASE WHEN r.ts_utc >= NOW() - INTERVAL '1 hour' THEN r.scope_key END) as active_stations_1h,
                COUNT(DISTINCT CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN r.scope_key END) as active_stations_24h,
                COUNT(CASE WHEN r.ts_utc >= NOW() - INTERVAL '1 hour' THEN 1 END) as readings_1h,
                COUNT(CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN 1 END) as readings_24h,
                AVG(CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN r.pm25 END) as avg_pm25_24h,
                AVG(CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN r.aqi_us END) as avg_aqi_24h,
                MAX(r.ts_utc) as latest_reading
            FROM readings r
            WHERE r.scope_type = 'station'
        """)
        
        result = await db.execute(metrics_query)
        metrics = dict(result.fetchone()._mapping)
        
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "stations": {
                "total": metrics["total_stations"],
                "active_1h": metrics["active_stations_1h"],
                "active_24h": metrics["active_stations_24h"]
            },
            "readings": {
                "last_1h": metrics["readings_1h"],
                "last_24h": metrics["readings_24h"]
            },
            "air_quality": {
                "avg_pm25_24h": float(metrics["avg_pm25_24h"]) if metrics["avg_pm25_24h"] else None,
                "avg_aqi_24h": float(metrics["avg_aqi_24h"]) if metrics["avg_aqi_24h"] else None
            },
            "data_freshness": {
                "latest_reading": metrics["latest_reading"].isoformat() + "Z" if metrics["latest_reading"] else None
            }
        }
        
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.utcnow().isoformat() + "Z"}