"""
Upstream history fetching service for AirVisual API
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.cache import get_cache
from app.models.current import StationMeta
from app.models.history import HistoryQuery
from app.utils.history_params import is_within_last_48h

# Import the local IQAir client
from app.services.iqair_client import IQAirClient

logger = logging.getLogger(__name__)

# Global semaphore for rate limiting (5 concurrent requests max)
_rate_limit_semaphore = asyncio.Semaphore(5)


class HistoryUpstreamService:
    """Service for fetching historical data from AirVisual API"""
    
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
    
    def _make_city_cache_key(self, country: str, state: str, city: str) -> str:
        """Generate cache key for city history"""
        return f"history:last48:city:{country}:{state}:{city}"
    
    def _make_station_cache_key(self, station_id: str) -> str:
        """Generate cache key for station history"""
        return f"history:last48:station:{station_id}"
    
    async def get_city_history_last48h(
        self, 
        country: str, 
        state: str, 
        city: str
    ) -> List[Dict[str, Any]]:
        """
        Get last 48h history for a city from AirVisual API
        
        Args:
            country: Country name
            state: State/province name
            city: City name
            
        Returns:
            List of historical readings
        """
        self._check_client_available()
        
        cache_key = self._make_city_cache_key(country, state, city)
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Retrieved city history from cache: {city}, {state}, {country}")
            return cached_result
        
        try:
            # Fetch city history data (includes current + history)
            raw_data = await self._rate_limited_request(
                self.iqair_client.get_city_history(country, state, city)
            )
            
            # Extract history from the response
            history_readings = self._extract_city_history(raw_data, country, state, city)
            
            # Cache for 10 minutes
            await self.cache.set(cache_key, history_readings, 10 * 60)
            
            logger.info(f"Fetched {len(history_readings)} history readings for {city}, {state}, {country}")
            return history_readings
            
        except Exception as e:
            logger.error(f"Failed to fetch city history for {city}, {state}, {country}: {e}")
            # Return empty list on error to allow DB-only responses
            return []
    
    async def get_station_history_last48h(
        self, 
        station_meta: StationMeta
    ) -> List[Dict[str, Any]]:
        """
        Get last 48h history for a station from AirVisual API
        
        Args:
            station_meta: Station metadata
            
        Returns:
            List of historical readings
        """
        self._check_client_available()
        
        # Generate a unique station_id for caching
        from app.schemas.directory import make_station_id
        station_id = make_station_id(
            station_meta.country, station_meta.state, station_meta.city,
            station_meta.name, station_meta.lat, station_meta.lon
        )
        
        cache_key = self._make_station_cache_key(station_id)
        
        # Try cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Retrieved station history from cache: {station_meta.name}")
            return cached_result
        
        try:
            # Try station-specific endpoint first
            if station_meta.source_station_id:
                try:
                    raw_data = await self._rate_limited_request(
                        self.iqair_client.get_station_history(
                            station_meta.country,
                            station_meta.state,
                            station_meta.city,
                            station_meta.name
                        )
                    )
                except Exception as station_e:
                    logger.warning(f"Station endpoint failed, trying city endpoint: {station_e}")
                    # Fallback to city data
                    raw_data = await self._rate_limited_request(
                        self.iqair_client.get_city_history(
                            station_meta.country,
                            station_meta.state,
                            station_meta.city
                        )
                    )
            else:
                # Use city history data as proxy for station
                raw_data = await self._rate_limited_request(
                    self.iqair_client.get_city_history(
                        station_meta.country,
                        station_meta.state,
                        station_meta.city
                    )
                )
            
            # Extract history from the response
            history_readings = self._extract_station_history(raw_data, station_meta)
            
            # Cache for 10 minutes
            await self.cache.set(cache_key, history_readings, 10 * 60)
            
            logger.info(f"Fetched {len(history_readings)} history readings for station {station_meta.name}")
            return history_readings
            
        except Exception as e:
            # Check for plan limitations
            if any(term in str(e).lower() for term in ["not available", "upgrade", "plan", "subscription"]):
                logger.info(f"Station history not available on current plan: {station_meta.name}")
                return []  # Not an error, just not available
            
            logger.error(f"Failed to fetch station history for {station_meta.name}: {e}")
            return []
    
    def _extract_city_history(
        self, 
        raw_data: Dict[str, Any], 
        country: str, 
        state: str, 
        city: str
    ) -> List[Dict[str, Any]]:
        """
        Extract historical readings from AirVisual city response
        
        Args:
            raw_data: Raw AirVisual API response
            country: Country name
            state: State name
            city: City name
            
        Returns:
            List of historical reading dictionaries
        """
        readings = []
        
        try:
            # AirVisual includes history in the response
            history_data = raw_data.get("history", {}).get("pollution", [])
            
            for hist_point in history_data:
                try:
                    # Parse timestamp
                    ts_str = hist_point.get("ts")
                    if not ts_str:
                        continue
                    
                    ts_utc = self._parse_airvisual_timestamp(ts_str)
                    if not ts_utc:
                        continue
                    
                    # Only include points within last 48h
                    if not is_within_last_48h(ts_utc):
                        continue
                    
                    reading = {
                        'ts_utc': ts_utc,
                        'scope_country': country,
                        'scope_state': state,
                        'scope_city': city,
                        'source': 'upstream',
                        
                        # Extract pollutant data
                        'aqi_raw': hist_point.get('aqius'),
                        'pm25': hist_point.get('p2', {}).get('conc') if hist_point.get('p2') else None,
                        'pm10': hist_point.get('p1', {}).get('conc') if hist_point.get('p1') else None,
                        'o3': hist_point.get('o3', {}).get('conc') if hist_point.get('o3') else None,
                        'no2': hist_point.get('n2', {}).get('conc') if hist_point.get('n2') else None,
                        'so2': hist_point.get('s2', {}).get('conc') if hist_point.get('s2') else None,
                        'co': hist_point.get('co', {}).get('conc') if hist_point.get('co') else None,
                        
                        # Note: Historical data typically doesn't include weather
                        'temp_c': None,
                        'humidity': None,
                        'pressure_hpa': None,
                        'wind_speed_ms': None,
                        'wind_dir_deg': None,
                        'icon': None,
                        'heatIndex_c': None,
                        
                        'qc_state': 'OK'
                    }
                    
                    readings.append(reading)
                    
                except Exception as e:
                    logger.warning(f"Failed to parse history point: {e}")
                    continue
            
            logger.debug(f"Extracted {len(readings)} history readings from AirVisual response")
            
        except Exception as e:
            logger.error(f"Failed to extract city history from response: {e}")
        
        return readings
    
    def _extract_station_history(
        self, 
        raw_data: Dict[str, Any], 
        station_meta: StationMeta
    ) -> List[Dict[str, Any]]:
        """
        Extract historical readings from AirVisual station response
        
        Args:
            raw_data: Raw AirVisual API response
            station_meta: Station metadata
            
        Returns:
            List of historical reading dictionaries
        """
        # Station history has same format as city history
        return self._extract_city_history(
            raw_data, 
            station_meta.country, 
            station_meta.state, 
            station_meta.city
        )
    
    def _parse_airvisual_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """
        Parse AirVisual timestamp string to UTC datetime
        
        Args:
            timestamp_str: ISO timestamp string from AirVisual
            
        Returns:
            UTC datetime object or None if parsing fails
        """
        try:
            if timestamp_str.endswith('Z'):
                ts = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
            else:
                ts = datetime.fromisoformat(timestamp_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
            
            return ts
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse timestamp '{timestamp_str}': {e}")
            return None
    
    def has_upstream_coverage(self, query: HistoryQuery) -> bool:
        """
        Check if the query time range has potential upstream coverage
        
        Args:
            query: History query parameters
            
        Returns:
            True if any part of the range could have upstream data
        """
        # AirVisual only provides ~48h of history
        return (is_within_last_48h(query.from_time) or 
                is_within_last_48h(query.to_time))
    
    def get_upstream_coverage_note(self, has_plan_access: bool = True) -> Optional[str]:
        """
        Get a note about upstream coverage limitations
        
        Args:
            has_plan_access: Whether the plan supports the feature
            
        Returns:
            Note string or None
        """
        if not has_plan_access:
            return "station_history_unavailable_on_plan"
        return None


# Global service instance
_history_upstream_service: Optional[HistoryUpstreamService] = None


def get_history_upstream_service() -> HistoryUpstreamService:
    """Get or create global history upstream service instance"""
    global _history_upstream_service
    if _history_upstream_service is None:
        _history_upstream_service = HistoryUpstreamService()
    return _history_upstream_service