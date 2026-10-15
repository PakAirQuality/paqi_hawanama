"""Exports: explicit membership, no OpenAQ loop, evidence-backed hardware/units, tie-safe pagination."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.ingestion import export_membership as em


# ---------------------------------------------------------------- pure

def test_cursor_round_trip_and_rejection():
    ts = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    c = em.encode_cursor(ts, "abc123          ")
    assert em.decode_cursor(c) == (ts, "abc123")
    assert em.decode_cursor(None) is None
    with pytest.raises(HTTPException):
        em.decode_cursor("not-a-cursor!!")


def test_unit_or_unknown_never_guesses():
    assert em.unit_or_unknown({"units_pm25": "µg/m³"}, "pm25") == "µg/m³"
    assert em.unit_or_unknown({"units_pm25": None}, "pm25") == "unknown"
    assert em.unit_or_unknown({}, "o3") == "unknown"


def test_membership_sql_fragments():
    assert "(s.metadata_json->'export'->>'openaq')::boolean IS TRUE" in em.MEMBERSHIP_WHERE
    assert "p.code <> 'openaq'" in em.MEMBERSHIP_WHERE and "origin" in em.MEMBERSHIP_WHERE
    assert em.READINGS_NOT_OPENAQ.strip() == "AND r.source <> 'openaq'"
    assert "ORDER BY r.ts_utc DESC, r.scope_key DESC" in em.KEYSET_ORDER


def test_routers_do_not_filter_on_display_name(api_root):
    for f in ("app/routers/openaq_network.py", "app/routers/public.py"):
        src = (api_root / f).read_text()
        assert "display_name" not in src and "IQAIR Airvisual Outdoor" not in src, f
        assert "MEMBERSHIP_WHERE" in src and "next_cursor" in src


# ---------------------------------------------------------------- real Postgres

@pytest.fixture
async def sf(api_root):
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


T = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


async def _seed(sf):
    """Four stations under a unique country; returns the ids of the two exportable ones."""
    tag = uuid.uuid4().hex[:6]
    ids = {k: f"{tag}{k}".ljust(16, "0")[:16] for k in ("A", "B", "C", "D", "E")}
    async with sf() as s:
        co = (await s.execute(text("INSERT INTO countries (name, iso2) VALUES (:n, 'PK') RETURNING id"), {"n": f"PK-{tag}"})).scalar()
        pav = (await s.execute(text("SELECT id FROM providers WHERE code='airvisual'"))).scalar() or \
              (await s.execute(text("INSERT INTO providers (code, display_name) VALUES ('airvisual','Airvisual') RETURNING id"))).scalar()
        poq = (await s.execute(text("SELECT id FROM providers WHERE code='openaq'"))).scalar() or \
              (await s.execute(text("INSERT INTO providers (code, display_name, metadata) VALUES ('openaq','OpenAQ','{\"origin\":\"openaq\"}') RETURNING id"))).scalar()

        async def st(key, provider, meta, name):
            await s.execute(text("""INSERT INTO stations (station_id, country_id, name, lat, lon, provider_id, source_station_id, metadata_json, active)
                                    VALUES (:id, :co, :name, 31.5, 74.3, :p, :sid, CAST(:m AS jsonb), true)"""),
                            {"id": ids[key], "co": co, "name": name, "p": provider, "sid": f"{tag}-{key}", "m": meta})
        await st("A", pav, '{"export": {"openaq": true}, "hardware": {"manufacturer": "IQAir", "model": "AVO", "confidence": "attested"}}', "Exported A")
        await st("E", pav, '{"export": {"openaq": true}}', "Exported E")
        await st("B", pav, '{"export": {"openaq": false}}', "Not exported")
        await st("C", pav, '{"export": {"openaq": true}, "origin": "openaq"}', "Loop C")
        await st("D", poq, '{"export": {"openaq": true}}', "OpenAQ provider D")

        async def rd(key, ts, pm25, units, source="airvisual"):
            await s.execute(text("""INSERT INTO readings (scope_type, scope_key, ts_utc, pm25, units_pm25, source)
                                    VALUES ('station', :k, :t, :v, :u, :src)"""),
                            {"k": ids[key], "t": ts, "v": pm25, "u": units, "src": source})
        await rd("A", T, 10.0, "µg/m³")
        await rd("E", T, 20.0, None)                       # same timestamp as A → tie
        await rd("A", T - timedelta(hours=1), 11.0, "µg/m³")
        await rd("A", T - timedelta(hours=2), 99.0, "µg/m³", source="openaq")   # imported row on an exported station
        await rd("B", T, 30.0, "µg/m³")
        await rd("C", T, 40.0, "µg/m³")
        await rd("D", T, 50.0, "µg/m³", source="openaq")
        await s.commit()
    return ids, tag


def _apps(sf):
    from app.core.database import get_database
    from app.routers import openaq_network, public

    async def override():
        async with sf() as s:
            yield s
    app = FastAPI()
    app.include_router(openaq_network.router, prefix="/api/v1")
    app.include_router(public.router, prefix="/api/v1")
    app.state.limiter = public.limiter
    app.dependency_overrides[get_database] = override
    app.dependency_overrides[public.verify_api_key] = lambda: "test-partner"
    return app


async def test_locations_membership_hardware_and_loop_exclusion(sf):
    ids, tag = await _seed(sf)
    async with AsyncClient(transport=ASGITransport(app=_apps(sf)), base_url="http://t") as c:
        for path in ("/api/v1/openaq/locations", "/api/v1/public/locations"):
            r = await c.get(path)
            assert r.status_code == 200
            got = {x["location_id"]: x for x in r.json()["results"] if x["location_id"].startswith(tag)}
            assert set(got) == {ids["A"], ids["E"]}, path
            assert got[ids["A"]]["hardware"] == "IQAir AVO" and got[ids["E"]]["hardware"] == "unknown"


async def test_measurements_exclude_openaq_rows_and_report_units(sf):
    ids, tag = await _seed(sf)
    async with AsyncClient(transport=ASGITransport(app=_apps(sf)), base_url="http://t") as c:
        for path in ("/api/v1/openaq/measurements", "/api/v1/public/measurements"):
            r = await c.get(path, params={"limit": 10000, "datetime_from": "2026-10-15T00:00:00Z", "datetime_to": "2026-10-16T00:00:00Z"})
            assert r.status_code == 200
            mine = [m for m in r.json()["results"] if m["location_id"].startswith(tag)]
            by = {(m["location_id"], m["datetime"]): m for m in mine}
            assert {k[0] for k in by} == {ids["A"], ids["E"]}
            assert all(m["value"] != 99.0 for m in mine)                       # source='openaq' row excluded
            assert by[(ids["A"], "2026-10-15T10:00:00Z")]["unit"] == "µg/m³"
            assert by[(ids["E"], "2026-10-15T10:00:00Z")]["unit"] == "unknown"


async def test_tied_timestamps_paginate_without_loss(sf):
    ids, tag = await _seed(sf)
    seen, cursor, pages = [], None, 0
    async with AsyncClient(transport=ASGITransport(app=_apps(sf)), base_url="http://t") as c:
        while True:
            params = {"limit": 1, "datetime_from": "2026-10-15T00:00:00Z", "datetime_to": "2026-10-16T00:00:00Z"}
            if cursor:
                params["cursor"] = cursor
            r = await c.get("/api/v1/openaq/measurements", params=params)
            assert r.status_code == 200
            body = r.json()
            seen += [(m["location_id"], m["datetime"]) for m in body["results"] if m["location_id"].startswith(tag)]
            cursor = body["meta"]["next_cursor"]
            pages += 1
            if not cursor or pages > 5000:   # shared test DB accumulates rows across runs; walk to the end
                break
    mine = [x for x in seen if x[0].startswith(tag)]
    assert sorted(mine) == sorted([(ids["A"], "2026-10-15T10:00:00Z"), (ids["E"], "2026-10-15T10:00:00Z"),
                                   (ids["A"], "2026-10-15T09:00:00Z")])
    assert len(mine) == len(set(mine))


async def test_bad_cursor_is_400(sf):
    async with AsyncClient(transport=ASGITransport(app=_apps(sf)), base_url="http://t") as c:
        r = await c.get("/api/v1/openaq/measurements", params={"cursor": "zzz"})
        assert r.status_code == 400
