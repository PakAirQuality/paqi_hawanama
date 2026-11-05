"""fire_kinematic: wind field, integration, attribution, fire matching, cache, coverage, the copilot view and the tool."""

import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

from app.services import fire_kinematic as fk
from app.services import fire_regions as fr

LAHORE = (31.5204, 74.3587)
ARRIVAL = datetime(2026, 11, 5, 6)          # 11:00 PKT
NOW = datetime(2026, 11, 5, 12)


class FakeHttp:
    """Open-Meteo stand-in: a wind field that is uniform, or rotates with time, for every requested location."""

    def __init__(self, from_deg=315.0, speed=5.0, rotate_deg_per_h=0.0, fail=False, calls_before_fail=99):
        self.from_deg, self.speed, self.rot, self.fail, self.limit = from_deg, speed, rotate_deg_per_h, fail, calls_before_fail
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        if self.fail or len(self.calls) > self.limit:
            return NS(status_code=503, json=lambda: {})
        lats = [float(x) for x in params["latitude"].split(",")]
        lons = [float(x) for x in params["longitude"].split(",")]
        d0, d1 = datetime.fromisoformat(params["start_date"]), datetime.fromisoformat(params["end_date"])
        times, t = [], d0
        while t <= d1 + timedelta(hours=23):
            times.append(t.strftime("%Y-%m-%dT%H:%M"))
            t += timedelta(hours=1)
        recs = []
        for la, lo in zip(lats, lons):
            h = {"time": times}
            for lv in fk.LEVELS:
                h[f"wind_speed_{lv}hPa"] = [self.speed] * len(times)
                h[f"wind_direction_{lv}hPa"] = [(self.from_deg + self.rot * k) % 360 for k in range(len(times))]
                h[f"geopotential_height_{lv}hPa"] = [{1000: 120, 925: 780, 850: 1500}[lv]] * len(times)
            recs.append({"latitude": la, "longitude": lo, "hourly": h})
        return NS(status_code=200, json=lambda: recs)


class FakeStore:
    def __init__(self, det):
        self._det = det

    def manifest(self):
        return {"built_at": "2026-11-05T09:00:00Z", "days": {d.isoformat(): {"sources": ["N20"], "format": "pkt_v2"} for d in
                                                              (date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5))}}

    def detections(self, start, end):
        return self._det[(self._det["pk_day"] >= start) & (self._det["pk_day"] <= end)]

    def day_from_csv(self, day):
        return None


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, path):
        store = self.objects

        class B:
            def upload_from_string(self, body, content_type=None):
                store[path] = body

            def download_as_text(self):
                if path not in store:
                    raise FileNotFoundError(path)
                return store[path]

            def download_as_bytes(self):
                return self.download_as_text().encode()

            def exists(self):
                return path in store
        return B()


@pytest.fixture(autouse=True)
def _fresh():
    fk._MEMO.clear()
    yield
    fk._MEMO.clear()


def _det(rows):
    """rows: (lat, lon, frp, acq_utc, district, country, source_class)."""
    return pd.DataFrame([{"pk_day": (a[3] + timedelta(hours=5)).date(), "acq_utc": pd.Timestamp(a[3], tz="UTC"), "lat": a[0], "lon": a[1],
                          "frp": a[2], "confidence": "h", "satellite": "N20", "daynight": "D", "country": a[5], "province": None,
                          "district": a[4], "cell_id": 0, "dup_group": i, "is_primary": True, "grp_hn": True, "source_class": a[6],
                          "class_reasons": 0, "crop_frac": 0.9} for i, a in enumerate(rows)])


def test_uniform_wind_back_trajectory_ends_upwind_at_the_right_distance():
    http = FakeHttp(from_deg=315.0, speed=5.0)
    doc = asyncio.run(fk.run(http, None, *LAHORE, ARRIVAL, now=NOW, label="Lahore"))
    assert doc["status"] == "kinematic" and doc["engine"] == fk.ENGINE and doc["direction"] == "backward" and doc["hours"] == 72
    assert len(http.calls) == 2 and all(len(c["latitude"].split(",")) <= fk.MAX_LOCATIONS for c in http.calls)
    assert http.calls[0]["models"] == "ecmwf_ifs025" and http.calls[0]["wind_speed_unit"] == "ms" and http.calls[0]["timezone"] == "UTC"
    for lv in ("1000", "925", "850"):
        path = doc["paths"][lv]
        assert path[0]["age_h"] == 0.0 and path[-1]["age_h"] == -72.0 and len(path) == 73
        end = path[-1]
        km = fr.haversine_km_vec(LAHORE[0], LAHORE[1], [end["lat"]], [end["lon"]])[0]
        brg = fr.bearing_deg(LAHORE[0], LAHORE[1], [end["lat"]], [end["lon"]])[0]
        assert abs(km - 5.0 * 72 * 3.6) / (5.0 * 72 * 3.6) < 0.03, km       # 1,296 km within 3 %
        assert 310 <= brg <= 322, brg
    assert doc["sectors"]["24"]["modal"] == "NW" and doc["sectors"]["24"]["agreement"] == 1.0 and doc["sectors"]["72"]["n"] == 3
    assert doc["residence_hours"]["925"]["Pakistan Punjab"] > 10 and sum(doc["residence_hours"]["925"].values()) == 72
    assert doc["left_domain"] == {"1000": False, "925": False, "850": False}
    assert doc["at_pkt"] == "2026-11-05 11:00 PKT" and doc["uses_forecast"] is False
    assert "10–20 %" in doc["definitions"]["error"] and any("never 'caused'" in c for c in doc["caveats"])


