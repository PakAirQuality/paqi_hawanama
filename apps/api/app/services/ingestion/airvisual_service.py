"""
AirVisual Current Service - handles current conditions API calls with caching
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Literal
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.ingestion.cache import get_cache
from app.services.ingestion.station_utils import resolve_station_id
from app.services.ingestion.normalizer import normalize_current
from app.models.current import CurrentOut, StationMeta

# Import the local IQAir client
from app.services.ingestion.iqair_service import IQAirClient

logger = logging.getLogger(__name__)

# Global semaphore for rate limiting (5 concurrent requests max)
_rate_limit_semaphore = asyncio.Semaphore(5)


class AirVisualCurrentService:
    """Service layer for AirVisual current conditions endpoints with caching and rate limiting"""
    
    def __init__(self):
        self.cache = get_cache()
        try:
            self.iqair_client = IQAirClient()
        except (ValueError, RuntimeError) as e:
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
    
    def _make_city_cache_key(self, country: str, state: str, city: str, aqi_mode: str) -> str:
        """Generate cache key for city current requests"""
        return f"current:city:{country}:{state}:{city}:aqi={aqi_mode}"
    
    def _make_station_cache_key(self, station_id: str, aqi_mode: str) -> str:
        """Generate cache key for station current requests"""
        return f"current:station:{station_id}:aqi={aqi_mode}"
    
    async def fetch_city_current(self, country: str, state: str, city: str) -> Dict[str, Any]:
        """
        Fetch current city data from AirVisual API
        
        Args:
            country: Country name
            state: State/province name
            city: City name
            
        Returns:
            Raw API response data
            
        Raises:
            RuntimeError: If API client unavailable or upstream error
        """
        self._check_client_available()
        
        try:
            data = await self._rate_limited_request(
                self.iqair_client.get_city_current(country, state, city)
            )
            
            logger.info(f"Fetched current data for {city}, {state}, {country} from IQAir API")
            return data
            
        except Exception as e:
            logger.error(f"Failed to fetch current data for {city}, {state}, {country}: {e}")
            
            # Check for city not found
            if "city_not_found" in str(e).lower() or "not found" in str(e).lower():
                raise RuntimeError("city_not_found")
            
            # Log upstream payload for non-success
            logger.error(f"Upstream error payload: {e}")
            raise RuntimeError(f"Upstream API error: {e}")
    
    async def fetch_station_current(self, station_meta: StationMeta) -> Dict[str, Any]:
        """
        Fetch current station data from AirVisual API
        
        Args:
            station_meta: Station metadata for API call
            
        Returns:
            Raw API response data
            
        Raises:
            RuntimeError: If API client unavailable, plan limitation, or upstream error
        """
        self._check_client_available()
        
        try:
            # Try to use station-specific endpoint 
            data = await self._rate_limited_request(
                self.iqair_client.get_station_current(
                    station_meta.country,
                    station_meta.state,
                    station_meta.city,
                    station_meta.name
                )
            )
            
            logger.info(f"Fetched current data for station {station_meta.name} from IQAir API")
            return data
            
        except Exception as e:
            logger.error(f"Failed to fetch current data for station {station_meta.name}: {e}")
            
            # Check for plan limitations
            if any(term in str(e).lower() for term in ["not available", "upgrade", "plan", "subscription"]):
                raise RuntimeError("Station current requires plan upgrade")
            
            # Check for station not found
            if "station_not_found" in str(e).lower() or "not found" in str(e).lower():
                raise RuntimeError("station_not_found")
            
            # Log upstream payload for non-success
            logger.error(f"Upstream error payload: {e}")
            raise RuntimeError(f"Upstream API error: {e}")
    
    async def get_city_current(
        self,
        country: str,
        state: str, 
        city: str,
        aqi_mode: Literal["us", "cn", "both"] = "both",
        tz: str = "Asia/Karachi"
    ) -> CurrentOut:
        """
        Get current conditions for a city
        
        Args:
            country: Country name
            state: State/province name
            city: City name
            aqi_mode: Which AQI scales to include
            tz: Timezone for local timestamp conversion
            
        Returns:
            CurrentOut object with normalized data
            
        Raises:
            ValueError: Invalid parameters
            RuntimeError: API errors or city not found
        """
        # Validate parameters
        if not all([country.strip(), state.strip(), city.strip()]):
            raise ValueError("Country, state, and city parameters must be non-empty")
        
        cache_key = self._make_city_cache_key(country, state, city, aqi_mode)
        
        # Try cache first (excluding timezone to avoid cache fragmentation)
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            # Reconstruct from cached data and update local timestamp
            try:
                result = CurrentOut(**cached_result)
                # Update local timestamp with requested timezone
                from app.services.ingestion.normalizer import _convert_to_local_time
                result.ts_local = _convert_to_local_time(result.ts_utc, tz)
                return result
            except Exception as e:
                logger.warning(f"Failed to reconstruct cached data, fetching fresh: {e}")
        
        # Fetch from API
        try:
            raw_data = await self.fetch_city_current(country, state, city)
            
            # Normalize the data
            scope = {"country": country, "state": state, "city": city}
            result = normalize_current(raw_data, aqi_mode, tz, scope)
            
            # Cache for 55 minutes (excluding timezone-specific ts_local)
            cache_data = result.model_dump(mode='json')
            await self.cache.set(cache_key, cache_data, 55 * 60)
            
            logger.info(f"Retrieved and cached current data for {city}, {state}, {country}")
            
            return result
            
        except RuntimeError as e:
            if "city_not_found" in str(e):
                raise RuntimeError("city_not_found")
            raise
    
    async def get_station_current(
        self,
        station_id: str,
        aqi_mode: Literal["us", "cn", "both"] = "both",
        tz: str = "Asia/Karachi"
    ) -> CurrentOut:
        """
        Get current conditions for a station
        
        Args:
            station_id: 16-character SHA1 hash station ID
            aqi_mode: Which AQI scales to include
            tz: Timezone for local timestamp conversion
            
        Returns:
            CurrentOut object with normalized data
            
        Raises:
            ValueError: Invalid station_id format
            RuntimeError: API errors, plan limitation, or station not found
        """
        # Validate station_id format
        if not station_id or len(station_id) != 16:
            raise ValueError("station_id must be a 16-character string")
        
        cache_key = self._make_station_cache_key(station_id, aqi_mode)
        
        # Try cache first (excluding timezone to avoid cache fragmentation)
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            # Reconstruct from cached data and update local timestamp
            try:
                result = CurrentOut(**cached_result)
                # Update local timestamp with requested timezone
                from app.services.ingestion.normalizer import _convert_to_local_time
                result.ts_local = _convert_to_local_time(result.ts_utc, tz)
                return result
            except Exception as e:
                logger.warning(f"Failed to reconstruct cached data, fetching fresh: {e}")
        
        # Resolve station_id to metadata
        station_meta = await resolve_station_id(station_id)
        if not station_meta:
            raise RuntimeError("station_not_found")
        
        # Fetch from API
        try:
            raw_data = await self.fetch_station_current(station_meta)
            
            # Normalize the data
            scope = {
                "country": station_meta.country,
                "state": station_meta.state, 
                "city": station_meta.city
            }
            result = normalize_current(raw_data, aqi_mode, tz, scope)
            
            # Cache for 55 minutes (excluding timezone-specific ts_local)
            cache_data = result.model_dump(mode='json')
            await self.cache.set(cache_key, cache_data, 55 * 60)
            
            logger.info(f"Retrieved and cached current data for station {station_meta.name}")
            
            return result
            
        except RuntimeError as e:
            if "plan upgrade" in str(e):
                raise RuntimeError("Station current requires plan upgrade")
            if "station_not_found" in str(e):
                raise RuntimeError("station_not_found")
            raise


# Global service instance
_current_service: Optional[AirVisualCurrentService] = None


def get_current_service() -> AirVisualCurrentService:
    """Get or create global current service instance"""
    global _current_service
    if _current_service is None:
        _current_service = AirVisualCurrentService()
    return _current_service