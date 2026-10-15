"""
IQAir (AirVisual) API client — https://api-docs.iqair.com/

Transport rules:
  * HTTPS, one shared httpx client per event loop, explicit timeouts
  * never logs response bodies or the API key (see app.ingestion.http)
  * errors are typed: TransientError (5xx, network, timeout) is retried with
    bounded jittered backoff; RateLimited honours Retry-After; Unauthorized
    (401/403) is persistent and never retried
  * every attempt (including retries) is paced locally and, when a quota
    service is attached, reserved against the shared per-credential budget
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.core.config import settings as _settings
from app.ingestion.http import default_timeout, get_shared_async_client, parse_retry_after, redact_url, register_secret
from app.ingestion.quota import QuotaExhausted, default_quota
from app.ingestion.ratelimit import LocalPacer

_UNSET = object()

logger = logging.getLogger(__name__)


# === typed exceptions =========================================================
class IQAirError(RuntimeError):
    retryable = False


class TransientError(IQAirError):
    """5xx, network or timeout: safe to retry."""
    retryable = True


class RateLimited(TransientError):
    def __init__(self, msg: str = "rate_limited", retry_after_s: Optional[float] = None):
        super().__init__(msg)
        self.retry_after_s = retry_after_s


class Unauthorized(IQAirError):
    """401/403: the credential is bad for every request; never retried."""


class BadRequest(IQAirError): pass
class StationNotFound(IQAirError): pass
class CityNotFound(IQAirError): pass
class StateNotFound(IQAirError): pass
class FeatureNotAvailable(IQAirError): pass
# ==============================================================================


@dataclass
class FetchEnvelope:
    """A successful response plus the facts the raw archive and provenance need."""
    data: Any
    http_status: int
    fetched_at: datetime
    endpoint: str
    params_redacted: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    attempts: int = 1


class IQAirClient:
    """
    IQAir API client based on official documentation:
    https://api-docs.iqair.com/

    `IQAirClient()` with no arguments keeps working for the read-path services.
    Ingestion passes `quota=` so requests count against the shared budget.
    """

    def __init__(self, *, settings=None, http: Optional[httpx.AsyncClient] = None,
                 quota=_UNSET, pacer: Optional[LocalPacer] = None, retry_sleep=None):
        s = settings or _settings
        self.settings = s
        self.base_url = s.IQAIR_BASE_URL.rstrip("/")
        self.api_key = s.IQAIR_API_KEY
        if not self.api_key:
            raise ValueError("IQAIR_API_KEY is required")
        register_secret(self.api_key)

        self.max_calls_per_min = int(s.IQAIR_MAX_CALLS_PER_MIN)
        self.max_concurrency = int(s.IQAIR_CONCURRENCY)
        self.credential_alias = s.IQAIR_CREDENTIAL_ALIAS

        self._http = http
        self._pacer = pacer or LocalPacer(self.max_calls_per_min, self.max_concurrency)
        # Read-path services construct IQAirClient() with no quota: meter them best-effort
        # (required=False) so the shared budget counts every request but never breaks a page.
        # Ingestion tasks pass a required quota explicitly. quota=None disables metering.
        self._quota = default_quota(required=False) if quota is _UNSET else quota
        self._timeout = default_timeout(connect=float(s.IQAIR_HTTP_CONNECT_TIMEOUT_S),
                                        read=float(s.IQAIR_HTTP_READ_TIMEOUT_S))
        self._max_attempts = max(1, int(s.IQAIR_RETRY_MAX_ATTEMPTS))
        self._max_wait = float(s.IQAIR_RETRY_MAX_WAIT_S)
        self._retry_sleep = retry_sleep or asyncio.sleep

    @property
    def quota(self):
        return self._quota

    def _client(self) -> httpx.AsyncClient:
        return self._http or get_shared_async_client()

    # ---- retry policy ----------------------------------------------------------

    def _wait(self, retry_state) -> float:
        """Jittered exponential backoff, never shorter than the server's Retry-After."""
        base = wait_random_exponential(multiplier=1, max=self._max_wait)(retry_state)
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        hinted = getattr(exc, "retry_after_s", None)
        if hinted:
            return max(base, float(hinted))
        return base

    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make an HTTP request to the IQAir API with pacing, quota and bounded retries."""
        return (await self._request_envelope(endpoint, params)).data

    async def _request_envelope(self, endpoint: str, params: Dict[str, Any] = None) -> FetchEnvelope:
        """Same as _make_request but keeps HTTP status, fetch time and timing for provenance."""
        attempts = 0
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(self._max_attempts),
            wait=self._wait,
            retry=retry_if_exception_type(TransientError),
            sleep=self._retry_sleep,
        ):
            with attempt:
                attempts += 1
                env = await self._request_once(endpoint, params)
                env.attempts = attempts
                return env

    # ---- envelope-returning fetches used by ingestion (raw archive + provenance) ----
    async def fetch_station(self, station: str, city: str = None, state: str = None, country: str = None) -> FetchEnvelope:
        params = {"station": station}
        if city:
            params["city"] = city
        if state:
            params["state"] = state
        if country:
            params["country"] = country
        return await self._request_envelope("station", params)

    async def fetch_city(self, city: str, state: str, country: str) -> FetchEnvelope:
        return await self._request_envelope("city", {"city": city, "state": state, "country": country})

    async def fetch_nearest_city(self, lat: float, lon: float) -> FetchEnvelope:
        return await self._request_envelope("nearest_city", {"lat": lat, "lon": lon})

    async def _reserve_quota(self) -> None:
        """Reserve one request against the shared per-credential budget (no-op without a quota service)."""
        if self._quota is None:
            return
        try:
            await self._quota.reserve_or_wait(self.credential_alias, limit_per_min=self.max_calls_per_min,
                                              max_wait_s=float(self.settings.IQAIR_QUOTA_MAX_WAIT_S))
        except QuotaExhausted as exc:
            # Let the normal bounded retry policy decide whether to try again.
            raise RateLimited("shared_quota_exhausted", retry_after_s=exc.retry_in_s) from exc

    async def _request_once(self, endpoint: str, params: Dict[str, Any] = None) -> FetchEnvelope:
        url = f"{self.base_url}/{endpoint}"
        request_params: Dict[str, Any] = dict(params or {})
        request_params["key"] = self.api_key
        params_redacted = {k: v for k, v in (params or {}).items()}

        async with self._pacer:
            await self._reserve_quota()
            logger.info("IQAir request %s params=%s", endpoint, params_redacted)
            fetched_at = datetime.now(timezone.utc)
            t0 = time.monotonic()
            try:
                response = await self._client().get(url, params=request_params, timeout=self._timeout)
            except httpx.TimeoutException as e:
                logger.warning("IQAir timeout calling %s: %s", endpoint, type(e).__name__)
                raise TransientError(f"timeout:{type(e).__name__}") from e
            except httpx.TransportError as e:
                logger.warning("IQAir transport error calling %s: %s", endpoint, type(e).__name__)
                raise TransientError(f"transport_error:{type(e).__name__}") from e

        status_code = response.status_code
        if status_code == 429:
            retry_after = parse_retry_after(response.headers)
            logger.warning("IQAir 429 on %s (retry_after=%s)", endpoint, retry_after)
            raise RateLimited("remote_429", retry_after_s=retry_after)
        if status_code in (401, 403):
            logger.error("IQAir rejected the credential on %s: HTTP %d", endpoint, status_code)
            raise Unauthorized(f"unauthorized_{status_code}")
        if status_code >= 500:
            # Status and size only — never the body.
            logger.warning("IQAir server error on %s: HTTP %d (%d bytes)", endpoint, status_code, len(response.content or b""))
            raise TransientError(f"server_error_{status_code}")

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            logger.error("IQAir returned non-JSON on %s: HTTP %d (%d bytes)", endpoint, status_code, len(response.content or b""))
            raise IQAirError(f"invalid_json_{status_code}")

        status = payload.get("status") if isinstance(payload, dict) else None
        data = payload.get("data") if isinstance(payload, dict) else None

        if status_code == 400 or status == "fail":
            msg = ""
            if isinstance(data, dict):
                msg = str(data.get("message") or "").lower()
            if "station_not_found" in msg:
                raise StationNotFound("station_not_found")
            if "city_not_found" in msg:
                raise CityNotFound("city_not_found")
            if "state_not_found" in msg:
                raise StateNotFound("state_not_found")
            if "feature_not_available" in msg:
                raise FeatureNotAvailable("feature_not_available")
            raise BadRequest(msg[:120] or f"bad_request_{status_code}")

        if status != "success":
            raise IQAirError(f"unexpected_status:{status}")

        logger.debug("IQAir %s ok (%s)", endpoint, redact_url(url))
        return FetchEnvelope(data=data, http_status=status_code, fetched_at=fetched_at, endpoint=endpoint,
                             params_redacted=params_redacted, elapsed_ms=int((time.monotonic() - t0) * 1000))

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