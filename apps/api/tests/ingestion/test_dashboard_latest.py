"""Map/popup show the newest PM2.5-bearing hour (not a weather-only row); timestamps are RFC 3339 Z."""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def test_latest_row_prefers_pm25(api_root):
    src = (api_root / "app/routers/dashboard.py").read_text()
    assert src.count("ORDER BY scope_key, (pm25 IS NOT NULL AND ts_utc > NOW() - INTERVAL '6 hours') DESC, ts_utc DESC") == 2
    assert 'isoformat() + "Z"' not in src
    for f in ("app/routers/history.py", "app/services/analytics.py", "app/routers/public.py", "app/routers/nasa_database.py"):
        assert 'isoformat() + "Z"' not in (api_root / f).read_text(), f


def test_meta_stations_accepts_city_alias(api_root):
    src = (api_root / "app/routers/meta.py").read_text()
    assert "city_name = city_name or city" in src and "province_name = province_name or province" in src


def test_start_sh_uses_proxy_headers(api_root):
    assert "--proxy-headers" in (api_root / "start.sh").read_text()


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


def _app(sf):
    from app.core.database import get_database
    from app.routers import dashboard

    async def override():
        async with sf() as s:
            yield s
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api/v1/dashboard")
    app.dependency_overrides[get_database] = override
    return app


async def test_weather_only_newest_hour_does_not_blank_the_map(sf):
    tag = uuid.uuid4().hex[:6]
    sid = f"{tag}dash".ljust(16, "0")[:16]
    now_h = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    async with sf() as s:
        co = (await s.execute(text("INSERT INTO countries (name, iso2) VALUES (:n, 'PK') RETURNING id"), {"n": f"PK-{tag}"})).scalar()
        pav = (await s.execute(text("SELECT id FROM providers WHERE code='airvisual'"))).scalar() or \
              (await s.execute(text("INSERT INTO providers (code, display_name) VALUES ('airvisual','Airvisual') RETURNING id"))).scalar()
        await s.execute(text("""INSERT INTO stations (station_id, country_id, name, lat, lon, provider_id, source_station_id, active)
                                VALUES (:id, :co, :name, 31.5, 74.3, :p, :sid, true)"""),
                        {"id": sid, "co": co, "name": f"Dash {tag}", "p": pav, "sid": f"{tag}-sid"})
        # H: pollution + weather; H+1: weather-only (IQAir's current.weather.ts runs an hour ahead)
        await s.execute(text("INSERT INTO readings (scope_type, scope_key, ts_utc, pm25, aqi_us, temp_c, source) VALUES ('station', :k, :t, 42.5, 118, 30, 'airvisual')"),
                        {"k": sid, "t": now_h - timedelta(hours=1)})
        await s.execute(text("INSERT INTO readings (scope_type, scope_key, ts_utc, temp_c, source) VALUES ('station', :k, :t, 31, 'airvisual')"),
                        {"k": sid, "t": now_h})
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=_app(sf)), base_url="http://t") as c:
        r = await c.get("/api/v1/dashboard/stations")
        me = next(x for x in r.json()["stations"] if x["id"].strip() == sid)
        assert me["pm25"] == 42.5 and me["aqi_raw"] == 118 and me["aqi_category"] == "unhealthy_sensitive"
        assert me["last_reading"].startswith((now_h - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00")) and me["last_reading"].endswith("Z")
        r = await c.get(f"/api/v1/dashboard/stations/{sid}/current")
        body = r.json()
        assert body["main_value"] == 42.5 and body["aqi_us"] == 118 and Z_RE.match(body["last_update"])
        r = await c.get(f"/api/v1/dashboard/stations/{sid}/history", params={"hours": 48})
        rows = r.json()
        assert rows and all(Z_RE.match(x["timestamp_utc"]) and Z_RE.match(x["timestamp"]) and x["timestamp_pk"].endswith("+05:00") for x in rows)
        r = await c.get(f"/api/v1/dashboard/stations/{sid}/history/pm25", params={"hours": 48})
        assert all(Z_RE.match(x["timestamp_utc"]) for x in r.json())


async def test_aqi_only_station_with_old_pm25_row_stays_on_map(sf):
    tag = uuid.uuid4().hex[:6]
    sid = f"{tag}aqio".ljust(16, "0")[:16]
    now_h = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    async with sf() as s:
        co = (await s.execute(text("INSERT INTO countries (name, iso2) VALUES (:n, 'PK') RETURNING id"), {"n": f"PK-{tag}"})).scalar()
        pav = (await s.execute(text("SELECT id FROM providers WHERE code='airvisual'"))).scalar() or \
              (await s.execute(text("INSERT INTO providers (code, display_name) VALUES ('airvisual','Airvisual') RETURNING id"))).scalar()
        await s.execute(text("""INSERT INTO stations (station_id, country_id, name, lat, lon, provider_id, source_station_id, active)
                                VALUES (:id, :co, :name, 31.5, 74.3, :p, :sid, true)"""),
                        {"id": sid, "co": co, "name": f"AqiOnly {tag}", "p": pav, "sid": f"{tag}-sid"})
        await s.execute(text("INSERT INTO readings (scope_type, scope_key, ts_utc, pm25, aqi_us, source) VALUES ('station', :k, :t, 9.0, 38, 'airvisual')"),
                        {"k": sid, "t": now_h - timedelta(hours=40)})
        await s.execute(text("INSERT INTO readings (scope_type, scope_key, ts_utc, aqi_us, source) VALUES ('station', :k, :t, 14, 'airvisual')"),
                        {"k": sid, "t": now_h - timedelta(hours=1)})
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=_app(sf)), base_url="http://t") as c:
        r = await c.get("/api/v1/dashboard/stations")
        me = next(x for x in r.json()["stations"] if x["id"].strip() == sid)
        assert me["pm25"] is None and me["aqi_raw"] == 14 and me["aqi_category"] == "good"
        assert me["last_reading"].startswith((now_h - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00"))
