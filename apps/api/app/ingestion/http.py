"""
Shared HTTP plumbing for provider clients.

* one httpx.AsyncClient per event loop (connection reuse; the old client opened a
  new connection pool for every request)
* explicit timeouts
* secret redaction for logs: a LogRecord factory rewrites `key=...`-style query
  parameters and any configured credential value in every record, whichever
  handler ends up emitting it (httpx logs full request URLs at INFO)
* Retry-After / X-RateLimit-Reset parsing shared by the IQAir and OpenAQ clients
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, Mapping, Optional

import httpx

from app.ingestion.provenance import GIT_SHA

logger = logging.getLogger(__name__)

SECRET_QUERY_KEYS = ("key", "api_key", "apikey", "token", "x-api-key", "access_token")
_QUERY_RE = re.compile(r"(?i)([?&](?:%s)=)[^&\s'\"]+" % "|".join(re.escape(k) for k in SECRET_QUERY_KEYS))
_REDACTED = "***"


# ---------------------------------------------------------------- redaction

def redact_url(url) -> str:
    """Mask credential-bearing query parameters in a URL (or any string)."""
    return _QUERY_RE.sub(r"\1" + _REDACTED, str(url))


_secret_values: list[str] = []


def register_secret(value: Optional[str]) -> None:
    """Add a credential value to the redaction list (idempotent; ignores short/empty)."""
    if value and len(value) >= 8 and value not in _secret_values:
        _secret_values.append(value)


def redact_text(text: str) -> str:
    text = _QUERY_RE.sub(r"\1" + _REDACTED, text)
    for v in _secret_values:
        if v in text:
            text = text.replace(v, _REDACTED)
    return text


_configured = False
_original_factory = None


def _redacting_record_factory(*args, **kwargs):
    record = _original_factory(*args, **kwargs)
    try:
        msg = record.getMessage()
    except Exception:
        return record
    redacted = redact_text(msg)
    if redacted != msg:
        record.msg = redacted
        record.args = ()
    return record


def configure_logging(level: str = "INFO", *, secrets: Iterable[Optional[str]] = ()) -> None:
    """
    Idempotent process-wide logging setup for the API and the worker shims:
    basicConfig if nothing is configured, redaction of credentials in every
    record, and httpx/httpcore quietened so request lines (with query strings)
    are not logged at INFO.
    """
    global _configured, _original_factory
    for s in secrets:
        register_secret(s)
    if _configured:
        return
    _configured = True
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=getattr(logging, (level or "INFO").upper(), logging.INFO),
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    _original_factory = logging.getLogRecordFactory()
    logging.setLogRecordFactory(_redacting_record_factory)
    # Tracebacks (exc_info / logger.exception) are rendered by the formatter after the
    # record factory ran, so redact them there too. Patching the base class covers
    # uvicorn's and any third-party formatter.
    if not getattr(logging.Formatter, "_hawanama_redacting", False):
        _orig_format_exception = logging.Formatter.formatException

        def _redacting_format_exception(self, ei):  # type: ignore[no-untyped-def]
            return redact_text(_orig_format_exception(self, ei))

        logging.Formatter.formatException = _redacting_format_exception  # type: ignore[method-assign]
        logging.Formatter._hawanama_redacting = True  # type: ignore[attr-defined]
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ---------------------------------------------------------------- shared client

_clients: Dict[int, httpx.AsyncClient] = {}


def default_timeout(connect: float = 10.0, read: float = 30.0) -> httpx.Timeout:
    return httpx.Timeout(connect=connect, read=read, write=10.0, pool=30.0)


def get_shared_async_client() -> httpx.AsyncClient:
    """One client per running event loop. Callers pass per-request timeouts."""
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=default_timeout(),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": f"hawanama-ingest/{GIT_SHA}"},
        )
        _clients[key] = client
    return client


async def aclose_shared_clients() -> None:
    for key, client in list(_clients.items()):
        try:
            await client.aclose()
        except Exception:
            pass
        _clients.pop(key, None)


# ---------------------------------------------------------------- rate-limit headers

def parse_retry_after(headers: Mapping[str, str], now: Optional[datetime] = None) -> Optional[float]:
    """
    Seconds to wait before retrying, from Retry-After (delta-seconds or HTTP-date)
    or X-RateLimit-Reset / x-ratelimit-reset (epoch seconds, or seconds-until when
    the value is small). None when no usable header is present. Clamped to 1h.
    """
    now = now or datetime.now(timezone.utc)
    val = headers.get("retry-after") or headers.get("Retry-After")
    secs: Optional[float] = None
    if val:
        v = val.strip()
        if re.fullmatch(r"\d+(\.\d+)?", v):
            secs = float(v)
        else:
            try:
                dt = parsedate_to_datetime(v)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                secs = (dt - now).total_seconds()
            except Exception:
                secs = None
    if secs is None:
        for h in ("x-ratelimit-reset", "X-RateLimit-Reset", "ratelimit-reset", "RateLimit-Reset"):
            raw = headers.get(h)
            if raw and re.fullmatch(r"\d+(\.\d+)?", raw.strip()):
                n = float(raw)
                # Epoch seconds are > 1e9; anything smaller is treated as seconds-until.
                secs = (n - now.timestamp()) if n > 1e9 else n
                break
    if secs is None:
        return None
    return max(0.0, min(secs, 3600.0))
