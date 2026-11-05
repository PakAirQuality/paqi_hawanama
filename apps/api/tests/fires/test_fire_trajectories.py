"""fire_trajectories: planning, CONTROL/SETUP rendering, tdump parsing, fire matching, sector agreement, the dry-run task."""

import json
from datetime import date, datetime

import pandas as pd
import pytest

from app.ingestion.runs import RunStatus
from app.services import fire_aggregates as fa
from app.services import fire_trajectories as ft
from tests.copilot.test_fire_analytics import A, B, D3, META, _csv
from tests.fires.test_fire_classify import _inputs
from tests.ingestion.fakes import CapturingRecorder, make_settings

NOW = datetime(2026, 11, 5, 14, 20)

TDUMP = """     2     1
    GFSG    26    11     3     0     0
    GFSG    26    11     4     0     0
     2 BACKWARD OMEGA
    26    11     5    12    31.520    74.359   100.0
    26    11     5    12    31.520    74.359   500.0
     2 MIXDEPTH TERR_MSL
     1     1    26    11     5    12     0     0     0.0   31.520   74.359   100.0   820.0   214.0
     2     1    26    11     5    12     0     0     0.0   31.520   74.359   500.0   820.0   214.0
     1     1    26    11     5    11     0     1    -1.0   31.560   74.300    95.0   900.0   212.0
     2     1    26    11     5    11     0     1    -1.0   31.600   74.250   480.0   900.0   212.0
     1     1    26    11     4    12     0    24   -24.0   31.900   73.900    60.0  1200.0   205.0
     2     1    26    11     4    12     0    24   -24.0   32.400   73.500   700.0  1200.0   205.0
"""


def test_plan_runs_backward_ensemble_and_forward():
    clusters = pd.DataFrame([{"lat": 31.7, "lon": 74.1, "frp_mw": 300.0, "n": 4, "start_utc": pd.Timestamp("2026-11-05T08:15"), "district": "Sheikhupura", "country": "Pakistan"}])
    runs = ft.plan_runs(NOW, clusters)
    kinds = [r.kind for r in runs]
    assert kinds.count("backward") == 8 and kinds.count("ensemble") == 2 and kinds.count("forward") == 1
    b = [r for r in runs if r.kind == "backward" and r.name == "Lahore"]
    assert [r.start_utc.hour for r in b] == [12, 6, 0, 18] and b[0].hours == -72 and b[0].met_files == ["20261102_gfs0p25", "20261103_gfs0p25", "20261104_gfs0p25", "20261105_gfs0p25"]
    e = next(r for r in runs if r.kind == "ensemble" and r.name == "Delhi")
    assert e.start_utc == datetime(2026, 11, 6, 12) and e.met_files[-1] == "hysplit.t12z.gfs0p25f" and (e.lat, e.lon) == ft.RECEPTORS["Delhi"]
    f = next(r for r in runs if r.kind == "forward")
    assert f.hours == 72 and f.heights == (100.0,) and f.start_utc == datetime(2026, 11, 5, 8, 15) and "300 MW" in f.note
    assert len(ft.plan_runs(NOW, None)) == 10


def test_crop_clusters_from_the_store():
    ci = _inputs(sources=[B])
    b = fa.build_day(D3, _csv(D3, [(A, 50.0, "h", "N20", "0815"), (A, 45.0, "h", "N21", "0905"), (B, 20.0, "n", "N20", "0815")]), META, None, ci)
    c = ft.crop_clusters(b.detections, D3)
    assert len(c) == 1 and c.iloc[0]["frp_mw"] == 50.0 and c.iloc[0]["n"] == 1 and c.iloc[0]["district"] == "Sheikhpura"
    assert pd.Timestamp(c.iloc[0]["start_utc"]).hour == 8
    assert ft.crop_clusters(pd.DataFrame(), D3).empty and ft.crop_clusters(b.detections, date(2020, 1, 1)).empty


def test_control_and_setup_rendering():
    r = ft.Run("backward", "Lahore", 31.52, 74.36, datetime(2026, 11, 5, 12), -72, met_files=["20261104_gfs0p25", "20261105_gfs0p25"])
    ctl = ft.render_control(r, "/met/gfs0p25")
    lines = ctl.splitlines()
    assert lines[0] == "26 11 05 12" and lines[1] == "3" and lines[2] == "31.5200 74.3600 100.0" and lines[5] == "-72"
    assert lines[7] == "10000.0" and lines[8] == "2" and lines[9] == "/met/gfs0p25/" and lines[10] == "20261104_gfs0p25" and lines[-1] == "tdump"
    fwd = ft.Run("forward", "cluster-00", 31.7, 74.1, datetime(2026, 11, 5, 8), 72, heights=(100.0,), met_files=["x"])
    assert ft.render_control(fwd, "/met/").splitlines()[3] == "72"
    with pytest.raises(ValueError):
        ft.render_control(r, "/" + "m" * 80)
    assert "tm_mixd = 1" in ft.render_setup() and "dxf" not in ft.render_setup() and "dxf = 1.0" in ft.render_setup(ensemble=True)