def test_forward_run_mirrors_backward_and_rotating_wind_curves_the_path():
    fwd = asyncio.run(fk.run(FakeHttp(315.0, 5.0), None, *LAHORE, ARRIVAL, direction="forward", now=NOW))
    end = fwd["paths"]["925"][-1]
    assert end["age_h"] == 72.0 and 128 <= fr.bearing_deg(LAHORE[0], LAHORE[1], [end["lat"]], [end["lon"]])[0] <= 140
    assert fwd["uses_forecast"] is True                                   # the run extends past 'now'
    rot = asyncio.run(fk.run(FakeHttp(315.0, 5.0, rotate_deg_per_h=2.0), None, *LAHORE, ARRIVAL, now=NOW))
    pts = rot["paths"]["925"]
    brg = [fr.bearing_deg(LAHORE[0], LAHORE[1], [p["lat"]], [p["lon"]])[0] for p in pts[6:]]
    assert max(brg) - min(brg) > 30                                       # the path bends as the wind turns


def test_fires_along_the_path_are_matched_strictly_and_loosely():
    doc0 = asyncio.run(fk.run(FakeHttp(315.0, 5.0), None, *LAHORE, ARRIVAL, now=NOW))
    p24 = next(p for p in doc0["paths"]["1000"] if p["age_h"] == -24.0)
    t24 = datetime.fromisoformat(p24["time_utc"])
    off_lat = p24["lat"] + 20 / 111.0                                     # 20 km north of the 24 h point
    det = _det([(p24["lat"], p24["lon"], 40.0, t24 + timedelta(minutes=20), "Sheikhupura", "PK", "crop"),
                (off_lat, p24["lon"], 15.0, t24, "Gujranwala", "PK", "other"),
                (p24["lat"], p24["lon"], 99.0, t24 - timedelta(hours=30), "Sheikhupura", "PK", "crop"),   # right place, wrong time
                (20.0, 70.0, 500.0, t24, "Thar", "PK", "other")])                                        # far away
    fk._MEMO.clear()
    doc = asyncio.run(fk.run(FakeHttp(315.0, 5.0), FakeStore(det), *LAHORE, ARRIVAL, now=NOW))
    f = doc["fires"]
    assert f["strict"]["n_fires"] == 3 and f["strict"]["by_level"]["1000"]["n_fires"] == 1          # the on-path fire, once per level
    assert f["strict"]["by_level"]["1000"]["first_age_h"] == 24.0 and f["strict"]["by_level"]["1000"]["districts"] == ["Sheikhupura"]
    assert f["loose"]["n_fires"] == 2 and f["loose"]["frp_mw"] == 55.0                               # on-path plus the 20 km one
    assert f["loose"]["source_classes"] == {"crop": 1, "other": 1} and f["loose"]["by_country"]["Pakistan"]["n_fires"] == 2
    assert [d["district"] for d in f["loose"]["top_districts"]] == ["Sheikhupura", "Gujranwala"]


def test_cache_memo_and_bucket_skip_the_wind_requests():
    bucket = FakeBucket()
    http = FakeHttp(315.0, 5.0)
    doc = asyncio.run(fk.run(http, None, *LAHORE, ARRIVAL, now=NOW, bucket=bucket))
    assert len(http.calls) == 2 and "cached" not in doc
    path = fk.cache_path(LAHORE[0], LAHORE[1], ARRIVAL, "backward", 72)
    assert path in bucket.objects
    again = asyncio.run(fk.run(http, None, *LAHORE, ARRIVAL, now=NOW, bucket=bucket))
    assert again["cached"] is True and len(http.calls) == 2
    fk._MEMO.clear()                                                      # memo gone: the bucket copy serves
    third = asyncio.run(fk.run(http, None, *LAHORE, ARRIVAL, now=NOW, bucket=bucket))
    assert third["cached"] is True and len(http.calls) == 2
    # a forecast-based document is refreshed after FORECAST_REFRESH_H
    fwd = asyncio.run(fk.run(http, None, *LAHORE, ARRIVAL, direction="forward", now=NOW, bucket=bucket))
    assert fwd["uses_forecast"] and len(http.calls) == 4
    later = asyncio.run(fk.run(http, None, *LAHORE, ARRIVAL, direction="forward", now=NOW + timedelta(hours=7), bucket=bucket))
    assert "cached" not in later and len(http.calls) == 6


