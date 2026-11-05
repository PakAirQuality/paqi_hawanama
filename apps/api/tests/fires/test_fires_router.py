"""/api/v1/fires: status codes, cache headers, input validation, city endpoints on fakes."""

import json
from datetime import date

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import get_database
from app.routers import fires as fires_router
from app.services import fire_analytics as fa
from app.services import fire_public as fp
from tests.copilot.test_fire_analytics import FakeDB, FakeStore, _builds, _loaders, _ref_daily

TODAY = date(2026, 11, 4)


@pytest.fixture
def client(monkeypatch):
    store = FakeStore(_builds(), _ref_daily())
    monkeypatch.setattr(fires_router, "agg_store", lambda: store)
    monkeypatch.setattr(fp, "agg_store", lambda: store)
    monkeypatch.setattr(fires_router, "_pkt_today", lambda: TODAY)
    monkeypatch.setattr(fa, "_default_era5_uv", lambda lat, lon, d: (3.0, -3.0))
    monkeypatch.setattr(fa, "_default_summary", lambda d: None)
    monkeypatch.setattr(fa, "_default_driver_summary", lambda d: None)
    monkeypatch.setattr(fa, "_default_trajectory", lambda c, d: None)
    fp._TABLE = None
    fp._MEMO.clear()
    app = FastAPI()
    app.include_router(fires_router.router, prefix="/api/v1/fires")

    async def override():
        yield FakeDB()
    app.dependency_overrides[get_database] = override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_store_endpoints_cache_headers_and_sizes(client):
    async with client as c:
        for path, cc in (("/api/v1/fires/meta", fires_router.CC_META), ("/api/v1/fires/seasons?region=pakistan&season=rice", fires_router.CC_LIVE),
                         ("/api/v1/fires/districts?season=rice&region=punjab", fires_router.CC_LIVE), ("/api/v1/fires/split?season=rice", fires_router.CC_LIVE),
                         ("/api/v1/fires/persistent?region=pakistan&min_days=5", fires_router.CC_LIVE)):
            r = await c.get(path)
            assert r.status_code == 200, path
            assert r.headers["cache-control"] == cc and len(r.content) < 50_000
        r = await c.get("/api/v1/fires/seasons?region=indian-punjab")
        assert r.json()["region"]["label"] == "Indian Punjab" and r.json()["headline"]["fires"] == 3
        assert (await c.get("/api/v1/fires/seasons?season=monsoon")).status_code == 422
        r = await c.get("/api/v1/fires/seasons?region=Narnia")
        assert r.status_code == 400 and "not recognised" in r.json()["detail"]
        assert (await c.get("/api/v1/fires/persistent?min_days=2")).status_code == 422


async def test_city_endpoints(client):
    async with client as c:
        r = await c.get("/api/v1/fires/exposure?city=lahore&date=2026-11-03")
        assert r.status_code == 200 and r.headers["cache-control"] == fires_router.CC_LIVE
        body = r.json()
        assert body["status"] == "ok" and body["city"] == "Lahore" and body["wind"]["source"] == "era5" and body["rings"]["50km"]["fires"] == 2
        r = await c.get("/api/v1/fires/exposure?city=lahore&date=2026-10-20")
        assert r.status_code == 200 and r.json()["status"] == "no_file" and r.headers["cache-control"] == fires_router.CC_LIVE
        assert (await c.get("/api/v1/fires/exposure?city=atlantis")).status_code == 404
        assert (await c.get("/api/v1/fires/exposure?city=kotl")).status_code == 400
        assert (await c.get("/api/v1/fires/exposure?city=lahore&date=2031-01-01")).status_code == 400
        assert (await c.get("/api/v1/fires/exposure?city=lahore&date=yesterday")).status_code == 400


async def test_pm25_link_endpoint(client, monkeypatch):
    async def fake_link(db, city, start, end, *, store=None, today=None):
        return {"city": city, "rows": [], "days": (end - start).days + 1, "window": {"end_pkt_day": end.isoformat()}}
    monkeypatch.setattr(fa, "fire_pm25_link", fake_link)
    async with client as c:
        r = await c.get("/api/v1/fires/pm25-link?city=Lahore&end=2026-10-20&days=30")
        assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["days"] == 30
        assert r.headers["cache-control"] == fires_router.CC_ARCHIVE
        assert (await c.get("/api/v1/fires/pm25-link?city=Lahore&days=5")).status_code == 422


async def test_cities_endpoint(monkeypatch):
    from types import SimpleNamespace as NS

    class DB:
        async def execute(self, stmt, params=None):
            return NS(fetchall=lambda: [NS(id=10, name="Lahore", province="Punjab", lat=31.52, lon=74.35, stations=40)])
    app = FastAPI()
    app.include_router(fires_router.router, prefix="/api/v1/fires")

    async def override():
        yield DB()
    app.dependency_overrides[get_database] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/fires/cities")
    assert r.status_code == 200 and r.json() == {"cities": [{"id": 10, "name": "Lahore", "province": "Punjab", "lat": 31.52, "lon": 74.35, "stations": 40}], "count": 1}
    assert r.headers["cache-control"] == fires_router.CC_CITIES


async def test_outlook_endpoints(client, monkeypatch):
    doc = {"generated_at": "2026-11-04T06:00:00Z", "today_pkt": "2026-11-04", "model": "ecmwf_ifs025", "fires_as_of": {"days": ["2026-11-03", "2026-11-04"]},
           "definitions": {}, "caveats": [],
           "cities": [{"city": "Lahore", "province": "Punjab", "lat": 31.5, "lon": 74.3,
                       "leads": [{"lead": "D+0", "status": "ok", "band": "low", "upwind_load_mw": 120.0, "by_country": {}, "fires_in_cone": 1, "wind_850": {"from_compass": "NW"}},
                                 {"lead": "D+1", "status": "ok", "band": "high", "upwind_load_mw": 1500.0, "by_country": {"Pakistan": 9}, "fires_in_cone": 9, "wind_850": {"from_compass": "NW"}}]}],
           "summary": {"lead": "D+1", "alert": [{"city": "Lahore", "upwind_load_mw": 1500.0, "from_compass": "NW"}], "top": [], "cities_by_band": {"high": ["Lahore"]}, "n_cities": 1}}
    monkeypatch.setattr(fires_router.fo, "read_latest", lambda bucket=None: doc)
    monkeypatch.setattr(fires_router.fo, "outlook_status", lambda d, now=None: "ok")
    async with client as c:
        r = await c.get("/api/v1/fires/outlook")
        assert r.status_code == 200 and r.headers["cache-control"] == fires_router.CC_OUTLOOK
        body = r.json()
        assert body["status"] == "ok" and body["cities"][0]["d1"] == {"band": "high", "upwind_load_mw": 1500.0, "by_country": {"Pakistan": 9}, "fires_in_cone": 9, "from_compass": "NW"}
        r = await c.get("/api/v1/fires/outlook?city=lahore")
        assert r.status_code == 200 and r.json()["city"] == "Lahore" and len(r.json()["leads"]) == 2 and r.json()["others_at_alert_d1"] == []
        assert (await c.get("/api/v1/fires/outlook?city=atlantis")).status_code == 404
        monkeypatch.setattr(fires_router.fo, "read_latest", lambda bucket=None: None)
        fp._MEMO.clear()
        assert (await c.get("/api/v1/fires/outlook")).json()["status"] == "unavailable"