def test_tdump_parsing_matching_and_sectors():
    traj = ft.parse_tdump(TDUMP)
    assert len(traj) == 6 and set(traj["traj_id"]) == {1, 2} and traj["mixdepth"].iloc[0] == 820.0 and traj["terr_msl"].iloc[0] == 214.0
    assert traj["time"].iloc[-1] == datetime(2026, 11, 4, 12) and traj["age_h"].iloc[-1] == -24.0
    det = pd.DataFrame([{"lat": 31.9, "lon": 73.9, "frp": 40.0, "district": "Hafizabad", "acq_utc": pd.Timestamp("2026-11-04T12:30")},
                        {"lat": 32.4, "lon": 73.5, "frp": 20.0, "district": "Gujrat", "acq_utc": pd.Timestamp("2026-11-04T18:00")},     # 6 h off: no match
                        {"lat": 31.56, "lon": 74.30, "frp": 9.0, "district": "Lahore", "acq_utc": pd.NaT}])                              # no time: matched by place
    m = ft.match_fires(traj, det)
    # the timeless Lahore row sits within 10 km of both trajectories at ages 0 and -1 h; Hafizabad only at -24 h on trajectory 1
    assert len(m) == 5 and set(zip(m["traj_id"], m["age_h"])) == {(1, 0.0), (2, 0.0), (1, -1.0), (2, -1.0), (1, -24.0)}
    assert not any("Gujrat" in d for d in m["districts"]) and m[m["age_h"] == -24.0]["districts"].iloc[0] == ["Hafizabad"]
    # a point above the mixed layer never matches
    high = traj.copy()
    high.loc[high["traj_id"] == 1, "height_agl"] = 2000.0
    assert (ft.match_fires(high, det)["traj_id"] == 2).all()
    s = ft.sector_agreement(traj, 31.52, 74.359, 24)
    assert s["n"] == 2 and s["modal"] == "NW" and s["agreement"] == 1.0
    assert ft.sector_agreement(traj, 31.52, 74.359, 48)["n"] == 0
    assert ft.status(None) == "not_run" and ft.status({"generated_at": "2026-11-05T12:00:00Z"}, datetime(2026, 11, 5, 14, tzinfo=__import__("datetime").timezone.utc)) == "ok"
    assert ft.status({"generated_at": "2026-11-05T00:00:00Z"}, datetime(2026, 11, 5, 14, tzinfo=__import__("datetime").timezone.utc)) == "stale"


class _Blob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def exists(self):
        return self.name in self.store

    def upload_from_string(self, data, content_type=None):
        self.store[self.name] = data


class _Bucket:
    def __init__(self):
        self.store = {f"{ft.MET_PREFIX}/20261104_gfs0p25": b"x"}

    def blob(self, name):
        return _Blob(self.store, name)


class _Store:
    def __init__(self, det):
        self._det = det

    def detections(self, start, end):
        return self._det


async def test_task_dry_run_plans_without_a_binary(tmp_path, monkeypatch):
    monkeypatch.delenv("HYSPLIT_EXEC", raising=False)
    ci = _inputs()
    b = fa.build_day(date(2026, 11, 4), _csv(date(2026, 11, 4), [(A, 50.0, "h", "N20", "0815")]), META, None, ci)
    bucket = _Bucket()
    task = ft.FireTrajectoryTask(settings=make_settings(tmp_path), bucket=bucket, recorder=CapturingRecorder(tmp_path / "runs"), store=_Store(b.detections),
                                 now_utc=datetime(2026, 11, 5, 14, 20, tzinfo=__import__("datetime").timezone.utc))
    out = await task.run(dry_run=True)
    assert out.status is RunStatus.success and out.details["status"] == "dry_run" and out.details["binary"] is None and out.details["clusters"] == 1
    assert out.details["runs"] == 11 and "20261102_gfs0p25" in out.details["met_missing"] and "20261104_gfs0p25" not in out.details["met_missing"]
    assert f"{ft.OUT_PREFIX}/plan_latest.json" not in bucket.store and task.last_plan["control_example"].startswith("26 11 05 12\n3\n")
    out2 = await task.run(dry_run=False)
    assert out2.status is RunStatus.success and json.loads(bucket.store[f"{ft.OUT_PREFIX}/plan_latest.json"])["status"] == "dry_run"
