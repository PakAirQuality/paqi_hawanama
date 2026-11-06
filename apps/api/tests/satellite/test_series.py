"""satellite_series: the plan, the row shaping, the merge, the task against a fake Earth Engine and the reader."""

import io
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from app.services import satellite_series as ss
from app.services import satellite_climatology as sc
from app.services.satellite_regions import REGION_IDS
from tests.ingestion.fakes import CapturingRecorder

TODAY = date(2026, 11, 7)


class NotFound(Exception):
    """Named like google.api_core.exceptions.NotFound, which the store helpers treat as absent."""


class FakeBucket:
    """In-memory GCS bucket: text and bytes bodies."""

    def __init__(self):
        self.objects = {}

    def blob(self, path):
        store = self.objects

        class B:
            def upload_from_string(self, body, content_type=None):
                store[path] = body

            def download_as_text(self):
                if path not in store:
                    raise NotFound(path)
                b = store[path]
                return b.decode() if isinstance(b, bytes) else b

            def download_as_bytes(self):
                if path not in store:
                    raise NotFound(path)
                b = store[path]
                return b if isinstance(b, bytes) else b.encode()

            def exists(self):
                return path in store
        return B()


class FakeEE:
    """Canned reductions: a value per region and product; some days unpublished; optional failures."""

    def __init__(self, *, unpublished=(), fail_days=(), value=1e-4):
        self.unpublished = set(unpublished)
        self.fail_days = set(fail_days)
        self.value = value
        self.calls = []
        self.pings = 0

    def ping(self):
        self.pings += 1
        return 1

    def n_possible(self, kind, day):
        return {r: (100 if kind == "tropomi" else 900) for r in REGION_IDS}

    def day_regions(self, kind, day, products=None):
        self.calls.append((kind, day))
        if day in self.fail_days:
            raise RuntimeError("EE boom")
        if day in self.unpublished:
            return []
        rows = []
        if kind == "tropomi":
            for i, r in enumerate(REGION_IDS):
                for q in ss.KINDS["tropomi"]:
                    n = 0 if (q == "no2" and r == "af_east") else 80
                    rows.append({"region": r, "product": q, "platform": None, "value": self.value * (1 + i) if n else None, "n_valid": n})
        else:
            for r in REGION_IDS:
                for plat in ("terra", "aqua"):
                    for q in ("aod550", "aod470"):
                        rows.append({"region": r, "product": q, "platform": plat, "value": 0.5 if plat == "terra" else 0.3, "n_valid": 300 if plat == "terra" else 100})
        return rows


def _task(bucket, ee, tmp_path, **kw):
    rec = CapturingRecorder(tmp_path)
    return ss.SatelliteSeriesTask(settings=type("S", (), {"INGEST_OUT_DIR": str(tmp_path), "EE_PROJECT": "hawanama-2"})(),
                                  bucket=bucket, recorder=rec, ee_client=ee, workers=2, today=TODAY, retries=2, backoff_s=0.0, **kw), rec


def _read_parquet(bucket, path):
    return pd.read_parquet(io.BytesIO(bucket.objects[path]))


# ── pure pieces ───────────────────────────────────────────────────────────────

def test_plan_days_fetches_missing_days_and_always_the_recent_window():
    have = {p: {TODAY - pd.Timedelta(days=k).to_pytimedelta() for k in range(1, 31)} for p in ss.PRODUCTS}
    have["co"].discard(TODAY - pd.Timedelta(days=20).to_pytimedelta())        # one product lacks one old day
    plan = ss.plan_days(have, today=TODAY, kinds=["tropomi", "maiac"])
    t = plan["tropomi"]
    assert t[0] == TODAY - pd.Timedelta(days=20).to_pytimedelta()               # the gap
    assert t[1:] == [TODAY - pd.Timedelta(days=k).to_pytimedelta() for k in range(7, 0, -1)]   # the recent 7, oldest first
    assert plan["maiac"] == [TODAY - pd.Timedelta(days=k).to_pytimedelta() for k in range(7, 0, -1)]
    # a long gap is capped per run, oldest first, and since/until bound the window
    plan = ss.plan_days({}, today=TODAY, kinds=["maiac"], since=date(2026, 1, 1), until=date(2026, 6, 30))
    assert len(plan["maiac"]) == ss.MAX_DAYS_PER_RUN and plan["maiac"][0] == date(2026, 1, 1)
    plan = ss.plan_days(have, today=TODAY, kinds=["tropomi"], force=True, lookback=10)
    assert len(plan["tropomi"]) == 10
    assert ss.plan_days({}, today=TODAY, kinds=["maiac"], until=date(2030, 1, 1), lookback=3)["maiac"][-1] == TODAY - pd.Timedelta(days=1).to_pytimedelta()


