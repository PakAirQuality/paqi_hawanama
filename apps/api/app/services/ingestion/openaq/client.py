"""
OpenAQ v3 HTTP client.

  * X-API-Key header (never a query parameter); the key is registered for log redaction
  * every attempt — including retries and discovery — reserves one request against the
    shared per-credential budget (minute AND hour windows) before it is sent
  * 401/403 → OpenAQAuthError (persistent: the run stops, other adapters are unaffected)
  * 429 → OpenAQRateLimited with the reset parsed from Retry-After / x-ratelimit-reset
    (seconds-until or epoch, both handled); x-ratelimit-remaining == 0 sets a cooldown
  * 5xx / network / timeout → OpenAQTransient, retried 3 times with jittered backoff
  * paginate() stops on a short page, an empty page, an integer `found`, or the page cap,
    and raises PaginationAnomaly on a repeated page or zero progress
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.core.config import settings as _settings
from app.ingestion.http import default_timeout, get_shared_async_client, parse_retry_after, register_secret
from app.ingestion.quota import QuotaExhausted
from app.services.ingestion.openaq.models import OpenAQRateInfo

logger = logging.getLogger(__name__)


class OpenAQError(RuntimeError):
    pass


class OpenAQTransient(OpenAQError):
    pass


class OpenAQRateLimited(OpenAQTransient):
    def __init__(self, msg: str = "rate_limited", retry_after_s: Optional[float] = None):
        super().__init__(msg)
        self.retry_after_s = retry_after_s


class OpenAQAuthError(OpenAQError):
    """401/403: the credential is bad; never retried."""


class BudgetExhausted(OpenAQError):
    """The per-run request cap or the shared hour/minute budget is spent."""

    def __init__(self, msg: str, retry_in_s: Optional[float] = None):
        super().__init__(msg)
        self.retry_in_s = retry_in_s


class PaginationAnomaly(OpenAQError):
    pass


@dataclass
class PageResult:
    page: int
    payload: Dict[str, Any]
    results: List[Any]
    found: Optional[int]
    fetched_at: datetime
    http_status: int
    rate: OpenAQRateInfo


def _rate_info(headers: httpx.Headers) -> OpenAQRateInfo:
    def _int(name):
        v = headers.get(name)
        try:
            return int(v) if v is not None else None
        except ValueError:
            return None
    return OpenAQRateInfo(limit=_int("x-ratelimit-limit"), used=_int("x-ratelimit-used"),
                          remaining=_int("x-ratelimit-remaining"), reset_in_s=parse_retry_after(headers),
                          reset_raw=headers.get("x-ratelimit-reset"))


class OpenAQClient:
    def __init__(self, *, settings=None, quota=None, http: Optional[httpx.AsyncClient] = None, retry_sleep=None,
                 max_requests: Optional[int] = None):
        s = settings or _settings
        self.settings = s
        self.base_url = (s.OPENAQ_BASE_URL or "https://api.openaq.org/v3").rstrip("/")
        self.api_key = s.OPENAQ_API_KEY or ""
        if self.api_key:
            register_secret(self.api_key)
        self.alias = s.OPENAQ_CREDENTIAL_ALIAS
        self.rate_per_min = int(s.OPENAQ_RATE_PER_MIN)
        self.rate_per_hour = int(s.OPENAQ_RATE_PER_HOUR)
        self.max_requests = int(max_requests if max_requests is not None else s.OPENAQ_MAX_REQUESTS_PER_RUN)
        self._quota = quota
        self._http = http
        self._timeout = default_timeout(connect=10.0, read=float(s.OPENAQ_HTTP_TIMEOUT_S))
        self._retry_sleep = retry_sleep or asyncio.sleep
        self.requests_made = 0
        self.cooldown_until: Optional[float] = None   # monotonic seconds
        self.last_rate: Optional[OpenAQRateInfo] = None

    @property
    def quota(self):
        return self._quota

    def _client(self) -> httpx.AsyncClient:
        return self._http or get_shared_async_client()

    # ---- budget ----------------------------------------------------------------

    async def _reserve(self) -> None:
        if self.requests_made >= self.max_requests:
            raise BudgetExhausted(f"per-run request cap reached ({self.max_requests})")
        if self.cooldown_until is not None:
            wait = self.cooldown_until - time.monotonic()
            if wait > 0:
                if wait > 90:
                    raise BudgetExhausted("provider rate limit cooldown exceeds 90s", retry_in_s=wait)
                await self._retry_sleep(wait)
            self.cooldown_until = None
        if self._quota is not None:
            try:
                await self._quota.reserve_or_wait(self.alias, limit_per_min=self.rate_per_min, max_wait_s=90.0,
                                                  limit_per_hour=self.rate_per_hour)
            except QuotaExhausted as exc:
                raise BudgetExhausted(str(exc), retry_in_s=exc.retry_in_s) from exc
        self.requests_made += 1

    # ---- transport -------------------------------------------------------------

    def _wait(self, retry_state) -> float:
        base = wait_random_exponential(multiplier=1, max=8)(retry_state)
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        hinted = getattr(exc, "retry_after_s", None)
        return max(base, float(hinted)) if hinted else base

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> tuple[Dict[str, Any], OpenAQRateInfo, int, datetime]:
        async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(3), wait=self._wait,
                                           retry=retry_if_exception_type(OpenAQTransient), sleep=self._retry_sleep):
            with attempt:
                return await self._get_once(path, params)

    async def _get_once(self, path: str, params: Optional[Dict[str, Any]]):
        await self._reserve()
        url = f"{self.base_url}/{path.lstrip('/')}"
        fetched_at = datetime.now(timezone.utc)
        try:
            resp = await self._client().get(url, params=params, headers={"X-API-Key": self.api_key, "Accept": "application/json"},
                                            timeout=self._timeout)
        except httpx.TimeoutException as e:
            raise OpenAQTransient(f"timeout:{type(e).__name__}") from e
        except httpx.TransportError as e:
            raise OpenAQTransient(f"transport_error:{type(e).__name__}") from e
        rate = _rate_info(resp.headers)
        self.last_rate = rate
        if resp.status_code == 429:
            raise OpenAQRateLimited("remote_429", retry_after_s=rate.reset_in_s)
        if resp.status_code in (401, 403):
            logger.error("OpenAQ rejected the credential on %s: HTTP %d", path, resp.status_code)
            raise OpenAQAuthError(f"unauthorized_{resp.status_code}")
        if resp.status_code >= 500:
            logger.warning("OpenAQ server error on %s: HTTP %d (%d bytes)", path, resp.status_code, len(resp.content or b""))
            raise OpenAQTransient(f"server_error_{resp.status_code}")
        if resp.status_code >= 400:
            raise OpenAQError(f"http_{resp.status_code}")
        if rate.remaining is not None and rate.remaining <= 0 and rate.reset_in_s:
            self.cooldown_until = time.monotonic() + float(rate.reset_in_s)
        try:
            payload = resp.json()
        except ValueError:
            raise OpenAQError(f"invalid_json_{resp.status_code}")
        return payload, rate, resp.status_code, fetched_at

    # ---- pagination ------------------------------------------------------------

    async def paginate(self, path: str, params: Dict[str, Any], *, limit: int, max_pages: int,
                       fingerprint: Callable[[Any], str]) -> AsyncIterator[PageResult]:
        """Yield pages until a documented stop condition; raise on repeated/stuck pages."""
        seen_fp: set[str] = set()
        seen_keys: set[str] = set()
        page = 1
        while True:
            if page > max_pages:
                raise PaginationAnomaly(f"page_cap:{max_pages}")
            payload, rate, status, fetched_at = await self.get(path, {**params, "limit": limit, "page": page})
            results = payload.get("results") or [] if isinstance(payload, dict) else []
            meta = payload.get("meta") or {} if isinstance(payload, dict) else {}
            found = meta.get("found") if isinstance(meta.get("found"), int) else None
            fp = hashlib.sha256(json.dumps([fingerprint(r) for r in results], sort_keys=True).encode()).hexdigest()
            if results and fp in seen_fp:
                raise PaginationAnomaly(f"repeated_page:{page}")
            seen_fp.add(fp)
            new_keys = {fingerprint(r) for r in results}
            if results and not (new_keys - seen_keys):
                raise PaginationAnomaly(f"zero_progress:{page}")
            seen_keys |= new_keys
            yield PageResult(page=page, payload=payload, results=results, found=found, fetched_at=fetched_at,
                             http_status=status, rate=rate)
            if not results or len(results) < limit:
                return
            if found is not None and page * limit >= found:
                return
            page += 1

    # ---- endpoints -------------------------------------------------------------

    def locations_pages(self, iso: str, *, limit: int, max_pages: int) -> AsyncIterator[PageResult]:
        return self.paginate("locations", {"iso": iso, "order_by": "id", "sort_order": "asc"}, limit=limit,
                             max_pages=max_pages, fingerprint=lambda r: str(r.get("id")))

    def measurements_pages(self, sensor_id: int, dt_from: datetime, dt_to: datetime, *, limit: int,
                           max_pages: int) -> AsyncIterator[PageResult]:
        def fp(r):
            p = (r.get("period") or {})
            dt = ((p.get("datetimeTo") or {}).get("utc")) or ((p.get("datetimeFrom") or {}).get("utc")) or ""
            return f"{dt}|{r.get('value')}"
        return self.paginate(f"sensors/{int(sensor_id)}/measurements",
                             {"datetime_from": _iso(dt_from), "datetime_to": _iso(dt_to)},
                             limit=limit, max_pages=max_pages, fingerprint=fp)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
