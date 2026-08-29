"""
Current Conditions API Router - provides current air quality and weather data
"""

import logging
from typing import Literal
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Query, Path, status
from fastapi.responses import JSONResponse

from app.models.current import CurrentOut, CityStationsResponse, CityTop10PM25Response, CityAverageResponse
from app.services.ingestion.airvisual_service import get_current_service
from app.utils.normalization import pm25_to_aqi, get_aqi_label, get_aqi_category

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/cities/{city}/current",
    response_model=CityStationsResponse,
    summary="Get current conditions for a city",
    description="Retrieve current air quality data for all stations in a specific city"
)
async def city_current(
    city: str = Path(
        ...,
        description="City name (validated against database)",
        example="Lahore",
    )
):
    """
    Get current air quality data for all stations in a city.
    
    - **city**: City name (required, URL encoded)
    
    Returns simplified current conditions including:
    - Station ID and name
    - PM2.5 concentration (µg/m³)
    - Air Quality Index (US EPA scale)
    
    **Error responses:**
    - `400`: Invalid parameters  
    - `404`: City not found in data source
    - `500`: Internal server error
    """
    try:
        # URL decode path parameter
        city = unquote(city)
        
        # Validate non-empty parameter
        if not city.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="City path parameter must be non-empty"
            )
        
        # Import database dependencies here to avoid circular imports
        from app.core.database import get_database
        from sqlalchemy import text
        
        # Get database session
        async for db in get_database():
            # Query stations in the city with latest readings
            query = text("""
                SELECT 
                    s.station_id,
                    s.name as station_name,
                    r.pm25,
                    r.aqi_us
                FROM stations s
                JOIN cities c ON s.city_id = c.id
                JOIN LATERAL (
                    SELECT aqi_us, pm25
                    FROM readings r_sub
                    WHERE r_sub.scope_key = s.station_id
                    AND r_sub.ts_utc >= NOW() - INTERVAL '24 hours'
                    ORDER BY r_sub.ts_utc DESC
                    LIMIT 1
                ) r ON true
                WHERE LOWER(c.name) = LOWER(:city_name)
                AND r.aqi_us IS NOT NULL
                ORDER BY s.name
            """)
            
            result = await db.execute(query, {'city_name': city})
            stations_data = result.fetchall()
            
            if not stations_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="City not found or no stations with current data"
                )
            
            # Format response
            stations = []
            for row in stations_data:
                station = {
                    "station_id": row.station_id,
                    "station_name": row.station_name,
                    "pm25_concentration": float(row.pm25) if row.pm25 is not None else None,
                    "aqi": int(row.aqi_us) if row.aqi_us is not None else None
                }
                stations.append(station)
            
            return CityStationsResponse(
                city=city,
                stations=stations
            )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in city_current: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/cities/{city}/top10-stations",
    response_model=CityTop10PM25Response,
    summary="Get top 10 highest PM2.5 stations in a city",
    description="Retrieve the 10 stations with highest PM2.5 concentrations and AQI in a specific city"
)
async def city_top10_stations(
    city: str = Path(
        ...,
        description="City name (validated against database)",
        example="Lahore",
    )
):
    """
    Get the top 10 stations with highest PM2.5 concentrations in a city.
    
    - **city**: City name (required, URL encoded)
    
    Returns the most polluted stations including:
    - Station ID and name
    - PM2.5 concentration (µg/m³) - ranked highest to lowest
    - Total number of active stations in the city
    
    **Use Cases:**
    - Identify pollution hotspots within a city
    - Environmental monitoring and alerts
    - Urban planning and policy decisions
    - Public health assessments
    
    **Error responses:**
    - `400`: Invalid parameters  
    - `404`: City not found or no stations with current data
    - `500`: Internal server error
    """
    try:
        # URL decode path parameter
        city = unquote(city)
        
        # Validate non-empty parameter
        if not city.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="City path parameter must be non-empty"
            )
        
        # Import database dependencies here to avoid circular imports
        from app.core.database import get_database
        from sqlalchemy import text
        
        # Get database session
        async for db in get_database():
            # Query to get all stations with PM2.5 and AQI data, ordered by highest concentration
            query = text("""
                SELECT 
                    s.station_id,
                    s.name as station_name,
                    r.pm25,
                    r.aqi_us
                FROM stations s
                JOIN cities c ON s.city_id = c.id
                JOIN LATERAL (
                    SELECT pm25, aqi_us
                    FROM readings r_sub
                    WHERE r_sub.scope_key = s.station_id
                    AND r_sub.ts_utc >= NOW() - INTERVAL '24 hours'
                    ORDER BY r_sub.ts_utc DESC
                    LIMIT 1
                ) r ON true
                WHERE LOWER(c.name) = LOWER(:city_name)
                AND r.pm25 IS NOT NULL
                ORDER BY r.pm25 DESC
                LIMIT 10
            """)
            
            result = await db.execute(query, {'city_name': city})
            top_stations_data = result.fetchall()
            
            # Also get total count of stations with data in this city
            count_query = text("""
                SELECT COUNT(DISTINCT s.station_id) as total_count
                FROM stations s
                JOIN cities c ON s.city_id = c.id
                JOIN LATERAL (
                    SELECT pm25, aqi_us
                    FROM readings r_sub
                    WHERE r_sub.scope_key = s.station_id
                    AND r_sub.ts_utc >= NOW() - INTERVAL '24 hours'
                    ORDER BY r_sub.ts_utc DESC
                    LIMIT 1
                ) r ON true
                WHERE LOWER(c.name) = LOWER(:city_name)
                AND r.pm25 IS NOT NULL
            """)
            
            count_result = await db.execute(count_query, {'city_name': city})
            total_count = count_result.fetchone().total_count
            
            if not top_stations_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="City not found or no stations with current PM2.5 data"
                )
            
            # Format response
            top_stations = []
            for row in top_stations_data:
                station = {
                    "station_id": row.station_id,
                    "station_name": row.station_name,
                    "pm25_concentration": float(row.pm25),
                    "aqi": int(row.aqi_us) if row.aqi_us is not None else None
                }
                top_stations.append(station)
            
            return CityTop10PM25Response(
                city=city,
                top_stations=top_stations,
                total_stations=total_count
            )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in city_top10_stations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/cities/{city}/top3-stations",
    response_model=CityTop10PM25Response,
    summary="Get top 3 highest PM2.5 stations in a city",
    description="Retrieve the 3 stations with highest PM2.5 concentrations and AQI in a specific city"
)
async def city_top3_stations(
    city: str = Path(
        ...,
        description="City name (validated against database)",
        example="Lahore",
    )
):
    """
    Get the top 3 stations with highest PM2.5 concentrations in a city.
    
    - **city**: City name (required, URL encoded)
    
    Returns the 3 most polluted stations including:
    - Station ID and name
    - PM2.5 concentration (µg/m³) - ranked highest to lowest
    - AQI value for each station
    - Total number of active stations in the city
    
    **Use Cases:**
    - Quick identification of worst pollution hotspots
    - Social media alerts and bot notifications
    - Emergency response prioritization
    - Public health warnings for specific areas
    
    **Error responses:**
    - `400`: Invalid parameters  
    - `404`: City not found or no stations with current data
    - `500`: Internal server error
    """
    try:
        # URL decode path parameter
        city = unquote(city)
        
        # Validate non-empty parameter
        if not city.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="City path parameter must be non-empty"
            )
        
        # Import database dependencies here to avoid circular imports
        from app.core.database import get_database
        from sqlalchemy import text
        
        # Get database session
        async for db in get_database():
            # Query to get top 3 stations with PM2.5 and AQI data, ordered by highest concentration
            query = text("""
                SELECT 
                    s.station_id,
                    s.name as station_name,
                    r.pm25,
                    r.aqi_us
                FROM stations s
                JOIN cities c ON s.city_id = c.id
                JOIN LATERAL (
                    SELECT pm25, aqi_us
                    FROM readings r_sub
                    WHERE r_sub.scope_key = s.station_id
                    AND r_sub.ts_utc >= NOW() - INTERVAL '24 hours'
                    ORDER BY r_sub.ts_utc DESC
                    LIMIT 1
                ) r ON true
                WHERE LOWER(c.name) = LOWER(:city_name)
                AND r.pm25 IS NOT NULL
                ORDER BY r.pm25 DESC
                LIMIT 3
            """)
            
            result = await db.execute(query, {'city_name': city})
            top_stations_data = result.fetchall()
            
            # Also get total count of stations with data in this city
            count_query = text("""
                SELECT COUNT(DISTINCT s.station_id) as total_count
                FROM stations s
                JOIN cities c ON s.city_id = c.id
                JOIN LATERAL (
                    SELECT pm25, aqi_us
                    FROM readings r_sub
                    WHERE r_sub.scope_key = s.station_id
                    AND r_sub.ts_utc >= NOW() - INTERVAL '24 hours'
                    ORDER BY r_sub.ts_utc DESC
                    LIMIT 1
                ) r ON true
                WHERE LOWER(c.name) = LOWER(:city_name)
                AND r.pm25 IS NOT NULL
            """)
            
            count_result = await db.execute(count_query, {'city_name': city})
            total_count = count_result.fetchone().total_count
            
            if not top_stations_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="City not found or no stations with current PM2.5 data"
                )
            
            # Format response
            top_stations = []
            for row in top_stations_data:
                station = {
                    "station_id": row.station_id,
                    "station_name": row.station_name,
                    "pm25_concentration": float(row.pm25),
                    "aqi": int(row.aqi_us) if row.aqi_us is not None else None
                }
                top_stations.append(station)
            
            return CityTop10PM25Response(
                city=city,
                top_stations=top_stations,
                total_stations=total_count
            )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in city_top3_stations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/stations/{station_id}/current",
    response_model=CurrentOut,
    summary="Get current conditions for a station",
    description="Retrieve current air quality and weather conditions for a specific monitoring station"
)
async def station_current(
    station_id: str = Path(
        ...,
        description="16-character station identifier (SHA1 hash)",
        example="9f1a0c2b8d6e3a41",
        regex="^[a-f0-9]{16}$"
    ),
    aqi: Literal["us", "cn", "both"] = Query(
        "both", 
        description="Which AQI scales to include in response"
    ),
    tz: str = Query(
        "Asia/Karachi",
        description="IANA timezone for local timestamp conversion",
        example="Asia/Karachi"
    )
):
    """
    Get current air quality and weather conditions for a monitoring station.
    
    - **station_id**: 16-character station identifier (required, SHA1 hash format)
    - **aqi**: AQI scales to include - "us" (US EPA), "cn" (China MEE), or "both" (default)
    - **tz**: IANA timezone string for local timestamp conversion (default "Asia/Karachi")
    
    Returns current conditions including:
    - Air Quality Index for requested scales
    - Weather conditions (temperature, humidity, pressure, wind)  
    - Pollutant concentrations (PM2.5, PM10, O3, NO2, SO2, CO)
    - Timestamps in UTC and local time
    
    **Station Resolution**: The station_id is resolved to geographic location and 
    source-specific parameters for API calls.
    
    **Geographic Scope**: The response includes the station's geographic scope 
    (country/state/city) for context and data attribution.
    
    **Error responses:**
    - `400`: Invalid station_id format
    - `404`: Station not found in registry
    - `501`: Station data requires plan upgrade  
    - `502`: Upstream API error
    - `503`: Service unavailable
    
    **Note**: This endpoint may require a premium AirVisual API plan. If not available,
    a 501 response is returned with upgrade information.
    """
    try:
        service = get_current_service()
        result = await service.get_station_current(
            station_id=station_id,
            aqi_mode=aqi,
            tz=tz
        )
        
        # Add timezone warning header if invalid timezone was provided
        response = JSONResponse(content=result.model_dump(mode='json'))
        
        # Check if timezone conversion failed (ts_local equals ts_utc in UTC)
        if (tz != "UTC" and tz != "Asia/Karachi" and 
            result.ts_local.tzinfo.zone == "UTC" and result.ts_utc == result.ts_local):
            response.headers["tz_warning"] = "invalid_tz_fallback_utc"
        
        return response
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    except RuntimeError as e:
        if "client not available" in str(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AirVisual API service unavailable - check configuration"
            )
        
        if "Station current requires plan upgrade" in str(e):
            return JSONResponse(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                content={"detail": "Station current requires plan upgrade"},
                headers={"feature_limitation": "true"}
            )
        
        if "station_not_found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="station_not_found"
            )
        
        # Upstream API errors
        if "upstream" in str(e).lower():
            logger.error(f"Upstream error in station_current: {e}")
            # Extract upstream details if available
            error_detail = {"detail": "upstream_error"}
            if "upstream_code" in str(e):
                error_detail["upstream_code"] = "api_error"
            if "upstream_status" in str(e):
                error_detail["upstream_status"] = "error"
            
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error_detail,
                headers={"upstream_error": "true"}
            )
        
        # Other runtime errors
        logger.error(f"Runtime error in station_current: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream API error: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in station_current: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/cities/{city}/average",
    response_model=CityAverageResponse,
    summary="Get average air quality for a city",
    description="Calculate average PM2.5 concentration across all stations in a city and convert to AQI"
)
async def city_average(
    city: str = Path(
        ...,
        description="City name (validated against database)",
        example="Lahore",
    )
):
    """
    Calculate average PM2.5 concentration for all stations in a city and convert to AQI.
    
    - **city**: City name (required, URL encoded)
    
    Returns city-wide average air quality including:
    - Average PM2.5 concentration across all active stations (µg/m³)
    - AQI calculated from the average PM2.5 (US EPA 2024 scale)
    - Total number of active stations used in calculation
    
    **Methodology:**
    - Averages PM2.5 concentrations from all stations with recent data (last 24 hours)
    - Converts average PM2.5 to AQI using EPA 2024 breakpoints
    - Uses proper EPA truncation and rounding procedures
    
    **Use Cases:**
    - City-wide air quality overview
    - Regional air quality comparisons
    - Public health assessments at city level
    - Environmental policy monitoring
    
    **Error responses:**
    - `400`: Invalid parameters  
    - `404`: City not found or no stations with current data
    - `500`: Internal server error
    """
    try:
        # URL decode path parameter
        city = unquote(city)
        
        # Validate non-empty parameter
        if not city.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="City path parameter must be non-empty"
            )
        
        # Import database dependencies here to avoid circular imports
        from app.core.database import get_database
        from sqlalchemy import text
        
        # Get database session
        async for db in get_database():
            # Query to get all PM2.5 readings for stations in the city
            query = text("""
                SELECT 
                    r.pm25
                FROM stations s
                JOIN cities c ON s.city_id = c.id
                JOIN LATERAL (
                    SELECT pm25
                    FROM readings r_sub
                    WHERE r_sub.scope_key = s.station_id
                    AND r_sub.ts_utc >= NOW() - INTERVAL '24 hours'
                    ORDER BY r_sub.ts_utc DESC
                    LIMIT 1
                ) r ON true
                WHERE LOWER(c.name) = LOWER(:city_name)
                AND r.pm25 IS NOT NULL
            """)
            
            result = await db.execute(query, {'city_name': city})
            pm25_readings = result.fetchall()
            
            if not pm25_readings:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="City not found or no stations with current PM2.5 data"
                )
            
            # Calculate average PM2.5
            pm25_values = [float(row.pm25) for row in pm25_readings]
            avg_pm25 = sum(pm25_values) / len(pm25_values)
            
            # Convert average PM2.5 to AQI using the corrected 2024 EPA formula
            aqi_value = pm25_to_aqi(avg_pm25)
            
            # Get health message and category based on AQI
            health_message = get_aqi_label(aqi_value)
            category = get_aqi_category(aqi_value)
            
            return CityAverageResponse(
                city=city,
                avg_pm25_concentration=round(avg_pm25, 1),
                aqi=aqi_value,
                category=category,
                health_message=health_message,
                total_stations=len(pm25_readings)
            )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in city_average: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )