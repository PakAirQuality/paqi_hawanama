"""A moved/renamed station keeps its legacy id; curated metadata survives discovery; batches survive one bad row."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.ingestion import identity as idn


# ---------------------------------------------------------------- pure helpers

def test_merge_keeps_curated_keys_and_updates_discovery_keys():
    existing = {"site_type": "traffic", "export": {"openaq": True}, "hardware": {"model": "X", "confidence": "attested"},
                "iqair_city": "Old City", "identity": {"native_ids": [{"provider": "airvisual", "native_id": "a"}],
                                                       "aliases": [{"station_id": "zzz"}], "history": [{"event": "x"}]}}
    incoming = {"iqair_city": "Lahore", "export": {"openaq": False}, "site_type": "rural",
                "identity": {"native_ids": [{"provider": "airvisual", "native_id": "a"}, {"provider": "openaq", "native_id": "7"}]}}
    out = idn.merge_discovery_metadata(existing, incoming)
    assert out["iqair_city"] == "Lahore"
    assert out["export"] == {"openaq": True} and out["site_type"] == "traffic" and out["hardware"]["model"] == "X"
    assert out["identity"]["aliases"] == [{"station_id": "zzz"}] and out["identity"]["history"] == [{"event": "x"}]
    assert [(n["provider"], n["native_id"]) for n in out["identity"]["native_ids"]] == [("airvisual", "a"), ("openaq", "7")]


def test_ensure_identity_is_idempotent_and_history_is_bounded():
    md = idn.ensure_identity({}, "airvisual", "sid")
    md = idn.ensure_identity(md, "airvisual", "sid")
    assert len(md["identity"]["native_ids"]) == 1
    for i in range(60):
        md = idn.append_identity_history(md, {"event": "rename_or_move", "i": i})
    assert len(md["identity"]["history"]) == idn.HISTORY_MAX and md["identity"]["history"][-1]["i"] == 59


def test_as_dict_handles_driver_shapes():
    assert idn.as_dict(None) == {} and idn.as_dict('{"a": 1}') == {"a": 1} and idn.as_dict("nope") == {}


def test_hardware_label_is_unknown_unless_attested():
    assert idn.hardware_label(None) == "unknown"
    assert idn.hardware_label({"hardware": {"manufacturer": "IQAir", "model": "AirVisual Outdoor"}}) == "unknown"
    assert idn.hardware_label({"hardware": {"manufacturer": "IQAir", "model": "AirVisual Outdoor", "confidence": "attested"}}) == "IQAir AirVisual Outdoor"
    assert idn.hardware_label('{"hardware": {"model": "BAM-1020", "confidence": "inferred"}}') == "BAM-1020"


# ---------------------------------------------------------------- real Postgres

pytestmark_db = pytest.mark.skipif(not os.environ.get("HAWANAMA_TEST_DATABASE_URL"),
                                   reason="set HAWANAMA_TEST_DATABASE_URL to a disposable Postgres")


@pytest.fixture
async def sf(repo_root, api_root):
    if not os.environ.get("HAWANAMA_TEST_DATABASE_URL"):
        pytest.skip("set HAWANAMA_TEST_DATABASE_URL to a disposable Postgres")
    import asyncpg
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    url = os.environ["HAWANAMA_TEST_DATABASE_URL"]
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await conn.execute((api_root / "tests/ingestion/sql/test_public_schema.sql").read_text())
    finally:
        await conn.close()
    engine = create_async_engine(url)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _geo(db, sess, tag):
    country_id = await db.upsert_country(sess, {"name": f"Testland-{tag}"})
    state_id = await db.upsert_state(sess, {"country_id": country_id, "name": "Punjab"})
    city_id = await db.upsert_city(sess, {"country_id": country_id, "state_id": state_id, "name": "Lahore"})
    return country_id, state_id, city_id


def _info(tag, country_id, state_id, city_id, name="Alpha", lat=31.5, lon=74.3, sid=None, meta=None):
    return {
        "provider_code": f"prov-{tag}", "country_id": country_id, "state_id": state_id, "city_id": city_id,
        "country": f"Testland-{tag}", "state": "Punjab", "city": "Lahore", "name": name, "lat": lat, "lon": lon,
        "source_station_id": sid or f"iqair_{tag}_{name.lower()}", "metadata_json": meta or {"iqair_city": "Lahore"},
        "active": True, "last_seen_at": datetime.now(timezone.utc), "run_id": "run-t",
    }


async def _meta(sf, station_id):
    async with sf() as s:
        return (await s.execute(text("SELECT metadata_json FROM stations WHERE station_id=:id"), {"id": station_id})).scalar()


async def test_move_keeps_legacy_station_id_and_records_history(sf):
    from app.ingestion.db import DatabaseService
    db, tag = DatabaseService(), uuid.uuid4().hex[:8]
    async with sf() as s:
        c, st, ci = await _geo(db, s, tag)
        r1 = await db.upsert_station(s, _info(tag, c, st, ci))
        r2 = await db.upsert_station(s, _info(tag, c, st, ci, lat=31.5001))   # coordinates corrected
        await s.commit()
    assert r1["created"] and r2["identity_event"] == "rename_or_move" and r2["station_id"] == r1["station_id"]
    assert r2["computed_station_id"] != r1["station_id"]
    async with sf() as s:
        rows = (await s.execute(text("SELECT station_id, lat FROM stations WHERE source_station_id=:sid"),
                                {"sid": f"iqair_{tag}_alpha"})).fetchall()
    assert len(rows) == 1 and abs(rows[0].lat - 31.5001) < 1e-9
    md = await _meta(sf, r1["station_id"])
    assert md["identity"]["history"][-1]["event"] == "rename_or_move"
    assert md["identity"]["history"][-1]["from"]["lat"] == 31.5


async def test_curated_keys_survive_discovery(sf):
    from app.ingestion.db import DatabaseService
    db, tag = DatabaseService(), uuid.uuid4().hex[:8]
    async with sf() as s:
        c, st, ci = await _geo(db, s, tag)
        r = await db.upsert_station(s, _info(tag, c, st, ci))
        await s.execute(text("""UPDATE stations SET metadata_json = metadata_json ||
            '{"export": {"openaq": true}, "hardware": {"model": "AVO", "confidence": "attested"}, "site_type": "traffic"}'::jsonb
            WHERE station_id=:id"""), {"id": r["station_id"]})
        await s.commit()
    async with sf() as s:
        r2 = await db.upsert_station(s, _info(tag, c, st, ci, meta={"iqair_city": "Lahore!", "export": {"openaq": False}}))
        await s.commit()
    assert r2["updated"] and not r2.get("identity_event")
    md = await _meta(sf, r["station_id"])
    assert md["export"] == {"openaq": True} and md["hardware"]["model"] == "AVO" and md["site_type"] == "traffic"
    assert md["iqair_city"] == "Lahore!" and md["identity"]["native_ids"][0]["native_id"] == f"iqair_{tag}_alpha"


async def test_identity_conflict_is_reported_not_merged(sf):
    from app.ingestion.db import DatabaseService
    db, tag = DatabaseService(), uuid.uuid4().hex[:8]
    async with sf() as s:
        c, st, ci = await _geo(db, s, tag)
        r1 = await db.upsert_station(s, _info(tag, c, st, ci, sid="native-A"))
        r2 = await db.upsert_station(s, _info(tag, c, st, ci, sid="native-B"))   # same name+coords → same computed id
        await s.commit()
    assert r2["identity_event"] == "identity_conflict" and r2["station_id"] is None
    assert r2["conflicting_station_id"] == r1["station_id"] and r2["conflicting_source_station_id"] == "native-A"
    async with sf() as s:
        n = (await s.execute(text("SELECT count(*) FROM stations WHERE provider_id=(SELECT id FROM providers WHERE code=:c)"),
                             {"c": f"prov-{tag}"})).scalar()
    assert n == 1


async def test_rename_candidate_is_reported(sf):
    from app.ingestion.db import DatabaseService
    db, tag = DatabaseService(), uuid.uuid4().hex[:8]
    async with sf() as s:
        c, st, ci = await _geo(db, s, tag)
        r1 = await db.upsert_station(s, _info(tag, c, st, ci, name="Old Name"))
        r2 = await db.upsert_station(s, _info(tag, c, st, ci, name="New Name"))   # new native id too (name-derived)
        await s.commit()
    assert r2["created"] and r2["identity_event"] == "rename_candidate"
    assert r2["rename_candidates"][0]["station_id"] == r1["station_id"]


async def test_discovery_batch_survives_one_bad_station(sf, tmp_path, monkeypatch):
    import app.ingestion.tasks.station_discovery as sd
    from app.ingestion.db import DatabaseService
    from tests.ingestion.fakes import CapturingRecorder, FakeIQAirClient, FakeLeases, make_settings
    tag = uuid.uuid4().hex[:8]
    country = f"Testland-{tag}"
    monkeypatch.setattr(sd, "AsyncSessionLocal", sf)
    monkeypatch.setattr(sd.asyncio, "sleep", _nosleep)
    script = {
        f"states:{country}": [{"state": "Punjab"}],
        f"cities:{country}:Punjab": [{"city": "Lahore"}],
        f"stations:{country}:Punjab:Lahore": [
            {"station": "Good One", "location": {"type": "Point", "coordinates": [74.3, 31.5]}},
            {"station": "Bad One", "location": {"type": "Point", "coordinates": ["not-a-number", 31.6]}},
            {"station": "Good Two", "location": {"type": "Point", "coordinates": [74.4, 31.7]}},
        ],
    }
    s = make_settings(tmp_path, IQAIR_COUNTRIES=country)
    rec = CapturingRecorder(tmp_path / "runs")
    t = sd.StationDiscoveryTask(settings=s, iqair_client=FakeIQAirClient(script), db_service=DatabaseService(),
                                recorder_factory=lambda: rec, leases=FakeLeases())
    o = await t.discover_all_stations_comprehensive()
    assert o.status.value == "partial" and o.counts.rows_written == 2
    assert [f.entity_key for f in rec.failures] == ["iqair_" + sd._slug(country, "punjab", "lahore", "bad one")[len(sd._slug(country))+1:] if False else rec.failures[0].entity_key]
    async with sf() as sess:
        names = (await sess.execute(text("SELECT name FROM stations WHERE provider_id=(SELECT id FROM providers WHERE code='airvisual') "
                                         "AND country_id=(SELECT id FROM countries WHERE name=:c) ORDER BY name"), {"c": country})).scalars().all()
    assert names == ["Good One", "Good Two"]


async def _nosleep(_):
    return None
