"""Fire detections: Pakistan-day keying, status semantics, no silent fallback."""

import json
from datetime import date, datetime, timezone

import pytest

from app.services import fires

RAW = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
31.5,74.3,330.1,0.4,0.4,2026-10-16,2045,N20,VIIRS,n,2.0NRT,290.1,12.34,N
31.6,74.4,330.1,0.4,0.4,2026-10-16,0815,N21,VIIRS,h,2.0NRT,290.1,55.0,D
"""


def test_parse_resolves_utc_time_and_pakistan_day():
    rows = fires.parse_firms_csv(RAW)
    assert len(rows) == 2
    night, day = rows
    assert night["acq_datetime_utc"] == "2026-10-16T20:45:00Z"
    # 20:45 UTC is 01:45 the next day in Pakistan
    assert fires.pk_day_of(night) == "2026-10-17"
    assert fires.pk_day_of(day) == "2026-10-16"
    assert night["frp"] == 12.3


def test_sources_drop_snpp_after_its_end_date():
    assert "VIIRS_SNPP_NRT" in fires.sources_for(date(2026, 10, 18))
    assert "VIIRS_SNPP_NRT" in fires.sources_for(date(2026, 10, 31))
    assert "VIIRS_SNPP_NRT" not in fires.sources_for(date(2026, 11, 1))
    assert "VIIRS_SNPP_NRT" not in fires.sources_for(date(2026, 11, 2))
    assert fires.sources_for(date(2026, 11, 2)) == ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]


def _store(files):
    return lambda path: files.get(path)


def test_feature_collection_statuses():
    csv_path, meta_path = fires.blob_paths(date(2026, 10, 17))
    simplified = fires.rows_to_csv(fires.parse_firms_csv(RAW))
    meta_ok = json.dumps({"status": "ok", "fetched_at": "2026-10-17T06:20:00Z", "day_basis": "acq_pkt",
                          "sources": [{"source": "VIIRS_NOAA20_NRT", "status": "ok", "rows": 2}]})

    fc = fires.build_feature_collection("2026-10-17", _store({csv_path: simplified, meta_path: meta_ok}))
    assert fc["status"] == "ok" and fc["count"] == 2 and fc["date"] == "2026-10-17"
    assert fc["last_successful_fetch"] == "2026-10-17T06:20:00Z"
    assert fc["fetched_age_hours"] is not None and fc["fetched_age_hours"] > 0
    assert fires._age_hours("2026-10-17T06:20:00Z", now=datetime(2026, 10, 17, 9, 50, tzinfo=timezone.utc)) == 3.5
    assert fc["features"][0]["properties"]["acq_datetime_utc"]

    header_only = fires.rows_to_csv([])
    fc = fires.build_feature_collection("2026-10-17", _store({csv_path: header_only, meta_path: meta_ok}))
    assert fc["status"] == "empty" and fc["features"] == []

    meta_partial = json.dumps({"status": "partial", "sources": [{"source": "VIIRS_NOAA21_NRT", "status": "error", "error": "HTTP 503"}]})
    fc = fires.build_feature_collection("2026-10-17", _store({csv_path: simplified, meta_path: meta_partial}))
    assert fc["status"] == "partial"

    # Requested day missing, previous day present: stale, and the date names the day served
    fc = fires.build_feature_collection("2026-10-18", _store({csv_path: simplified, meta_path: meta_ok}))
    assert fc["status"] == "stale" and fc["date"] == "2026-10-17" and fc["requested_date"] == "2026-10-18"

    fc = fires.build_feature_collection("2026-10-25", _store({csv_path: simplified}))
    assert fc["status"] == "unavailable" and fc["features"] == []

    with pytest.raises(ValueError):
        fires.build_feature_collection("yesterday", _store({}))


class _Resp:
    def __init__(self, status_code, text):
        self.status_code, self.text = status_code, text


KEY_OK = '{ "transaction_limit" : 5000, "current_transactions": 3, "transaction_interval" : "10 minutes" }'


class _Http:
    """by_source maps a FIRMS source to a response (or a list of responses, one per attempt);
    the key-status call answers `key_status` (valid by default)."""

    def __init__(self, by_source, key_status=KEY_OK):
        self.by_source = by_source
        self.key_status = key_status
        self.urls = []
        self.key_calls = 0

    async def get(self, url, params=None):
        if "mapkey_status" in url:
            self.key_calls += 1
            assert params and "MAP_KEY" in params
            return _Resp(200, self.key_status)
        self.urls.append(url)
        for src, resp in self.by_source.items():
            if f"/{src}/" in url:
                if isinstance(resp, list):
                    return resp.pop(0)
                return resp
        return _Resp(404, "")


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    async def instant(_s):
        return None
    monkeypatch.setattr(fires, "_sleep", instant)


class _Blob:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def upload_from_string(self, data, content_type=None):
        self.store[self.path] = data


class _Bucket:
    def __init__(self):
        self.store = {}

    def blob(self, path):
        return _Blob(self.store, path)


@pytest.mark.asyncio
async def test_ingest_window_rekeys_days_and_records_source_failures():
    http = _Http({
        "VIIRS_NOAA20_NRT": _Resp(200, RAW),
        "VIIRS_NOAA21_NRT": _Resp(200, "Invalid MAP_KEY."),
        "VIIRS_SNPP_NRT": _Resp(503, ""),
    })
    bucket = _Bucket()
    now = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)
    out = await fires.ingest_window(http=http, key="k", bucket=bucket, gcs_client=None, now_utc=now, window_days=2)

    assert [s.status for s in out.sources] == ["ok", "error", "error"]
    assert out.sources[1].error.startswith("Invalid MAP_KEY")
    assert all("/60,23,78,37/2/2026-10-16" in u for u in http.urls)  # area API, west,south,east,north, 2 days
    # Pakistan days 2026-10-17 (fully covered) is written; the night fire landed there
    csv17, meta17 = fires.blob_paths(date(2026, 10, 17))
    assert "2026-10-16T20:45:00Z" in bucket.store[csv17]
    meta = json.loads(bucket.store[meta17])
    assert meta["status"] == "partial" and meta["day_basis"] == "acq_pkt" and meta["count"] == 1
    assert out.per_day["2026-10-17"]["written"] is True


@pytest.mark.asyncio
async def test_invalid_key_fails_fast_without_area_requests():
    http = _Http({"VIIRS_NOAA20_NRT": _Resp(200, RAW)},
                 key_status="MAP_KEY is invalid or your have exceeded your transaction/time limit.")
    bucket = _Bucket()
    out = await fires.ingest_window(http=http, key="dead", bucket=bucket, gcs_client=None,
                                    now_utc=datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc), window_days=3)
    assert out.key["status"] == "invalid" and "dead" not in json.dumps(out.key)
    assert out.status == "unavailable"
    assert http.urls == [] and bucket.store == {}          # no budget spent, nothing overwritten
    assert all(s.error == "invalid_key" for s in out.sources)


@pytest.mark.asyncio
async def test_all_sources_failing_keeps_csv_and_marks_sidecar_unavailable():
    now = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)
    bucket = _Bucket()
    good = await fires.ingest_window(http=_Http({"VIIRS_NOAA20_NRT": _Resp(200, RAW), "VIIRS_NOAA21_NRT": _Resp(200, RAW),
                                                 "VIIRS_SNPP_NRT": _Resp(200, RAW)}),
                                     key="k", bucket=bucket, gcs_client=None, now_utc=now, window_days=2)
    assert good.status == "ok" and good.rows_fetched == 6 and good.rows_written == 3
    assert good.latest_acq_utc == datetime(2026, 10, 16, 20, 45, tzinfo=timezone.utc)
    csv17, meta17 = fires.blob_paths(date(2026, 10, 17))
    before = bucket.store[csv17]

    bad = await fires.ingest_window(http=_Http({"VIIRS_NOAA20_NRT": _Resp(503, ""), "VIIRS_NOAA21_NRT": _Resp(500, ""),
                                                "VIIRS_SNPP_NRT": _Resp(502, "")}),
                                    key="k", bucket=bucket, gcs_client=None, now_utc=now, window_days=2)
    assert bad.status == "unavailable" and bad.rows_written == 0
    assert bucket.store[csv17] == before                     # detections kept
    assert json.loads(bucket.store[meta17])["status"] == "unavailable"
    fc = fires.build_feature_collection("2026-10-17", _store(bucket.store))
    assert fc["status"] == "unavailable"                     # sidecar wins over the kept file


@pytest.mark.asyncio
async def test_fetch_source_retries_once_on_5xx_and_429():
    http = _Http({"VIIRS_NOAA20_NRT": [_Resp(503, ""), _Resp(200, RAW)],
                  "VIIRS_NOAA21_NRT": [_Resp(429, ""), _Resp(429, "")],
                  "VIIRS_SNPP_NRT": [_Resp(400, "Invalid MAP_KEY."), _Resp(200, RAW)]})
    out = await fires.ingest_window(http=http, key="k", bucket=_Bucket(), gcs_client=None,
                                    now_utc=datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc), window_days=2)
    by = {s.source: s for s in out.sources}
    assert by["VIIRS_NOAA20_NRT"].status == "ok"            # recovered on the retry
    assert by["VIIRS_NOAA21_NRT"].error == "HTTP 429"       # retried, still throttled
    assert by["VIIRS_SNPP_NRT"].error == "HTTP 400"         # 4xx is not retried
    assert sum(1 for u in http.urls if "SNPP" in u) == 1
    assert out.status == "partial"


@pytest.mark.asyncio
async def test_window_is_capped_at_the_firms_maximum():
    http = _Http({"VIIRS_NOAA20_NRT": _Resp(200, RAW), "VIIRS_NOAA21_NRT": _Resp(200, RAW), "VIIRS_SNPP_NRT": _Resp(200, RAW)})
    await fires.ingest_window(http=http, key="k", bucket=_Bucket(), gcs_client=None,
                              now_utc=datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc), window_days=30)
    assert all("/10/2026-10-08" in u for u in http.urls)


@pytest.mark.asyncio
async def test_check_key_reports_budget_and_never_echoes_the_key():
    ok = await fires.check_key(_Http({}), "secret-key")
    assert ok == {"status": "ok", "transaction_limit": 5000, "current_transactions": 3, "transaction_interval": "10 minutes"}
    bad = await fires.check_key(_Http({}, key_status="MAP_KEY secret-key is invalid"), "secret-key")
    assert bad["status"] == "invalid" and "secret-key" not in bad["error"]
