"""ICIMOD ingest end-to-end against respx with the in-memory repository."""

from datetime import timedelta

import httpx
import pytest
import respx

from app.ingestion.raw_archive import NullArchiver
from app.ingestion.runs import RunStatus
from app.services.ingestion.icimod.client import ICIMODClient
from app.services.ingestion.icimod.ingest import ICIMODIngestTask
from app.services.ingestion.icimod.normalize import station_id_for_icimod
from app.services.ingestion.icimod.repository import InMemoryICIMODRepository
from tests.icimod.fixtures import BASE, DAY, DISTRICTS, collection, feature, hourly, label, station, stations_payload
from tests.ingestion.fakes import CapturingRecorder, FakeLeases, make_settings

NOW = DAY + timedelta(hours=17, minutes=50)
PILOT_KEYS = {"districts", "stations_in_catalogue", "stations_in_response", "stations_with_data", "hours_covered",
              "stations_per_hour", "earliest_label", "latest_label", "latest_label_age_min", "normalize_notes",
              "unmatched_features", "duplicate_names", "catalogue_notes", "ts_policy", "requests_made", "dry_run"}


class SleepSpy:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


def _settings(tmp_path, **kw):
    base = dict(ICIMOD_ENABLED=True, ICIMOD_BASE_URL=BASE)
    base.update(kw)
    return make_settings(tmp_path, **base)


def _task(tmp_path, repo=None, s=None, now=NOW, leases=None):
    s = s or _settings(tmp_path)
    rec = CapturingRecorder(tmp_path / "runs")
    client = ICIMODClient(settings=s, retry_sleep=SleepSpy())
    t = ICIMODIngestTask(settings=s, client=client, repo=repo if repo is not None else InMemoryICIMODRepository(),
                         archiver=NullArchiver(), recorder_factory=lambda: rec, leases=leases or FakeLeases(), now=lambda: now)
    return t, rec


def _mock_catalogue(stations=None, districts=DISTRICTS):
    respx.get(f"{BASE}/pakistan-dashboard/districts/").mock(return_value=httpx.Response(200, json=districts))
    return respx.get(f"{BASE}/pakistan-dashboard/icimod/stations/").mock(
        return_value=httpx.Response(200, json=stations if stations is not None else stations_payload()))


def _mock_recent(payload, status=200):
    return respx.post(f"{BASE}/external-api/charts/timeseries/recent/geojson/").mock(
        return_value=httpx.Response(status, json=payload) if status == 200 else httpx.Response(status))


@respx.mock
async def test_happy_path_writes_shadow_stations_and_readings(tmp_path):
    stations_route = _mock_catalogue()
    recent = _mock_recent(collection(feature("Egerton Road", hourly(0, 17, base=346.0, step=-10)),
                                     feature("Gulberg III, Lahore", hourly(1, 16, base=122.0, step=-3)),
                                     feature("Barki Road", {})))
    nearby = [{"station_id": "pb_000000000001".ljust(16), "provider_code": "punjab", "name": "Egerton Road", "distance_m": 12.0}]
    repo = InMemoryICIMODRepository(nearby=nearby)
    t, rec = _task(tmp_path, repo)
    o = await t.run()
    assert o.status is RunStatus.success, (o.error_class, o.error_message)
    assert t.client.requests_made == 3 and recent.call_count == 1
    assert stations_route.calls[0].request.url.params["district_name"] == "Lahore,Kasur"
    body = recent.calls[0].request.content
    assert b'"pollutant":"PM2.5"' in body and b'"source":"Ground Station"' in body and b"Barki Road" in body

    # shadow stations: inactive, no geography, identity + alias candidates toward the Punjab EPA row
    sid = station_id_for_icimod(26)
    st = repo.stations[sid]
    assert st["active"] is False and st["city_id"] is None and st["state_id"] is None and st["source_station_id"] == "26"
    md = st["metadata_json"]
    assert md["ingest_mode"] == "shadow" and md["origin"] == "icimod" and md["icimod"]["district"] == "Lahore"
    assert md["identity"]["native_ids"][0]["provider"] == "icimod" and md["identity"]["aliases"] == []
    cand = md["identity"]["alias_candidates"][0]
    assert cand["station_id"] == "pb_000000000001" and cand["provider_hint_match"] is True and cand["name_similarity"] == 1.0

    # readings: 17 + 16 rows, keyed on the floored hour, source icimod, label kept
    assert len(repo.readings) == 33 and o.counts.rows_written == 33 and o.counts.rows_fetched == 33
    r = repo.readings[("station", sid, DAY)]
    assert r["source"] == "icimod" and r["pm25"] == 346.0 and r["raw"]["prov"]["label"] == label(0)
    assert len(repo.refs) == 1 and repo.refs[0].stream == "timeseries_recent"
    assert o.latest_observation_ts == DAY + timedelta(hours=16)

    c, d = o.counts, o.details
    assert (c.expected, c.attempted, c.completed, c.failed) == (3, 3, 2, 0)
    assert PILOT_KEYS <= set(d)
    assert d["stations_in_catalogue"] == 3 and d["stations_in_response"] == 3 and d["stations_with_data"] == 2
    assert d["hours_covered"] == 17 and d["stations_per_hour"][DAY.isoformat()] == 1 and d["latest_label"] == label(16)
    assert d["latest_label_age_min"] == 110.0 and d["normalize_notes"] == {"no_hourly_data": 1}
    assert d["unmatched_features"] == [] and d["duplicate_names"] == [] and d["dry_run"] is False
    assert d["revisions_recorded"] == 0 and rec.failures == []


@respx.mock
async def test_second_run_replays_unchanged_and_records_revisions(tmp_path):
    _mock_catalogue()
    _mock_recent(collection(feature("Egerton Road", hourly(0, 3))))
    repo = InMemoryICIMODRepository()
    t, _ = _task(tmp_path, repo)
    assert (await t.run()).counts.rows_written == 3
    revised = hourly(0, 4)
    revised[label(1)] = 999.0
    _mock_recent(collection(feature("Egerton Road", revised)))
    t2, _ = _task(tmp_path, repo, now=NOW + timedelta(hours=1))
    o = await t2.run()
    assert o.counts.rows_written == 2 and o.counts.rows_unchanged == 2 and o.details["revisions_recorded"] == 1
    assert repo.readings[("station", station_id_for_icimod(26), DAY + timedelta(hours=1))]["pm25"] == 999.0


@respx.mock
async def test_disabled_is_skipped_with_zero_requests_but_dry_run_still_probes(tmp_path):
    _mock_catalogue()
    recent = _mock_recent(collection(feature("Egerton Road", hourly(0, 2))))
    repo = InMemoryICIMODRepository()
    t, _ = _task(tmp_path, repo, s=_settings(tmp_path, ICIMOD_ENABLED=False))
    o = await t.run()
    assert o.status is RunStatus.skipped and o.error_class == "disabled" and t.client.requests_made == 0

    t2, _ = _task(tmp_path, repo, s=_settings(tmp_path, ICIMOD_ENABLED=False))
    o2 = await t2.run(dry_run=True)
    assert o2.status is RunStatus.success and recent.call_count == 1
    assert repo.stations == {} and repo.readings == {} and repo.refs == []
    assert o2.details["dry_run"] is True and o2.details["rows_would_write"] == 2 and o2.details["stations_with_data"] == 1


@respx.mock
async def test_empty_catalogue_and_no_districts_fail(tmp_path):
    _mock_catalogue(stations=[])
    t, _ = _task(tmp_path)
    o = await t.run()
    assert o.status is RunStatus.failed and o.error_class == "catalogue_empty"
    _mock_catalogue(districts=[])
    t2, _ = _task(tmp_path)
    o2 = await t2.run()
    assert o2.status is RunStatus.failed and o2.error_class == "catalogue_empty" and t2.client.requests_made == 1


@respx.mock
async def test_server_error_is_retried_then_provider_error(tmp_path):
    _mock_catalogue()
    recent = _mock_recent(None, status=503)
    t, _ = _task(tmp_path, s=_settings(tmp_path, ICIMOD_RETRY_MAX_ATTEMPTS=3))
    o = await t.run()
    assert o.status is RunStatus.failed and o.error_class == "provider_error" and "server_error_503" in o.error_message
    assert recent.call_count == 3 and t.repo.readings == {}


@respx.mock
async def test_empty_feature_collection_fails_and_unmatched_names_are_reported(tmp_path):
    _mock_catalogue()
    _mock_recent(collection())
    t, _ = _task(tmp_path)
    o = await t.run()
    assert o.status is RunStatus.failed and o.error_class == "timeseries_empty"

    _mock_recent(collection(feature("Egerton Road", hourly(0, 1)), feature("Somewhere Else", hourly(0, 1))))
    t2, _ = _task(tmp_path)
    o2 = await t2.run()
    assert o2.status is RunStatus.success and o2.details["unmatched_features"] == ["Somewhere Else"]
    assert o2.counts.attempted == 3 and o2.counts.completed == 1 and len(t2.repo.readings) == 1


@respx.mock
async def test_duplicate_station_names_are_dropped_from_the_request(tmp_path):
    _mock_catalogue(stations=[station(1, "Twin"), station(2, "Twin", lat=31.0), station(3, "Solo")])
    recent = _mock_recent(collection(feature("Solo", hourly(0, 1))))
    t, _ = _task(tmp_path)
    o = await t.run()
    assert o.status is RunStatus.success and o.details["duplicate_names"] == ["Twin"]
    assert b"Twin" not in recent.calls[0].request.content and set(t.repo.stations) == {station_id_for_icimod(3)}


@respx.mock
async def test_lease_held_is_skipped(tmp_path):
    _mock_catalogue()
    _mock_recent(collection(feature("Egerton Road", hourly(0, 1))))

    class DeniedLeases(FakeLeases):
        async def acquire(self, *a, **k):
            return None
    t, _ = _task(tmp_path, leases=DeniedLeases())
    o = await t.run()
    assert o.status is RunStatus.skipped and o.error_class == "lease_held" and t.client.requests_made == 0


@respx.mock
async def test_station_upsert_failure_is_partial_and_the_rest_still_ingests(tmp_path):
    _mock_catalogue()
    _mock_recent(collection(feature("Egerton Road", hourly(0, 1)), feature("Barki Road", hourly(0, 1))))
    repo = InMemoryICIMODRepository()
    orig = repo.upsert_shadow_station

    async def flaky(st, provider_id, run_id):
        if st.name == "Egerton Road":
            raise RuntimeError("boom")
        return await orig(st, provider_id, run_id)
    repo.upsert_shadow_station = flaky
    t, rec = _task(tmp_path, repo)
    o = await t.run()
    assert o.status is RunStatus.partial and o.counts.failed == 1 and rec.failures[0].entity_key == "Egerton Road"
    assert o.details["unmatched_features"] == ["Egerton Road"] and len(repo.readings) == 1