def test_coverage_limits_and_failures():
    assert "88 days" in fk.coverage_error(NOW - timedelta(days=100), "backward", 72, NOW)
    assert fk.coverage_error(NOW - timedelta(days=80), "backward", 72, NOW) is None
    assert "15 days" in fk.coverage_error(NOW + timedelta(days=14), "forward", 72, NOW)
    old = asyncio.run(fk.run(FakeHttp(), None, *LAHORE, NOW - timedelta(days=100), now=NOW))
    assert old["status"] == "unavailable" and "HYSPLIT catalogue" in old["message"]
    with pytest.raises(RuntimeError, match="Open-Meteo winds failed"):
        asyncio.run(fk.run(FakeHttp(fail=True), None, *LAHORE, ARRIVAL, now=NOW))
    with pytest.raises(RuntimeError):                                     # the second (corridor) request fails
        asyncio.run(fk.run(FakeHttp(calls_before_fail=1), None, *LAHORE, ARRIVAL, now=NOW))


def test_wind_field_sampling_and_leaving_the_domain():
    http = FakeHttp(315.0, 5.0)
    pts = fk._grid(31.5, 74.4, 2.0, 4.0, 4.0)
    field = asyncio.run(fk.fetch_winds(http, pts, ARRIVAL - timedelta(hours=73), ARRIVAL + timedelta(hours=1)))
    u, v, z = field.sample(925, 31.5, 74.4, field.hours_since_t0(ARRIVAL))
    assert abs(u - 5.0 * np.sin(np.radians(135))) < 1e-6 and abs(v - 5.0 * np.cos(np.radians(135))) < 1e-6 and z == 780
    assert field.sample(925, 60.0, 74.4, 1.0) is None                      # outside the grid
    p = fk.integrate(field, 31.5, 74.4, 925, ARRIVAL, 72, "backward")      # the small field is left after ~a day
    assert p.attrs["left_domain"] is True and 10 < len(p) < 73


def test_copilot_view_is_compact():
    doc = asyncio.run(fk.run(FakeHttp(315.0, 5.0), None, *LAHORE, ARRIVAL, now=NOW, label="Lahore"))
    view = fk.copilot_view(doc)
    assert len(view["points_6h"]["925"]) == 13 and view["points_6h"]["925"][0]["age_h"] == 0.0
    assert set(view) >= {"engine", "status", "sectors", "residence_hours", "fires", "caveats", "definitions", "origin"}
    assert "paths" not in view and view["origin"]["label"] == "Lahore"


async def test_tool_resolves_delhi_without_the_database_and_falls_back_when_the_engine_fails(monkeypatch):
    from app.services.copilot import tools
    from app.services.copilot.context import CopilotSession
    from app.services import fire_trajectories as ft
    import httpx

    async def broken_db():
        raise RuntimeError("no database in tests")
    monkeypatch.setattr(tools, "_get_db", broken_db)
    monkeypatch.setattr(ft, "read_latest", lambda bucket=None: None)
    monkeypatch.setattr(fk, "run", lambda *a, **k: _coro({"status": fk.STATUS, "engine": fk.ENGINE, "direction": "backward", "hours": 72,
                                                          "levels_hpa": [1000, 925, 850], "origin": {"lat": 28.61, "lon": 77.21, "label": "Delhi"},
                                                          "at_utc": "2026-11-05T06:00:00", "at_pkt": "x", "uses_forecast": False, "wind_source": "w",
                                                          "left_domain": {}, "residence_hours": {}, "sectors": {}, "caveats": fk.CAVEATS,
                                                          "paths": {"925": [{"age_h": 0.0, "time_utc": "t", "lat": 28.6, "lon": 77.2, "region": "Haryana", "district": None}]},
                                                          "fires": {}, "definitions": fk.DEFINITIONS}))
    monkeypatch.setattr("app.services.fire_aggregates.agg_store", lambda: None)
    monkeypatch.setattr("app.services.fire_aggregates.default_bucket", lambda: None)
    monkeypatch.setattr(httpx, "AsyncClient", _NoClient)
    ctx = NS(deps=CopilotSession(session_id="abcdefgh", current_date="2026-11-05"))
    out = await tools.aq_trajectory(ctx, city="delhi", date="2026-11-05", hour_pkt=11)
    assert out["data"]["status"] == "kinematic" and out["data"]["place"] == "Delhi" and "open_meteo_ecmwf_ifs025" in out["basis"]["sources"]
    assert out["data"]["points_6h"]["925"][0]["region"] == "Haryana"
    # no place at all
    none = await tools.aq_trajectory(ctx)
    assert "Give a city" in none["data"]["message"]
    # the engine fails → the old corridor, with the failure named (the corridor itself needs the DB here, so it fails loudly through _safe_tool)
    async def boom(*a, **k):
        raise RuntimeError("Open-Meteo down")
    monkeypatch.setattr(fk, "run", boom)
    from app.services.copilot import agent as agent_mod
    safe = agent_mod._safe_tool(tools.aq_trajectory)
    out = await safe(ctx, city="Delhi", date="2026-11-05", hour_pkt=11)
    assert "lookup failed" in out["data"]["message"]


class _NoClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


async def _coro(v):
    return v
