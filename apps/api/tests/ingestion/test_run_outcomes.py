"""
Runs report what actually happened. Total failure, an empty inventory, a bad
credential and a held lease are not 'success'.
"""

import json
from pathlib import Path

import pytest

from app.ingestion.runs import (RunCounts, RunOutcome, RunRecorder, RunStatus, classify, new_run_id,
                                worst_status, EntityFailure)
from app.ingestion.tasks.data_ingestion import DataIngestionTask
from app.ingestion.tasks.city_ingest import CityIngestionTask
from app.ingestion.tasks.station_discovery import StationDiscoveryTask
from app.ingestion.raw_archive import NullArchiver
from app.services.ingestion.iqair_service import IQAirError, StationNotFound, Unauthorized

from tests.ingestion.fakes import (CapturingRecorder, FakeDatabaseService, FakeIQAirClient, FakeLeases, FakeSessionFactory,
                                   city_row, iqair_payload, make_settings,
                                   station_row, write_city_manifest, write_station_manifest)


# ---------------------------------------------------------------- classify

@pytest.mark.parametrize("expected,attempted,failed,fatal,want", [
    (0, 0, 0, None, RunStatus.failed),          # empty inventory
    (3, 3, 3, None, RunStatus.failed),          # all failed
    (3, 3, 1, None, RunStatus.partial),         # some failed
    (3, 3, 0, None, RunStatus.success),
    (3, 3, 0, "boom", RunStatus.failed),        # fatal always wins
    (3, 1, 1, None, RunStatus.failed),          # only attempted one, it failed
])
def test_classify(expected, attempted, failed, fatal, want):
    c = RunCounts(expected=expected, attempted=attempted, failed=failed)
    assert classify(c, fatal_error=fatal) is want


def test_http_status_mapping():
    o = RunOutcome(run_id="r", task="t", provider_code="p")
    for status, code in [(RunStatus.success, 200), (RunStatus.skipped, 200), (RunStatus.partial, 207), (RunStatus.failed, 500)]:
        o.status = status
        assert o.http_status() == code


def test_worst_status():
    a = RunOutcome(run_id="a", task="t", provider_code="p", status=RunStatus.success)
    b = RunOutcome(run_id="b", task="t", provider_code="p", status=RunStatus.partial)
    c = RunOutcome(run_id="c", task="t", provider_code="p", status=RunStatus.failed)
    assert worst_status(a, b) is RunStatus.partial
    assert worst_status(a, b, c) is RunStatus.failed
    assert worst_status(a) is RunStatus.success


def test_new_run_id_is_unique_per_call():
    ids = {new_run_id("ingest-stations") for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith("ingest-stations-") for i in ids)


def test_finish_degrades_to_partial_on_partial_reason():
    o = RunOutcome(run_id="r", task="t", provider_code="p", counts=RunCounts(expected=2, attempted=2, completed=2))
    o.partial_reason = "entities_skipped"
    o.finish()
    assert o.status is RunStatus.partial and o.error_class == "entities_skipped"


# ---------------------------------------------------------------- recorder

async def test_recorder_writes_local_report_without_db(tmp_path):
    rec = RunRecorder(None, tmp_path)
    o = RunOutcome(run_id="run-1", task="t", provider_code="p", counts=RunCounts(expected=1, attempted=1, failed=1))
    await rec.start(o)
    rec.add_failure(EntityFailure("station", "s1", "StationNotFound", "nope"))
    await rec.finish(o)
    d = tmp_path / "run-1"
    assert json.loads((d / "metrics.json").read_text())["status"] == "failed"
    assert (d / "failures.jsonl").read_text().count("\n") == 1


class _UndefinedTable(Exception):
    sqlstate = "42P01"


async def test_recorder_degrades_when_ops_tables_missing(tmp_path, caplog):
    RunRecorder._warned_missing = False
    sf = FakeSessionFactory(fail_with=_UndefinedTable('relation "ops.ingest_runs" does not exist'))
    rec = RunRecorder(sf, tmp_path, required=False)
    o = RunOutcome(run_id="run-2", task="t", provider_code="p", counts=RunCounts(expected=1, attempted=1, completed=1))
    await rec.start(o)
    await rec.finish(o)                      # must not raise
    assert rec._db_ok is False
    assert (tmp_path / "run-2" / "metrics.json").exists()
    assert "ops tables missing" in caplog.text


async def test_recorder_raises_when_required_and_tables_missing(tmp_path):
    sf = FakeSessionFactory(fail_with=_UndefinedTable('relation "ops.ingest_runs" does not exist'))
    rec = RunRecorder(sf, tmp_path, required=True)
    o = RunOutcome(run_id="run-3", task="t", provider_code="p")
    with pytest.raises(_UndefinedTable):
        await rec.start(o)


