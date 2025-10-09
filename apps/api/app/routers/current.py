"""
Current Conditions API Router - provides current air quality and weather data
"""

import logging
from typing import Literal
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Query, Path, status
from fastapi.responses import JSONResponse

from app.models.current import CurrentOut
from app.services.airvisual_current import get_current_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/cities/{country}/{state}/{city}/current",
    response_model=CurrentOut,
    summary="Get current conditions for a city",
    description="Retrieve current air quality and weather conditions for a specific city"
)
async def city_current(
    country: str = Path(
        ...,
        description="Country name (URL encoded)",
        example="Pakistan"
    ),
    state: str = Path(
        ...,
        description="State or province name (URL encoded)",
        example="Punjab"
    ),
    city: str = Path(
        ...,
        description="City name (URL encoded)",
        example="Lahore"
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
    Get current air quality and weather conditions for a city.
    
    - **country**: Country name (required, URL encoded)
    - **state**: State or province name (required, URL encoded)  
    - **city**: City name (required, URL encoded)
    - **aqi**: AQI scales to include - "us" (US EPA), "cn" (China MEE), or "both" (default)
    - **tz**: IANA timezone string for local timestamp conversion (default "Asia/Karachi")
    
    Returns current conditions including:
    - Air Quality Index for requested scales
    - Weather conditions (temperature, humidity, pressure, wind)
    - Pollutant concentrations (PM2.5, PM10, O3, NO2, SO2, CO)
    - Timestamps in UTC and local time
    
    **Geographic Scope**: The response includes the geographic scope (country/state/city) 
    for context and data attribution.
    
    **Error responses:**
    - `400`: Invalid parameters  
    - `404`: City not found in data source
    - `502`: Upstream API error
    - `503`: Service unavailable
    """
    try:
        # URL decode path parameters
        country = unquote(country)
        state = unquote(state)
        city = unquote(city)
        
        # Validate non-empty parameters
        if not all([country.strip(), state.strip(), city.strip()]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Country, state, and city path parameters must be non-empty"
            )
        
        service = get_current_service()
        result = await service.get_city_current(
            country=country,
            state=state,
            city=city,
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
        
        if "city_not_found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="city_not_found"
            )
        
        # Upstream API errors
        if "upstream" in str(e).lower():
            logger.error(f"Upstream error in city_current: {e}")
            # Extract upstream details if available
            error_detail = {"detail": "upstream_error"}
            if "upstream_code" in str(e):
                # Parse upstream code if present in error message
                error_detail["upstream_code"] = "api_error"
            if "upstream_status" in str(e):
                error_detail["upstream_status"] = "error"
            
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error_detail,
                headers={"upstream_error": "true"}
            )
        
        # Other runtime errors
        logger.error(f"Runtime error in city_current: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream API error: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in city_current: {e}")
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