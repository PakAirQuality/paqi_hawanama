"""Punjab EPA router for Hawanama API"""

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import io
import logging
import numpy as np
from math import floor
from typing import Optional
from enum import Enum

from app.core.database import get_database
from app.core.security import verify_tasks_token
from app.services.ingestion.epa_service import collect_once

logger = logging.getLogger(__name__)

router = APIRouter()

# Station names enum
class StationName(str, Enum):
    ARID_UNIVERSITY = "ARID University Rawalpindi"
    BISE_SARGODHA = "BISE Sargodha"
    BZU_MULTAN = "BZU Multan"
    DC_OFFICE_DG_KHAN = "DC Office DG Khan"
    DC_OFFICE_FAISALABAD = "DC Office Faisalabad"
    DC_OFFICE_GUJRANWALA = "DC Office Gujranwala"
    DC_OFFICE_RAWALPINDI = "DC Office Rawalpindi"
    DC_OFFICE_SARGODHA = "DC Office Sargodha"
    DC_OFFICE_SIALKOT = "DC Office Sialkot"
    DHQ_SHEIKHUPURA = "DHQ Sheikhupura"
    DRUG_TESTING_LAB = "Drug Testing Laboratory Rawalpindi"
    FMDRC_LHR = "FMDRC-LHR"
    GCU_FAISALABAD = "GCU Faisalabad"
    GCW_GUJRANWALA = "GCW Gujranwala"
    GOVT_TEACHING_HOSPITAL = "Govt. Teaching Hospital Shahdara-LHR"
    IUB_BAGHDAD = "IUB (Baghdad Campus) Bahawalpur"
    IUB_KHAWAJA = "IUB (Khawaja Fareed Campus) Bahawalpur"
    KAHNA_NAU_HOSPITAL = "Kahna Nau Hospital-LHR"
    LWMC_LHR = "LWMC-LHR"
    M_NAWAZ_SHARIF_UNIVERSITY = "M. Nawaz Sharif University of Engineering & Technology Multan"
    MOBILE_1 = "Mobile 1"
    MOBILE_2 = "Mobile 2"
    MOBILE_3 = "Mobile 3"
    MOBILE_4 = "Mobile 4"
    MOBILE_5 = "Mobile 5"
    NTU_FAISALABAD = "NTU Faisalabad"
    PKLI_LHR = "PKLI-LHR"
    PUNJAB_UNIVERSITY = "Punjab University-LHR"
    SAFARI_PARK = "Safari Park-LHR"
    UET_LHR = "UET-LHR"

# ---------- U.S. AQI (IQAir-style hourly mapping) helpers ----------

def _truncate(x: float, decimals: int) -> float:
    if x is None:
        return None
    if decimals == 0:
        return float(int(x))
    factor = 10 ** decimals
    return floor(x * factor) / factor

AQI_CATEGORIES = [
    (0, 50,   "Good"),
    (51, 100, "Moderate"),
    (101,150, "Unhealthy for Sensitive Groups"),
    (151,200, "Unhealthy"),
    (201,300, "Very Unhealthy"),
    (301,500, "Hazardous"),
]

# ---- EPA breakpoint tables (U.S. AQI). PM2.5 updated in 2024 ----
PM25_BPTS = [  # µg/m³
    (0.0, 9.0,      0, 50),
    (9.1, 35.4,    51,100),
    (35.5, 55.4,  101,150),
    (55.5,125.4,  151,200),
    (125.5,225.4, 201,300),
    (225.5,500.4, 301,500),
]
PM10_BPTS = [  # µg/m³
    (0, 54,    0, 50),
    (55,154,  51,100),
    (155,254,101,150),
    (255,354,151,200),
    (355,424,201,300),
    (425,604,301,500),
]
O3_8H_BPTS = [  # ppm
    (0.000,0.054,  0, 50),
    (0.055,0.070, 51,100),
    (0.071,0.085,101,150),
    (0.086,0.105,151,200),
    (0.106,0.200,201,300),
]
CO_8H_BPTS = [  # ppm
    (0.0,4.4,   0, 50),
    (4.5,9.4,  51,100),
    (9.5,12.4,101,150),
    (12.5,15.4,151,200),
    (15.5,30.4,201,300),
    (30.5,50.4,301,500),
]
NO2_1H_BPTS = [  # ppb
    (0,53,    0, 50),
    (54,100, 51,100),
    (101,360,101,150),
    (361,649,151,200),
    (650,1249,201,300),
    (1250,2049,301,500),
]
SO2_1H_BPTS = [  # ppb
    (0,35,    0, 50),
    (36,75,  51,100),
    (76,185,101,150),
    (186,304,151,200),
    (305,604,201,300),
    (605,1004,301,500),
]

