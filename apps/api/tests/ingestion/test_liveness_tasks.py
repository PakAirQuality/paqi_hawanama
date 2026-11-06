"""
Liveness end to end: the hourly station job skips inactive rows and polls dormant
rows once a day; discovery reports unresolvable states without going partial,
hands the listed names to the identity rules and mirrors inactivity into the DB.
"""

import json
from pathlib import Path

from app.ingestion.runs import RunStatus
from app.ingestion.tasks.data_ingestion import DataIngestionTask
from app.ingestion.tasks.station_discovery import StationDiscoveryTask
from app.ingestion.raw_archive import NullArchiver
from app.services.ingestion.iqair_service import StationNotFound

from tests.ingestion.fakes import (CapturingRecorder, FakeDatabaseService, FakeIQAirClient, FakeLeases, FakeSessionFactory,
                                   iqair_payload, make_settings, station_row, write_station_manifest)


# ---------------------------------------------------------------- hourly station job

def _station_task(tmp_path, script, rows, **overrides):
    s = make_settings(tmp_path, **overrides)
    write_station_manifest(s, rows)
    rec = CapturingRecorder(Path(s.INGEST_OUT_DIR))
    t = DataIngestionTask(settings=s, iqair_client=FakeIQAirClient(script), db_service=FakeDatabaseService(),
                          recorder_factory=lambda: rec, leases=FakeLeases(), archiver=NullArchiver())
    return t, rec


async def test_inactive_rows_are_never_polled(tmp_path):
    rows = [station_row(0), station_row(1, active=False), station_row(2, active="false")]
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, rows)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.success and o.counts.expected == 1
    assert [c["station"] for c in t.iqair_client.calls] == ["Station 0"]
    assert o.details["liveness"]["inactive_skipped"] == 2


async def test_dormant_rows_polled_only_in_the_00_utc_run(tmp_path, monkeypatch):
    rows = [station_row(0), station_row(1, dormant=True)]
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, rows)
    monkeypatch.setattr(DataIngestionTask, "_poll_dormant_now", staticmethod(lambda now=None: False))
    o = await t.fetch_station_readings()
    assert o.counts.expected == 1 and o.details["liveness"] == {"inactive_skipped": 0, "dormant_skipped": 1, "dormant_polled": False}
    monkeypatch.setattr(DataIngestionTask, "_poll_dormant_now", staticmethod(lambda now=None: True))
    o = await t.fetch_station_readings()
    assert o.counts.expected == 2 and o.details["liveness"]["dormant_polled"] is True


def test_poll_dormant_now_is_the_midnight_hour():
    from datetime import datetime, timezone
    assert DataIngestionTask._poll_dormant_now(datetime(2026, 11, 6, 0, 15, tzinfo=timezone.utc)) is True
    assert DataIngestionTask._poll_dormant_now(datetime(2026, 11, 6, 13, 15, tzinfo=timezone.utc)) is False


async def test_failures_are_summarised_by_country(tmp_path):
    rows = [station_row(0), station_row(1, country="India", iqair_station_name="Peenya", source_station_id="iqair_india_x"),
            station_row(2, country="India", iqair_station_name="Jadavpur", source_station_id="iqair_india_y")]
    script = {"Station 0": iqair_payload(), "Peenya": StationNotFound("station_not_found"), "Jadavpur": StationNotFound("station_not_found")}
    t, rec = _station_task(tmp_path, script, rows, IQAIR_COUNTRIES="Pakistan,India")
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.partial
    assert o.details["failures_by_country"] == {"India": {"StationNotFound": 2}}


# ---------------------------------------------------------------- discovery

def _discovery(tmp_path, script, monkeypatch, countries="Pakistan", **overrides):
    import app.ingestion.tasks.station_discovery as sd
    s = make_settings(tmp_path, IQAIR_COUNTRIES=countries, **overrides)
    rec = CapturingRecorder(Path(s.INGEST_OUT_DIR))
    sf = FakeSessionFactory()
    monkeypatch.setattr(sd, "AsyncSessionLocal", sf)

    async def _nosleep(_):
        return None
    monkeypatch.setattr(sd.asyncio, "sleep", _nosleep)
    t = StationDiscoveryTask(settings=s, iqair_client=FakeIQAirClient(script), db_service=FakeDatabaseService(),
                             recorder_factory=lambda: rec, leases=FakeLeases())
    return t, rec


def _st(name, lon=74.3, lat=31.5):
    return {"station": name, "location": {"type": "Point", "coordinates": [lon, lat]}}


def _latest(t):
    p = Path(t.settings.STATION_MANIFEST_DIR) / "latest.jsonl"
    return {r["source_station_id"]: r for r in (json.loads(l) for l in p.read_text().splitlines() if l.strip())}


async def test_unresolvable_state_does_not_make_discovery_partial(tmp_path, monkeypatch):
    from app.services.ingestion.iqair_service import BadRequest
    script = {
        "states:Pakistan": [{"state": "Punjab"}, {"state": "FATA"}],
        "cities:Pakistan:Punjab": [{"city": "Lahore"}],
        "stations:Pakistan:Punjab:Lahore": [_st("A")],
        "cities:Pakistan:FATA": BadRequest("state_not_found"),
    }
    t, rec = _discovery(tmp_path, script, monkeypatch)
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.success
    assert o.details["states_unsupported"] == [{"state": "FATA", "country": "Pakistan", "reason": "provider_state_not_found"}]
    assert o.details["states_skipped"] == [] and rec.failures == []
    assert any(c["kind"] == "cities" and c["state"] == "FATA" for c in t.iqair_client.calls)   # still probed once