async def test_recorder_persists_run_and_entities(tmp_path):
    sf = FakeSessionFactory()
    rec = RunRecorder(sf, tmp_path)
    o = RunOutcome(run_id="run-4", task="ingest-stations", provider_code="airvisual",
                   counts=RunCounts(expected=2, attempted=2, completed=1, failed=1))
    await rec.start(o)
    rec.add_failure(EntityFailure("station", "s1", "IQAirError", "server_error_503"))
    await rec.finish(o)
    executed = [sql for sess in sf.sessions for sql, _ in sess.executed]
    assert any("INSERT INTO ops.ingest_runs" in q for q in executed)
    assert any("UPDATE ops.ingest_runs" in q for q in executed)
    assert any("INSERT INTO ops.ingest_run_entities" in q for q in executed)
    assert o.status is RunStatus.partial


# ---------------------------------------------------------------- station task

def _station_task(tmp_path, script, rows, monkeypatch, **settings_overrides):
    s = make_settings(tmp_path, **settings_overrides)
    write_station_manifest(s, rows)
    rec = CapturingRecorder(Path(s.INGEST_OUT_DIR))
    t = DataIngestionTask(settings=s, iqair_client=FakeIQAirClient(script), db_service=FakeDatabaseService(),
                          recorder_factory=lambda: rec, leases=FakeLeases(), archiver=NullArchiver())
    return t, rec


async def test_all_stations_fail_is_failed(tmp_path, monkeypatch):
    rows = [station_row(i) for i in range(3)]
    t, rec = _station_task(tmp_path, {"*": IQAirError("server_error_503")}, rows, monkeypatch)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.failed
    assert o.error_class == "all_entities_failed"
    c = o.counts
    assert (c.expected, c.attempted, c.failed, c.completed) == (3, 3, 3, 0)
    assert len(rec.failures) == 3 and all(f.error_class == "IQAirError" for f in rec.failures)
    assert o.http_status() == 500
    assert (Path(o.report_dir) / "failures.jsonl").exists()


async def test_partial_when_some_fail(tmp_path, monkeypatch):
    rows = [station_row(i) for i in range(3)]
    script = {"Station 0": iqair_payload(), "Station 1": iqair_payload(), "Station 2": StationNotFound("station_not_found")}
    t, rec = _station_task(tmp_path, script, rows, monkeypatch)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.partial and o.http_status() == 207
    c = o.counts
    assert (c.expected, c.attempted, c.completed, c.failed) == (3, 3, 2, 1)
    assert c.rows_fetched == 2 and c.rows_written == 2 and c.rows_unchanged == 0
    assert o.latest_observation_ts is not None and o.observation_lag_s is not None
    assert len(t.db_service.written) == 2
    assert t.db_service.policies[0].source == "airvisual" and t.db_service.policies[0].run_id == o.run_id
    w = t.db_service.written[0]
    assert w["qc_state"] == "raw" and w["raw"]["prov"]["tsp"] == "iqair_station_v1" and w["raw"]["prov"]["run"] == o.run_id
    assert o.details["extraction"]["rejected"] == {}


async def test_success_counts_unchanged_rows(tmp_path, monkeypatch):
    rows = [station_row(i) for i in range(2)]
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, rows, monkeypatch)
    t.db_service.unchanged_all = True            # exact replay: reconcile touches nothing
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.success
    assert o.counts.rows_written == 0 and o.counts.rows_unchanged == 2
    assert o.details["reconcile"]["unchanged"] == 2


async def test_empty_inventory_is_failed_not_success(tmp_path, monkeypatch):
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, [], monkeypatch)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.failed and o.error_class == "empty_inventory"
    assert o.counts.expected == 0 and o.http_status() == 500
    assert t.iqair_client.calls == []


async def test_filtered_out_inventory_is_failed(tmp_path, monkeypatch):
    rows = [station_row(0, country="India")]      # IQAIR_COUNTRIES=Pakistan in make_settings
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, rows, monkeypatch)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.failed and o.error_class == "empty_inventory"
    assert o.manifest_rows == 1


async def test_unauthorized_aborts_remaining_stations(tmp_path, monkeypatch):
    rows = [station_row(i) for i in range(4)]
    t, rec = _station_task(tmp_path, {"*": Unauthorized("invalid_api_key_or_unauthorized")}, rows, monkeypatch)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.failed and o.error_class == "provider_auth"
    c = o.counts
    assert c.attempted == 1 and c.failed == 1 and c.skipped == 3
    assert len(t.iqair_client.calls) == 1            # no further requests after the 401/403


