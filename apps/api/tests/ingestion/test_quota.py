"""
Shared provider quota: one atomic reservation per request across the fleet.
Pure-Python tests run everywhere; the concurrency test needs a disposable
Postgres with migration 001 applied (HAWANAMA_TEST_DATABASE_URL), else skips.
"""

import asyncio
import os
from datetime import datetime, timezone

import pytest

from app.ingestion.quota import LocalQuota, PostgresQuota, QuotaDecision, QuotaExhausted, QuotaUnavailable


# ----------------------------------------------------------------- LocalQuota

async def test_local_quota_minute_bucket():
    q = LocalQuota()
    for i in range(5):
        d = await q.reserve("a", limit_per_min=5)
        assert d.granted and d.used == i + 1
    d = await q.reserve("a", limit_per_min=5)
    assert not d.granted and d.used == 5 and d.retry_in_s > 0


async def test_reserve_or_wait_sleeps_until_granted():
    q = LocalQuota(limit_per_min=1)
    await q.reserve("a", limit_per_min=1)       # bucket now full
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        q._window = None                         # simulate the window rolling over
    d = await q.reserve_or_wait("a", limit_per_min=1, max_wait_s=120, sleep=fake_sleep)
    assert d.granted and len(sleeps) == 1


async def test_reserve_or_wait_raises_when_budget_exhausted():
    q = LocalQuota(limit_per_min=1)
    await q.reserve("a", limit_per_min=1)
    with pytest.raises(QuotaExhausted):
        await q.reserve_or_wait("a", limit_per_min=1, max_wait_s=0.1, sleep=lambda s: asyncio.sleep(0))


# ----------------------------------------------------------------- PostgresQuota with fake session

class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, rows, fail=None):
        self.rows = list(rows)
        self.fail = fail
        self.calls = []

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


def _factory(rows, fail=None):
    sess = _Session(rows, fail)
    return (lambda: sess), sess


async def test_postgres_reserve_granted_uses_single_statement():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    sf, sess = _factory([(3, 500, now, 30.0)])
    q = PostgresQuota(sf, required=True)
    d = await q.reserve("iqair-prod", limit_per_min=500)
    assert d == QuotaDecision(True, 3, 500, now, 30.0)
    assert len(sess.calls) == 1
    sql, params = sess.calls[0]
    assert "ON CONFLICT (credential_alias, window_kind, window_start)" in sql
    assert "WHERE q.used < EXCLUDED.quota_limit" in sql and "RETURNING" in sql
    assert params == {"alias": "iqair-prod", "limit": 500}


async def test_postgres_reserve_denied_reports_window_state():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    sf, sess = _factory([None, (500, 500, now, 12.5)])     # INSERT returned nothing → read state
    q = PostgresQuota(sf, required=True)
    d = await q.reserve("iqair-prod", limit_per_min=500)
    assert not d.granted and d.used == 500 and d.retry_in_s == 12.5


class _Undefined(Exception):
    sqlstate = "42P01"


async def test_postgres_required_raises_quota_unavailable():
    sf, _ = _factory([], fail=_Undefined('relation "ops.provider_quota" does not exist'))
    q = PostgresQuota(sf, required=True)
    with pytest.raises(QuotaUnavailable):
        await q.healthcheck()
    with pytest.raises(QuotaUnavailable):
        await q.reserve("iqair-prod", limit_per_min=10)


async def test_postgres_not_required_degrades_to_unmetered_with_one_warning(caplog):
    PostgresQuota._warned = False
    sf, _ = _factory([], fail=_Undefined("missing"))
    q = PostgresQuota(sf, required=False)
    d1 = await q.reserve("iqair-prod", limit_per_min=10)
    d2 = await q.reserve("iqair-prod", limit_per_min=10)
    assert d1.granted and d2.granted
    assert caplog.text.count("running UNMETERED") == 1


# ----------------------------------------------------------------- real Postgres (optional)

@pytest.fixture
def pg_url():
    url = os.environ.get("HAWANAMA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set HAWANAMA_TEST_DATABASE_URL to a disposable Postgres with migration 001 applied")
    return url


async def test_two_engines_cannot_exceed_shared_budget(pg_url):
    """Simulates two Cloud Run instances hammering the same credential."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text

    alias = f"test-{datetime.now(timezone.utc):%H%M%S%f}"
    engines = [create_async_engine(pg_url) for _ in range(2)]
    factories = [sessionmaker(e, class_=AsyncSession, expire_on_commit=False) for e in engines]
    quotas = [PostgresQuota(f, required=True) for f in factories]
    try:
        results = await asyncio.gather(*[quotas[i % 2].reserve(alias, limit_per_min=25) for i in range(60)])
        assert sum(1 for d in results if d.granted) == 25
        async with factories[0]() as s:
            used = (await s.execute(text("SELECT used FROM ops.provider_quota WHERE credential_alias=:a"), {"a": alias})).scalar()
        assert used == 25
    finally:
        async with factories[0]() as s:
            await s.execute(text("DELETE FROM ops.provider_quota WHERE credential_alias=:a"), {"a": alias})
            await s.commit()
        for e in engines:
            await e.dispose()


# ----------------------------------------------------------------- hour window

async def test_postgres_reserve_with_hour_limit_denies_when_hour_spent():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    hour = now.replace(minute=0)
    # minute granted, hour INSERT returns nothing, hour state says spent
    sf, sess = _factory([(3, 45, now, 30.0), None, (1500, 1500, hour, 1800.0)])
    q = PostgresQuota(sf, required=True)
    d = await q.reserve("openaq-prod", limit_per_min=45, limit_per_hour=1500)
    assert not d.granted and d.used == 1500 and d.limit == 1500 and d.retry_in_s == 1800.0
    assert "window_kind, window_start" in sess.calls[1][0] and sess.calls[1][1] == {"alias": "openaq-prod", "limit": 1500}


async def test_postgres_reserve_with_hour_limit_granted():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    sf, sess = _factory([(3, 45, now, 30.0), (10, 1500, now.replace(minute=0), 1800.0)])
    d = await PostgresQuota(sf, required=True).reserve("openaq-prod", limit_per_min=45, limit_per_hour=1500)
    assert d.granted and d.used == 3 and len(sess.calls) == 2


async def test_real_hour_window(pg_url):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    engine = create_async_engine(pg_url)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    alias = f"hour-{datetime.now(timezone.utc):%H%M%S%f}"
    q = PostgresQuota(sf, required=True)
    try:
        d1 = await q.reserve(alias, limit_per_min=10, limit_per_hour=2)
        d2 = await q.reserve(alias, limit_per_min=10, limit_per_hour=2)
        d3 = await q.reserve(alias, limit_per_min=10, limit_per_hour=2)
        assert d1.granted and d2.granted and not d3.granted and d3.limit == 2
        async with sf() as s:
            kinds = (await s.execute(text("SELECT window_kind, used FROM ops.provider_quota WHERE credential_alias=:a ORDER BY 1"), {"a": alias})).fetchall()
        assert [(k, u) for k, u in kinds] == [("hour", 2), ("minute", 3)]
    finally:
        async with sf() as s:
            await s.execute(text("DELETE FROM ops.provider_quota WHERE credential_alias=:a"), {"a": alias})
            await s.commit()
        await engine.dispose()