async def test_unknown_state_failure_is_still_a_skip(tmp_path, monkeypatch):
    from app.services.ingestion.iqair_service import IQAirError
    script = {
        "states:Pakistan": [{"state": "Punjab"}, {"state": "Gilgit-Baltistan"}],
        "cities:Pakistan:Punjab": [{"city": "Lahore"}],
        "stations:Pakistan:Punjab:Lahore": [_st("A")],
        "cities:Pakistan:Gilgit-Baltistan": IQAirError("server_error_503"),
    }
    t, rec = _discovery(tmp_path, script, monkeypatch)
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.partial and o.details["states_skipped"][0]["state"] == "Gilgit-Baltistan"


async def test_discovery_passes_listed_names_and_liveness_evidence(tmp_path, monkeypatch):
    script = {
        "states:Pakistan": [{"state": "Punjab"}],
        "cities:Pakistan:Punjab": [{"city": "Lahore"}, {"city": "Kasur"}],
        "stations:Pakistan:Punjab:Lahore": [_st("A"), _st("B", lon=74.31)],
        "stations:Pakistan:Punjab:Kasur": [],
    }
    t, rec = _discovery(tmp_path, script, monkeypatch, MANIFEST_DORMANT_AFTER_MISSES=1, MANIFEST_INACTIVE_AFTER_MISSES=2)
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.success
    assert all(info["listed_names"] == ["A", "B"] for info in t.db_service.stations)
    assert o.details["manifest_total"] == 2 and o.details["manifest_inactive"] == 0 and o.details["stations_deactivated"] == 0

    # Next run: IQAir lists Lahore without B → B dormant after 1 miss, inactive after 2, mirrored into the DB.
    t.iqair_client.script["stations:Pakistan:Punjab:Lahore"] = [_st("A")]
    o2 = await t.discover_all_stations_comprehensive()
    b = _latest(t)["iqair_pakistan_punjab_lahore_b"]
    assert (b["miss_count"], b["dormant"], b["active"]) == (1, True, True)
    assert o2.details["manifest_dormant"] == 1 and o2.details["manifest_inactive"] == 0
    o3 = await t.discover_all_stations_comprehensive()
    b = _latest(t)["iqair_pakistan_punjab_lahore_b"]
    assert (b["miss_count"], b["dormant"], b["active"]) == (2, True, False)
    assert o3.status is RunStatus.success
    assert o3.details["manifest_inactive"] == 1 and o3.details["stations_deactivated"] == 1
    assert t.db_service.active_calls == [(["iqair_pakistan_punjab_lahore_b"], False)]
    # the derived city manifest only carries live stations; Lahore stays (A is live)
    city = Path(t.settings.CITY_MANIFEST_DIR) / "latest.jsonl"
    assert [json.loads(l)["city"] for l in city.read_text().splitlines() if l.strip()] == ["Lahore"]

    # Rediscovered: live again, counters reset.
    t.iqair_client.script["stations:Pakistan:Punjab:Lahore"] = [_st("A"), _st("B", lon=74.31)]
    await t.discover_all_stations_comprehensive()
    b = _latest(t)["iqair_pakistan_punjab_lahore_b"]
    assert (b["miss_count"], b["dormant"], b["active"]) == (0, False, True)


async def test_vanished_city_ages_its_stations_but_failed_state_does_not(tmp_path, monkeypatch):
    from app.services.ingestion.iqair_service import IQAirError
    script = {
        "states:Pakistan": [{"state": "Punjab"}, {"state": "Sindh"}],
        "cities:Pakistan:Punjab": [{"city": "Lahore"}, {"city": "Kasur"}],
        "stations:Pakistan:Punjab:Lahore": [_st("A")],
        "stations:Pakistan:Punjab:Kasur": [_st("K", lon=74.4)],
        "cities:Pakistan:Sindh": [{"city": "Karachi"}],
        "stations:Pakistan:Sindh:Karachi": [_st("S", lon=67.0, lat=24.8)],
    }
    t, rec = _discovery(tmp_path, script, monkeypatch)
    await t.discover_all_stations_comprehensive()
    # Kasur disappears from /cities; Sindh cannot be read at all this run.
    t.iqair_client.script["cities:Pakistan:Punjab"] = [{"city": "Lahore"}]
    t.iqair_client.script["cities:Pakistan:Sindh"] = IQAirError("server_error_503")
    o = await t.discover_all_stations_comprehensive()
    latest = _latest(t)
    assert latest["iqair_pakistan_punjab_kasur_k"]["miss_count"] == 1
    assert latest["iqair_pakistan_sindh_karachi_s"]["miss_count"] == 0
    assert latest["iqair_pakistan_punjab_lahore_a"]["miss_count"] == 0
    assert o.status is RunStatus.partial   # Sindh skipped is still a real skip


async def test_deactivation_failure_is_reported_not_fatal(tmp_path, monkeypatch):
    script = {"states:Pakistan": [{"state": "Punjab"}], "cities:Pakistan:Punjab": [{"city": "Lahore"}],
              "stations:Pakistan:Punjab:Lahore": [_st("A"), _st("B", lon=74.31)]}
    t, rec = _discovery(tmp_path, script, monkeypatch, MANIFEST_DORMANT_AFTER_MISSES=1, MANIFEST_INACTIVE_AFTER_MISSES=1)
    await t.discover_all_stations_comprehensive()
    t.iqair_client.script["stations:Pakistan:Punjab:Lahore"] = [_st("A")]

    async def boom(session, ids, active, provider_codes=None):
        raise RuntimeError("db down")
    t.db_service.set_stations_active = boom
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.partial and o.details["deactivation_error"].startswith("RuntimeError")
    assert [f.error_class for f in rec.failures] == ["deactivation_failed"]