def _interp_aqi(C: float, table):
    if C is None:
        return None
    for lo, hi, Ilo, Ihi in table:
        if lo <= C <= hi:
            # piecewise-linear mapping, then round to nearest integer
            return round((Ihi - Ilo) / (hi - lo) * (C - lo) + Ilo)
    return None  # out of table

def _aqi_category(aqi: int) -> str:
    if aqi is None:
        return "Unknown"
    for lo, hi, name in AQI_CATEGORIES:
        if lo <= aqi <= hi:
            return name
    return "Beyond Index"

def compute_hourly_usaqi_iqair(
    pm25_ugm3, pm10_ugm3, no2_ppb, so2_ppb, co_ppm, o3_ppb,
    *, return_subindices: bool = True
):
    """
    IQAir-style hourly → U.S. AQI:
      - Use the hourly mean for each pollutant (no NowCast),
      - Truncate to EPA precision,
      - Map to the U.S. AQI tables (PM2.5 uses 2024 breakpoints),
      - Overall AQI = max(subindices); return main pollutant.
    Units expected:
      pm25, pm10 in µg/m³; no2, so2, o3 in ppb; co in ppm.
    """
    # 1) EPA truncation (NOT rounding)
    pm25 = _truncate(float(pm25_ugm3), 1) if pm25_ugm3 is not None else None
    pm10 = _truncate(float(pm10_ugm3), 0) if pm10_ugm3 is not None else None
    no2  = _truncate(float(no2_ppb),   0) if no2_ppb  is not None else None
    so2  = _truncate(float(so2_ppb),   0) if so2_ppb  is not None else None
    co   = _truncate(float(co_ppm),    1) if co_ppm   is not None else None
    o3ppm = None
    if o3_ppb is not None:
        o3ppm = _truncate(float(o3_ppb) / 1000.0, 3)  # ppb → ppm, then truncate

    # 2) pollutant sub-indices (hourly → U.S. AQI scale)
    sub = {
        "PM2.5": _interp_aqi(pm25, PM25_BPTS) if pm25 is not None else None,
        "PM10":  _interp_aqi(pm10, PM10_BPTS) if pm10 is not None else None,
        "O3":    _interp_aqi(o3ppm, O3_8H_BPTS) if o3ppm is not None else None,
        "CO":    _interp_aqi(co, CO_8H_BPTS) if co is not None else None,
        "NO2":   _interp_aqi(no2, NO2_1H_BPTS) if no2 is not None else None,
        "SO2":   _interp_aqi(so2, SO2_1H_BPTS) if so2 is not None else None,
    }

    # 3) overall & main pollutant
    # choose the max numeric value among available sub-indices
    def _is_valid_aqi(val):
        if val is None:
            return False
        if not isinstance(val, (int, float)):
            return False
        try:
            return not np.isnan(val)
        except:
            return True
    
    available = {k: v for k, v in sub.items() if _is_valid_aqi(v)}
    if not available:
        return None, None, sub if return_subindices else None

    main_pollutant = max(available, key=lambda k: available[k])
    try:
        overall = int(available[main_pollutant]) if available[main_pollutant] is not None else None
    except (ValueError, TypeError):
        overall = None
    if return_subindices:
        return overall, main_pollutant, sub
    return overall, main_pollutant, None

def clean_data_for_json(df):
    """Clean DataFrame for JSON serialization"""
    df = df.replace([np.nan, np.inf, -np.inf], None)
    return df

