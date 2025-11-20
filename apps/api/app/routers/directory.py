"""
Directory API Router - mirrors AirVisual directory listings with caching
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.schemas.directory import CountryOut, StateOut, CityOut, StationOut
from app.services.ingestion.directory_service import get_directory_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/countries",
    response_model=List[CountryOut],
    summary="List supported countries",
    description="Get list of countries supported by AirVisual API with optional search filtering"
)
async def get_countries(
    q: Optional[str] = Query(
        None, 
        description="Case-insensitive substring filter for country names",
        example="Pak"
    )
):
    """
    Get list of countries with optional search filter.
    
    - **q**: Optional case-insensitive substring filter (e.g., "Pak" matches "Pakistan")
    
    Returns list of countries in format: `[{"country": "Pakistan"}, ...]`
    """
    try:
        service = get_directory_service()
        countries = await service.get_countries(q=q)
        return countries
        
    except RuntimeError as e:
        if "client not available" in str(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AirVisual API service unavailable - check configuration"
            )
        
        # Upstream API errors
        logger.error(f"Upstream error in get_countries: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream API error: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in get_countries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/states",
    response_model=List[StateOut],
    summary="List states/provinces for a country",
    description="Get list of states or provinces for a specific country"
)
async def get_states(
    country: str = Query(
        ..., 
        description="Country name (required)",
        example="Pakistan"
    )
):
    """
    Get list of states/provinces for a country.
    
    - **country**: Country name (required, cannot be empty)
    
    Returns list of states in format: `[{"state": "Punjab"}, ...]`
    """
    try:
        service = get_directory_service()
        states = await service.get_states(country)
        return states
        
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
        
        # Upstream API errors
        logger.error(f"Upstream error in get_states: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream API error: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in get_states: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/cities",
    response_model=List[CityOut],
    summary="List cities for a state",
    description="Get list of cities for a specific country and state"
)
async def get_cities(
    country: str = Query(
        ..., 
        description="Country name (required)",
        example="Pakistan"
    ),
    state: str = Query(
        ..., 
        description="State or province name (required)",
        example="Punjab"
    )
):
    """
    Get list of cities for a country and state.
    
    - **country**: Country name (required, cannot be empty)
    - **state**: State or province name (required, cannot be empty)
    
    Returns list of cities in format: `[{"city": "Lahore"}, ...]`
    """
    try:
        service = get_directory_service()
        cities = await service.get_cities(country, state)
        return cities
        
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
        
        # Upstream API errors
        logger.error(f"Upstream error in get_cities: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream API error: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in get_cities: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/stations", 
    response_model=List[StationOut],
    summary="List monitoring stations",
    description="Get list of air quality monitoring stations with optional geographic filtering"
)
async def get_stations(
    country: Optional[str] = Query(
        None,
        description="Country name (optional but either country or bbox required)",
        example="Pakistan"
    ),
    state: Optional[str] = Query(
        None,
        description="State or province name (optional)",
        example="Punjab"
    ),
    city: Optional[str] = Query(
        None,
        description="City name (optional)",
        example="Lahore"
    ),
    bbox: Optional[str] = Query(
        None,
        description="Bounding box filter: minLon,minLat,maxLon,maxLat (optional, requires country)",
        example="74.0,31.0,75.0,32.0"
    )
):
    """
    Get list of monitoring stations with optional filtering.
    
    - **country**: Country name (optional but at least country or bbox required)
    - **state**: State or province name (optional)
    - **city**: City name (optional) 
    - **bbox**: Bounding box as "minLon,minLat,maxLon,maxLat" (optional, filters results locally)
    
    **Important**: At least one of `country` or `bbox` must be provided. If only `bbox` is provided without
    location parameters, a 400 error is returned to prevent excessive upstream API calls.
    
    Returns list of stations in format:
    ```json
    [{
        "station_id": "9f1a0c2b8d6e3a41",
        "name": "Lahore US Consulate", 
        "country": "Pakistan",
        "state": "Punjab",
        "city": "Lahore",
        "lat": 31.5204,
        "lon": 74.3587
    }]
    ```
    
    The `station_id` is a stable 16-character SHA1 hash based on location and station details.
    """
    try:
        service = get_directory_service()
        stations = await service.get_stations(
            country=country,
            state=state,
            city=city,
            bbox=bbox
        )
        return stations
        
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
        
        # Check for plan upgrade requirement
        if "plan upgrade" in str(e):
            return JSONResponse(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                content={"detail": "Stations listing requires plan upgrade"},
                headers={"feature_limitation": "true"}
            )
        
        # Other upstream API errors
        logger.error(f"Upstream error in get_stations: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream API error: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in get_stations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )