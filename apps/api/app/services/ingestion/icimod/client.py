"""
ICIMOD Air Quality Watch HTTP client.

  * no credential: the `external-api` and `pakistan-dashboard` routes are public
  * 5xx / network / timeout → ICIMODTransient, retried with jittered backoff
  * any other non-2xx or invalid JSON → ICIMODError (the run fails; nothing is retried)
  * one POST per run fetches the current UTC day for every station, so there is no
    per-request budget or quota table involved

Endpoints (base ICIMOD_BASE_URL, default https://pakistan.smog.icimod.org/api/v1):
  GET  /pakistan-dashboard/districts/?state=Punjab&source=Ground%20Station        → ["Attock", ...]
  GET  /pakistan-dashboard/icimod/stations/?district_name=A,B,C                   → [{id, station_name, district_name, city, state, latitude, longitude}]
  POST /external-api/charts/timeseries/recent/geojson/ {station:[names], pollutant, source}
       → GeoJSON FeatureCollection; properties {name, country, value, hourly_data:{"<iso>": value}}
  POST /pakistan-dashboard/charts/timeseries/gridded-forecast-trend/ (verification only)
       {parameter, source, stations, start_date, end_date} → {"archive":[{"timestamp": "YYYY-MM-DD HH:MM:SS", "<station>": v}]}
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.core.config import settings as _settings
from app.ingestion.http import default_timeout, get_shared_async_client

logger = logging.getLogger(__name__)

DISTRICTS_PATH = "pakistan-dashboard/districts/"
STATIONS_PATH = "pakistan-dashboard/icimod/stations/"
RECENT_PATH = "external-api/charts/timeseries/recent/geojson/"
TREND_PATH = "pakistan-dashboard/charts/timeseries/gridded-forecast-trend/"

Fetched = Tuple[Any, datetime, int]   # (payload, fetched_at, http_status)


class ICIMODError(RuntimeError):
    pass


class ICIMODTransient(ICIMODError):
    """5xx, timeout or transport error: retried, then the run fails as provider_error."""


class ICIMODClient:
    def __init__(self, *, settings=None, http: Optional[httpx.AsyncClient] = None, retry_sleep=None):
        s = settings or _settings
        self.settings = s
        self.base_url = (s.ICIMOD_BASE_URL or "https://pakistan.smog.icimod.org/api/v1").rstrip("/")
        self._http = http
        self._timeout = default_timeout(connect=10.0, read=float(s.ICIMOD_HTTP_TIMEOUT_S))
        self._attempts = max(1, int(s.ICIMOD_RETRY_MAX_ATTEMPTS))
        self._retry_sleep = retry_sleep or asyncio.sleep
        self.requests_made = 0

    def _client(self) -> httpx.AsyncClient:
        return self._http or get_shared_async_client()

    async def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                       json_body: Optional[Dict[str, Any]] = None) -> Fetched:
        async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(self._attempts),
                                           wait=wait_random_exponential(multiplier=1, max=8),
                                           retry=retry_if_exception_type(ICIMODTransient), sleep=self._retry_sleep):
            with attempt:
                return await self._request_once(method, path, params=params, json_body=json_body)

    async def _request_once(self, method: str, path: str, *, params=None, json_body=None) -> Fetched:
        url = f"{self.base_url}/{path.lstrip('/')}"
        fetched_at = datetime.now(timezone.utc)
        self.requests_made += 1
        try:
            resp = await self._client().request(method, url, params=params, json=json_body,
                                                headers={"Accept": "application/json"}, timeout=self._timeout)
        except httpx.TimeoutException as e:
            raise ICIMODTransient(f"timeout:{type(e).__name__}") from e
        except httpx.TransportError as e:
            raise ICIMODTransient(f"transport_error:{type(e).__name__}") from e
        if resp.status_code >= 500:
            logger.warning("ICIMOD server error on %s: HTTP %d (%d bytes)", path, resp.status_code, len(resp.content or b""))
            raise ICIMODTransient(f"server_error_{resp.status_code}")
        if resp.status_code >= 400:
            raise ICIMODError(f"http_{resp.status_code}")
        try:
            payload = resp.json()
        except ValueError:
            raise ICIMODError(f"invalid_json_{resp.status_code}")
        return payload, fetched_at, resp.status_code

    # ---- endpoints -------------------------------------------------------------

    async def list_districts(self) -> Fetched:
        s = self.settings
        return await self._request("GET", DISTRICTS_PATH, params={"state": s.ICIMOD_STATE, "source": s.ICIMOD_SOURCE})

    async def list_stations(self, districts: List[str]) -> Fetched:
        return await self._request("GET", STATIONS_PATH, params={"district_name": ",".join(districts)})

    async def recent_timeseries(self, station_names: List[str], *, pollutant: Optional[str] = None,
                                source: Optional[str] = None) -> Fetched:
        s = self.settings
        body = {"station": list(station_names), "pollutant": pollutant or s.ICIMOD_POLLUTANT, "source": source or s.ICIMOD_SOURCE}
        return await self._request("POST", RECENT_PATH, json_body=body)

    async def archive_trend(self, station_names: List[str], start_date: str, end_date: str, *,
                            parameter: Optional[str] = None, source: Optional[str] = None) -> Fetched:
        """Hourly history for a date window (timestamps are PKT without an offset). Verification only."""
        s = self.settings
        body = {"parameter": parameter or s.ICIMOD_POLLUTANT, "source": source or s.ICIMOD_SOURCE,
                "stations": list(station_names), "start_date": start_date, "end_date": end_date}
        return await self._request("POST", TREND_PATH, json_body=body)
