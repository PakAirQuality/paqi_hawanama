"""fire_outlook: hourly→day winds, cone and reach, bands, build/summary/alert line, the task and storage."""

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest

from app.ingestion.runs import RunStatus
from app.services import fire_outlook as fo
from tests.copilot.test_fire_analytics import A, B, C, D1, D2, D3, FakeStore, LAHORE, META, _builds, _csv, fa
from tests.ingestion.fakes import CapturingRecorder, make_settings


def _hourly(days, from_deg_by_day, speed_kmh=18.0):
    times, spd, dirs = [], [], []
    for d, deg in zip(days, from_deg_by_day):
        for h in range(24):
            times.append(f"{d.isoformat()}T{h:02d}:00"); spd.append(speed_kmh); dirs.append(deg)
    return times, spd, dirs


class FakeHttp:
    def __init__(self, from_deg_by_day, speed_kmh=18.0, fail_for=()):
        self.from_deg_by_day, self.speed_kmh, self.fail_for = from_deg_by_day, speed_kmh, fail_for
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        if any(abs(float(params["latitude"]) - la) < 1e-3 for la in self.fail_for):
            return NS(status_code=503, json=lambda: {})
        days = [D3, date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
        t, s, d = _hourly(days, self.from_deg_by_day, self.speed_kmh)
        return NS(status_code=200, json=lambda: {"hourly": {"time": t, "wind_speed_10m": s, "wind_direction_10m": d,
                                                            "wind_speed_850hPa": [x * 1.5 for x in s], "wind_direction_850hPa": d}})


@pytest.fixture(autouse=True)
def _fresh():
    fo._FORECAST_MEMO.clear()
    yield
    fo._FORECAST_MEMO.clear()


def test_aggregate_hourly_vector_mean_and_daytime():
    t, s, d = _hourly([D3], [350.0])
    d[12:16] = [10.0] * 4                      # a few hours from the other side of north
    out = fo.aggregate_hourly(t, s, d)
    w = out[D3]
    assert w.n_hours == 24 and 350 <= w.from_deg < 360 and w.speed_ms == 5.0            # 20 h at 350°, 4 h at 10° → just west of north
    assert w.day_from_deg is not None and w.day_speed_ms == 5.0
    assert fo.aggregate_hourly(["2026-11-03T00:00"], [None], [None]) == {}


def test_bands():
    assert [fo.band_for(v) for v in (0, 99, 100, 299, 300, 999, 1000, 2999, 3000, 1e6)] == \
        ["none", "none", "low", "low", "elevated", "elevated", "high", "high", "very_high", "very_high"]


async def test_city_outlook_cone_and_reach(monkeypatch):
    store = FakeStore(_builds())
    fires, info = fo.recent_fires(store, D3)
    assert set(fires["pk_day"]) == {D2, D3} and info["days"] == [D2.isoformat(), D3.isoformat()] and info["satellites"]
    http = FakeHttp([315.0, 315.0, 90.0, 90.0], speed_kmh=18.0)      # NW wind D+0/D+1, E wind D+2/D+3; 5 m/s → reach 432 km
    winds = await fo.fetch_city_forecast(http, *LAHORE)
    out = fo.city_outlook("Lahore", LAHORE[0], LAHORE[1], winds, fires, today=D3)
    d0, d1, d2 = out["leads"][0], out["leads"][1], out["leads"][2]
    assert d0["status"] == "ok" and d0["wind_850"]["from_compass"] == "NW" and d0["wind_850"]["speed_ms"] == 7.5
    assert d0["fires_in_cone"] == 2 and d0["fires_reachable"] == 2 and d0["upwind_load_mw"] == 80.0 and d0["band"] == "none"   # A on D2 (30) + A on D3 (50)
    assert d0["by_country"] == {"Pakistan": 2} and d0["top_fires"][0]["frp_mw"] == 50.0 and d0["top_fires"][0]["direction"] == "NW"
    assert d2["wind_850"]["from_compass"] == "E" and d2["fires_in_cone"] == 3 and d2["upwind_load_mw"] == 160.0 and d2["band"] == "low"   # B twice + C
    assert d2["by_country"] == {"India (Punjab+Haryana)": 3}
    # reach: with six hours of transport at the 1 m/s floor (22 km) nothing upwind is reachable, the cone FRP still counts
    slow = FakeHttp([90.0] * 4, speed_kmh=0.36)
    winds = await fo.fetch_city_forecast(slow, LAHORE[0] + 1.0, LAHORE[1])   # different point → not memoised
    monkeypatch.setattr(fo, "REACH_HOURS", 6.0)
    out = fo.city_outlook("Lahore", LAHORE[0], LAHORE[1], winds, fires, today=D3)
    d0 = out["leads"][0]
    assert d0["cone_frp_mw"] == 160.0 and d0["fires_in_cone"] == 3 and d0["fires_reachable"] == 0 and d0["upwind_load_mw"] == 0.0 and d0["reach_km"] == 22
    # no forecast for a day → status no_forecast
    out = fo.city_outlook("Lahore", LAHORE[0], LAHORE[1], {"850hPa": {}, "10m": {}}, fires, today=D3)
    assert all(l["status"] == "no_forecast" and l["band"] is None for l in out["leads"])


async def test_fetch_memo_and_retry():
    http = FakeHttp([0.0] * 4)
    await fo.fetch_city_forecast(http, 30.0, 70.0)
    await fo.fetch_city_forecast(http, 30.001, 70.001)
    assert len(http.calls) == 1                                           # memoised per rounded point
    with pytest.raises(RuntimeError):
        await fo.fetch_city_forecast(FakeHttp([0.0] * 4, fail_for=(31.0,)), 31.0, 70.0)


async def test_build_summary_alert_line_and_storage(tmp_path):
    store = FakeStore(_builds())
    cities = [{"id": 10, "name": "Lahore", "province": "Punjab", "lat": LAHORE[0], "lon": LAHORE[1]},
              {"id": 2, "name": "Nowhere", "province": "Sindh", "lat": 25.0, "lon": 67.0},
              {"id": 3, "name": "Broken", "province": "KP", "lat": 34.0, "lon": 71.0}]
    http = FakeHttp([315.0] * 4, fail_for=(34.0,))
    doc, failures = await fo.build_outlook(store, cities, http=http, today=D3, now_utc=datetime(2026, 11, 3, 12, tzinfo=timezone.utc))
    assert [f["city"] for f in failures] == ["Broken"] and [c["city"] for c in doc["cities"]] == ["Lahore", "Nowhere"]
    s = doc["summary"]
    assert s["lead"] == "D+1" and s["n_cities"] == 2 and s["top"][0]["city"] == "Lahore" and s["cities_by_band"] == {"none": ["Lahore", "Nowhere"]}
    assert s["alert"] == [] and fo.alert_line(doc) == "SMOKE OUTLOOK: no city above elevated for D+1"
    doc["summary"]["alert"] = [{"city": "Lahore", "upwind_load_mw": 2400.0, "from_compass": "NW"}]
    assert fo.alert_line(doc) == "SMOKE OUTLOOK: D+1 high/very_high: Lahore (2,400 MW from NW)"
    assert fo.outlook_status(doc, datetime(2026, 11, 3, 15, tzinfo=timezone.utc)) == "ok"
    assert fo.outlook_status(doc, datetime(2026, 11, 3, 19, tzinfo=timezone.utc)) == "stale" and fo.outlook_status(None) == "unavailable"
    assert fo.city_view(doc, "lahore")["city"] == "Lahore" and fo.city_view(doc, "Atlantis") is None

    class Bucket:
        store = {}

        def blob(self, name):
            b = self
            class Blob:
                def upload_from_string(self, data, content_type=None): b.store[name] = data
                def download_as_text(self): return b.store[name]
            return Blob()
    bucket = Bucket()
    paths = fo.write_outlook(bucket, doc, datetime(2026, 11, 3, 12, 5, tzinfo=timezone.utc))
    assert paths == [fo.LATEST_PATH, "forecasts/smoke_outlook/smoke_outlook_20261103T12.json"] and json.loads(bucket.store[fo.LATEST_PATH])["model"] == "ecmwf_ifs025"
    assert fo.read_latest(bucket)["summary"]["n_cities"] == 2


async def test_task_dry_run_and_write(tmp_path):
    class DB:
        async def execute(self, stmt, params=None):
            return NS(fetchall=lambda: [NS(id=10, name="Lahore", province="Punjab", lat=LAHORE[0], lon=LAHORE[1], stations=40)])
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class Bucket:
        def __init__(self): self.store = {}
        def blob(self, name):
            b = self
            class Blob:
                def upload_from_string(self, data, content_type=None): b.store[name] = data
            return Blob()
    bucket = Bucket()
    task = fo.SmokeOutlookTask(settings=make_settings(tmp_path), session_factory=lambda: DB(), bucket=bucket,
                               recorder=CapturingRecorder(tmp_path / "runs"), http=FakeHttp([315.0] * 4), store=FakeStore(_builds()))
    out = await task.run(dry_run=True, today=D3)
    assert out.status is RunStatus.success and out.counts.expected == 1 and out.counts.rows_written == 0 and bucket.store == {}
    assert out.details["alert_line"].startswith("SMOKE OUTLOOK") and out.details["summary"]["n_cities"] == 1
    out = await task.run(dry_run=False, today=D3)
    assert out.counts.rows_written == 1 and fo.LATEST_PATH in bucket.store and out.details["written"][0] == fo.LATEST_PATH
