"""fire_aggregates: per-day build, planning, suspect days, the task and the store on a fake bucket."""

import io
import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.ingestion.runs import RunStatus
from app.services import fire_aggregates as fa
from app.services.fires import blob_paths
from tests.ingestion.fakes import CapturingRecorder, make_settings

NEW_CSV = """latitude,longitude,frp,confidence,acq_date,acq_time,acq_datetime_utc,satellite
31.5000,74.3000,12.0,n,2026-11-02,2116,2026-11-02T21:16:00Z,N20
31.5036,74.3000,20.0,h,2026-11-02,2206,2026-11-02T22:06:00Z,N21
31.6300,74.8700,55.0,h,2026-11-03,0815,2026-11-03T08:15:00Z,N20
29.6900,76.9900,8.0,l,2026-11-03,0815,2026-11-03T08:15:00Z,N20
34.0000,71.5500,30.0,n,2026-11-03,0816,2026-11-03T08:16:00Z,N21
34.5000,69.2000,5.0,n,2026-11-03,0816,2026-11-03T08:16:00Z,N21
"""
OLD_CSV = """latitude,longitude,frp,confidence,acq_date,satellite
31.5,74.3,106.3,h,2020-11-05,N
31.5,74.3,90.0,n,2020-11-05,1
"""
META = {"status": "ok", "fetched_at": "2026-11-03T12:20:00Z", "day_basis": "acq_pkt",
        "observation_period": {"start": "2026-11-02T21:16:00Z", "end": "2026-11-03T08:16:00Z"},
        "sources": [{"source": "VIIRS_NOAA20_NRT", "status": "ok", "rows": 3}, {"source": "VIIRS_NOAA21_NRT", "status": "ok", "rows": 3}]}


def test_build_day_attributes_dedups_and_rolls_up():
    b = fa.build_day(date(2026, 11, 3), NEW_CSV, META)
    det = b.detections
    assert b.info["format"] == "pkt_v2" and b.info["status"] == "ok" and b.info["rows"] == 6
    assert b.info["sources"] == ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"] and b.info["n_dedup_hn"] == 4
    assert b.info["rows_by_satellite"] == {"n20": 3, "n21": 3}
    assert det["country"].tolist() == ["PK", "PK", "IN", "IN", "PK", "XX"]
    assert det["district"].tolist()[:3] == ["Lahore", "Lahore", None] and det["province"].tolist()[2:4] == ["Punjab (IN)", "Haryana (IN)"]
    assert det["dup_group"].iloc[0] == det["dup_group"].iloc[1] and det["is_primary"].tolist()[:2] == [False, True]
    assert det["daynight"].tolist() == ["N", "N", "D", "D", "D", "D"] and det["day_basis"].iloc[0] == "acq_pkt"
    r = b.regions.set_index(["region_kind", "region"])
    pk = r.loc[("country", "Pakistan")]
    assert (pk["n_raw"], pk["n_dedup"], pk["n_dedup_hn"], pk["frp_dedup_hn"], pk["frp_max"]) == (3, 2, 2, 50.0, 30.0)
    assert (pk["n_n20_raw"], pk["n_n20_hn"], pk["frp_n20_hn"]) == (1, 1, 12.0)          # the N20 pixel of the merged pair, plus nothing else
    ind = r.loc[("country", "India (Punjab+Haryana)")]
    assert (ind["n_n20_raw"], ind["n_n20_hn"]) == (2, 1)                                 # the low-confidence Haryana row is N20 too
    ind = r.loc[("country", "India (Punjab+Haryana)")]
    assert (ind["n_raw"], ind["n_low"], ind["n_dedup_hn"], ind["n_day"]) == (2, 1, 1, 2)
    assert r.loc[("india_state", "Haryana (IN)")]["n_hn"] == 0 and r.loc[("district", "Peshawar")]["n_raw"] == 1
    assert r.loc[("province", "Khyber Pakhtunkhwa")]["frp_raw"] == 30.0 and ("country", "other in bbox") in r.index


def test_build_day_handles_the_utc_keyed_archive_format_and_empty_files():
    b = fa.build_day(date(2020, 11, 5), OLD_CSV, None)
    assert b.info["format"] == "utc_v1" and b.info["status"] == "archive" and b.info["sources"] == ["1", "N"]
    assert b.info["rows_by_satellite"] == {"n20": 1, "snpp": 1} and b.regions.iloc[0]["n_n20_hn"] == 1
    assert b.detections["day_basis"].iloc[0] == "acq_utc" and b.detections["daynight"].tolist() == [None, None]
    assert b.detections["acq_utc"].isna().all()
    assert b.info["n_dedup_hn"] == 1 and b.detections["frp"].max() == pytest.approx(106.3, abs=0.01)  # merged without times
    e = fa.build_day(date(2026, 7, 1), "latitude,longitude,frp,confidence,acq_date,acq_time,acq_datetime_utc,satellite\n", {"status": "ok"})
    assert e.info["rows"] == 0 and e.detections.empty and e.regions.empty and list(e.detections.columns) == fa.DET_COLUMNS


def test_plan_days_backfill_changed_and_recent():
    blobs = {date(2026, 10, 30): fa.BlobInfo("a", "t1"), date(2026, 10, 31): fa.BlobInfo("b", "t2"),
             date(2026, 11, 2): fa.BlobInfo("c", "t3"), date(2026, 11, 3): fa.BlobInfo("d", "t4")}
    manifest = {"days": {"2026-10-30": {"csv_updated": "t1"}, "2026-10-31": {"csv_updated": "OLD"}, "2026-11-02": {"csv_updated": "t3"}}}
    today = date(2026, 11, 4)
    assert fa.plan_days(blobs, manifest, backfill=True, today_pkt=today) == sorted(blobs)
    assert fa.plan_days(blobs, manifest, backfill=False, today_pkt=today) == [date(2026, 10, 31), date(2026, 11, 2), date(2026, 11, 3)]
    assert fa.plan_days(blobs, manifest, backfill=False, since=date(2026, 11, 3), today_pkt=today) == [date(2026, 11, 3)]
    assert fa.day_of_blob("hindcast/firms/firms_20261103.csv") == date(2026, 11, 3)
    assert fa.day_of_blob("hindcast/firms/firms_20261103.meta.json") is None and fa.day_of_blob("hindcast/firms/agg/manifest.json") is None


def test_suspect_days_flags_a_thin_peak_season_day_only():
    rows = []
    for y in (2020, 2021, 2022, 2023):
        for d in (date(y, 11, 3), date(y, 11, 5), date(y, 11, 7), date(y, 7, 10)):
            rows.append({"pk_day": d, "region_kind": "country", "region": "Pakistan", "n_raw": 4000 if d.month == 11 else 30})
    rows += [{"pk_day": date(2024, 11, 5), "region_kind": "country", "region": "Pakistan", "n_raw": 300},
             {"pk_day": date(2024, 7, 10), "region_kind": "country", "region": "Pakistan", "n_raw": 1},
             {"pk_day": date(2025, 11, 5), "region_kind": "country", "region": "Pakistan", "n_raw": 3500}]
    out = fa.suspect_days(pd.DataFrame(rows))
    assert out == [{"day": "2024-11-05", "n_raw": 300, "reference_median": 4000}]
    assert fa.suspect_days(pd.DataFrame()) == []


class _Blob:
    def __init__(self, bucket, name):
        self.b, self.name = bucket, name
        self.updated = bucket.updated.get(name)
        self.size = len(bucket.store.get(name, b""))

    def exists(self, *a):
        return self.name in self.b.store

    def download_as_text(self):
        v = self.b.store[self.name]
        return v.decode() if isinstance(v, bytes) else v

    def download_as_bytes(self):
        v = self.b.store[self.name]
        return v if isinstance(v, bytes) else v.encode()

    def upload_from_string(self, data, content_type=None):
        self.b.store[self.name] = data
        self.b.updated[self.name] = datetime.now(timezone.utc)
        self.b.writes.append(self.name)


