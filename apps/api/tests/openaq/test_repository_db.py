"""PostgresOpenAQRepository against a real Postgres (HAWANAMA_TEST_DATABASE_URL), else skipped."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.ingestion.raw_archive import NullArchiver
from app.services.ingestion.openaq.repository import (PostgresOpenAQRepository, StationUpsert, StreamSeed,
                                                     station_id_for_location, stream_key_for)

pytestmark = pytest.mark.skipif(not os.environ.get("HAWANAMA_TEST_DATABASE_URL"), reason="needs HAWANAMA_TEST_DATABASE_URL")
T = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
async def repo(repo_root, api_root):
    import asyncpg
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    url = os.environ["HAWANAMA_TEST_DATABASE_URL"]
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await conn.execute((api_root / "tests/ingestion/sql/test_public_schema.sql").read_text())
        for m in ("001_ops_ingestion.sql", "002_ops_provenance.sql", "003_openaq_streams.sql"):
            await conn.execute((repo_root / "db_schema/migrations" / m).read_text())
    finally:
        await conn.close()
    engine = create_async_engine(url)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield PostgresOpenAQRepository(sf), sf
    await engine.dispose()


def _st(lid, name="Loc", lat=31.5, lon=74.3, country_id=1, mode=None):
    md = {"openaq": {"location_id": lid, "name": name, "lat": lat, "lon": lon, "instruments": [{"name": "X"}]}, "origin": "external",
          "geo_resolution": {"method": "none"}}
    return StationUpsert(lid, name, lat, lon, country_id, "Asia/Karachi", "low_cost_reported_by_openaq", md,
                         [{"station_id": "abc", "reviewed": False}])


async def test_provider_and_station_upsert_are_shadow_and_idempotent(repo):
    r, sf = repo
    pid = await r.ensure_provider()
    assert pid == await r.ensure_provider()
    cid = await r.resolve_country_id("PK", "Pakistan")
    lid = int(uuid.uuid4().int % 10**8)
    sid = await r.upsert_shadow_station(_st(lid, country_id=cid), pid, "run-1")
    assert sid == station_id_for_location(lid) and len(sid) == 16
    async with sf() as s:
        row = (await s.execute(text("SELECT active, city_id, state_id, metadata_json, monitor_type FROM stations WHERE station_id=:id"),
                               {"id": sid})).first()
        prov = (await s.execute(text("SELECT metadata->>'origin' FROM providers WHERE id=:p"), {"p": pid})).scalar()
    assert row.active is False and row.city_id is None and row.state_id is None and prov == "openaq"
    assert row.metadata_json["ingest_mode"] == "shadow" and row.metadata_json["identity"]["alias_candidates"][0]["station_id"] == "abc"

    # cutover flag and reviewed aliases survive re-discovery; candidates are replaced; moves keep the id
    async with sf() as s:
        await s.execute(text("""UPDATE stations SET metadata_json = metadata_json || '{"ingest_mode": "primary"}'::jsonb
                                 || jsonb_build_object('identity', (metadata_json->'identity') || '{"aliases": [{"station_id": "zzz", "reviewed": true}]}'::jsonb)
                                WHERE station_id=:id"""), {"id": sid})
        await s.commit()
    st2 = _st(lid, name="Moved", lat=31.6, country_id=cid)
    st2.alias_candidates = []
    sid2 = await r.upsert_shadow_station(st2, pid, "run-2")
    async with sf() as s:
        md = (await s.execute(text("SELECT metadata_json FROM stations WHERE station_id=:id"), {"id": sid})).scalar()
        n = (await s.execute(text("SELECT count(*) FROM stations WHERE source_station_id=:l"), {"l": str(lid)})).scalar()
    assert sid2 == sid and n == 1
    assert md["ingest_mode"] == "primary" and md["identity"]["aliases"] == [{"station_id": "zzz", "reviewed": True}]
    assert md["identity"]["alias_candidates"] == [] and md["openaq"]["history"][-1]["to"]["name"] == "Moved"


async def test_streams_seed_list_commit_window_and_atomic_rollback(repo):
    r, sf = repo
    pid = await r.ensure_provider()
    cid = await r.resolve_country_id("PK", "Pakistan")
    lid = int(uuid.uuid4().int % 10**8)
    sid = await r.upsert_shadow_station(_st(lid, country_id=cid), pid, "run-1")
    key = stream_key_for(lid * 10, "pm25")
    await r.seed_stream(StreamSeed(key, sid, str(lid), str(lid * 10), "pm25", "µg/m³"))
    await r.seed_stream(StreamSeed(key, sid, str(lid), str(lid * 10), "pm25", "µg/m³"))   # idempotent
    streams = [s for s in await r.list_streams("active", 10000) if s.stream_key == key]
    assert len(streams) == 1 and streams[0].completed_through is None and streams[0].station_id == sid

    rows = [{"scope_type": "station", "scope_key": sid, "ts_utc": T + timedelta(hours=i), "pm25": float(i), "units_pm25": "µg/m³",
             "source": "openaq", "qc_flags": [], "raw": {"prov": {"sha": "s"}}} for i in range(3)]
    refs = [await NullArchiver().archive(provider="openaq", stream="measurements", native_id=str(lid * 10), payload={"a": 1},
                                         request_meta=None, fetched_at=T, http_status=200, run_id="run-1", parser_version="v")]
    res = await r.commit_window(streams[0], rows, refs, completed_through=T + timedelta(hours=3), run_id="run-1", page_count=1,
                                interval_observed="01:00:00")
    assert res.rows_inserted == 3
    async with sf() as s:
        cp = (await s.execute(text("SELECT completed_through, last_page_count, last_row_count, interval_observed FROM ops.stream_checkpoints WHERE stream_key=:k"), {"k": key})).first()
        n = (await s.execute(text("SELECT count(*) FROM readings WHERE scope_key=:k AND source='openaq'"), {"k": sid})).scalar()
        idx = (await s.execute(text("SELECT count(*) FROM ops.raw_payloads WHERE provider='openaq' AND native_id=:n"), {"n": str(lid * 10)})).scalar()
    assert cp.completed_through == T + timedelta(hours=3) and cp.last_page_count == 1 and cp.last_row_count == 3 and cp.interval_observed == "01:00:00"
    assert n == 3 and idx == 1

    # A bad row aborts the whole window: no new readings, checkpoint unchanged.
    bad = dict(rows[0]); bad["ts_utc"] = T + timedelta(hours=10); bad["scope_type"] = "bogus"
    with pytest.raises(Exception):
        await r.commit_window(streams[0], [bad], [], completed_through=T + timedelta(hours=20), run_id="run-2", page_count=1, interval_observed=None)
    async with sf() as s:
        cp2 = (await s.execute(text("SELECT completed_through FROM ops.stream_checkpoints WHERE stream_key=:k"), {"k": key})).scalar()
        n2 = (await s.execute(text("SELECT count(*) FROM readings WHERE scope_key=:k"), {"k": sid})).scalar()
    assert cp2 == T + timedelta(hours=3) and n2 == 3

    await r.mark_stream_failed(key, "boom", "run-2")
    await r.set_stream_status(key, "deferred_subhourly", interval_observed="00:01:00")
    assert await r.mark_unseen_streams(set(), retire_after=1) >= 1
    async with sf() as s:
        st = (await s.execute(text("SELECT status, consecutive_failures, last_error, missed_runs FROM ops.stream_checkpoints WHERE stream_key=:k"), {"k": key})).first()
    assert st.status == "deferred_subhourly" and st.consecutive_failures == 1 and st.last_error == "boom" and st.missed_runs == 1


async def test_geo_and_alias_lookups_degrade_without_postgis(repo):
    r, _ = repo
    assert (await r.resolve_geo(31.5, 74.3))["method"] == "none"
    assert await r.candidate_stations_near(31.5, 74.3, 150.0) == []
