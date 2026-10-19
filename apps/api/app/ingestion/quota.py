"""
Shared provider request budget.

Cloud Run runs several ingest instances, and discovery, station ingestion, city
ingestion and every retry all spend the same IQAir credential. The old limiter
was a GET-then-SETEX minute bucket in a cache that is a no-op in production, so
nothing coordinated across processes.

PostgresQuota reserves one request with a single row-locked statement in
ops.provider_quota:

    INSERT ... ON CONFLICT DO UPDATE SET used = used + 1
    WHERE used < quota_limit RETURNING ...

Concurrent instances serialise on the (alias, window) primary-key row, so at
most quota_limit grants can succeed per window across the whole fleet. The
limit is supplied by the caller on every call, so a config change takes effect
in the next window.

If the table is missing or the database is unreachable the limiter cannot
coordinate. With required=True (the ingest role) that is a visible failure
(QuotaUnavailable → the run fails); with required=False (public read path) it
logs once and grants.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from sqlalchemy import text

logger = logging.getLogger(__name__)


class QuotaUnavailable(RuntimeError):
    """The shared quota backend cannot be used; the caller must not run unmetered."""


class QuotaExhausted(RuntimeError):
    """The budget for the current window is spent and the wait budget ran out."""

    def __init__(self, msg: str, retry_in_s: float, decision: "QuotaDecision"):
        super().__init__(msg)
        self.retry_in_s = retry_in_s
        self.decision = decision


@dataclass(frozen=True)
class QuotaDecision:
    granted: bool
    used: int
    limit: int
    window_start: datetime
    retry_in_s: float


class QuotaReservation(Protocol):
    async def reserve(self, credential_alias: str, *, limit_per_min: int, limit_per_hour: Optional[int] = None) -> QuotaDecision: ...
    async def healthcheck(self) -> None: ...
    async def reserve_or_wait(self, credential_alias: str, *, limit_per_min: int, max_wait_s: float,
                              limit_per_hour: Optional[int] = None) -> QuotaDecision: ...


class _BaseQuota:
    async def reserve_or_wait(self, credential_alias: str, *, limit_per_min: int, max_wait_s: float,
                              limit_per_hour: Optional[int] = None, sleep=asyncio.sleep) -> QuotaDecision:
        """
        Reserve, sleeping until the next window when denied, up to max_wait_s in
        total. Raises QuotaExhausted when the wait budget runs out; the provider
        client turns that into its RateLimited so the normal retry policy applies.
        """
        waited = 0.0
        while True:
            d = await self.reserve(credential_alias, limit_per_min=limit_per_min, limit_per_hour=limit_per_hour)
            if d.granted:
                return d
            delay = min(max(d.retry_in_s, 0.25), 60.0) + random.random() * 0.5
            if waited + delay > max_wait_s:
                raise QuotaExhausted(f"shared quota exhausted for {credential_alias} "
                                     f"({d.used}/{d.limit} in window starting {d.window_start.isoformat()})",
                                     retry_in_s=d.retry_in_s, decision=d)
            logger.info("Shared quota full for %s (%d/%d); waiting %.1fs", credential_alias, d.used, d.limit, delay)
            await sleep(delay)
            waited += delay


class PostgresQuota(_BaseQuota):
    RESERVE_SQL = text("""
        WITH res AS (
            INSERT INTO ops.provider_quota AS q
                (credential_alias, window_kind, window_start, used, quota_limit, updated_at)
            VALUES
                (:alias, 'minute', date_trunc('minute', now()), 1, :limit, now())
            ON CONFLICT (credential_alias, window_kind, window_start)
            DO UPDATE SET used = q.used + 1, quota_limit = EXCLUDED.quota_limit, updated_at = now()
            WHERE q.used < EXCLUDED.quota_limit
            RETURNING used, quota_limit, window_start
        )
        SELECT used, quota_limit, window_start,
               EXTRACT(EPOCH FROM (date_trunc('minute', now()) + interval '1 minute' - now())) AS until_next
        FROM res
    """)
    # When the reservation is denied (no row returned) we still need the window state for the caller.
    STATE_SQL = text("""
        SELECT used, quota_limit, window_start,
               EXTRACT(EPOCH FROM (date_trunc('minute', now()) + interval '1 minute' - now())) AS until_next
        FROM ops.provider_quota
        WHERE credential_alias = :alias AND window_kind = 'minute' AND window_start = date_trunc('minute', now())
    """)
    HEALTH_SQL = text("SELECT 1 FROM ops.provider_quota LIMIT 1")
    # Hour window (OpenAQ has a per-hour entitlement as well as per-minute). Reserved after the
    # minute slot; a denial here wastes one minute slot, which is harmless.
    RESERVE_HOUR_SQL = text("""
        WITH res AS (
            INSERT INTO ops.provider_quota AS q
                (credential_alias, window_kind, window_start, used, quota_limit, updated_at)
            VALUES
                (:alias, 'hour', date_trunc('hour', now()), 1, :limit, now())
            ON CONFLICT (credential_alias, window_kind, window_start)
            DO UPDATE SET used = q.used + 1, quota_limit = EXCLUDED.quota_limit, updated_at = now()
            WHERE q.used < EXCLUDED.quota_limit
            RETURNING used, quota_limit, window_start
        )
        SELECT used, quota_limit, window_start,
               EXTRACT(EPOCH FROM (date_trunc('hour', now()) + interval '1 hour' - now())) AS until_next
        FROM res
    """)
    STATE_HOUR_SQL = text("""
        SELECT used, quota_limit, window_start,
               EXTRACT(EPOCH FROM (date_trunc('hour', now()) + interval '1 hour' - now())) AS until_next
        FROM ops.provider_quota
        WHERE credential_alias = :alias AND window_kind = 'hour' AND window_start = date_trunc('hour', now())
    """)

    _warned = False

    def __init__(self, session_factory, *, required: bool = True):
        self._sf = session_factory
        self._required = required
        self._degraded = False

    async def healthcheck(self) -> None:
        """Raise QuotaUnavailable if the table cannot be read (missing migration, DB down)."""
        try:
            async with self._sf() as sess:
                await sess.execute(self.HEALTH_SQL)
        except Exception as exc:
            raise QuotaUnavailable(f"ops.provider_quota unavailable: {type(exc).__name__}: {exc}") from exc

    async def reserve(self, credential_alias: str, *, limit_per_min: int, limit_per_hour: Optional[int] = None) -> QuotaDecision:
        if self._degraded:
            return _granted_unmetered(limit_per_min)
        limit = max(1, int(limit_per_min))
        state = None
        hour_row = hour_state = None
        try:
            async with self._sf() as sess:
                row = (await sess.execute(self.RESERVE_SQL, {"alias": credential_alias, "limit": limit})).first()
                if row is None:
                    state = (await sess.execute(self.STATE_SQL, {"alias": credential_alias})).first()
                elif limit_per_hour:
                    hour_row = (await sess.execute(self.RESERVE_HOUR_SQL, {"alias": credential_alias, "limit": int(limit_per_hour)})).first()
                    if hour_row is None:
                        hour_state = (await sess.execute(self.STATE_HOUR_SQL, {"alias": credential_alias})).first()
                await sess.commit()
        except Exception as exc:
            if self._required:
                raise QuotaUnavailable(f"shared quota reservation failed: {type(exc).__name__}: {exc}") from exc
            if not PostgresQuota._warned:
                PostgresQuota._warned = True
                logger.warning("Shared quota unavailable (%s: %s); this process is running UNMETERED "
                               "(apply db_schema/migrations/001_ops_ingestion.sql)", type(exc).__name__, exc)
            self._degraded = True
            return _granted_unmetered(limit)

        if row is not None and limit_per_hour and hour_row is None:
            # Minute slot granted but the hour budget is spent: deny until the next hour.
            if hour_state is not None:
                return QuotaDecision(False, int(hour_state[0]), int(hour_state[1]), _aware(hour_state[2]),
                                     max(float(hour_state[3] or 0.0), 1.0))
            return QuotaDecision(False, int(limit_per_hour), int(limit_per_hour), datetime.now(timezone.utc), 60.0)
        if row is not None:
            used, qlimit, window_start, until_next = row[0], row[1], row[2], float(row[3] or 0.0)
            return QuotaDecision(True, int(used), int(qlimit), _aware(window_start), until_next)
        if state is not None:
            used, qlimit, window_start, until_next = state[0], state[1], state[2], float(state[3] or 0.0)
            return QuotaDecision(False, int(used), int(qlimit), _aware(window_start), max(until_next, 0.25))
        # Row vanished between statements (GC); treat as a denial for one short beat.
        return QuotaDecision(False, limit, limit, datetime.now(timezone.utc), 1.0)


class LocalQuota(_BaseQuota):
    """In-process minute bucket for tests and the CLI; never coordinates across processes."""

    def __init__(self, limit_per_min: Optional[int] = None):
        self._fixed_limit = limit_per_min
        self._window: Optional[int] = None
        self._used = 0

    async def healthcheck(self) -> None:
        return None

    async def reserve(self, credential_alias: str, *, limit_per_min: int, limit_per_hour: Optional[int] = None) -> QuotaDecision:
        limit = max(1, int(self._fixed_limit or limit_per_min))
        now = time.time()
        window = int(now // 60)
        if window != self._window:
            self._window, self._used = window, 0
        window_start = datetime.fromtimestamp(window * 60, tz=timezone.utc)
        until_next = (window + 1) * 60 - now
        if self._used < limit:
            self._used += 1
            return QuotaDecision(True, self._used, limit, window_start, until_next)
        return QuotaDecision(False, self._used, limit, window_start, until_next)


def _granted_unmetered(limit: int) -> QuotaDecision:
    return QuotaDecision(True, 0, limit, datetime.now(timezone.utc), 0.0)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def default_quota(*, required: bool) -> PostgresQuota:
    from app.ingestion.db import AsyncSessionLocal
    return PostgresQuota(AsyncSessionLocal, required=required)
