"""
Distributed leases for scheduled ingestion work.

Cloud Scheduler retries non-2xx responses and hawanama-ingest runs up to four
instances, so two copies of the same hourly job can overlap. A lease per
(task, provider, scope) in ops.ingest_leases makes the second copy a visible
`skipped` run instead of a duplicate. Acquisition is one statement:

    INSERT ... ON CONFLICT (lease_key) DO UPDATE ... WHERE expires_at < now()
    RETURNING fence

so an expired lease is stolen atomically and the fence increments; renew and
release are fenced so a stale holder cannot touch a lease it lost.

If the table is missing and the lease is not required, the manager hands out a
synthetic lease (today's single-instance semantics) after warning once.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lease:
    lease_key: str
    holder: str
    fence: int
    expires_at: datetime
    synthetic: bool = False


def lease_key_for(task: str, provider_code: str, scope: str = "all") -> str:
    return f"{task}:{provider_code}:{scope or 'all'}"


def holder_id(run_id: str) -> str:
    rev = os.getenv("K_REVISION") or socket.gethostname()
    return f"{rev}:{os.getpid()}:{run_id}"


class LeaseManager:
    ACQUIRE_SQL = text("""
        INSERT INTO ops.ingest_leases (lease_key, holder, acquired_at, expires_at, fence)
        VALUES (:key, :holder, now(), now() + make_interval(secs => :ttl), 1)
        ON CONFLICT (lease_key) DO UPDATE
            SET holder = EXCLUDED.holder,
                acquired_at = now(),
                expires_at = EXCLUDED.expires_at,
                fence = ops.ingest_leases.fence + 1
            WHERE ops.ingest_leases.expires_at < now()
        RETURNING fence, expires_at
    """)
    RENEW_SQL = text("""
        UPDATE ops.ingest_leases
           SET expires_at = now() + make_interval(secs => :ttl)
         WHERE lease_key = :key AND fence = :fence AND holder = :holder
        RETURNING expires_at
    """)
    RELEASE_SQL = text("""
        DELETE FROM ops.ingest_leases WHERE lease_key = :key AND fence = :fence AND holder = :holder
    """)
    HOLDER_SQL = text("SELECT holder, expires_at FROM ops.ingest_leases WHERE lease_key = :key")

    _warned = False

    def __init__(self, session_factory, *, required: bool = False):
        self._sf = session_factory
        self._required = required
        self._degraded = session_factory is None

    async def acquire(self, lease_key: str, holder: str, ttl_s: int) -> Optional[Lease]:
        """Return a Lease, or None when another live holder has it."""
        if self._degraded:
            return self._synthetic(lease_key, holder, ttl_s)
        try:
            async with self._sf() as sess:
                row = (await sess.execute(self.ACQUIRE_SQL, {"key": lease_key, "holder": holder, "ttl": int(ttl_s)})).first()
                other = None if row is not None else (await sess.execute(self.HOLDER_SQL, {"key": lease_key})).first()
                await sess.commit()
        except Exception as exc:
            return self._handle_error("acquire", exc, lease_key, holder, ttl_s)
        if row is None:
            logger.warning("Lease %s held by %s until %s; skipping", lease_key,
                           other[0] if other else "?", other[1] if other else "?")
            return None
        return Lease(lease_key, holder, int(row[0]), _aware(row[1]))

    async def renew(self, lease: Lease, ttl_s: int) -> bool:
        if lease.synthetic or self._degraded:
            return True
        try:
            async with self._sf() as sess:
                row = (await sess.execute(self.RENEW_SQL, {"key": lease.lease_key, "fence": lease.fence,
                                                           "holder": lease.holder, "ttl": int(ttl_s)})).first()
                await sess.commit()
            return row is not None
        except Exception as exc:
            logger.warning("Lease renew failed for %s: %s", lease.lease_key, exc)
            return False

    async def release(self, lease: Optional[Lease]) -> None:
        if lease is None or lease.synthetic or self._degraded:
            return
        try:
            async with self._sf() as sess:
                await sess.execute(self.RELEASE_SQL, {"key": lease.lease_key, "fence": lease.fence, "holder": lease.holder})
                await sess.commit()
        except Exception as exc:
            logger.warning("Lease release failed for %s (it will expire on its own): %s", lease.lease_key, exc)

    # ---- internals ----

    def _handle_error(self, what: str, exc: Exception, lease_key: str, holder: str, ttl_s: int) -> Optional[Lease]:
        if self._required:
            raise
        if not LeaseManager._warned:
            LeaseManager._warned = True
            logger.warning("ops.ingest_leases unavailable (%s: %s); proceeding without distributed leases "
                           "(apply db_schema/migrations/001_ops_ingestion.sql)", type(exc).__name__, exc)
        self._degraded = True
        return self._synthetic(lease_key, holder, ttl_s)

    @staticmethod
    def _synthetic(lease_key: str, holder: str, ttl_s: int) -> Lease:
        from datetime import timedelta
        return Lease(lease_key, holder, 0, datetime.now(timezone.utc) + timedelta(seconds=ttl_s), synthetic=True)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
