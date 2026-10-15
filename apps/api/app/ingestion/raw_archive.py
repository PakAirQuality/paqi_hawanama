"""
Immutable raw-payload archive.

Until now nothing kept the provider's original response: the station extractor
set raw=None and deleted it before writing, so a timestamp shift or parser bug
could never be audited against what the provider actually said. Every fetched
payload is now:

  * redacted (API keys, tokens, auth headers, `?key=` in URLs),
  * hashed (sha256 over the canonical JSON of the payload),
  * gzip-uploaded to GCS under raw_payloads/<provider>/<stream>/<native>/<Y>/<M>/<D>/,
  * indexed in ops.raw_payloads (migration 002) with request window, fetch time,
    parser version, run id, HTTP status and size.

Normalized rows carry a small {"prov": {"sha": ...}} in readings.raw that points
back here. Archival is best-effort: a GCS or DB failure is counted on the run
and the readings are still written.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.ingestion.http import redact_text

logger = logging.getLogger(__name__)

REDACT_KEYS = {"key", "api_key", "apikey", "api-key", "x-api-key", "token", "access_token", "authorization",
               "secret", "password", "x-api-token"}
_REDACTED = "***"
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def redact(obj: Any) -> Any:
    """Recursively mask credential-bearing dict keys and query parameters in strings."""
    if isinstance(obj, dict):
        return {k: (_REDACTED if str(k).lower() in REDACT_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_sha256(payload: Any) -> str:
    """Stable across key order; identical payloads fetched twice hash the same."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def slug(value: Any, max_len: int = 80) -> str:
    s = _SLUG_RE.sub("_", str(value)).strip("_") or "unknown"
    return s[:max_len]


def build_object_key(prefix: str, provider: str, stream: str, native_id: Any, fetched_at: datetime, sha256: str) -> str:
    fa = fetched_at.astimezone(timezone.utc)
    return (f"{prefix.strip('/')}/{slug(provider)}/{slug(stream)}/{slug(native_id)}/"
            f"{fa:%Y/%m/%d}/{fa:%Y%m%dT%H%M%SZ}_{sha256[:16]}.json.gz")


@dataclass(frozen=True)
class RawPayloadRef:
    sha256: str
    fetched_at: datetime
    parser_version: str
    provider: str
    stream: str
    native_id: str
    size_bytes: int
    archived: bool
    gcs_uri: Optional[str] = None
    error: Optional[str] = None
    http_status: Optional[int] = None
    request_window_from: Optional[datetime] = None
    request_window_to: Optional[datetime] = None
    request_meta: Optional[Dict[str, Any]] = None
    run_id: Optional[str] = None

    def prov(self) -> Dict[str, Any]:
        """The compact provenance stub that goes into readings.raw.prov."""
        return {"sha": self.sha256, "pv": self.parser_version,
                "fa": self.fetched_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "archived": self.archived}


