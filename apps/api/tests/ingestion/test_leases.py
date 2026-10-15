"""Overlapping scheduled runs are skipped, not duplicated."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.ingestion.leases import Lease, LeaseManager, lease_key_for


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, rows, fail=None):
        self.rows, self.fail, self.calls = list(rows), fail, []

    async def execute(self, sql, params=None):
        if self.fail:
            raise self.fail
        self.calls.append((str(sql), params))
        return _Result(self.rows.pop(0) if self.rows else None)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _mgr(rows, fail=None, required=False):
    sess = _Session(rows, fail)
    return LeaseManager(lambda: sess, required=required), sess


def test_lease_key_format():
    assert lease_key_for("ingest-stations", "airvisual", "all") == "ingest-stations:airvisual:all"
    assert lease_key_for("ingest-cities", "airvisual", "") == "ingest-cities:airvisual:all"


async def test_acquire_returns_fenced_lease():
    exp = datetime.now(timezone.utc) + timedelta(seconds=3300)
    mgr, sess = _mgr([(1, exp)])
    lease = await mgr.acquire("k", "h", 3300)
    assert lease == Lease("k", "h", 1, exp)
    sql, params = sess.calls[0]
    assert "ON CONFLICT (lease_key) DO UPDATE" in sql and "WHERE ops.ingest_leases.expires_at < now()" in sql
    assert params == {"key": "k", "holder": "h", "ttl": 3300}


async def test_acquire_denied_when_live_holder_exists():
    mgr, sess = _mgr([None, ("other-holder", datetime.now(timezone.utc) + timedelta(minutes=10))])
    assert await mgr.acquire("k", "h", 3300) is None


async def test_release_and_renew_are_fenced():
    exp = datetime.now(timezone.utc)
    mgr, sess = _mgr([(7, exp), (exp,), None])
    lease = await mgr.acquire("k", "h", 10)
    assert await mgr.renew(lease, 10) is True
    await mgr.release(lease)
    assert sess.calls[1][1]["fence"] == 7 and sess.calls[2][1]["fence"] == 7
    assert "fence = :fence" in sess.calls[2][0]


async def test_missing_table_degrades_to_synthetic_lease(caplog):
    LeaseManager._warned = False
    mgr, _ = _mgr([], fail=RuntimeError('relation "ops.ingest_leases" does not exist'))
    lease = await mgr.acquire("k", "h", 10)
    assert lease is not None and lease.synthetic and lease.fence == 0
    assert "proceeding without distributed leases" in caplog.text
    await mgr.release(lease)   # no-op, must not raise


async def test_missing_table_raises_when_required():
    mgr, _ = _mgr([], fail=RuntimeError("down"), required=True)
    with pytest.raises(RuntimeError):
        await mgr.acquire("k", "h", 10)


async def test_no_session_factory_means_synthetic():
    mgr = LeaseManager(None)
    lease = await mgr.acquire("k", "h", 10)
    assert lease.synthetic


@pytest.fixture
def pg_url():
    url = os.environ.get("HAWANAMA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set HAWANAMA_TEST_DATABASE_URL to a disposable Postgres with migration 001 applied")
    return url


async def test_real_lease_second_holder_denied_then_expired_lease_stolen(pg_url):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import asyncio

    engine = create_async_engine(pg_url)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    key = f"test:{datetime.now(timezone.utc):%H%M%S%f}"
    mgr = LeaseManager(sf, required=True)
    try:
        a = await mgr.acquire(key, "a", 2)
        assert a is not None and a.fence == 1
        assert await mgr.acquire(key, "b", 2) is None
        await asyncio.sleep(2.2)
        b = await mgr.acquire(key, "b", 2)
        assert b is not None and b.fence == 2
        assert await mgr.renew(a, 2) is False          # stale fence cannot renew
        await mgr.release(a)                           # stale release is a no-op
        async with sf() as s:
            assert (await s.execute(text("SELECT holder FROM ops.ingest_leases WHERE lease_key=:k"), {"k": key})).scalar() == "b"
        await mgr.release(b)
    finally:
        async with sf() as s:
            await s.execute(text("DELETE FROM ops.ingest_leases WHERE lease_key=:k"), {"k": key})
            await s.commit()
        await engine.dispose()
