"""
IQAir API client for directory endpoints
Simplified version focused on directory listings only
"""

import asyncio
import httpx
import logging
from typing import Dict, List, Any
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)


class IQAirClient:
    """
    Simplified IQAir API client for directory endpoints only
    Based on IQAir API documentation: https://api-docs.iqair.com/
    """
    
    def __init__(self):
        self.base_url = "http://api.airvisual.com/v2"
        self.api_key = settings.IQAIR_API_KEY
        
        if not self.api_key:
            raise ValueError("IQAIR_API_KEY is required")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8)
    )
    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Make HTTP request to IQAir API with retries"""
        
        request_params = {"key": self.api_key}
        if params:
            request_params.update(params)
        
        url = f"{self.base_url}/{endpoint}"
        logger.info(f"Making IQAir API request: {endpoint}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, params=request_params)
                
                if response.status_code == 429:
                    logger.error("Rate limit hit by IQAir API")
                    raise Exception("Rate limit hit by API")
                elif response.status_code == 403:
                    logger.error("Invalid API key or unauthorized access")
                    raise Exception("Invalid API key or unauthorized")
                elif response.status_code != 200:
                    logger.error(f"API error: {response.status_code} - {response.text}")
                    raise Exception(f"API error: {response.status_code}")
                
                data = response.json()
                
                if data.get("status") != "success":
                    logger.error(f"API returned error: {data}")
                    raise Exception(f"API returned error: {data.get('message', 'Unknown error')}")
                
                logger.info(f"Successful API response for {endpoint}")
                return data["data"]
                
            except httpx.TimeoutException:
                logger.error(f"Timeout calling IQAir API: {endpoint}")
                raise Exception("API request timeout")
            except httpx.RequestError as e:
                logger.error(f"Request error calling IQAir API: {e}")
                raise Exception(f"API request failed: {e}")
    
    async def get_countries(self) -> List[Dict[str, Any]]:
        """Get list of supported countries"""
        return await self._make_request("countries")
    
    async def get_states(self, country: str) -> List[Dict[str, Any]]:
        """Get states/provinces for a country"""
        return await self._make_request("states", {"country": country})
    
    async def get_cities(self, country: str, state: str) -> List[Dict[str, Any]]:
        """Get cities for a state"""
        return await self._make_request("cities", {"country": country, "state": state})
    
    async def get_stations(self, city: str, state: str, country: str) -> List[Dict[str, Any]]:
        """
        Get all monitoring stations for a city
        Note: This endpoint requires a higher-tier API plan
        """
        return await self._make_request("stations", {
            "city": city,
            "state": state,
            "country": country
        })
    
    async def get_nearest_city_data(self, lat: float, lon: float) -> Dict[str, Any]:
        """Get air quality data for nearest city to coordinates"""
        return await self._make_request("nearest_city", {
            "lat": lat,
            "lon": lon
        })
    
    async def get_nearest_station_data(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Get air quality data for nearest station to coordinates
        Note: This endpoint may require a higher-tier API plan
        """
        return await self._make_request("nearest_station", {
            "lat": lat,
            "lon": lon
        })

    async def get_city_current(self, country: str, state: str, city: str) -> Dict[str, Any]:
        """Get current air quality and weather data for a city"""
        return await self._make_request("city", {
            "city": city,
            "state": state,
            "country": country
        })

    async def get_station_current(self, country: str, state: str, city: str, station: str) -> Dict[str, Any]:
        """
        Get current air quality and weather data for a station
        Note: This endpoint may require a higher-tier API plan
        """
        return await self._make_request("station", {
            "city": city,
            "state": state,
            "country": country,
            "station": station
        })

    async def get_city_history(self, country: str, state: str, city: str) -> Dict[str, Any]:
        """Get historical air quality data for a city (last 48h)"""
        return await self._make_request("city", {
            "city": city,
            "state": state,
            "country": country
        })

    async def get_station_history(self, country: str, state: str, city: str, station: str) -> Dict[str, Any]:
        """
        Get historical air quality data for a station (last 48h)
        Note: This endpoint may require a higher-tier API plan
        """
        return await self._make_request("station", {
            "city": city,
            "state": state,
            "country": country,
            "station": station
        })

    async def test_connection(self) -> bool:
        """Test if API key and connection are working"""
        try:
            countries = await self.get_countries()
            logger.info(f"API test successful. Found {len(countries)} countries.")
            return True
        except Exception as e:
            logger.error(f"API test failed: {e}")
            return False