async def test_run_id_and_report_dir_are_per_invocation(tmp_path, monkeypatch):
    rows = [station_row(0)]
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, rows, monkeypatch)
    o1 = await t.fetch_station_readings()
    o2 = await t.fetch_station_readings()
    assert o1.run_id != o2.run_id and o1.report_dir != o2.report_dir
    assert Path(o1.report_dir).exists() and Path(o2.report_dir).exists()


async def test_unexpected_exception_is_failed_and_recorded(tmp_path, monkeypatch):
    rows = [station_row(0)]
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, rows, monkeypatch)

    async def boom(self, rows, run_id):
        raise RuntimeError("db exploded")
    monkeypatch.setattr(DataIngestionTask, "_write_rows", boom)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.failed and o.error_class == "RuntimeError"
    assert rec.finished is o


class _BrokenQuota:
    async def healthcheck(self):
        from app.ingestion.quota import QuotaUnavailable
        raise QuotaUnavailable("ops.provider_quota unavailable: relation does not exist")


async def test_quota_unavailable_fails_run_before_any_request(tmp_path, monkeypatch):
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, [station_row(0)], monkeypatch)
    t.iqair_client.quota = _BrokenQuota()
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.failed and o.error_class == "quota_unavailable"
    assert t.iqair_client.calls == [] and o.http_status() == 500


async def test_city_quota_unavailable_fails_run(tmp_path, monkeypatch):
    t, rec = _city_task(tmp_path, {"*": iqair_payload()}, [city_row(0)], monkeypatch)
    t.iqair_client.quota = _BrokenQuota()
    o = await t.fetch_city_readings_hourly()
    assert o.status is RunStatus.failed and o.error_class == "quota_unavailable" and t.iqair_client.calls == []


async def test_discovery_quota_unavailable_fails_run(tmp_path, monkeypatch):
    t, rec = _discovery(tmp_path, {"states:Pakistan": [{"state": "Punjab"}]}, monkeypatch, countries="Pakistan")
    t.iqair_client.quota = _BrokenQuota()
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.failed and o.error_class == "quota_unavailable" and t.iqair_client.calls == []


async def test_lease_held_is_skipped_with_200(tmp_path, monkeypatch):
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, [station_row(0)], monkeypatch)
    t._leases = FakeLeases(deny=True)
    o = await t.fetch_station_readings()
    assert o.status is RunStatus.skipped and o.error_class == "lease_held" and o.http_status() == 200
    assert t.iqair_client.calls == [] and t._leases.released == [None]
    assert rec.finished is o


async def test_lease_is_recorded_and_released(tmp_path, monkeypatch):
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, [station_row(0)], monkeypatch)
    o = await t.fetch_station_readings()
    assert o.lease_key == "ingest-stations:airvisual:Pakistan" and o.lease_fence == 42
    assert len(t._leases.released) == 1 and t._leases.released[0].fence == 42
    assert t._leases.acquired[0][2] == t.settings.INGEST_LEASE_TTL_S


async def test_city_lease_held_is_skipped(tmp_path, monkeypatch):
    t, rec = _city_task(tmp_path, {"*": iqair_payload()}, [city_row(0)], monkeypatch)
    t._leases = FakeLeases(deny=True)
    o = await t.fetch_city_readings_hourly()
    assert o.status is RunStatus.skipped and t.iqair_client.calls == []


async def test_discovery_lease_held_is_skipped(tmp_path, monkeypatch):
    t, rec = _discovery(tmp_path, {"states:Pakistan": [{"state": "Punjab"}]}, monkeypatch, countries="Pakistan")
    t._leases = FakeLeases(deny=True)
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.skipped and o.error_class == "lease_held" and t.iqair_client.calls == []


async def test_trigger_is_recorded(tmp_path, monkeypatch):
    t, rec = _station_task(tmp_path, {"*": iqair_payload()}, [station_row(0)], monkeypatch)
    o = await t.fetch_station_readings(trigger="scheduler")
    assert o.trigger == "scheduler" and o.to_dict()["trigger"] == "scheduler"


# ---------------------------------------------------------------- city task

def _city_task(tmp_path, script, rows, monkeypatch):
    s = make_settings(tmp_path)
    write_city_manifest(s, rows)
    rec = CapturingRecorder(Path(s.INGEST_OUT_DIR))
    t = CityIngestionTask(settings=s, iqair_client=FakeIQAirClient(script), db_service=FakeDatabaseService(),
                          recorder_factory=lambda: rec, leases=FakeLeases(), archiver=NullArchiver())
    return t, rec