class RawPayloadArchiver:
    """
    settings: needs OPS_RAW_PAYLOADS_BUCKET (falls back to MANIFEST_GCS_BUCKET),
    OPS_RAW_PAYLOADS_PREFIX and RAW_ARCHIVE_ENABLED.
    gcs_client_factory: callable returning a google.cloud.storage.Client (tests inject a fake).
    """

    def __init__(self, settings, *, gcs_client_factory=None, enabled: Optional[bool] = None):
        self._bucket_name = (settings.OPS_RAW_PAYLOADS_BUCKET or settings.MANIFEST_GCS_BUCKET or "").strip()
        self._prefix = (settings.OPS_RAW_PAYLOADS_PREFIX or "raw_payloads").strip("/")
        self._enabled = bool(settings.RAW_ARCHIVE_ENABLED) if enabled is None else enabled
        self._client_factory = gcs_client_factory or _default_gcs_client
        self._client = None
        self.failures = 0
        self.archived = 0

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._bucket_name)

    async def archive(self, *, provider: str, stream: str, native_id: Any, payload: Any,
                      request_meta: Optional[Dict[str, Any]], fetched_at: datetime, http_status: Optional[int],
                      run_id: Optional[str], parser_version: str,
                      window_from: Optional[datetime] = None, window_to: Optional[datetime] = None) -> RawPayloadRef:
        """Never raises. Returns a ref with archived=False and error set when the upload failed."""
        redacted_payload = redact(payload)
        redacted_meta = redact(request_meta or {})
        sha = canonical_sha256(redacted_payload)
        body = {
            "provider": provider, "stream": stream, "native_id": str(native_id),
            "fetched_at": fetched_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "http_status": http_status, "parser_version": parser_version, "run_id": run_id,
            "request": redacted_meta, "payload_sha256": sha, "payload": redacted_payload,
        }
        raw_bytes = canonical_json(body).encode("utf-8")
        size = len(raw_bytes)
        base = dict(sha256=sha, fetched_at=fetched_at, parser_version=parser_version, provider=provider,
                    stream=stream, native_id=str(native_id), size_bytes=size, http_status=http_status,
                    request_window_from=window_from, request_window_to=window_to, request_meta=redacted_meta,
                    run_id=run_id)
        if not self.enabled:
            return RawPayloadRef(archived=False, error=None if not self._enabled else "no_bucket_configured", **base)

        key = build_object_key(self._prefix, provider, stream, native_id, fetched_at, sha)
        uri = f"gs://{self._bucket_name}/{key}"
        try:
            await asyncio.to_thread(self._upload, key, gzip.compress(raw_bytes))
            self.archived += 1
            return RawPayloadRef(archived=True, gcs_uri=uri, **base)
        except Exception as exc:
            self.failures += 1
            logger.warning("Raw payload archive failed for %s/%s/%s: %s: %s", provider, stream, native_id,
                           type(exc).__name__, exc)
            return RawPayloadRef(archived=False, gcs_uri=None, error=f"{type(exc).__name__}: {str(exc)[:200]}", **base)

    def _upload(self, key: str, data: bytes) -> None:
        if self._client is None:
            self._client = self._client_factory()
        blob = self._client.bucket(self._bucket_name).blob(key)
        blob.content_encoding = "gzip"
        blob.upload_from_string(data, content_type="application/json")

    RECORD_SQL = text("""
        INSERT INTO ops.raw_payloads
            (provider, stream, native_id, request_window_from, request_window_to, fetched_at, sha256,
             gcs_uri, archived, archive_error, parser_version, run_id, http_status, size_bytes, request_meta)
        VALUES
            (:provider, :stream, :native_id, :window_from, :window_to, :fetched_at, :sha256,
             :gcs_uri, :archived, :archive_error, :parser_version, :run_id, :http_status, :size_bytes,
             CAST(:request_meta AS jsonb))
    """)

    _warned_missing = False

    async def record(self, session_factory, ref: RawPayloadRef) -> bool:
        """Index the payload in ops.raw_payloads in its own short transaction. Never raises."""
        if session_factory is None:
            return False
        params = {
            "provider": ref.provider, "stream": ref.stream, "native_id": ref.native_id,
            "window_from": ref.request_window_from, "window_to": ref.request_window_to,
            "fetched_at": ref.fetched_at, "sha256": ref.sha256, "gcs_uri": ref.gcs_uri, "archived": ref.archived,
            "archive_error": ref.error, "parser_version": ref.parser_version, "run_id": ref.run_id,
            "http_status": ref.http_status, "size_bytes": ref.size_bytes,
            "request_meta": json.dumps(ref.request_meta or {}, default=str),
        }
        try:
            async with session_factory() as sess:
                await sess.execute(self.RECORD_SQL, params)
                await sess.commit()
            return True
        except Exception as exc:
            if not RawPayloadArchiver._warned_missing:
                RawPayloadArchiver._warned_missing = True
                logger.warning("ops.raw_payloads write failed (apply migration 002?): %s: %s", type(exc).__name__, exc)
            return False


async def record_in_session(session, ref: RawPayloadRef) -> None:
    """Index a payload inside the caller's transaction (used by the OpenAQ window commit)."""
    await session.execute(RawPayloadArchiver.RECORD_SQL, {
        "provider": ref.provider, "stream": ref.stream, "native_id": ref.native_id,
        "window_from": ref.request_window_from, "window_to": ref.request_window_to,
        "fetched_at": ref.fetched_at, "sha256": ref.sha256, "gcs_uri": ref.gcs_uri, "archived": ref.archived,
        "archive_error": ref.error, "parser_version": ref.parser_version, "run_id": ref.run_id,
        "http_status": ref.http_status, "size_bytes": ref.size_bytes,
        "request_meta": json.dumps(ref.request_meta or {}, default=str),
    })


class NullArchiver(RawPayloadArchiver):
    """Computes hashes/refs but never uploads or records (tests, dry runs)."""

    def __init__(self, settings=None):
        self._bucket_name = ""
        self._prefix = "raw_payloads"
        self._enabled = False
        self._client_factory = None
        self._client = None
        self.failures = 0
        self.archived = 0

    async def record(self, session_factory, ref: RawPayloadRef) -> bool:
        return False


def _default_gcs_client():
    from google.cloud import storage  # type: ignore
    return storage.Client()
