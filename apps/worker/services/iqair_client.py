import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Dict, List, Optional, Any, Tuple

# Dual-path imports for API container compatibility
try:
    from app.config.settings import get_settings
    settings = get_settings()
except ImportError:  # running in pure worker repo layout
    from config.settings import settings
import json
import time
import asyncio
from datetime import datetime, timezone
import logging

# Import cache abstraction with dual-path support
try:
    from app.services.cache import cache
except ImportError:  # running in pure worker repo layout
    from services.cache import cache

logger = logging.getLogger(__name__)

# === NEW: typed exceptions =====================================================
class IQAirError(RuntimeError): pass
class BadRequest(IQAirError): pass
class Unauthorized(IQAirError): pass
class RateLimited(IQAirError): pass
class StationNotFound(IQAirError): pass
class CityNotFound(IQAirError): pass
class StateNotFound(IQAirError): pass
class FeatureNotAvailable(IQAirError): pass
# ==============================================================================

class IQAirClient:
    """
    IQAir API client based on official documentation:
    https://api-docs.iqair.com/
    """
    
    def __init__(self):
        self.base_url = "http://api.airvisual.com/v2"  # Official IQAir API URL
        self.api_key = settings.IQAIR_API_KEY
        self.cache = cache
        self.rate_limit_key = "iqair:rate_limit"

        # === CHANGES: make pacing configurable by calls/min ====================
        self.max_calls_per_min = int(getattr(settings, "IQAIR_MAX_CALLS_PER_MIN", 90))
        self.max_concurrency   = int(getattr(settings, "IQAIR_CONCURRENCY", 6))
        self._rate_limiter = asyncio.Semaphore(self.max_concurrency)
        self._last_request_time = 0.0
        self._min_interval = max(0.001, 60.0 / float(self.max_calls_per_min))
        # ======================================================================

        if not self.api_key:
            raise ValueError("IQAIR_API_KEY is required")
    
    def _check_rate_limit(self) -> bool:
        """
        Distributed minute bucket with cache (Redis/null).
        Hard limit (default 90/min). If exceeded, caller should treat as RateLimited.
        """
        current_time = int(time.time())
        minute_key = f"{self.rate_limit_key}:{current_time // 60}"
        
        current_count = self.cache.get(minute_key)
        current_count = int(current_count) if current_count else 0
        
        if current_count >= self.max_calls_per_min:
            logger.warning(f"Rate limit exceeded: {current_count} calls this minute")
            return False
        
        # Increment counter with cache abstraction
        new_count = current_count + 1
        self.cache.setex(minute_key, 60, str(new_count))
        
        return True
    
    async def _global_rate_limit(self):
        """Smooth per-request spacing to keep average under max_calls_per_min."""
        async with self._rate_limiter:
            now = time.time()
            delta = now - self._last_request_time
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last_request_time = time.time()

    # === CHANGES: retry only on transient/network issues =======================
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((RateLimited, httpx.RequestError, httpx.TimeoutException))
    )
    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make HTTP request to IQAir API with centralized rate limiting."""
        
        # Smooth local limiter
        await self._global_rate_limit()
        
        # Distributed limiter (minute bucket)
        if not self._check_rate_limit():
            # trigger tenacity backoff & retry
            raise RateLimited("local_minute_bucket_exceeded")
        
        request_params = {"key": self.api_key}
        if params:
            request_params.update(params)
        
        url = f"{self.base_url}/{endpoint}"
        logger.info(f"Making IQAir API request: {endpoint} with params: {params}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=request_params)
        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.warning("HTTP error calling %s: %s", url, e)
            # retryable by decorator
            raise

        # Map HTTP status codes -> typed errors
        if response.status_code == 429:
            logger.error("IQAir returned 429 (rate limited)")
            raise RateLimited("remote_429")
        if response.status_code == 403:
            logger.error("Invalid API key or unauthorized access")
            raise Unauthorized("invalid_api_key_or_unauthorized")
        if response.status_code >= 500:
            logger.error("Server error from IQAir: %s - %s", response.status_code, response.text)
            # treat as generic error (tenacity will retry because not typed explicitly;
            # but it's wrapped by RequestError normally; keep as IQAirError)
            raise IQAirError(f"server_error_{response.status_code}")

        # Parse JSON
        try:
            payload = response.json()
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response: {response.text[:200]}")
            raise IQAirError("invalid_json")

        status = payload.get("status")
        data   = payload.get("data")

        if response.status_code == 400 or status == "fail":
            # Extract canonical message text
            msg = ""
            if isinstance(data, dict):
                msg = (data.get("message") or "").lower()
            # Map to typed errors
            if "station_not_found" in msg:
                raise StationNotFound("station_not_found")
            if "city_not_found" in msg:
                raise CityNotFound("city_not_found")
            if "state_not_found" in msg:
                raise StateNotFound("state_not_found")
            if "feature_not_available" in msg:
                raise FeatureNotAvailable("feature_not_available")
            # Any other 400/fail
            raise BadRequest(msg or f"bad_request_{response.text[:120]}")

        if status != "success":
            # Defensive: unexpected shape
            raise IQAirError(f"unexpected_status:{status}")

        logger.info(f"Successful API response for {endpoint}")
        return data  # NOTE: return the API 'data' object exactly as before

    # ---------------- History (pollution) ----------------
    async def get_station_history_pollution(
        self,
        station: str,
        city: Optional[str],
        state: Optional[str],
        country: Optional[str],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch hourly pollution history for a station within [start_utc, end_utc].
        If your plan uses a different endpoint/params, adjust this method only.
        """
        def _iso(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        params: Dict[str, Any] = {
            "station": station,
            "type": "hourly",
            "measure": "pollution",
            "start": _iso(start_utc),
            "end": _iso(end_utc),
        }
        if city:    params["city"] = city
        if state:   params["state"] = state
        if country: params["country"] = country
        return await self._make_request("history", params)

    def parse_history_pollution(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Normalize history payload into a list of 'pollution' dicts, each containing:
        ts, aqius, aqicn, mainus, maincn, p2, p1, o3, n2, s2, co
        """
        if not data:
            return []
        hist = (
            (data.get("history") or {}).get("pollution")
            or data.get("pollution")
            or data.get("items")
            or []
        )
        return [p for p in hist if isinstance(p, dict)]

    # ---------------- History (weather) ------------------
    async def get_station_history_weather(
        self,
        station: str,
        city: Optional[str],
        state: Optional[str],
        country: Optional[str],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Dict[str, Any]:
        """
        Fetch hourly weather history for a station within [start_utc, end_utc].
        If your plan uses a different endpoint/params, adjust this method only.
        """
        def _iso(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        params: Dict[str, Any] = {
            "station": station,
            "type": "hourly",
            "measure": "weather",
            "start": _iso(start_utc),
            "end": _iso(end_utc),
        }
        if city:    params["city"] = city
        if state:   params["state"] = state
        if country: params["country"] = country
        return await self._make_request("history", params)

    def parse_history_weather(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Normalize weather history into a list of dicts, each with at least:
        ts, tp, pr, hu, ws, wd, ic, heatIndex (keys mirror current.weather)
        """
        if not data:
            return []
        hist = (
            (data.get("history") or {}).get("weather")
            or data.get("weather")
            or data.get("items")
            or []
        )
        return [w for w in hist if isinstance(w, dict)]
    
    # ---------------- Location discovery ----------------
    async def get_countries(self) -> List[Dict[str, Any]]:
        return await self._make_request("countries")
    
    async def get_states(self, country: str) -> List[Dict[str, Any]]:
        return await self._make_request("states", {"country": country})
    
    async def get_cities(self, country: str, state: str) -> List[Dict[str, Any]]:
        return await self._make_request("cities", {"country": country, "state": state})
    
    async def get_stations(self, city: str, state: str, country: str) -> List[Dict[str, Any]]:
        return await self._make_request("stations", {"city": city, "state": state, "country": country})
    
    # ---------------- Data retrieval --------------------
    async def get_city_data(self, city: str, state: str, country: str) -> Dict[str, Any]:
        return await self._make_request("city", {"city": city, "state": state, "country": country})
    
    async def get_nearest_city_data(self, lat: float, lon: float) -> Dict[str, Any]:
        return await self._make_request("nearest_city", {"lat": lat, "lon": lon})
    
    async def get_station_data(self, station: str, city: str = None, state: str = None, country: str = None) -> Dict[str, Any]:
        params = {"station": station}
        if city:
            params["city"] = city
        if state:
            params["state"] = state
        if country:
            params["country"] = country
        return await self._make_request("station", params)
    
    # ---------------- Parsing helpers (unchanged) ----------------
    def parse_city_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # Keep the richer "current/history" layout so ingestion can merge history.
        location = data.get("location", {}) or {}
        coords = location.get("coordinates") or []
        lat = coords[1] if len(coords) > 1 else None
        lon = coords[0] if len(coords) > 0 else None
        out = {
            "station_info": {
                "city": data.get("city"),
                "state": data.get("state"),
                "country": data.get("country"),
                "latitude": lat,
                "longitude": lon,
                "location_type": location.get("type"),
            },
            "current": {
                "pollution": (data.get("current") or {}).get("pollution"),
                "weather":   (data.get("current") or {}).get("weather"),
            },
            "history": {
                # These may be empty; ingestion will merge fetched history here.
                "pollution": (data.get("history") or {}).get("pollution") or [],
                "weather":   (data.get("history") or {}).get("weather") or [],
            },
            "raw_response": data,
        }
        return out
    
    def parse_station_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.parse_city_data(data)

    def normalize_to_new_schema(self, parsed_data: Dict[str, Any], station_id: str) -> Dict[str, Any]:
        from datetime import datetime
        timestamp_str = parsed_data.get("timestamp")
        if timestamp_str:
            try:
                if timestamp_str.endswith('Z'):
                    ts_utc = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
                else:
                    ts_utc = datetime.fromisoformat(timestamp_str.replace('Z', '')).replace(tzinfo=timezone.utc)
                ts_utc = ts_utc.replace(minute=0, second=0, microsecond=0)
            except:
                ts_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        else:
            ts_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        pollution = parsed_data.get("pollution", {})
        weather = parsed_data.get("weather", {})
        main_us = pollution.get("main_pollutant_us")
        main_cn = pollution.get("main_pollutant_cn")
        pollutant_mapping = {"p1": "pm10", "p2": "pm25", "o3": "o3", "n2": "no2", "s2": "so2", "co": "co"}
        return {
            "scope_type": "station",
            "scope_key": station_id,
            "ts_utc": ts_utc,
            "aqi_us": pollution.get("aqi_us"),
            "aqi_cn": pollution.get("aqi_cn"),
            "main_us": pollutant_mapping.get(main_us, main_us) if main_us else None,
            "main_cn": pollutant_mapping.get(main_cn, main_cn) if main_cn else None,
            "pm25": pollution.get("pm25_conc"),
            "pm10": pollution.get("pm10_conc"),
            "o3": pollution.get("o3_conc"),
            "no2": pollution.get("no2_conc"),
            "so2": pollution.get("so2_conc"),
            "co": pollution.get("co_conc"),
            "units_pm25": "µg/m³",
            "units_pm10": "µg/m³",
            "units_o3": "ppb",
            "units_no2": "ppb", 
            "units_so2": "ppb",
            "units_co": "ppm",
            "temp_c": weather.get("temperature"),
            "humidity": weather.get("humidity"),
            "pressure_hpa": weather.get("pressure"),
            "wind_speed_ms": weather.get("wind_speed"),
            "wind_dir_deg": weather.get("wind_direction"),
            "weather_icon": weather.get("icon"),
            "heatindex_c": weather.get("heat_index"),
            "pop_pct": weather.get("precipitation_probability"),
            "qc_state": "OK",
            "source": "airvisual",
            "raw": json.dumps(parsed_data.get("raw_response", {}))
        }

    def convert_to_db_format(self, parsed_data: Dict[str, Any], station_id: int) -> Dict[str, Any]:
        """Convert parsed IQAir data to database format - DEPRECATED, use normalize_to_new_schema"""
        
        # Parse timestamp
        timestamp_str = parsed_data.get("timestamp")
        if timestamp_str:
            try:
                # IQAir timestamps are in ISO format with 'Z' suffix
                ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Could not parse timestamp: {timestamp_str}")
                ts = datetime.utcnow()
        else:
            ts = datetime.utcnow()
        
        pollution = parsed_data.get("pollution", {})
        weather = parsed_data.get("weather", {})
        
        # Extract meteorological data
        temperature = weather.get("temperature")
        humidity = weather.get("humidity")
        pressure = weather.get("pressure")
        wind_speed = weather.get("wind_speed")
        wind_direction = weather.get("wind_direction")
        weather_icon = weather.get("icon")
        
        # Use heat index from API if available, otherwise calculate it
        heat_index = weather.get("heat_index")
        if heat_index is None and temperature is not None and humidity is not None:
            heat_index = self._calculate_heat_index(temperature, humidity)
        
        return {
            "station_id": station_id,
            "ts": ts,
            # Air Quality data
            "pm25": pollution.get("pm25_conc"),  # Now available from p2.conc
            "pm10": pollution.get("pm10_conc"),  # Now available from p1.conc  
            "o3": None,  # Could be extracted from o3.conc if available
            "no2": None,  # Could be extracted from n2.conc if available
            "so2": None,  # Could be extracted from s2.conc if available
            "co": None,   # Could be extracted from co.conc if available
            "aqi_raw": pollution.get("aqi_us"),  # Use US AQI (aqius)
            
            # Meteorological data
            "temp": temperature,  # Temperature in Celsius
            "hum": humidity,      # Humidity percentage
            "pressure": pressure,  # Atmospheric pressure in hPa
            "wind_speed": wind_speed,  # Wind speed in m/s
            "wind_direction": wind_direction,  # Wind direction in degrees
            "weather_icon": weather_icon,  # Weather icon code
            "heat_index": heat_index,  # Calculated heat index
            
            # Metadata
            "qc_state": "OK",  # Initial state, will be validated later
            "origin": "minute",
            # Store only essential metadata, not the entire API response
            "payload_json": json.dumps({
                "city": parsed_data.get("station_info", {}).get("city"),
                "state": parsed_data.get("station_info", {}).get("state"),
                "country": parsed_data.get("station_info", {}).get("country"),
                "location": parsed_data.get("station_info", {}).get("location_type"),
                "timestamp": parsed_data.get("timestamp"),
                "api_version": "v2",
                "ingestion_time": datetime.utcnow().isoformat()
            })
        }
    
    def create_station_info(self, parsed_data: Dict[str, Any], source_id: int = 1) -> Dict[str, Any]:
        """Create station info for database insertion"""
        station_info = parsed_data.get("station_info", {})
        
        # Create external ID from location
        external_id = f"iqair-{station_info.get('country', '')}-{station_info.get('state', '')}-{station_info.get('city', '')}".lower().replace(' ', '-')
        
        return {
            "source_id": source_id,  # IQAir source ID
            "external_id": external_id,
            "name": f"{station_info.get('city', 'Unknown')}, {station_info.get('state', 'Unknown')}",
            "city_id": None,  # Will be linked later
            "latitude": station_info.get("latitude"),
            "longitude": station_info.get("longitude"),
            "meta_json": {
                "iqair_city": station_info.get("city"),
                "iqair_state": station_info.get("state"),
                "iqair_country": station_info.get("country"),
                "location_type": station_info.get("location_type"),
                "data_source": "iqair_city_endpoint",
                "last_updated": datetime.utcnow().isoformat()
            }
        }

    def _calculate_heat_index(self, temp_celsius: float, humidity: float) -> float:
        """
        Calculate heat index in Celsius using the National Weather Service formula
        Heat index is a measure of how hot it feels when relative humidity is factored in
        """
        # Convert Celsius to Fahrenheit for the calculation
        temp_f = (temp_celsius * 9/5) + 32
        
        # Use simplified formula for temperatures < 80°F
        if temp_f < 80:
            return temp_celsius  # Return original temperature
            
        # Full heat index formula (in Fahrenheit)
        hi_f = (-42.379 + 
                2.04901523 * temp_f + 
                10.14333127 * humidity - 
                0.22475541 * temp_f * humidity - 
                0.00683783 * temp_f**2 - 
                0.05481717 * humidity**2 + 
                0.00122874 * temp_f**2 * humidity + 
                0.00085282 * temp_f * humidity**2 - 
                0.00000199 * temp_f**2 * humidity**2)
        
        # Convert back to Celsius
        heat_index_celsius = (hi_f - 32) * 5/9
        
        return round(heat_index_celsius, 1)

    async def test_api_connection(self) -> bool:
        """Test if API key and connection are working"""
        try:
            countries = await self.get_countries()
            logger.info(f"API test successful. Found {len(countries)} countries.")
            return True
        except Exception as e:
            logger.error(f"API test failed: {e}")
            return False