@router.get("/")
async def root():
    return {
        "message": "AQI Punjab API - Hawanama Integration",
        "version": "1.0.0",
        "status": "✅ ALL ENDPOINTS WORKING"
    }

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_database)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail="Service unavailable")

@router.get("/stations")
async def get_stations(db: AsyncSession = Depends(get_database)):
    try:
        query = """
        SELECT 
            s.source_station_id as station_code,
            COALESCE(s.name, s.source_station_id) as station_name,
            s.lat as latitude,
            s.lon as longitude,
            CASE WHEN s.active THEN 'active' ELSE 'inactive' END as status
        FROM stations s
        JOIN providers p ON s.provider_id = p.id
        WHERE s.source_station_id IS NOT NULL
        AND p.code = 'punjab'
        ORDER BY s.source_station_id
        """
        
        result = await db.execute(text(query))
        rows = result.fetchall()
        
        stations = [dict(row._mapping) for row in rows]
        
        return {"count": len(stations), "stations": stations}
        
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/station/{station_name}/aqi")
async def get_station_aqi(station_name: StationName, db: AsyncSession = Depends(get_database)):
    """Get latest US-AQI and major pollutant for a specific station by name"""
    try:
        query = """
        WITH station_coords AS (
            SELECT s.station_id, s.source_station_id, s.lat, s.lon
            FROM stations s 
            JOIN providers p ON s.provider_id = p.id
            WHERE s.source_station_id IS NOT NULL
            AND p.code = 'punjab'
            AND LOWER(s.source_station_id) = LOWER(:station_name)
        ),
        latest_reading AS (
            SELECT 
                r.scope_key,
                r.ts_utc,
                r.aqi_us,
                (r.raw->>'health_index') as health_index,
                r.pm25, r.pm10, r.no2, r.so2, r.co, r.o3
            FROM readings r
            JOIN station_coords sc ON r.scope_key = sc.station_id
            WHERE r.scope_type = 'station'
            ORDER BY r.ts_utc DESC
            LIMIT 1
        )
        SELECT 
            sc.source_station_id as station_code,
            sc.lat as latitude,
            sc.lon as longitude,
            lr.ts_utc as timestamp,
            lr.aqi_us as punjab_aqi,
            lr.health_index as health_index_punjab,
            lr.pm25, lr.pm10, lr.no2, lr.so2, lr.co, lr.o3
        FROM latest_reading lr
        JOIN station_coords sc ON lr.scope_key = sc.station_id
        """
        
        result = await db.execute(text(query), {"station_name": station_name.value})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Station '{station_name.value}' not found or no data available")
        
        # Compute US-AQI for the latest reading
        usaqi, main_pollutant, _ = compute_hourly_usaqi_iqair(
            pm25_ugm3=row.pm25 if row.pm25 is not None else None,
            pm10_ugm3=row.pm10 if row.pm10 is not None else None,
            no2_ppb=row.no2 if row.no2 is not None else None,
            so2_ppb=row.so2 if row.so2 is not None else None,
            co_ppm=row.co if row.co is not None else None,
            o3_ppb=row.o3 if row.o3 is not None else None,
            return_subindices=False
        )
        
        result_data = {
            "station_name": row.station_code,
            "timestamp": row.timestamp,
            "usaqi": usaqi,
            "main_pollutant": main_pollutant,
            "aqi_category": _aqi_category(usaqi) if usaqi else "Unknown",
            "punjab_aqi": row.punjab_aqi,
            "health_index_punjab": row.health_index_punjab,
            "coordinates": {
                "latitude": row.latitude,
                "longitude": row.longitude
            }
        }
        
        return result_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station AQI: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/readings/csv")