async def test_city_all_fail_is_failed(tmp_path, monkeypatch):
    t, rec = _city_task(tmp_path, {"*": IQAirError("server_error_503")}, [city_row(i) for i in range(2)], monkeypatch)
    o = await t.fetch_city_readings_hourly()
    assert o.status is RunStatus.failed and o.counts.failed == 2 and len(rec.failures) == 2


async def test_city_partial_and_counts(tmp_path, monkeypatch):
    script = {"City0": iqair_payload(), "City1": IQAirError("city_not_found")}
    t, rec = _city_task(tmp_path, script, [city_row(0), city_row(1)], monkeypatch)
    o = await t.fetch_city_readings_hourly()
    assert o.status is RunStatus.partial
    assert o.counts.completed == 1 and o.counts.failed == 1 and o.counts.rows_written == 1


async def test_city_empty_inventory_is_failed(tmp_path, monkeypatch):
    t, rec = _city_task(tmp_path, {"*": iqair_payload()}, [], monkeypatch)
    o = await t.fetch_city_readings_hourly()
    assert o.status is RunStatus.failed and o.error_class == "empty_inventory"


async def test_city_unauthorized_aborts(tmp_path, monkeypatch):
    t, rec = _city_task(tmp_path, {"*": Unauthorized("bad key")}, [city_row(i) for i in range(3)], monkeypatch)
    o = await t.fetch_city_readings_hourly()
    assert o.status is RunStatus.failed and o.error_class == "provider_auth"
    assert o.counts.skipped == 2 and len(t.iqair_client.calls) == 1


# ---------------------------------------------------------------- discovery

def _discovery(tmp_path, script, monkeypatch, countries="Pakistan,India"):
    import app.ingestion.tasks.station_discovery as sd
    s = make_settings(tmp_path, IQAIR_COUNTRIES=countries)
    rec = CapturingRecorder(Path(s.INGEST_OUT_DIR))
    monkeypatch.setattr(sd, "AsyncSessionFactory", None, raising=False)
    monkeypatch.setattr(sd, "AsyncSessionLocal", FakeSessionFactory())
    monkeypatch.setattr(sd.asyncio, "sleep", _nosleep)
    t = StationDiscoveryTask(settings=s, iqair_client=FakeIQAirClient(script), db_service=FakeDatabaseService(),
                             recorder_factory=lambda: rec, leases=FakeLeases())
    return t, rec


async def _nosleep(_):
    return None


def _station_payload(name="Alpha"):
    return {"station": name, "location": {"type": "Point", "coordinates": [74.3, 31.5]}}


async def test_discovery_partial_when_one_country_fails(tmp_path, monkeypatch):
    script = {
        "states:Pakistan": [{"state": "Punjab"}],
        "cities:Pakistan:Punjab": [{"city": "Lahore"}],
        "stations:Pakistan:Punjab:Lahore": [_station_payload()],
        "states:India": IQAirError("server_error_503"),
    }
    t, rec = _discovery(tmp_path, script, monkeypatch)
    o = await t.discover_all_stations_comprehensive()
    # One of two countries failed: classify() gives partial from the counts alone.
    assert o.status is RunStatus.partial and o.http_status() == 207
    c = o.counts
    assert (c.expected, c.attempted, c.failed, c.rows_written) == (2, 2, 1, 1)
    assert [f.entity_type for f in rec.failures] == ["country"]
    assert (Path(t.settings.STATION_MANIFEST_DIR) / "latest.jsonl").exists()


async def test_discovery_all_countries_fail_is_failed(tmp_path, monkeypatch):
    script = {"states:Pakistan": IQAirError("x"), "states:India": IQAirError("y")}
    t, rec = _discovery(tmp_path, script, monkeypatch)
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.failed and o.error_class == "all_countries_failed"


async def test_discovery_zero_stations_is_failed(tmp_path, monkeypatch):
    script = {"states:Pakistan": [{"state": "Punjab"}], "cities:Pakistan:Punjab": [],
              "cities:Pakistan:Islamabad Capital Territory": []}
    t, rec = _discovery(tmp_path, script, monkeypatch, countries="Pakistan")
    o = await t.discover_all_stations_comprehensive()
    assert o.status is RunStatus.failed and o.error_class == "no_stations_discovered"


async def test_discovery_success(tmp_path, monkeypatch):
    script = {
        "states:Pakistan": [{"state": "Punjab"}],
        "cities:Pakistan:Punjab": [{"city": "Lahore"}],
        "stations:Pakistan:Punjab:Lahore": [_station_payload("A"), _station_payload("B")],
    }
    t, rec = _discovery(tmp_path, script, monkeypatch, countries="Pakistan")
    o = await t.discover_all_stations_comprehensive(trigger="scheduler")
    assert o.status is RunStatus.success and o.counts.rows_written == 2 and o.trigger == "scheduler"