def test_rows_from_results_and_merge_series():
    at = datetime(2026, 11, 7, 1, 40, tzinfo=timezone.utc)
    rows = [{"region": "lahore", "product": "no2", "platform": None, "value": 2e-4, "n_valid": 80},
            {"region": "af_east", "product": "no2", "platform": None, "value": None, "n_valid": 0},
            {"region": "lahore", "product": "aod550", "platform": "terra", "value": 0.5, "n_valid": 300}]
    frames = ss.rows_from_results(date(2026, 11, 1), rows, {"lahore": 100, "af_east": 100}, at)   # one n_possible per region (per kind in the task)
    no2 = frames["no2"]
    assert list(no2.columns) == ss.SERIES_COLUMNS
    assert no2.loc[no2["region"] == "lahore", "coverage"].iloc[0] == 0.8
    assert np.isnan(no2.loc[no2["region"] == "af_east", "value"].iloc[0]) and no2.loc[no2["region"] == "af_east", "coverage"].iloc[0] == 0.0
    assert frames["aod550"]["platform"].iloc[0] == "terra" and frames["aod550"]["n_valid"].iloc[0] == 300
    old = frames["no2"].assign(value=[9e-4, 9e-4], source="zarr_export")
    new = frames["no2"].iloc[:1]
    merged = ss.merge_series(old, new)
    assert len(merged) == 2
    assert merged.loc[merged["region"] == "lahore", "source"].iloc[0] == "ee_direct"       # replaced
    assert merged.loc[merged["region"] == "af_east", "source"].iloc[0] == "zarr_export"    # kept
    assert ss.days_present(merged) == {date(2026, 11, 1)}
    assert ss.days_present(None) == set() and ss.merge_series(None, new).equals(new.reset_index(drop=True)[ss.SERIES_COLUMNS])


def test_combine_platforms_weights_by_valid_pixels():
    df = pd.DataFrame([
        {"day": date(2026, 11, 1), "region": "lahore", "platform": "terra", "value": 0.5, "n_valid": 300, "n_possible": 900, "coverage": 300 / 900, "source": "ee_direct", "fetched_at": None},
        {"day": date(2026, 11, 1), "region": "lahore", "platform": "aqua", "value": 0.3, "n_valid": 100, "n_possible": 900, "coverage": 100 / 900, "source": "ee_direct", "fetched_at": None},
    ])
    out = ss.combine_platforms(df)
    assert len(out) == 1
    assert abs(out["value"].iloc[0] - (0.5 * 300 + 0.3 * 100) / 400) < 1e-12
    assert out["n_valid"].iloc[0] == 400 and out["n_possible"].iloc[0] == 1800 and abs(out["coverage"].iloc[0] - 400 / 1800) < 1e-12


# ── the task ──────────────────────────────────────────────────────────────────

async def test_a_run_writes_the_series_manifest_regions_and_findings_and_a_second_run_is_a_no_op(tmp_path):
    bucket = FakeBucket()
    ee = FakeEE(unpublished={TODAY - pd.Timedelta(days=1).to_pytimedelta(), TODAY - pd.Timedelta(days=2).to_pytimedelta()})
    task, rec = _task(bucket, ee, tmp_path)
    out = await task.run(days=10)
    assert out.status.value == "success", out.to_dict()
    c = out.counts
    assert c.expected == 20 and c.attempted == 20 and c.completed == 16 and c.skipped == 4 and c.failed == 0
    assert set(bucket.objects) >= {ss.MANIFEST_PATH, ss.REGIONS_PATH, ss.FINDINGS_LATEST_PATH, ss.series_path("no2"), ss.series_path("aod550")}
    no2 = _read_parquet(bucket, ss.series_path("no2"))
    assert len(no2) == 8 * 24 and set(no2["source"]) == {"ee_direct"}
    assert no2.loc[no2["region"] == "af_east", "n_valid"].eq(0).all()
    aod = _read_parquet(bucket, ss.series_path("aod550"))
    assert len(aod) == 8 * 24 * 2 and set(aod["platform"]) == {"terra", "aqua"}
    m = json.loads(bucket.objects[ss.MANIFEST_PATH])
    assert m["schema_version"] == ss.SCHEMA_VERSION and m["products"]["no2"]["days"] == 8
    assert m["products"]["no2"]["pending"] == [(TODAY - pd.Timedelta(days=2).to_pytimedelta()).isoformat(), (TODAY - pd.Timedelta(days=1).to_pytimedelta()).isoformat()]
    assert m["n_possible"]["tropomi"]["lahore"] == 100 and len(m["regions"]) == 24
    geo = json.loads(bucket.objects[ss.REGIONS_PATH])
    assert len(geo["features"]) == 24
    f = json.loads(bucket.objects[ss.FINDINGS_LATEST_PATH])
    assert f["regions"]["city:lahore:r25"]["no2"]["days_assessable"] == 5          # 7-day window, 2 days pending
    assert f["regions"]["af_east"]["no2"]["days_assessable"] == 0
    assert "aai" in f["definitions"] and rec.finished is out

    # the second run: the 8 recent days are re-fetched (expected 7 per kind... the oldest fetched day is now outside the recent window)
    ee.calls.clear()
    task2, _ = _task(bucket, ee, tmp_path)
    out2 = await task2.run(days=10)
    assert out2.status.value == "success"
    assert out2.counts.expected == 14 and sorted(set(k for k, _ in ee.calls)) == ["maiac", "tropomi"]
    no2b = _read_parquet(bucket, ss.series_path("no2"))
    assert len(no2b) == len(no2)                                               # replaced, not duplicated
    assert json.loads(bucket.objects[ss.MANIFEST_PATH])["products"]["no2"]["days"] == 8