class _Bucket:
    def __init__(self):
        self.store, self.updated, self.writes = {}, {}, []

    def blob(self, name):
        return _Blob(self, name)

    def list_blobs(self, prefix=""):
        return [_Blob(self, n) for n in sorted(self.store) if n.startswith(prefix)]

    def put_day(self, day, csv, meta=None, updated="2026-11-04T10:00:00+00:00"):
        c, m = blob_paths(day)
        self.store[c] = csv
        self.updated[c] = datetime.fromisoformat(updated)
        if meta is not None:
            self.store[m] = json.dumps(meta)


def _bucket():
    b = _Bucket()
    b.put_day(date(2020, 11, 5), OLD_CSV, updated="2026-11-04T09:00:00+00:00")
    b.put_day(date(2026, 11, 3), NEW_CSV, META)
    b.put_day(date(2026, 11, 4), "latitude,longitude,frp,confidence,acq_date,acq_time,acq_datetime_utc,satellite\n", {"status": "partial", "sources": []})
    return b


def _task(tmp_path, bucket, today=date(2026, 11, 20)):
    return fa.FireAggregateTask(settings=make_settings(tmp_path), bucket=bucket, recorder=CapturingRecorder(tmp_path / "runs"),
                                workers=2, today_pkt=today)


async def test_task_dry_run_plans_and_writes_nothing(tmp_path):
    b = _bucket()
    out = await _task(tmp_path, b).run(backfill=True, dry_run=True)
    assert out.status is RunStatus.success and out.counts.expected == 3 and b.writes == []
    assert out.details["plan"] == {"days": 3, "files": 3, "by_year": {"2020": 1, "2026": 2}}


