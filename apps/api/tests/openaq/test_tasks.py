"""
OpenAQ discovery / ingest / reconcile end-to-end against respx with the
in-memory repository. Every acceptance scenario from the plan lives here.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.ingestion.quota import LocalQuota
from app.ingestion.raw_archive import NullArchiver
from app.ingestion.runs import RunStatus
from app.services.ingestion.openaq.client import OpenAQClient
from app.services.ingestion.openaq.discovery import OpenAQDiscoveryTask
from app.services.ingestion.openaq.ingest import OpenAQIngestTask
from app.services.ingestion.openaq.repository import (InMemoryOpenAQRepository, Stream, station_id_for_location,
                                                     stream_key_for)
from tests.ingestion.fakes import CapturingRecorder, FakeLeases, make_settings
from tests.openaq.fixtures import BASE, hourly_series, location, measurement, page, sensor

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


class SleepSpy:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


def _settings(tmp_path, **kw):
    base = dict(OPENAQ_ENABLED=True, OPENAQ_API_KEY="oq-SECRET-key-123456", OPENAQ_BASE_URL=BASE, OPENAQ_PAGE_LIMIT=2,
                OPENAQ_MAX_PAGES_PER_STREAM=6, OPENAQ_OVERLAP_HOURS=72, OPENAQ_WINDOW_HOURS=24,
                OPENAQ_INITIAL_BACKFILL_HOURS=72, OPENAQ_RECONCILE_LOOKBACK_DAYS=14, OPENAQ_MAX_REQUESTS_PER_RUN=1200)
    base.update(kw)
    return make_settings(tmp_path, **base)


def _client(s, **kw):
    return OpenAQClient(settings=s, quota=LocalQuota(), retry_sleep=SleepSpy(), **kw)


def _discovery(tmp_path, repo=None, s=None, **kw):
    s = s or _settings(tmp_path)
    rec = CapturingRecorder(tmp_path / "runs")
    t = OpenAQDiscoveryTask(settings=s, client=_client(s), repo=repo or InMemoryOpenAQRepository(), archiver=NullArchiver(),
                            recorder_factory=lambda: rec, leases=FakeLeases(), quota=LocalQuota(), **kw)
    return t, rec


def _ingest(tmp_path, repo, s=None, client=None, now=NOW):
    s = s or _settings(tmp_path)
    rec = CapturingRecorder(tmp_path / "runs")
    t = OpenAQIngestTask(settings=s, client=client or _client(s), repo=repo, archiver=NullArchiver(),
                         recorder_factory=lambda: rec, leases=FakeLeases(), quota=LocalQuota(), now=lambda: now)
    return t, rec


def _mock_locations(*locs, limit=2):
    """Serve `locs` as pages of `limit` with an integer `found`."""
    pages = [locs[i:i + limit] for i in range(0, len(locs), limit)] or [[]]
    for i, chunk in enumerate(pages, start=1):
        respx.get(f"{BASE}/locations", params={"page": str(i)}).mock(
            return_value=httpx.Response(200, json=page(list(chunk), page_no=i, limit=limit, found=len(locs))))


def _mock_measurements(sensor_id, rows, limit=2, fail_page=None):
    pages = [rows[i:i + limit] for i in range(0, len(rows), limit)] or [[]]
    for i, chunk in enumerate(pages, start=1):
        if fail_page == i:
            resp = httpx.Response(503)
        else:
            resp = httpx.Response(200, json=page(list(chunk), page_no=i, limit=limit, found=len(rows)))
        respx.get(f"{BASE}/sensors/{sensor_id}/measurements", params={"page": str(i)}).mock(return_value=resp)


async def _seeded_repo(tmp_path, *locs, **kw):
    repo = InMemoryOpenAQRepository(**kw)
    _mock_locations(*locs)
    t, rec = _discovery(tmp_path, repo=repo)
    o = await t.run()
    assert o.status in (RunStatus.success, RunStatus.partial), (o.status, o.error_class, o.error_message)
    return repo


# ---------------------------------------------------------------- discovery

@respx.mock
async def test_discovery_seeds_pm25_streams_as_shadow_stations(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1, sensors=[sensor(10), sensor(11, "pm10"), sensor(12, "no2")]),
                              location(2, is_monitor=True))
    assert set(repo.streams) == {"sensor:10:pm25", "sensor:20:pm25"}
    st = repo.stations[station_id_for_location(1)]
    assert st["active"] is False and st["city_id"] is None and st["state_id"] is None
    md = st["metadata_json"]
    assert md["ingest_mode"] == "shadow" and md["origin"] == "external" and md["geo_resolution"]["method"] == "none"
    assert md["openaq"]["location_id"] == 1 and md["openaq"]["licenses"][0]["name"] == "CC BY 4.0"
    assert md["identity"]["native_ids"][0] == {**md["identity"]["native_ids"][0], "provider": "openaq", "native_id": "1"}
    assert md["identity"]["hardware"]["confidence"] == "reported"
    assert repo.stations[station_id_for_location(2)]["monitor_type"] == "reference_reported_by_openaq"
    assert st["monitor_type"] == "low_cost_reported_by_openaq"
    assert repo.streams["sensor:10:pm25"].completed_through is None


@respx.mock
async def test_discovery_excludes_loops_and_mobile_and_writes_alias_candidates(tmp_path):
    nearby = [{"station_id": "abc".ljust(16), "provider_code": "airvisual", "name": "Location 1", "distance_m": 40.0}]
    repo = await _seeded_repo(tmp_path, location(1), location(2, provider="PAQI AirVisual"), location(3, is_mobile=True),
                              nearby=nearby)
    assert repo.streams["sensor:10:pm25"].status == "active"
    assert repo.streams["sensor:20:pm25"].status == "excluded_loop"
    assert repo.streams["sensor:30:pm25"].status == "excluded_mobile"
    loop_md = repo.stations[station_id_for_location(2)]["metadata_json"]
    assert loop_md["origin"] == "hawanama_loop" and loop_md["identity"]["alias_candidates"] == []
    cands = repo.stations[station_id_for_location(1)]["metadata_json"]["identity"]["alias_candidates"]
    assert cands[0]["station_id"] == "abc" and cands[0]["reviewed"] is False and cands[0]["name_similarity"] == 1.0
    assert repo.stations[station_id_for_location(1)]["metadata_json"]["identity"]["aliases"] == []


@respx.mock
async def test_discovery_renamed_or_moved_location_keeps_station_id(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1, name="Old", lat=31.5))
    sid = station_id_for_location(1)
    _mock_locations(location(1, name="New", lat=31.6))
    t, _ = _discovery(tmp_path, repo=repo)
    await t.run()
    assert set(repo.stations) == {sid} and repo.stations[sid]["name"] == "New" and repo.stations[sid]["lat"] == 31.6
    hist = repo.stations[sid]["metadata_json"]["openaq"]["history"]
    assert hist[-1]["from"]["name"] == "Old" and hist[-1]["to"]["lat"] == 31.6


@respx.mock
async def test_discovery_preserves_cutover_mode_and_retires_unseen_streams(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1), location(2))
    repo.stations[station_id_for_location(1)]["metadata_json"]["ingest_mode"] = "primary"
    for _ in range(7):
        _mock_locations(location(1))                       # location 2 disappears
        t, _ = _discovery(tmp_path, repo=repo)
        await t.run()
    assert repo.stations[station_id_for_location(1)]["metadata_json"]["ingest_mode"] == "primary"
    assert repo.streams["sensor:20:pm25"].status == "retired" and repo.streams["sensor:10:pm25"].status == "active"


@respx.mock
async def test_discovery_dry_run_reports_without_writing(tmp_path):
    repo = InMemoryOpenAQRepository()
    _mock_locations(location(1), location(2, provider="Hawanama"), location(3, sensors=[sensor(31, "pm10")]))
    t, _ = _discovery(tmp_path, repo=repo, s=_settings(tmp_path, OPENAQ_ENABLED=False))
    o = await t.run(dry_run=True)
    assert o.status is RunStatus.success and repo.stations == {} and repo.streams == {}
    d = o.details
    assert d["locations"] == 3 and d["active_streams"] == 1 and d["loop_excluded"] == 1
    assert d["sensors_by_parameter"] == {"pm25": 2, "pm10": 1} and d["budget"]["fits"] is True
    assert d["by_provider"]["Hawanama"] == 1 and d["requests_made"] == 2


@respx.mock
async def test_discovery_disabled_is_skipped_with_zero_requests(tmp_path):
    route = respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(200, json=page([location(1)])))
    t, _ = _discovery(tmp_path, s=_settings(tmp_path, OPENAQ_ENABLED=False))
    o = await t.run()
    assert o.status is RunStatus.skipped and o.error_class == "disabled" and route.call_count == 0


@respx.mock
async def test_discovery_no_locations_is_failed_and_missing_key_is_config_invalid(tmp_path):
    _mock_locations()
    t, _ = _discovery(tmp_path)
    o = await t.run()
    assert o.status is RunStatus.failed and o.error_class == "no_locations"
    t2, _ = _discovery(tmp_path, s=_settings(tmp_path, OPENAQ_API_KEY=None))
    o2 = await t2.run()
    assert o2.status is RunStatus.failed and o2.error_class == "config_invalid"


@respx.mock
async def test_discovery_auth_failure_is_failed_run(tmp_path):
    respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(403))
    t, _ = _discovery(tmp_path)
    o = await t.run()
    assert o.status is RunStatus.failed and o.error_class == "provider_auth"


# ---------------------------------------------------------------- ingest

@respx.mock
async def test_ingest_three_page_window_commits_once_and_advances_checkpoint(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1))
    rows = hourly_series(NOW - timedelta(hours=72), 5)          # 5 rows → pages of 2,2,1
    _mock_measurements(10, rows)
    t, rec = _ingest(tmp_path, repo)
    o = await t.run()
    assert o.status is RunStatus.success, (o.error_class, o.error_message)
    assert o.counts.rows_written == 5 and o.counts.rows_fetched == 5 and o.counts.completed == 1
    assert len(repo.commits) == 1 and repo.commits[0]["pages"] == 3 and repo.commits[0]["completed_through"] == NOW
    assert repo.streams["sensor:10:pm25"].completed_through == NOW and len(repo.readings) == 5
    r = next(iter(repo.readings.values()))
    assert r["source"] == "openaq" and r["scope_key"] == station_id_for_location(1) and r["raw"]["prov"]["tsp"].startswith("openaq_measurements_v1")
    assert len(repo.refs) == 3 and o.latest_observation_ts == NOW - timedelta(hours=67)


@respx.mock
async def test_ingest_page2_failure_writes_nothing_and_does_not_advance(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1))
    _mock_measurements(10, hourly_series(NOW - timedelta(hours=72), 5), fail_page=2)
    t, rec = _ingest(tmp_path, repo)
    o = await t.run()
    assert o.status is RunStatus.failed and o.counts.failed == 1
    assert repo.readings == {} and repo.commits == [] and repo.streams["sensor:10:pm25"].completed_through is None
    assert repo.streams["sensor:10:pm25"].consecutive_failures == 1 and rec.failures[0].error_class == "OpenAQTransient"


@respx.mock
async def test_ingest_restart_replays_safely_and_late_arrival_and_revision_are_handled(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1))
    start = NOW - timedelta(hours=72)
    rows = hourly_series(start, 4)
    _mock_measurements(10, rows)
    t, _ = _ingest(tmp_path, repo)
    o1 = await t.run()
    assert o1.counts.rows_written == 4
    # Next hour: checkpoint advanced; the overlap re-read now contains a late-arriving older hour and a revised value.
    later = NOW + timedelta(hours=1)
    rows2 = rows + [measurement(start + timedelta(hours=5), 99.0)]      # late arrival (hour 5)
    rows2[1] = measurement(start + timedelta(hours=2), 55.5)           # revised value at hour 2
    _mock_measurements(10, rows2)
    t2, _ = _ingest(tmp_path, repo, now=later)
    o2 = await t2.run()
    assert o2.status is RunStatus.success
    assert o2.counts.rows_written == 2 and o2.counts.rows_unchanged == 3     # 1 inserted + 1 updated, 3 exact replays
    assert repo.streams["sensor:10:pm25"].completed_through == later
    assert repo.readings[("station", station_id_for_location(1), start + timedelta(hours=2))]["pm25"] == 55.5
    assert repo.readings[("station", station_id_for_location(1), start + timedelta(hours=5))]["pm25"] == 99.0
    assert len(repo.readings) == 5


@respx.mock
async def test_ingest_subhourly_stream_is_deferred_without_readings(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1))
    _mock_measurements(10, [measurement(NOW - timedelta(hours=1), 3.0, interval="00:01:00")])
    t, _ = _ingest(tmp_path, repo)
    o = await t.run()
    assert repo.streams["sensor:10:pm25"].status == "deferred_subhourly"
    assert repo.streams["sensor:10:pm25"].interval_observed == "00:01:00" and repo.readings == {}
    assert o.details["streams_deferred_subhourly"] == 1 and o.counts.rows_written == 0


@respx.mock
async def test_ingest_budget_exhausted_mid_run_is_partial_with_exact_request_count(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1), location(2))
    s = _settings(tmp_path)
    for sid in (10, 20):
        _mock_measurements(sid, hourly_series(NOW - timedelta(hours=72), 1))
    client = _client(s, max_requests=1)
    t, _ = _ingest(tmp_path, repo, s=s, client=client)
    o = await t.run()
    assert o.status is RunStatus.partial and o.error_class == "budget"
    assert client.requests_made == 1 and len(repo.commits) == 1
    assert o.details["budget_stop"]["streams_remaining"] == 1 and o.counts.skipped == 1


@respx.mock
async def test_ingest_auth_failure_stops_run_and_other_adapters_still_work(tmp_path, monkeypatch):
    repo = await _seeded_repo(tmp_path, location(1), location(2))
    route = respx.get(url__regex=rf"{BASE}/sensors/\d+/measurements.*").mock(return_value=httpx.Response(401))
    t, rec = _ingest(tmp_path, repo)
    o = await t.run()
    assert o.status is RunStatus.failed and o.error_class == "provider_auth" and route.call_count == 1
    assert repo.commits == []

    # An independent adapter (IQAir station task) is unaffected by the OpenAQ credential failure.
    from app.ingestion.tasks.data_ingestion import DataIngestionTask
    from tests.ingestion.fakes import FakeDatabaseService, FakeIQAirClient, iqair_payload, station_row, write_station_manifest
    s = make_settings(tmp_path)
    write_station_manifest(s, [station_row(0)])
    task = DataIngestionTask(settings=s, iqair_client=FakeIQAirClient({"*": iqair_payload()}), db_service=FakeDatabaseService(),
                             recorder_factory=lambda: CapturingRecorder(tmp_path / "r2"), leases=FakeLeases(), archiver=NullArchiver())
    assert (await task.fetch_station_readings()).status is RunStatus.success


@respx.mock
async def test_ingest_disabled_and_no_streams(tmp_path):
    route = respx.get(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(200, json=page([])))
    t, _ = _ingest(tmp_path, InMemoryOpenAQRepository(), s=_settings(tmp_path, OPENAQ_ENABLED=False))
    o = await t.run()
    assert o.status is RunStatus.skipped and route.call_count == 0
    t2, _ = _ingest(tmp_path, InMemoryOpenAQRepository())
    o2 = await t2.run()
    assert o2.status is RunStatus.failed and o2.error_class == "no_streams"


@respx.mock
async def test_reconcile_rereads_older_windows_without_moving_checkpoint(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1))
    st = repo.streams["sensor:10:pm25"]
    st.completed_through = NOW - timedelta(hours=1)
    route = respx.get(url__regex=rf"{BASE}/sensors/10/measurements.*").mock(
        return_value=httpx.Response(200, json=page([measurement(NOW - timedelta(days=10), 7.0)], found=1)))
    t, _ = _ingest(tmp_path, repo)
    o = await t.run(mode="reconcile")
    assert o.status is RunStatus.success and o.details["mode"] == "reconcile"
    assert route.call_count == 2                                       # 14-day lookback → two 7-day chunks
    assert st.completed_through == NOW - timedelta(hours=1)            # untouched
    assert st.reconciled_through is not None and len(repo.readings) >= 1
    q = route.calls[0].request.url.params
    assert q["datetime_from"] < q["datetime_to"]


@respx.mock
async def test_reconcile_skips_streams_with_no_completed_window(tmp_path):
    repo = await _seeded_repo(tmp_path, location(1))
    route = respx.get(url__regex=rf"{BASE}/sensors/.*").mock(return_value=httpx.Response(200, json=page([])))
    t, _ = _ingest(tmp_path, repo)
    o = await t.run(mode="reconcile")
    assert route.call_count == 0 and o.counts.skipped == 1