async def test_dry_run_pings_earth_engine_and_writes_nothing(tmp_path):
    bucket = FakeBucket()
    ee = FakeEE()
    task, _ = _task(bucket, ee, tmp_path)
    out = await task.run(dry_run=True, days=3)
    assert out.status.value == "skipped" or out.counts.skipped == out.counts.expected
    assert ee.pings == 1 and ee.calls == [] and bucket.objects == {}
    assert out.details["plan"]["tropomi"]["days"] == 3 and out.details["regions_changed"] is True


async def test_failed_days_make_the_run_partial_and_are_retried(tmp_path):
    bucket = FakeBucket()
    bad = TODAY - pd.Timedelta(days=3).to_pytimedelta()
    ee = FakeEE(fail_days={bad})
    task, _ = _task(bucket, ee, tmp_path)
    out = await task.run(kind="tropomi", days=5)
    assert out.status.value == "partial" and out.error_class == "some_days_failed"
    assert out.counts.failed == 1 and out.counts.completed == 4
    assert out.details["failures"][0]["day"] == bad.isoformat() and "EE boom" in out.details["failures"][0]["error"]
    assert ee.calls.count(("tropomi", bad)) == 2                                   # retried once
    out2 = await task.run(kind="bogus")
    assert out2.status.value == "failed" and out2.error_class == "bad_kind"


# ── the reader ────────────────────────────────────────────────────────────────

def _store_with_history(bucket):
    """Two years of synthetic NO2 for Lahore with a climatology, then the reader."""
    days = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    rows = [{"day": d.date(), "region": "city:lahore:r25", "platform": None, "value": 1e-4 * (1 + 0.5 * np.sin(2 * np.pi * d.dayofyear / 366)) * (1.0 if d.year == 2024 else 1.2),
             "n_valid": 80, "n_possible": 100, "coverage": 0.8, "source": "zarr_export", "fetched_at": None} for d in days]
    # a cloudy stretch: no coverage in the last week of 2025
    for r in rows[-7:]:
        r.update(n_valid=5, coverage=0.05)
    df = pd.DataFrame(rows, columns=ss.SERIES_COLUMNS)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    bucket.objects[ss.series_path("no2")] = buf.getvalue()
    table = sc.build_table(df.set_index(pd.to_datetime(df["day"]).dt.tz_localize("UTC"))["value"])
    table.insert(0, "region", "city:lahore:r25")
    buf = io.BytesIO()
    table.to_parquet(buf, index=False)
    bucket.objects[ss.clim_path("no2")] = buf.getvalue()
    bucket.objects[ss.MANIFEST_PATH] = json.dumps({"built_at": "x", "products": {"no2": {"last_day": "2025-12-31"}}})
    return ss.SatStore(bucket)


def test_the_reader_gives_window_means_coverage_and_anomalies():
    store = _store_with_history(FakeBucket())
    w = store.window("no2", "city:lahore:r25", date(2025, 3, 1), date(2025, 3, 14))
    assert w["days_requested"] == 14 and w["days_with_data"] == 14 and w["days_assessable"] == 14
    assert w["mean"] is not None and w["units"] == "mol m-2"
    assert w["z_mean"] is not None and w["z_mean"] > 0                 # 2025 runs 20 % above 2024's baseline
    assert 115 < w["percent_of_normal"] < 125
    cloudy = store.window("no2", "city:lahore:r25", date(2025, 12, 25), date(2025, 12, 31))
    assert cloudy["days_with_data"] == 7 and cloudy["days_assessable"] == 0 and cloudy["mean"] is None
    assert cloudy["last_day"] == "2025-12-31"
    nothing = store.window("no2", "province:sindh", date(2025, 3, 1), date(2025, 3, 2))
    assert nothing["days_with_data"] == 0 and nothing["mean"] is None
    d = store.daily("no2", "city:lahore:r25", date(2025, 3, 1), date(2025, 3, 3))
    assert list(d["day"]) == [date(2025, 3, 1), date(2025, 3, 2), date(2025, 3, 3)] and d["z"].notna().all()
    assert store.series("aod550").empty and store.climatology("aod550") is None and store.adjudicated() == []
