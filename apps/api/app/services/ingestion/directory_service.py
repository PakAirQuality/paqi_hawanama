"""
AirVisual Directory Service - wraps IQAir client for directory endpoints
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.ingestion.cache import get_cache
from app.schemas.directory import CountryOut, StateOut, CityOut, StationOut, make_station_id

# Import the local IQAir client
from app.services.ingestion.iqair_service import IQAirClient

logger = logging.getLogger(__name__)

# Global semaphore for rate limiting (5 concurrent requests max)
_rate_limit_semaphore = asyncio.Semaphore(5)


class AirVisualDirectoryService:
    """Service layer for AirVisual directory endpoints with caching and rate limiting"""
    
    def __init__(self):
        self.cache = get_cache()
        try:
            self.iqair_client = IQAirClient()
            logger.info("IQAir client initialized successfully")
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
    
    async def get_countries(self, q: Optional[str] = None) -> List[CountryOut]:
        """
        Get list of countries with optional search filter
        
        Args:
            q: Optional case-insensitive substring filter
            
        Returns:
            List of CountryOut objects
        """
        self._check_client_available()
        
        cache_key = "dir:countries"
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            countries = [CountryOut(**item) for item in cached_result]
        else:
            # Fetch from API
            try:
                raw_countries = await self._rate_limited_request(
                    self.iqair_client.get_countries()
                )
                
                # Map to our format
                countries = [
                    CountryOut(country=item["country"])
                    for item in raw_countries
                ]
                
                # Cache for 24 hours
                cache_data = [country.model_dump() for country in countries]
                await self.cache.set(cache_key, cache_data, 24 * 3600)
                
                logger.info(f"Fetched {len(countries)} countries from IQAir API")
                
            except Exception as e:
                logger.error(f"Failed to fetch countries from IQAir API: {e}")
                raise RuntimeError(f"Upstream API error: {e}")
        
        # Apply search filter if provided
        if q:
            q_lower = q.lower()
            countries = [
                country for country in countries
                if q_lower in country.country.lower()
            ]
        
        return countries
    
    async def get_states(self, country: str) -> List[StateOut]:
        """
        Get list of states/provinces for a country
        
        Args:
            country: Country name (required)
            
        Returns:
            List of StateOut objects
        """
        self._check_client_available()
        
        if not country or not country.strip():
            raise ValueError("Country parameter is required and cannot be empty")
        
        cache_key = f"dir:states:{country}"
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            return [StateOut(**item) for item in cached_result]
        
        # Fetch from API
        try:
            raw_states = await self._rate_limited_request(
                self.iqair_client.get_states(country)
            )
            
            # Map to our format
            states = [
                StateOut(state=item["state"])
                for item in raw_states
            ]
            
            # Cache for 24 hours
            cache_data = [state.model_dump() for state in states]
            await self.cache.set(cache_key, cache_data, 24 * 3600)
            
            logger.info(f"Fetched {len(states)} states for {country} from IQAir API")
            
            return states
            
        except Exception as e:
            logger.error(f"Failed to fetch states for {country} from IQAir API: {e}")
            raise RuntimeError(f"Upstream API error: {e}")
    
    async def get_cities(self, country: str, state: str) -> List[CityOut]:
        """
        Get list of cities for a country and state
        
        Args:
            country: Country name (required)
            state: State/province name (required)
            
        Returns:
            List of CityOut objects
        """
        self._check_client_available()
        
        if not country or not country.strip():
            raise ValueError("Country parameter is required and cannot be empty")
        if not state or not state.strip():
            raise ValueError("State parameter is required and cannot be empty")
        
        cache_key = f"dir:cities:{country}:{state}"
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            return [CityOut(**item) for item in cached_result]
        
        # Fetch from API
        try:
            raw_cities = await self._rate_limited_request(
                self.iqair_client.get_cities(country, state)
            )
            
            # Map to our format
            cities = [
                CityOut(city=item["city"])
                for item in raw_cities
            ]
            
            # Cache for 24 hours
            cache_data = [city.model_dump() for city in cities]
            await self.cache.set(cache_key, cache_data, 24 * 3600)
            
            logger.info(f"Fetched {len(cities)} cities for {state}, {country} from IQAir API")
            
            return cities
            
        except Exception as e:
            logger.error(f"Failed to fetch cities for {state}, {country} from IQAir API: {e}")
            raise RuntimeError(f"Upstream API error: {e}")
    
    async def get_stations(
        self, 
        country: Optional[str] = None,
        state: Optional[str] = None, 
        city: Optional[str] = None,
        bbox: Optional[str] = None
    ) -> List[StationOut]:
        """
        Get list of stations with optional filtering
        
        Args:
            country: Country name (optional but at least country or bbox required)
            state: State/province name (optional)
            city: City name (optional)
            bbox: Bounding box as "minLon,minLat,maxLon,maxLat" (optional)
            
        Returns:
            List of StationOut objects
            
        Raises:
            ValueError: If neither country nor bbox is provided, or if only bbox is provided
            RuntimeError: If stations endpoint not available in API plan
        """
        self._check_client_available()
        
        # Validate parameters
        if not country and not bbox:
            raise ValueError("At least one of 'country' or 'bbox' must be provided")
        
        if bbox and not country:
            raise ValueError(
                "Provide country (and optionally state/city) to scope the stations, then bbox filters locally."
            )
        
        # Parse and validate bbox if provided
        bbox_coords = None
        if bbox:
            try:
                coords = [float(x.strip()) for x in bbox.split(',')]
                if len(coords) != 4:
                    raise ValueError("bbox must have exactly 4 values: minLon,minLat,maxLon,maxLat")
                
                min_lon, min_lat, max_lon, max_lat = coords
                
                # Validate coordinate ranges
                if not (-180 <= min_lon <= 180) or not (-180 <= max_lon <= 180):
                    raise ValueError("Longitude must be between -180 and 180")
                if not (-90 <= min_lat <= 90) or not (-90 <= max_lat <= 90):
                    raise ValueError("Latitude must be between -90 and 90")
                if min_lon >= max_lon or min_lat >= max_lat:
                    raise ValueError("bbox coordinates: min values must be less than max values")
                
                bbox_coords = (min_lon, min_lat, max_lon, max_lat)
                
            except ValueError as e:
                if "could not convert" in str(e) or "invalid literal" in str(e):
                    raise ValueError("bbox must contain valid numbers: minLon,minLat,maxLon,maxLat")
                raise
        
        # Build cache key
        cache_parts = [country or "__none__", state or "__none__", city or "__none__"]
        cache_key = f"dir:stations:{':'.join(cache_parts)}"
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            stations = [StationOut(**item) for item in cached_result]
        else:
            # Check if we have required parameters for API call
            if not (country and state and city):
                # For now, return empty list if we don't have full location info
                # In future, we could aggregate stations from multiple cities
                logger.info(f"Insufficient location parameters for stations API: country={country}, state={state}, city={city}")
                stations = []
            else:
                # Fetch from API
                try:
                    raw_stations = await self._rate_limited_request(
                        self.iqair_client.get_stations(city, state, country)
                    )
                    
                    # Map to our format
                    stations = []
                    for item in raw_stations:
                        # Extract coordinates - IQAir format may vary
                        lat = item.get("location", {}).get("coordinates", [None, None])[1]
                        lon = item.get("location", {}).get("coordinates", [None, None])[0]
                        
                        if lat is None or lon is None:
                            logger.warning(f"Station {item.get('name', 'unknown')} missing coordinates")
                            continue
                        
                        station_name = item.get("name", f"Station in {city}")
                        
                        station = StationOut(
                            station_id=make_station_id(country, state, city, station_name, lat, lon),
                            name=station_name,
                            country=country,
                            state=state,
                            city=city,
                            lat=lat,
                            lon=lon
                        )
                        stations.append(station)
                    
                    # Cache for 6 hours
                    cache_data = [station.model_dump() for station in stations]
                    await self.cache.set(cache_key, cache_data, 6 * 3600)
                    
                    logger.info(f"Fetched {len(stations)} stations for {city}, {state}, {country} from IQAir API")
                    
                except Exception as e:
                    # Check if this is a plan limitation
                    if "not available" in str(e).lower() or "upgrade" in str(e).lower():
                        logger.warning("Stations listing not available in current IQAir plan")
                        raise RuntimeError("Stations listing requires plan upgrade")
                    
                    logger.error(f"Failed to fetch stations for {city}, {state}, {country} from IQAir API: {e}")
                    raise RuntimeError(f"Upstream API error: {e}")
        
        # Apply bounding box filter if provided
        if bbox_coords and stations:
            min_lon, min_lat, max_lon, max_lat = bbox_coords
            stations = [
                station for station in stations
                if (min_lon <= station.lon <= max_lon and 
                    min_lat <= station.lat <= max_lat)
            ]
            logger.info(f"Filtered to {len(stations)} stations within bbox")
        
        return stations


# Global service instance
_directory_service: Optional[AirVisualDirectoryService] = None


def get_directory_service() -> AirVisualDirectoryService:
    """Get or create global directory service instance"""
    global _directory_service
    if _directory_service is None:
        _directory_service = AirVisualDirectoryService()
    return _directory_service