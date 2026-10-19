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
    assert "VIIRS_SNPP_NRT" not in fires.sources_for(date(2026, 11, 2))


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


class _Http:
    def __init__(self, by_source):
        self.by_source = by_source
        self.urls = []

    async def get(self, url):
        self.urls.append(url)
        for src, resp in self.by_source.items():
            if f"/{src}/" in url:
                return resp
        return _Resp(404, "")


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