async def test_task_backfill_then_incremental(tmp_path):
    b = _bucket()
    out = await _task(tmp_path, b).run(backfill=True)
    assert out.status is RunStatus.success and (out.counts.expected, out.counts.completed, out.counts.failed) == (3, 3, 0)
    assert out.counts.rows_fetched == 8 and out.counts.rows_written == 8 and out.details["years_written"] == [2020, 2026]
    assert set(b.writes) == {fa.year_path(2020), fa.year_path(2026), fa.DAILY_PATH, fa.MANIFEST_PATH}
    m = json.loads(b.store[fa.MANIFEST_PATH])
    assert m["schema_version"] == 3 and m["low_confidence_from"] == "2026-11-03" and m["pkt_from"] == "2026-11-03"
    assert set(m["days"]) == {"2020-11-05", "2026-11-03", "2026-11-04"} and m["consistent_satellite"] == "n20"
    assert m["days"]["2026-11-04"]["rows_by_satellite"] == {}
    assert m["days"]["2026-11-04"]["status"] == "partial" and m["days"]["2026-11-04"]["rows"] == 0
    assert m["days"]["2026-11-03"]["csv_updated"] == "2026-11-04T10:00:00+00:00"

    store = fa.AggStore(b)
    daily = store.daily_regions()
    assert daily[(daily["region_kind"] == "country") & (daily["region"] == "Pakistan")]["n_dedup_hn"].tolist() == [1, 2]
    det = store.detections(date(2026, 1, 1), date(2026, 12, 31))
    assert len(det) == 6 and det["pk_day"].iloc[0] == date(2026, 11, 3) and str(det["acq_utc"].dtype).startswith("datetime64")
    assert store.detections(date(2019, 1, 1), date(2019, 12, 31)).empty
    assert store.day_from_csv(date(2026, 11, 3)).info["n_dedup_hn"] == 4 and store.day_from_csv(date(2026, 11, 9)) is None

    # nothing changed → an all-clear run that writes nothing
    b.writes.clear()
    out2 = await _task(tmp_path, b).run(backfill=False)
    assert out2.status is RunStatus.success and out2.details["note"] == "no day files changed" and b.writes == []
    # the last four Pakistan days are always rebuilt (late NRT rows), even when the CSV did not change
    out2b = await _task(tmp_path, b, today=date(2026, 11, 5)).run(backfill=False)
    assert out2b.details["days_built"] == 2 and out2b.details["years_written"] == [2026]
    b.writes.clear()

    # one old day re-fetched → only its year and the daily table are rewritten; the row is replaced, not duplicated
    b.put_day(date(2020, 11, 5), OLD_CSV + "31.9,74.9,10.0,n,2020-11-05,N\n", updated="2026-11-05T01:00:00+00:00")
    out3 = await _task(tmp_path, b).run(backfill=False)
    assert out3.status is RunStatus.success and out3.details["years_written"] == [2020] and out3.details["days_built"] == 1
    store2 = fa.AggStore(b)
    det20 = store2.detections(date(2020, 1, 1), date(2020, 12, 31))
    assert len(det20) == 3
    daily2 = store2.daily_regions()
    assert daily2[(daily2["pk_day"] == date(2020, 11, 5)) & (daily2["region_kind"] == "country")]["n_raw"].sum() == 3   # the new row is across the border
    assert daily2[daily2["region_kind"] == "country"]["pk_day"].nunique() == 2

    # a manifest from an older schema makes the next incremental run a full rebuild
    m = json.loads(b.store[fa.MANIFEST_PATH])
    m["schema_version"] = 1
    b.store[fa.MANIFEST_PATH] = json.dumps(m)
    b.writes.clear()
    out4 = await _task(tmp_path, b).run(backfill=False)
    assert out4.details["schema_upgrade"] == {"from": 1, "to": 3} and out4.details["days_built"] == 3 and set(out4.details["years_written"]) == {2020, 2026}
    assert json.loads(b.store[fa.MANIFEST_PATH])["schema_version"] == 3


def test_store_fills_missing_metrics_from_an_older_build():
    b = _bucket()
    old = pd.DataFrame([{"pk_day": date(2026, 11, 3), "region_kind": "country", "region": "Pakistan", "n_raw": 3, "n_dedup_hn": 2}])
    fa._write_parquet(b, fa.DAILY_PATH, old)
    b.store[fa.MANIFEST_PATH] = json.dumps({"schema_version": 1, "built_at": "x", "days": {}})
    df = fa.AggStore(b).daily_regions()
    assert set(fa.REGION_METRICS) <= set(df.columns) and pd.isna(df["n_n20_hn"].iloc[0]) and df["n_dedup_hn"].iloc[0] == 2


async def test_task_reports_a_broken_day_as_partial_and_all_broken_as_failed(tmp_path, monkeypatch):
    b = _bucket()
    real = fa.build_day

    def boom(day, text, meta, idx=None, classifier=None):
        if day == date(2026, 11, 3):
            raise ValueError("bad csv")
        return real(day, text, meta, idx, classifier)
    monkeypatch.setattr(fa, "build_day", boom)
    out = await _task(tmp_path, b).run(backfill=True)
    assert out.status is RunStatus.partial and (out.counts.completed, out.counts.failed) == (2, 1)
    assert out.details["failures"] == [{"day": "2026-11-03", "error": "ValueError: bad csv"}]
    assert "2026-11-03" not in json.loads(b.store[fa.MANIFEST_PATH])["days"]       # left for the next run

    monkeypatch.setattr(fa, "build_day", lambda *a, **k: (_ for _ in ()).throw(ValueError("all bad")))
    out = await _task(tmp_path, _bucket()).run(backfill=True)
    assert out.status is RunStatus.failed and out.error_class == "all_days_failed"
