"""
AirVisual Nearest Service - handles nearest city/station API calls with caching
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Literal
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.ingestion.cache import get_cache
from app.schemas.nearest import (
    NearestStationOut, NearestCityOut, NearestStationEntity, NearestCityEntity, 
    make_station_id
)
from app.utils.geo import haversine_km, validate_coordinates, validate_radius
from app.utils.normalization import normalize_airvisual_current_data, extract_location_info

# Import the local IQAir client
from app.services.ingestion.iqair_service import IQAirClient

logger = logging.getLogger(__name__)

# Global semaphore for rate limiting (5 concurrent requests max)
_rate_limit_semaphore = asyncio.Semaphore(5)


class AirVisualNearestService:
    """Service layer for AirVisual nearest endpoints with caching and rate limiting"""
    
    def __init__(self):
        self.cache = get_cache()
        try:
            self.iqair_client = IQAirClient()
            logger.info("IQAir client initialized successfully for nearest service")
        except ValueError as e:
            logger.error(f"Failed to initialize IQAir client: {e}")
            self.iqair_client = None
    
    def _check_client_available(self) -> None:
        """Check if IQAir client is available"""
        if not self.iqair_client:
            raise RuntimeError("IQAir API client not available - check IQAIR_API_KEY")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8)
    )
    async def _rate_limited_request(self, coro):
        """Execute request with rate limiting and retries"""
        async with _rate_limit_semaphore:
            return await coro
    
    def _make_cache_key(self, endpoint: str, lat: float, lon: float, radius_km: float) -> str:
        """Generate cache key for nearest requests"""
        # Round coordinates to 4 decimal places for cache key (~11m precision)
        lat_rounded = round(lat, 4)
        lon_rounded = round(lon, 4)
        return f"nearest:{endpoint}:{lat_rounded:.4f}:{lon_rounded:.4f}:{radius_km}"
    
    async def fetch_nearest_city(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetch nearest city data from AirVisual API
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            
        Returns:
            Raw API response data
            
        Raises:
            RuntimeError: If API client unavailable or upstream error
        """
        self._check_client_available()
        
        try:
            data = await self._rate_limited_request(
                self.iqair_client.get_nearest_city_data(lat, lon)
            )
            
            logger.info(f"Fetched nearest city data for ({lat}, {lon}) from IQAir API")
            return data
            
        except Exception as e:
            logger.error(f"Failed to fetch nearest city for ({lat}, {lon}) from IQAir API: {e}")
            if "no_nearest_city" in str(e).lower():
                raise RuntimeError("no_nearest_city")
            raise RuntimeError(f"Upstream API error: {e}")
    
    async def fetch_nearest_station(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetch nearest station data from AirVisual API
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            
        Returns:
            Raw API response data
            
        Raises:
            RuntimeError: If API client unavailable, plan limitation, or upstream error
        """
        self._check_client_available()
        
        try:
            # Try to fetch nearest station data - this might not be available on all plans
            data = await self._rate_limited_request(
                self.iqair_client.get_nearest_station_data(lat, lon)
            )
            
            logger.info(f"Fetched nearest station data for ({lat}, {lon}) from IQAir API")
            return data
            
        except Exception as e:
            logger.error(f"Failed to fetch nearest station for ({lat}, {lon}) from IQAir API: {e}")
            
            # Check for plan limitations
            if any(term in str(e).lower() for term in ["not available", "upgrade", "plan"]):
                raise RuntimeError("Nearest station requires plan upgrade")
            
            if "no_nearest_station" in str(e).lower():
                raise RuntimeError("no_nearest_station")
            
            raise RuntimeError(f"Upstream API error: {e}")
    
    async def get_nearest_city(
        self,
        lat: float, 
        lon: float,
        radius_km: float = 50.0,
        aqi_filter: Literal["us", "cn", "both"] = "both",
        tz: str = "Asia/Karachi"
    ) -> NearestCityOut:
        """
        Get nearest city with current air quality data
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate  
            radius_km: Search radius in kilometers
            aqi_filter: Which AQI scales to include
            tz: Timezone for local timestamp conversion
            
        Returns:
            NearestCityOut object
            
        Raises:
            ValueError: Invalid coordinates or radius
            RuntimeError: API errors or no city within radius
        """
        # Validate inputs
        validate_coordinates(lat, lon)
        radius_km = validate_radius(radius_km)
        
        cache_key = self._make_cache_key("city", lat, lon, radius_km)
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            # Reconstruct from cached data
            return NearestCityOut(**cached_result)
        
        # Fetch from API
        try:
            raw_data = await self.fetch_nearest_city(lat, lon)
            
            # Extract location information
            location_info = extract_location_info(raw_data)
            
            if location_info["lat"] is None or location_info["lon"] is None:
                raise RuntimeError("Invalid location data from upstream API")
            
            # Calculate distance
            distance_km = haversine_km(lat, lon, location_info["lat"], location_info["lon"])
            
            # Check if within radius
            if distance_km > radius_km:
                raise RuntimeError("no_nearest_city")
            
            # Create entity
            entity = NearestCityEntity(
                lat=location_info["lat"],
                lon=location_info["lon"], 
                country=location_info["country"],
                state=location_info["state"],
                city=location_info["city"]
            )
            
            # Normalize current data
            current = normalize_airvisual_current_data(raw_data, aqi_filter, tz)
            
            # Create response
            result = NearestCityOut(
                source="airvisual",
                distance_km=distance_km,
                entity=entity,
                current=current
            )
            
            # Cache for 10 minutes
            await self.cache.set(cache_key, result.model_dump(), 10 * 60)
            
            logger.info(f"Found nearest city {entity.city} at {distance_km}km from ({lat}, {lon})")
            
            return result
            
        except RuntimeError as e:
            if "no_nearest_city" in str(e):
                raise RuntimeError("no_nearest_city")
            raise
    
    async def get_nearest_station(
        self,
        lat: float,
        lon: float, 
        radius_km: float = 50.0,
        aqi_filter: Literal["us", "cn", "both"] = "both",
        tz: str = "Asia/Karachi"
    ) -> NearestStationOut:
        """
        Get nearest station with current air quality data
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            radius_km: Search radius in kilometers
            aqi_filter: Which AQI scales to include
            tz: Timezone for local timestamp conversion
            
        Returns:
            NearestStationOut object
            
        Raises:
            ValueError: Invalid coordinates or radius
            RuntimeError: API errors, plan limitation, or no station within radius
        """
        # Validate inputs
        validate_coordinates(lat, lon)
        radius_km = validate_radius(radius_km)
        
        cache_key = self._make_cache_key("station", lat, lon, radius_km)
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            # Reconstruct from cached data
            return NearestStationOut(**cached_result)
        
        # Fetch from API
        try:
            raw_data = await self.fetch_nearest_station(lat, lon)
            
            # Extract location information
            location_info = extract_location_info(raw_data)
            
            if location_info["lat"] is None or location_info["lon"] is None:
                raise RuntimeError("Invalid location data from upstream API")
            
            # Calculate distance
            distance_km = haversine_km(lat, lon, location_info["lat"], location_info["lon"])
            
            # Check if within radius
            if distance_km > radius_km:
                raise RuntimeError("no_nearest_station")
            
            # Generate station name and ID
            station_name = f"{location_info['city']} Station"
            if "name" in raw_data:
                station_name = raw_data["name"]
            elif location_info["city"]:
                station_name = f"{location_info['city']} Air Quality Station"
            
            station_id = make_station_id(
                location_info["country"],
                location_info["state"], 
                location_info["city"],
                station_name,
                location_info["lat"],
                location_info["lon"]
            )
            
            # Create entity
            entity = NearestStationEntity(
                lat=location_info["lat"],
                lon=location_info["lon"],
                country=location_info["country"],
                state=location_info["state"],
                city=location_info["city"],
                name=station_name,
                station_id=station_id
            )
            
            # Normalize current data
            current = normalize_airvisual_current_data(raw_data, aqi_filter, tz)
            
            # Create response
            result = NearestStationOut(
                source="airvisual",
                distance_km=distance_km,
                entity=entity,
                current=current
            )
            
            # Cache for 10 minutes
            await self.cache.set(cache_key, result.model_dump(), 10 * 60)
            
            logger.info(f"Found nearest station {entity.name} at {distance_km}km from ({lat}, {lon})")
            
            return result
            
        except RuntimeError as e:
            if "plan upgrade" in str(e):
                raise RuntimeError("Nearest station requires plan upgrade")
            if "no_nearest_station" in str(e):
                raise RuntimeError("no_nearest_station")
            raise


# Global service instance
_nearest_service: Optional[AirVisualNearestService] = None


def get_nearest_service() -> AirVisualNearestService:
    """Get or create global nearest service instance"""
    global _nearest_service
    if _nearest_service is None:
        _nearest_service = AirVisualNearestService()
    return _nearest_service