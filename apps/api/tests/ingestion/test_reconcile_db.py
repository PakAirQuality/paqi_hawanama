"""
Reconcile semantics against a real Postgres. Needs HAWANAMA_TEST_DATABASE_URL
(postgresql+asyncpg://...) pointing at a disposable database; the test applies
tests/ingestion/sql/test_public_schema.sql and migrations 001/002 itself.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.ingestion.reconcile import ReconcilePolicy, reconcile_and_upsert_readings

pytestmark = pytest.mark.skipif(not os.environ.get("HAWANAMA_TEST_DATABASE_URL"),
                                reason="set HAWANAMA_TEST_DATABASE_URL to a disposable Postgres")

T10 = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
SHA_NEW = "f" * 64   # payload_sha256 is char(64)


@pytest.fixture
async def sf(repo_root, api_root):
    """Function-scoped: pytest-asyncio 0.21 runs each test in its own loop."""
    import asyncpg
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    url = os.environ["HAWANAMA_TEST_DATABASE_URL"]
    raw = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(raw)
    try:
        await conn.execute((api_root / "tests/ingestion/sql/test_public_schema.sql").read_text())
        for m in ("001_ops_ingestion.sql", "002_ops_provenance.sql"):
            await conn.execute((repo_root / "db_schema/migrations" / m).read_text())
    finally:
        await conn.close()
    engine = create_async_engine(url)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _key():
    return f"t{uuid.uuid4().hex[:15]}"


def _row(key, ts=T10, **kw):
    base = {"scope_type": "station", "scope_key": key, "ts_utc": ts, "source": "airvisual",
            "raw": {"prov": {"sha": "sha-" + uuid.uuid4().hex[:6]}}}
    base.update(kw)
    return base


async def _fetch(sf, key, ts=T10):
    async with sf() as s:
        r = (await s.execute(text("SELECT * FROM readings WHERE scope_type='station' AND scope_key=:k AND ts_utc=:t"),
                             {"k": key, "t": ts})).mappings().first()
        return dict(r) if r else None


async def _write(sf, rows, run_id="run-t"):
    async with sf() as s:
        res = await reconcile_and_upsert_readings(s, rows, ReconcilePolicy(source="airvisual", run_id=run_id))
        await s.commit()
        return res


async def test_weather_only_hour_then_pm25_fills_gap(sf):
    k = _key()
    r1 = await _write(sf, [_row(k, temp_c=30.0)])
    assert (r1.rows_inserted, r1.rows_updated, r1.rows_unchanged) == (1, 0, 0)
    r2 = await _write(sf, [_row(k, pm25=12.5)])
    assert (r2.rows_inserted, r2.rows_updated) == (0, 1) and r2.revisions_recorded == 0
    row = await _fetch(sf, k)
    assert row["pm25"] == 12.5 and row["temp_c"] == 30.0 and row["qc_state"] == "raw"


async def test_sparse_payload_cannot_erase_values(sf):
    k = _key()
    await _write(sf, [_row(k, pm25=12.5, temp_c=30.0, humidity=40.0)])
    res = await _write(sf, [_row(k, pm25=None, temp_c=None, humidity=41.0)])
    row = await _fetch(sf, k)
    assert row["pm25"] == 12.5 and row["temp_c"] == 30.0 and row["humidity"] == 41.0
    assert res.rows_updated == 1 and res.revisions_recorded == 1


async def test_exact_replay_is_a_noop(sf):
    k = _key()
    rows = [_row(k, pm25=12.5, temp_c=30.0, qc_state="raw", qc_flags=[])]
    await _write(sf, rows)
    before = await _fetch(sf, k)
    res = await _write(sf, [dict(rows[0])])
    after = await _fetch(sf, k)
    assert (res.rows_inserted, res.rows_updated, res.rows_unchanged) == (0, 0, 1)
    assert after["ingested_at"] == before["ingested_at"] and after["raw"] == before["raw"]


async def test_revised_value_updates_and_is_recorded(sf):
    k = _key()
    await _write(sf, [_row(k, pm25=11.0)])
    res = await _write(sf, [_row(k, pm25=12.0, raw={"prov": {"sha": SHA_NEW}})], run_id="run-2")
    assert res.rows_updated == 1 and res.revisions_recorded == 1 and not res.revisions_failed
    async with sf() as s:
        rev = (await s.execute(text("SELECT field, old_value, new_value, reason, run_id, payload_sha256 "
                                    "FROM ops.reading_revisions WHERE scope_key=:k"), {"k": k})).mappings().all()
    assert [(r["field"], r["old_value"], r["new_value"], r["reason"], r["run_id"], r["payload_sha256"]) for r in rev] == \
        [("pm25", 11.0, 12.0, "revised", "run-2", SHA_NEW)]
    assert (await _fetch(sf, k))["raw"]["prov"]["sha"] == SHA_NEW


async def test_explicit_withdrawal_nulls_field(sf):
    k = _key()
    await _write(sf, [_row(k, pm25=11.0, temp_c=30.0)])
    res = await _write(sf, [_row(k, _withdraw={"pm25"})])
    row = await _fetch(sf, k)
    assert row["pm25"] is None and row["units_pm25"] is None and row["temp_c"] == 30.0
    assert res.rows_withdrawn_fields == 1 and res.revisions_recorded == 1
    assert row["raw"]["withdrawn"]["fields"] == ["pm25"]


async def test_curated_state_is_not_downgraded_and_invalid_heals(sf):
    k = _key()
    await _write(sf, [_row(k, pm25=11.0, qc_state="OK", qc_flags=["high_rh"])])
    async with sf() as s:   # emulate a curated state set by BAM QC
        await s.execute(text("UPDATE readings SET qc_state='OK' WHERE scope_key=:k"), {"k": k})
        await s.commit()
    await _write(sf, [_row(k, pm25=12.0)])
    assert (await _fetch(sf, k))["qc_state"] == "OK"

    k2 = _key()
    await _write(sf, [_row(k2, pm25=None, qc_state="INVALID", qc_flags=["v:pm25:negative"], _present=set())])
    assert (await _fetch(sf, k2))["qc_state"] == "INVALID"
    await _write(sf, [_row(k2, pm25=9.0, qc_state="raw", qc_flags=[], _present={"pm25"})])
    row = await _fetch(sf, k2)
    assert row["qc_state"] == "raw" and row["qc_flags"] is None and row["pm25"] == 9.0


async def test_batching_and_city_scope(sf):
    k = _key()
    rows = [_row(k, ts=T10 + timedelta(hours=i), pm25=float(i)) for i in range(1200)]
    rows.append(_row(k, scope_type="city", pm25=1.0))
    res = await _write(sf, rows)
    assert res.rows_inserted == 1201 and res.rows_unchanged == 0
    assert (await _write(sf, rows)).rows_unchanged == 1201