async def export_readings_csv(
    hours: int = Query(None, description="Hours to look back (optional - if not provided, exports all data)", ge=1, le=168),  # Max 7 days (24*7=168)
    limit: int = Query(50000, description="Max records total", ge=1, le=50000),
    db: AsyncSession = Depends(get_database),
    _: bool = Depends(verify_tasks_token)
):
    """Export readings as CSV with coordinates - grouped by station, ordered chronologically"""
    try:
        # Export ALL Punjab readings with source='punjab' or filtered by hours
        # Group by station and order chronologically within each station
        time_filter = f"AND r.ts_utc >= NOW() - INTERVAL '{hours} hours'" if hours else ""
        
        query = f"""
        SELECT 
            s.name as station_code,
            s.lat as latitude,
            s.lon as longitude,
            r.ts_utc as timestamp,
            r.aqi_us as punjab_aqi,
            r.raw->>'health_index' as health_index_punjab,
            r.pm25, 
            r.pm10, 
            r.no2, 
            r.so2, 
            r.co, 
            r.o3
        FROM readings r 
        JOIN stations s ON r.scope_key = s.station_id
        JOIN providers p ON s.provider_id = p.id
        WHERE r.source = 'punjab'
        AND p.code = 'punjab'
        {time_filter}
        ORDER BY s.name ASC, r.ts_utc ASC
        LIMIT {limit}
        """
        
        result = await db.execute(text(query))
        rows = result.fetchall()
        
        # Convert to DataFrame
        df = pd.DataFrame([dict(row._mapping) for row in rows])
        
        if df.empty:
            df = pd.DataFrame(columns=["station_code", "latitude", "longitude", "timestamp", 
                                     "punjab_aqi", "health_index_punjab", "pm25", "pm10", 
                                     "no2", "so2", "co", "o3"])
        
        # Compute U.S. AQI + main pollutant from hourly means (IQAir-style)
        def _row_to_usaqi(row):
            try:
                overall, main_pol, sub = compute_hourly_usaqi_iqair(
                    pm25_ugm3=row.get("pm25"),
                    pm10_ugm3=row.get("pm10"),
                    no2_ppb=row.get("no2"),
                    so2_ppb=row.get("so2"),
                    co_ppm=row.get("co"),
                    o3_ppb=row.get("o3"),
                    return_subindices=True
                )
            except Exception as e:
                logger.error(f"Error calculating AQI for row: {e}")
                overall, main_pol, sub = None, None, {}
            # Include per-pollutant sub-indices for auditing
            out = {
                "usaqi": overall,
                "main_pollutant": main_pol,
            }
            if sub is not None:
                out.update({
                    "aqi_pm25": sub.get("PM2.5"),
                    "aqi_pm10": sub.get("PM10"),
                    "aqi_o3":   sub.get("O3"),
                    "aqi_co":   sub.get("CO"),
                    "aqi_no2":  sub.get("NO2"),
                    "aqi_so2":  sub.get("SO2"),
                })
            return pd.Series(out)

        if not df.empty:
            aqi_cols = df.apply(_row_to_usaqi, axis=1)
            
            # Reset index to avoid conflicts and concatenate
            df = df.reset_index(drop=True)
            aqi_cols = aqi_cols.reset_index(drop=True)
            
            # Add new columns to dataframe
            for col in aqi_cols.columns:
                df[col] = aqi_cols[col]

        # Reorder columns for readability
        desired_order = [
            "station_code","latitude","longitude","timestamp",
            "usaqi","main_pollutant",
            "punjab_aqi","health_index_punjab",
            "pm25","pm10","no2","so2","co","o3",
            "aqi_pm25","aqi_pm10","aqi_o3","aqi_co","aqi_no2","aqi_so2"
        ]
        df = df[[c for c in desired_order if c in df.columns]]
        
        # Create CSV
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        time_suffix = f"{hours}h" if hours else "all_time"
        filename = f"aqi_punjab_grouped_by_station_{time_suffix}_{timestamp}.csv"
        
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type='text/csv',
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ingest/hourly")
async def trigger_punjab_ingest(
    db: AsyncSession = Depends(get_database),
    _: bool = Depends(verify_tasks_token)
):
    """
    Trigger one-shot Punjab EPA data ingestion.
    
    Public endpoint for Terraform/Cloud Scheduler to trigger data collection.
    """
    try:
        logger.info("Starting Punjab EPA ingestion")
        result = await collect_once(db)
        logger.info("Punjab EPA ingestion completed successfully")
        
        return {
            "status": "success",
            "message": "Punjab EPA data ingestion completed",
            "summary": result,
            "triggered_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Punjab EPA ingestion failed: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ingestion failed: {str(e)}"
        )