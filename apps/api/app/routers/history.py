"""
History API Router - provides historical air quality data
"""

import logging
from typing import Optional
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Query, Path, status
from fastapi.responses import JSONResponse

from app.models.history import HistoryOut
from app.services.airvisual_history import get_history_service
from app.utils.history_params import parse_history_params

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/cities/{country}/{state}/{city}/history",
    response_model=HistoryOut,
    summary="Get historical air quality data for a city",
    description="Retrieve historical air quality and weather data for a specific city"
)
async def city_history(
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
    from_: Optional[str] = Query(
        None,
        alias="from",
        description="Start time (ISO 8601 UTC, e.g., '2025-09-24T10:00:00Z')",
        example="2025-09-24T10:00:00Z"
    ),
    to: Optional[str] = Query(
        None,
        description="End time (ISO 8601 UTC, e.g., '2025-09-26T10:00:00Z')",
        example="2025-09-26T10:00:00Z"
    ),
    pollutants: Optional[str] = Query(
        None,
        description="Comma-separated pollutants (pm25,pm10,o3,no2,so2,co)",
        example="pm25,pm10"
    ),
    granularity: str = Query(
        "hour",
        description="Time granularity (only 'hour' supported)",
        example="hour"
    ),
    aqi: str = Query(
        "both",
        description="AQI scales to include",
        example="both"
    ),
    tz: str = Query(
        "Asia/Karachi",
        description="IANA timezone for local timestamps",
        example="Asia/Karachi"
    ),
    fill: bool = Query(
        False,
        description="Fill missing hours with null values"
    ),
    include_rollups: bool = Query(
        False,
        description="Include statistical rollups"
    )
):
    """
    Get historical air quality data for a city.
    
    **Parameters:**
    - **country**: Country name (required, URL encoded)
    - **state**: State or province name (required, URL encoded)
    - **city**: City name (required, URL encoded)
    - **from**: Start time in ISO 8601 UTC format (optional, defaults to 48h ago)
    - **to**: End time in ISO 8601 UTC format (optional, defaults to now)
    - **pollutants**: Comma-separated pollutants to include (optional, defaults to all)
    - **granularity**: Time granularity - only "hour" supported currently
    - **aqi**: AQI scales - "us", "cn", or "both" (default: "both")
    - **tz**: IANA timezone for local timestamps (default: "Asia/Karachi")
    - **fill**: Fill missing hours with null values (default: false)
    - **include_rollups**: Include statistical rollups (default: false)
    
    **Data Sources:**
    - Primary: Database (unlimited historical range)
    - Fallback: AirVisual API (~48h history) for recent data gaps
    
    **Response:**
    - **scope**: Geographic scope (country/state/city)
    - **rows**: Array of hourly data points with AQI, pollutants, weather
    - **rollups**: Statistical summaries (if requested)
    - **units**: Standard units for measurements
    
    **Time Range Limits:**
    - Maximum span: 180 days per request
    - If no from/to specified: defaults to last 48 hours
    
    **Error responses:**
    - `400`: Invalid parameters or time range
    - `404`: City not found
    - `502`: Upstream API error
    - `503`: Service unavailable
    """
    try:
        # URL decode path parameters
        country = unquote(country)
        state = unquote(state)
        city = unquote(city)
        
        # Parse and validate parameters
        query = parse_history_params(
            from_str=from_,
            to_str=to,
            pollutants_str=pollutants,
            granularity=granularity,
            aqi=aqi,
            tz=tz,
            fill=fill,
            include_rollups=include_rollups
        )
        
        # Get history data
        service = get_history_service()
        result = await service.get_city_history(country, state, city, query)
        
        # Create JSON response with proper datetime serialization
        response_data = result.model_dump(mode='json')
        response = JSONResponse(content=response_data)
        
        # Add timezone warning header if needed
        if service.check_timezone_fallback(result, tz):
            response.headers["X-TZ-Warning"] = "invalid_tz_fallback_utc"
        
        return response
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    except RuntimeError as e:
        if "city_not_found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="city_not_found"
            )
        
        # Other runtime errors (likely upstream issues)
        logger.error(f"Runtime error in city_history: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve city history: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in city_history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get(
    "/stations/{station_id}/history",
    response_model=HistoryOut,
    summary="Get historical air quality data for a station",
    description="Retrieve historical air quality and weather data for a specific monitoring station"
)
async def station_history(
    station_id: str = Path(
        ...,
        description="16-character station identifier (SHA1 hash)",
        example="9f1a0c2b8d6e3a41",
        regex="^[a-f0-9]{16}$"
    ),
    from_: Optional[str] = Query(
        None,
        alias="from",
        description="Start time (ISO 8601 UTC, e.g., '2025-09-24T10:00:00Z')",
        example="2025-09-24T10:00:00Z"
    ),
    to: Optional[str] = Query(
        None,
        description="End time (ISO 8601 UTC, e.g., '2025-09-26T10:00:00Z')",
        example="2025-09-26T10:00:00Z"
    ),
    pollutants: Optional[str] = Query(
        None,
        description="Comma-separated pollutants (pm25,pm10,o3,no2,so2,co)",
        example="pm25,pm10"
    ),
    granularity: str = Query(
        "hour",
        description="Time granularity (only 'hour' supported)",
        example="hour"
    ),
    aqi: str = Query(
        "both",
        description="AQI scales to include",
        example="both"
    ),
    tz: str = Query(
        "Asia/Karachi",
        description="IANA timezone for local timestamps",
        example="Asia/Karachi"
    ),
    fill: bool = Query(
        False,
        description="Fill missing hours with null values"
    ),
    include_rollups: bool = Query(
        False,
        description="Include statistical rollups"
    )
):
    """
    Get historical air quality data for a monitoring station.
    
    **Parameters:**
    - **station_id**: 16-character station identifier (required, SHA1 hash format)
    - **from**: Start time in ISO 8601 UTC format (optional, defaults to 48h ago)
    - **to**: End time in ISO 8601 UTC format (optional, defaults to now)
    - **pollutants**: Comma-separated pollutants to include (optional, defaults to all)
    - **granularity**: Time granularity - only "hour" supported currently
    - **aqi**: AQI scales - "us", "cn", or "both" (default: "both")
    - **tz**: IANA timezone for local timestamps (default: "Asia/Karachi")
    - **fill**: Fill missing hours with null values (default: false)
    - **include_rollups**: Include statistical rollups (default: false)
    
    **Station Resolution:**
    The station_id is resolved to geographic location and metadata for data retrieval.
    
    **Data Sources:**
    - Primary: Database (unlimited historical range)
    - Fallback: AirVisual API (~48h history) for recent data gaps (plan permitting)
    
    **Response:**
    - **scope**: Station's geographic scope (country/state/city)
    - **rows**: Array of hourly data points with AQI, pollutants, weather
    - **rollups**: Statistical summaries (if requested)
    - **units**: Standard units for measurements
    
    **Time Range Limits:**
    - Maximum span: 180 days per request
    - If no from/to specified: defaults to last 48 hours
    
    **Plan Limitations:**
    If the API plan doesn't support station history and there's no database coverage,
    an empty result is returned with `X-Upstream-Note: station_history_unavailable_on_plan` header.
    
    **Error responses:**
    - `400`: Invalid station_id format or parameters
    - `404`: Station not found in registry
    - `502`: Upstream API error
    - `503`: Service unavailable
    
    **Note:** Unlike current endpoints, history endpoints don't return 501 for plan limitations.
    Instead, they return available data (database-only) with informational headers.
    """
    try:
        # Parse and validate parameters
        query = parse_history_params(
            from_str=from_,
            to_str=to,
            pollutants_str=pollutants,
            granularity=granularity,
            aqi=aqi,
            tz=tz,
            fill=fill,
            include_rollups=include_rollups
        )
        
        # Get history data
        service = get_history_service()
        result = await service.get_station_history(station_id, query)
        
        # Create JSON response with proper datetime serialization
        response_data = result.model_dump(mode='json')
        response = JSONResponse(content=response_data)
        
        # Add timezone warning header if needed
        if service.check_timezone_fallback(result, tz):
            response.headers["X-TZ-Warning"] = "invalid_tz_fallback_utc"
        
        # Add upstream limitation note if present
        if hasattr(result, 'upstream_note') and result.upstream_note:
            response.headers["X-Upstream-Note"] = result.upstream_note
        
        return response
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    except RuntimeError as e:
        if "station_not_found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="station_not_found"
            )
        
        # Other runtime errors (likely upstream issues)
        logger.error(f"Runtime error in station_history: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve station history: {str(e)}",
            headers={"upstream_error": "true"}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in station_history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )