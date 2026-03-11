"""
Nearest API Router - provides nearest station/city with current air quality data
"""

import logging
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.schemas.nearest import NearestStationOut, NearestCityOut
from app.services.ingestion.nearest_service import get_nearest_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/nearest/city",
    response_model=NearestCityOut,
    summary="Get nearest city with current air quality",
    description="Find the nearest city to given coordinates and return current air quality data"
)
async def nearest_city(
    lat: float = Query(
        ...,
        description="Latitude coordinate (-90 to 90)",
        example=31.5204,
        ge=-90,
        le=90
    ),
    lon: float = Query(
        ..., 
        description="Longitude coordinate (-180 to 180)",
        example=74.3587,
        ge=-180,
        le=180
    ),
    radius_km: float = Query(
        50.0,
        description="Search radius in kilometers (1-300)",
        example=50.0,
        ge=1.0,
        le=300.0
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
    Find the nearest city to given coordinates with current air quality data.
    
    - **lat**: Latitude coordinate (required, -90 to 90)
    - **lon**: Longitude coordinate (required, -180 to 180)
    - **radius_km**: Maximum search radius in kilometers (default 50, range 1-300)
    - **aqi**: AQI scales to include - "us" (US EPA), "cn" (China MEE), or "both" (default)
    - **tz**: IANA timezone string for local timestamp conversion (default "Asia/Karachi")
    
    Returns the nearest city within the specified radius along with:
    - Distance from query point
    - Current air quality measurements
    - Weather conditions
    - Normalized pollutant concentrations
    
    **Error responses:**
    - `400`: Invalid coordinates or parameters
    - `404`: No city found within the specified radius  
    - `502`: Upstream API error
    - `503`: Service unavailable
    """
    try:
        service = get_nearest_service()
        result = await service.get_nearest_city(
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            aqi_filter=aqi,
            tz=tz
        )
        return result
        
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
        
        if "no_nearest_city" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no_nearest_city"
            )
        
        # Other upstream API errors
        logger.error(f"Upstream error in nearest_city: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream API error.",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in nearest_city: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/nearest/station",
    response_model=NearestStationOut,
    summary="Get nearest station with current air quality",
    description="Find the nearest monitoring station to given coordinates and return current air quality data"
)
async def nearest_station(
    lat: float = Query(
        ...,
        description="Latitude coordinate (-90 to 90)",
        example=31.5204,
        ge=-90,
        le=90
    ),
    lon: float = Query(
        ...,
        description="Longitude coordinate (-180 to 180)", 
        example=74.3587,
        ge=-180,
        le=180
    ),
    radius_km: float = Query(
        50.0,
        description="Search radius in kilometers (1-300)",
        example=30.0,
        ge=1.0,
        le=300.0
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
    Find the nearest monitoring station to given coordinates with current air quality data.
    
    - **lat**: Latitude coordinate (required, -90 to 90)
    - **lon**: Longitude coordinate (required, -180 to 180)
    - **radius_km**: Maximum search radius in kilometers (default 50, range 1-300)
    - **aqi**: AQI scales to include - "us" (US EPA), "cn" (China MEE), or "both" (default)
    - **tz**: IANA timezone string for local timestamp conversion (default "Asia/Karachi")
    
    Returns the nearest monitoring station within the specified radius along with:
    - Station details including unique station ID
    - Distance from query point
    - Current air quality measurements
    - Weather conditions
    - Normalized pollutant concentrations
    
    **Station ID**: A stable 16-character SHA1 hash based on station location and details.
    
    **Error responses:**
    - `400`: Invalid coordinates or parameters
    - `404`: No station found within the specified radius
    - `501`: Station data requires plan upgrade
    - `502`: Upstream API error
    - `503`: Service unavailable
    
    **Note**: This endpoint may require a premium AirVisual API plan. If not available,
    a 501 response is returned with upgrade information.
    """
    try:
        service = get_nearest_service()
        result = await service.get_nearest_station(
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            aqi_filter=aqi,
            tz=tz
        )
        return result
        
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
        
        if "plan upgrade" in str(e):
            return JSONResponse(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                content={"detail": "Nearest station requires plan upgrade"},
                headers={"feature_limitation": "true"}
            )
        
        if "no_nearest_station" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no_nearest_station"
            )
        
        # Other upstream API errors
        logger.error(f"Upstream error in nearest_station: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream API error.",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in nearest_station: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )