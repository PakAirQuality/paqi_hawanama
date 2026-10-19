"""Raw payloads are redacted, hashed, archived and indexed; failures never break a run."""

import gzip
import json
from datetime import datetime, timezone

import httpx
import respx

from app.ingestion import raw_archive as ra
from tests.ingestion.fakes import make_settings


def test_redact_masks_keys_headers_and_urls():
    obj = {"key": "sk-1", "X-API-Key": "sk-2", "Authorization": "Bearer t", "nested": {"token": "x", "ok": 1},
           "url": "https://x/?city=Lahore&key=sk-3", "list": [{"api_key": "sk-4"}]}
    r = ra.redact(obj)
    assert r["key"] == "***" and r["X-API-Key"] == "***" and r["Authorization"] == "***"
    assert r["nested"] == {"token": "***", "ok": 1}
    assert r["url"] == "https://x/?city=Lahore&key=***" and r["list"] == [{"api_key": "***"}]
    assert "sk-" not in json.dumps(r)


def test_sha_is_stable_under_key_order():
    a = {"b": 1, "a": {"y": 2, "x": [1, 2]}}
    b = {"a": {"x": [1, 2], "y": 2}, "b": 1}
    assert ra.canonical_sha256(a) == ra.canonical_sha256(b)
    assert ra.canonical_sha256({"b": 2}) != ra.canonical_sha256({"b": 1})


def test_object_key_layout():
    fa = datetime(2026, 10, 15, 10, 7, 12, tzinfo=timezone.utc)
    key = ra.build_object_key("raw_payloads", "airvisual", "station", "iqair_pk/Punjab Lahore", fa, "ab" * 32)
    assert key == "raw_payloads/airvisual/station/iqair_pk_Punjab_Lahore/2026/10/15/20261015T100712Z_abababababababab.json.gz"


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upload_from_string(self, data, content_type=None):
        self.store[self.name] = data


class FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, name):
        return FakeBlob(self.store, name)


class FakeGCS:
    def __init__(self, store, fail=False):
        self.store, self.fail = store, fail

    def bucket(self, name):
        if self.fail:
            raise RuntimeError("gcs down")
        return FakeBucket(self.store)


async def test_archive_uploads_redacted_gzip_and_returns_ref(tmp_path):
    s = make_settings(tmp_path, OPS_RAW_PAYLOADS_BUCKET="raw-bucket")
    store = {}
    arch = ra.RawPayloadArchiver(s, gcs_client_factory=lambda: FakeGCS(store))
    fa = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    ref = await arch.archive(provider="airvisual", stream="station", native_id="s1",
                             payload={"current": {"pollution": {"aqius": 50}}, "key": "sk-leak"},
                             request_meta={"endpoint": "station", "params": {"key": "sk-leak", "city": "Lahore"}},
                             fetched_at=fa, http_status=200, run_id="run-1", parser_version="iqair_rows_v2")
    assert ref.archived and ref.gcs_uri.startswith("gs://raw-bucket/raw_payloads/airvisual/station/s1/2026/10/15/")
    body = json.loads(gzip.decompress(next(iter(store.values()))))
    assert body["payload"]["key"] == "***" and body["request"]["params"]["key"] == "***"
    assert body["payload_sha256"] == ref.sha256 and body["run_id"] == "run-1"
    assert "sk-leak" not in json.dumps(body)
    assert ref.prov()["sha"] == ref.sha256 and ref.prov()["pv"] == "iqair_rows_v2" and ref.prov()["archived"] is True


async def test_archive_failure_is_non_fatal(tmp_path, caplog):
    s = make_settings(tmp_path, OPS_RAW_PAYLOADS_BUCKET="raw-bucket")
    arch = ra.RawPayloadArchiver(s, gcs_client_factory=lambda: FakeGCS({}, fail=True))
    ref = await arch.archive(provider="airvisual", stream="station", native_id="s1", payload={"a": 1},
                             request_meta=None, fetched_at=datetime.now(timezone.utc), http_status=200,
                             run_id="r", parser_version="v")
    assert ref.archived is False and "gcs down" in ref.error and arch.failures == 1
    assert ref.sha256 == ra.canonical_sha256({"a": 1})


async def test_disabled_archiver_still_hashes(tmp_path):
    s = make_settings(tmp_path, RAW_ARCHIVE_ENABLED=False, OPS_RAW_PAYLOADS_BUCKET="b")
    arch = ra.RawPayloadArchiver(s, gcs_client_factory=lambda: FakeGCS({}, fail=True))
    ref = await arch.archive(provider="p", stream="s", native_id="n", payload={"a": 1}, request_meta=None,
                             fetched_at=datetime.now(timezone.utc), http_status=200, run_id=None, parser_version="v")
    assert ref.archived is False and ref.error is None and len(ref.sha256) == 64
    null = ra.NullArchiver()
    ref2 = await null.archive(provider="p", stream="s", native_id="n", payload={"a": 1}, request_meta=None,
                              fetched_at=datetime.now(timezone.utc), http_status=200, run_id=None, parser_version="v")
    assert ref2.sha256 == ref.sha256


async def test_record_writes_index_row_and_tolerates_missing_table(tmp_path):
    from tests.ingestion.fakes import FakeSessionFactory
    s = make_settings(tmp_path, OPS_RAW_PAYLOADS_BUCKET="b")
    arch = ra.RawPayloadArchiver(s, gcs_client_factory=lambda: FakeGCS({}))
    ref = await arch.archive(provider="airvisual", stream="station", native_id="s1", payload={"a": 1},
                             request_meta={"endpoint": "station"}, fetched_at=datetime.now(timezone.utc),
                             http_status=200, run_id="run-1", parser_version="v")
    sf = FakeSessionFactory()
    assert await arch.record(sf, ref) is True
    sql, params = sf.sessions[0].executed[0]
    assert "INSERT INTO ops.raw_payloads" in sql and params["sha256"] == ref.sha256 and params["archived"] is True
    assert await arch.record(FakeSessionFactory(fail_with=RuntimeError("relation does not exist")), ref) is False


@respx.mock
async def test_client_fetch_envelope_carries_status_and_time(tmp_path):
    from app.services.ingestion.iqair_service import IQAirClient
    respx.get("https://api.airvisual.com/v2/station").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {"current": {}}}))
    c = IQAirClient(settings=make_settings(tmp_path), quota=None)
    env = await c.fetch_station(station="S", city="Lahore", state="Punjab", country="Pakistan")
    assert env.http_status == 200 and env.data == {"current": {}} and env.endpoint == "station"
    assert env.fetched_at.tzinfo is not None and env.attempts == 1 and "key" not in env.params_redacted
    assert await c.get_station_data(station="S") == {"current": {}}   # legacy surface unchanged
