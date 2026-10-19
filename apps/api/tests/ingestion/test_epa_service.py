"""Punjab EPA: async, per-station isolation, provider AQI kept, no blocking sleep, real outcome."""

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.ingestion.raw_archive import NullArchiver
from app.ingestion.runs import RunStatus
from app.services.ingestion import epa_service as epa
from tests.ingestion.fakes import CapturingRecorder, FakeDatabaseService, FakeLeases, FakeSession, make_settings

BASE = "https://aqipunjab.test/api"


def _stations():
    return {"success": True, "data": [[
        {"station_code": "LHR1", "district": "Lahore", "station_name": "Lahore One", "lat": "31.5", "lon": "74.3"},
        {"station_code": "BAD1", "district": "Multan", "station_name": "Broken", "lat": None, "lon": "71.4"},
        {"station_code": "ERR1", "district": "Faisalabad", "station_name": "Server Error", "lat": "31.4", "lon": "73.0"},
    ]]}


def _24h(aqi=155):
    return {"success": True, "data": {"hourly_data": {
        "0": {"datetime": "2026-10-15T09:00:00Z", "pollutants": {"pm25": "61.2", "pm10": "100"}, "aqi": aqi,
              "main_pollutant": "pm25", "aqi_range": {"health_index": "Unhealthy", "color": "#f00"}},
        "1": {"datetime": "2026-10-15T10:00:00Z", "pollutants": {"pm25": -5, "pm10": 90}, "aqi": aqi + 1,
              "main_pollutant": "pm25", "aqi_range": {}},
        "2": {"datetime": "2099-01-01T00:00:00Z", "pollutants": {"pm25": 1}, "aqi": 1},      # future → rejected
    }}}


async def _run(tmp_path, sleep_spy):
    s = make_settings(tmp_path, PUNJAB_EPA_API_BASE=BASE, PUNJAB_EPA_API_KEY="pk-SECRET-1234567")
    rec = CapturingRecorder(tmp_path / "runs")
    dbs = FakeDatabaseService()
    client = epa.PunjabEPAClient(settings=s)
    out = await epa.collect_once(FakeSession(), settings=s, client=client, db_service=dbs, archiver=NullArchiver(),
                                 recorder=rec, leases=FakeLeases(), sleep=sleep_spy)
    return out, rec, dbs


class SleepSpy:
    def __init__(self):
        self.calls = []

    async def __call__(self, secs):
        self.calls.append(secs)


@respx.mock
async def test_one_bad_station_does_not_abort_the_batch(tmp_path, monkeypatch, caplog):
    respx.get(f"{BASE}/stations").mock(return_value=httpx.Response(200, json=_stations()))
    respx.get(f"{BASE}/historical/24hours", params={"station": "LHR1"}).mock(return_value=httpx.Response(200, json=_24h()))
    respx.get(f"{BASE}/historical/24hours", params={"station": "ERR1"}).mock(return_value=httpx.Response(500, text="boom"))
    import time
    monkeypatch.setattr(time, "sleep", lambda *_: (_ for _ in ()).throw(AssertionError("blocking sleep used")))
    spy = SleepSpy()
    out, rec, dbs = await _run(tmp_path, spy)

    assert out.status is RunStatus.partial and out.http_status() == 207
    c = out.counts
    assert (c.expected, c.attempted, c.completed, c.failed) == (3, 3, 1, 2)
    kinds = {f.entity_key: f.error_class for f in rec.failures}
    assert kinds["BAD1"] == "ValueError" and kinds["ERR1"] == "HTTPStatusError"   # not TypeError from float(None)
    assert len(spy.calls) == 3                                                   # async pacing, once per station
    assert "pk-SECRET-1234567" not in caplog.text


@respx.mock
async def test_rows_keep_provider_aqi_quarantine_and_reject(tmp_path):
    respx.get(f"{BASE}/stations").mock(return_value=httpx.Response(200, json={"success": True, "data": [[_stations()["data"][0][0]]]}))
    respx.get(f"{BASE}/historical/24hours").mock(return_value=httpx.Response(200, json=_24h()))
    out, rec, dbs = await _run(tmp_path, SleepSpy())
    assert out.status is RunStatus.success and out.counts.rows_fetched == 2 and out.counts.rows_written == 2
    assert out.details["extraction"]["rejected"] == {"ts_future": 1}
    rows = sorted(dbs.written, key=lambda r: r["ts_utc"])
    r9, r10 = rows
    assert r9["aqi_us"] == 155 and r9["pm25"] == 61.2 and r9["main_us"] == "pm25" and r9["source"] == "punjab"
    assert r9["units_pm25"] is None                                  # units not attested
    assert r9["raw"]["prov"]["aqi"] == {"source": "provider_reported", "scale": "unknown", "basis": "unknown"}
    assert r9["raw"]["prov"]["pv"] == "punjab_hourly_v2" and r9["raw"]["prov"]["run"] == out.run_id
    assert r10["pm25"] is None and r10["qc_state"] == "INVALID" and r10["raw"]["prov"]["q"] == {"pm25": -5}
    assert dbs.policies[0].source == "punjab"
    assert out.latest_observation_ts == datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


@respx.mock
async def test_inventory_failure_is_failed_run(tmp_path):
    respx.get(f"{BASE}/stations").mock(return_value=httpx.Response(503))
    out, rec, dbs = await _run(tmp_path, SleepSpy())
    assert out.status is RunStatus.failed and out.error_class == "inventory_fetch_failed"


@respx.mock
async def test_empty_inventory_is_failed_run(tmp_path):
    respx.get(f"{BASE}/stations").mock(return_value=httpx.Response(200, json={"success": True, "data": [[]]}))
    out, rec, dbs = await _run(tmp_path, SleepSpy())
    assert out.status is RunStatus.failed and out.error_class == "empty_inventory"


async def test_lease_held_is_skipped(tmp_path):
    s = make_settings(tmp_path, PUNJAB_EPA_API_BASE=BASE, PUNJAB_EPA_API_KEY="k" * 10)
    out = await epa.collect_once(FakeSession(), settings=s, client=epa.PunjabEPAClient(settings=s),
                                 db_service=FakeDatabaseService(), archiver=NullArchiver(),
                                 recorder=CapturingRecorder(tmp_path), leases=FakeLeases(deny=True))
    assert out.status is RunStatus.skipped and out.error_class == "lease_held"


def test_station_id_derivation_unchanged():
    assert epa.station_id_for_punjab("LHR1").startswith("pb_") and len(epa.station_id_for_punjab("LHR1")) == 15
