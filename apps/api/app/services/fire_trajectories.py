"""
Operational HYSPLIT trajectories for Lahore and Delhi (scaffold; runs only where a Linux HYSPLIT
build is installed, otherwise every run is a dry run that writes the plan and the CONTROL files).

What it does, every six hours once live:
- backward: 72 h trajectories arriving at each receptor at 00/06/12/18 UTC over the last day, started
  at 100, 500 and 1,000 m AGL, on NOAA's GFS 0.25° ARL files (the archive day files for the past,
  the +84 h forecast file for the future);
- forward: 48–72 h trajectories from the day's likely-crop detection clusters (0.02° cells with FRP at
  or above the day's 75th percentile, up to 40 starts), released at the observed pass time;
- sensitivity: the 27-member ensemble (hyts_ens) for the D+1 arrival at each receptor;
- matching: trajectory points inside the mixed layer (floor 100 m, cap 1,500 m) within 10 km and
  ±1 h of a detection; no distance cut-off; sector agreement across heights and members.

What it is not: a plausibility screen gives where air came from and whether fires sat on the path;
it is never a smoke-arrival probability or a PM2.5 contribution. The wording rule is copied from the
investigation engine: "transport pathway consistent with", never "caused".

Met: ARL cannot be subset, so the files are mirrored whole into gs://{bucket}/{MET_PREFIX}/ by the
task (archive days ≈ 1.2 GB, a forecast cycle ≈ 2.9 GB) and mounted or downloaded for the run.
Outputs: {OUT_PREFIX}/{receptor}/{YYYYMMDDTHH}.json and {OUT_PREFIX}/latest.json; the plan of the
last run at {OUT_PREFIX}/plan_latest.json. Binary: HYSPLIT_EXEC (a directory with hyts_std and
hyts_ens); unset → dry run.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.services import fire_regions as fr

logger = logging.getLogger(__name__)

TASK = "fires-trajectories"
RECEPTORS: Dict[str, Tuple[float, float]] = {"Lahore": (31.5204, 74.3587), "Delhi": (28.6139, 77.2090)}
HEIGHTS_M = (100.0, 500.0, 1000.0)
BACK_HOURS = 72
FORWARD_HOURS = 72
ARRIVAL_HOURS = (0, 6, 12, 18)
MAX_FORWARD_STARTS = 40
MATCH_KM = 10.0
MATCH_HOURS = 1.0
MIXED_FLOOR_M = 100.0
MIXED_CAP_M = 1500.0
MODEL_TOP_M = 10000.0
ENSEMBLE_MEMBERS = 27
MET_PREFIX = "met/gfs0p25"
OUT_PREFIX = "forecasts/trajectories"
NOAA_ARCHIVE = "ftp://ftp.arl.noaa.gov/pub/archives/gfs0p25/{ymd}_gfs0p25"
NOAA_FORECAST = "ftp://ftp.arl.noaa.gov/pub/forecast/{ymd}/hysplit.t{hh:02d}z.gfs0p25f"
STALE_HOURS = 9.0
DEFINITIONS = {
    "trajectory": "one air-parcel path from a HYSPLIT run on GFS 0.25° meteorology; a backward trajectory says where the air arriving at the receptor had been, a forward one where air leaving a fire cluster goes",
    "heights": "starts at 100, 500 and 1,000 m above ground; agreement across heights is reported, disagreement means the pathway is uncertain",
    "match": f"a trajectory point within {MATCH_KM:g} km and ±{MATCH_HOURS:g} h of a detection while inside the mixed layer (floor {MIXED_FLOOR_M:g} m, cap {MIXED_CAP_M:g} m); no distance cut-off",
    "ensemble": f"{ENSEMBLE_MEMBERS} members from offset starting points (hyts_ens) show how sensitive the path is to the meteorology; the spread is not a probability",
    "not_attribution": "a trajectory is a plausibility screen: 'transport pathway consistent with smoke from …', never a smoke-arrival probability or a PM2.5 contribution",
    "forward_vs_backward": "forward trajectories from fires show where smoke could go; forward trajectories from a city show where the city's air goes: do not confuse the two",
}


# ── planning ─────────────────────────────────────────────────────────────────

@dataclass
class Run:
    kind: str                   # backward | forward | ensemble
    name: str                   # receptor or cluster id
    lat: float
    lon: float
    start_utc: datetime         # arrival (backward) or release (forward)
    hours: int                  # negative = backward
    heights: Tuple[float, ...] = HEIGHTS_M
    met_files: List[str] = field(default_factory=list)
    note: str = ""


def _floor_hour(t: datetime, hours: Sequence[int]) -> datetime:
    h = max(x for x in hours if x <= t.hour)
    return t.replace(hour=h, minute=0, second=0, microsecond=0)


def archive_days(start: datetime, end: datetime) -> List[str]:
    """Archive day files covering [start, end] (UTC days)."""
    out = []
    d = start.date()
    while d <= end.date():
        out.append(f"{d:%Y%m%d}_gfs0p25")
        d += timedelta(days=1)
    return out


def forecast_file(cycle: datetime) -> str:
    return f"hysplit.t{cycle.hour:02d}z.gfs0p25f"


def plan_runs(now_utc: datetime, clusters: Optional[pd.DataFrame] = None) -> List[Run]:
    """Backward runs for the last day's arrivals at each receptor, forward runs from the fire clusters,
    one ensemble per receptor for the D+1 arrival."""
    now_utc = now_utc.astimezone(timezone.utc).replace(tzinfo=None) if now_utc.tzinfo else now_utc
    latest = _floor_hour(now_utc, ARRIVAL_HOURS)
    runs: List[Run] = []
    for name, (lat, lon) in RECEPTORS.items():
        for k in range(4):
            arrival = latest - timedelta(hours=6 * k)
            runs.append(Run("backward", name, lat, lon, arrival, -BACK_HOURS,
                            met_files=archive_days(arrival - timedelta(hours=BACK_HOURS), arrival)))
        d1 = latest + timedelta(hours=24)
        cycle = _floor_hour(now_utc, (0, 6, 12, 18))
        runs.append(Run("ensemble", name, lat, lon, d1, -BACK_HOURS,
                        met_files=archive_days(d1 - timedelta(hours=BACK_HOURS), now_utc) + [forecast_file(cycle)],
                        note="D+1 arrival; the forecast file covers the hours after now"))
    if clusters is not None and len(clusters):
        cycle = _floor_hour(now_utc, (0, 6, 12, 18))
        for i, c in enumerate(clusters.head(MAX_FORWARD_STARTS).itertuples()):
            start = pd.Timestamp(c.start_utc).to_pydatetime().replace(tzinfo=None)
            runs.append(Run("forward", f"cluster-{i:02d}", float(c.lat), float(c.lon), start, FORWARD_HOURS,
                            heights=(MIXED_FLOOR_M,), met_files=archive_days(start, now_utc) + [forecast_file(cycle)],
                            note=f"FRP {float(c.frp_mw):.0f} MW, {int(c.n)} detections, {c.district or c.country}"))
    return runs


def crop_clusters(det: pd.DataFrame, day: date) -> pd.DataFrame:
    """Likely-crop detection clusters of one Pakistan day with FRP at or above the day's 75th percentile:
    cell centre, summed FRP, count, the observed pass time, strongest first."""
    cols = ["lat", "lon", "frp_mw", "n", "start_utc", "district", "country"]
    if det is None or det.empty or "source_class" not in det.columns:
        return pd.DataFrame(columns=cols)
    d = det[(det["pk_day"] == day) & det["is_primary"] & det["grp_hn"] & (det["source_class"] == "crop")]
    if d.empty:
        return pd.DataFrame(columns=cols)
    g = d.groupby("cell_id")
    cells = pd.DataFrame({"lat": g["lat"].mean(), "lon": g["lon"].mean(), "frp_mw": g["frp"].sum(), "n": g.size(),
                          "start_utc": g["acq_utc"].min(), "district": g["district"].agg(lambda s: s.mode().iloc[0] if s.notna().any() else None),
                          "country": g["country"].agg(lambda s: fr.COUNTRY_LABELS.get(s.mode().iloc[0]))})
    cells = cells[cells["frp_mw"] >= cells["frp_mw"].quantile(0.75)].sort_values("frp_mw", ascending=False)
    cells["start_utc"] = cells["start_utc"].fillna(pd.Timestamp(datetime(day.year, day.month, day.day, 8, 0)))
    return cells.reset_index(drop=True)[cols]


# ── HYSPLIT files ────────────────────────────────────────────────────────────

def render_control(run: Run, met_dir: str, out_file: str = "tdump") -> str:
    """CONTROL for one run (several start heights in one file). Negative hours = backward."""
    if not met_dir.endswith("/"):
        met_dir += "/"
    if len(met_dir) >= 80:
        raise ValueError("met directory line must be under 80 characters for HYSPLIT")
    t = run.start_utc
    lines = [f"{t.year % 100:02d} {t.month:02d} {t.day:02d} {t.hour:02d}", str(len(run.heights))]
    lines += [f"{run.lat:.4f} {run.lon:.4f} {h:.1f}" for h in run.heights]
    lines += [str(int(run.hours)), "0", f"{MODEL_TOP_M:.1f}", str(len(run.met_files))]
    for f in run.met_files:
        lines += [met_dir, f]
    lines += ["./", out_file]
    return "\n".join(lines) + "\n"


def render_setup(ensemble: bool = False) -> str:
    """SETUP.CFG: mixed-layer depth and terrain height in the output; ensemble offsets when asked."""
    keys = ["tm_mixd = 1", "tm_tpot = 0", "tm_tamb = 0", "tm_rain = 0", "tm_relh = 0", "tm_terr = 1", "kmsl = 0"]
    if ensemble:
        keys += ["dxf = 1.0", "dyf = 1.0", "dzf = 0.01"]
    return "&SETUP\n" + "\n".join(" " + k + "," for k in keys) + "\n/\n"


_TDUMP_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)((?:\s+-?\d+\.\d+)*)\s*$")


def parse_tdump(text: str) -> pd.DataFrame:
    """Endpoint rows of a tdump: traj_id, time (UTC), age_h, lat, lon, height_agl, plus the diagnostics
    listed on the header line (mixdepth, terrain) when present."""
    lines = text.splitlines()
    diag: List[str] = []
    rows = []
    i = 0
    # header: n met grids, their lines, n trajectories + direction + vertical motion, start lines, then "n DIAG…"
    while i < len(lines):
        parts = lines[i].split()
        if (len(parts) >= 2 and parts[0].isdigit() and all(p.isupper() for p in parts[1:]) and int(parts[0]) == len(parts) - 1
                and parts[1] not in ("BACKWARD", "FORWARD")):          # the direction line looks the same: "2 BACKWARD OMEGA"
            diag = [p.lower() for p in parts[1:]]
            i += 1
            break
        i += 1
    for line in lines[i:]:
        m = _TDUMP_ROW.match(line)
        if not m:
            continue
        tid, grid, yy, mo, dd, hh, mi, fh = (int(m.group(k)) for k in range(1, 9))
        age, lat, lon, agl = (float(m.group(k)) for k in range(9, 13))
        extra = [float(x) for x in m.group(13).split()]
        year = 2000 + yy if yy < 70 else 1900 + yy
        row = {"traj_id": tid, "time": datetime(year, mo, dd, hh, mi), "age_h": age, "lat": lat, "lon": lon, "height_agl": agl}
        for name, v in zip(diag, extra):
            row[name] = v
        rows.append(row)
    return pd.DataFrame(rows)


# ── matching and summaries ───────────────────────────────────────────────────

def match_fires(traj: pd.DataFrame, det: pd.DataFrame, *, km: float = MATCH_KM, hours: float = MATCH_HOURS) -> pd.DataFrame:
    """Trajectory points inside the mixed layer that pass within km and ±hours of a detection."""
    if traj.empty or det is None or det.empty:
        return pd.DataFrame(columns=["traj_id", "age_h", "time", "lat", "lon", "n_fires", "frp_mw", "districts"])
    md = traj["mixdepth"] if "mixdepth" in traj else pd.Series(MIXED_CAP_M, index=traj.index)
    cap = md.clip(lower=MIXED_FLOOR_M, upper=MIXED_CAP_M)
    inside = traj[traj["height_agl"] <= cap]
    acq = pd.to_datetime(det["acq_utc"]).dt.tz_localize(None) if "acq_utc" in det else None
    out = []
    for r in inside.itertuples():
        dkm = fr.haversine_km_vec(r.lat, r.lon, det["lat"].to_numpy(), det["lon"].to_numpy())
        near = dkm <= km
        if acq is not None:
            dt = (acq - pd.Timestamp(r.time)).abs().dt.total_seconds() / 3600.0
            near &= ((dt <= hours) | dt.isna()).to_numpy()      # a detection without a time (old archive) is matched by place only
        if near.any():
            sel = det[near]
            out.append({"traj_id": r.traj_id, "age_h": r.age_h, "time": r.time, "lat": r.lat, "lon": r.lon, "n_fires": int(near.sum()),
                        "frp_mw": round(float(sel["frp"].sum()), 1), "districts": sorted({str(x) for x in sel["district"].dropna()})[:5]})
    return pd.DataFrame(out)


def sector_agreement(traj: pd.DataFrame, lat0: float, lon0: float, age_h: float = 24.0) -> Dict[str, Any]:
    """Compass sector of each trajectory at a given age and how many agree with the modal one."""
    pts = traj[traj["age_h"] == -abs(age_h)]
    if pts.empty:
        return {"age_h": age_h, "n": 0, "modal": None, "agreement": None, "sectors": {}}
    brg = fr.bearing_deg(lat0, lon0, pts["lat"].to_numpy(), pts["lon"].to_numpy())
    secs = [fr.compass(b) for b in brg]
    counts: Dict[str, int] = {}
    for s_ in secs:
        counts[s_] = counts.get(s_, 0) + 1
    modal = max(counts, key=counts.get)
    return {"age_h": age_h, "n": len(secs), "modal": modal, "agreement": round(counts[modal] / len(secs), 2), "sectors": counts}


# ── the task ─────────────────────────────────────────────────────────────────

def hysplit_exec() -> Optional[Path]:
    p = os.environ.get("HYSPLIT_EXEC")
    return Path(p) if p and (Path(p) / "hyts_std").exists() else None


def _met_present(bucket, files: Sequence[str]) -> Dict[str, bool]:
    out = {}
    for f in files:
        try:
            out[f] = bucket.blob(f"{MET_PREFIX}/{f}").exists()
        except Exception:  # noqa: BLE001
            out[f] = False
    return out


class FireTrajectoryTask:
    """Plan (and, with a binary, run) the trajectories. Without HYSPLIT_EXEC every run is a dry run that
    writes the plan, the CONTROL/SETUP files and the met inventory, so the pipeline can be checked end
    to end before the binary is installed."""

    def __init__(self, *, settings=None, bucket=None, recorder=None, store=None, now_utc: Optional[datetime] = None):
        from app.core.config import settings as _default_settings
        self.settings = settings or _default_settings
        self._bucket = bucket
        self.store = store
        self.now_utc = now_utc
        if recorder is None:
            from app.ingestion.db import AsyncSessionLocal
            from app.ingestion.runs import RunRecorder
            recorder = RunRecorder(AsyncSessionLocal, Path(self.settings.INGEST_OUT_DIR), required=False)
        self.recorder = recorder

    @property
    def bucket(self):
        if self._bucket is None:
            from app.services.fire_aggregates import default_bucket
            self._bucket = default_bucket()
        return self._bucket

    async def run(self, *, dry_run: bool = True, trigger: str = "http"):
        import asyncio
        from app.ingestion.runs import RunOutcome, new_run_id
        run_id = new_run_id(TASK)
        outcome = RunOutcome(run_id=run_id, task=TASK, provider_code="hysplit", scope="receptors", trigger=trigger)
        outcome.details.update({"dry_run": dry_run})
        await self.recorder.start(outcome)
        try:
            await asyncio.to_thread(self._run_sync, outcome, dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s run %s crashed", TASK, run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await self.recorder.finish(outcome)
        return outcome

    def _run_sync(self, outcome, dry_run: bool) -> None:
        from app.services.fire_aggregates import agg_store
        from app.services.fires import PK_TZ
        now = self.now_utc or datetime.now(timezone.utc)
        store = self.store or agg_store()
        today_pkt = now.astimezone(PK_TZ).date()
        day = today_pkt - timedelta(days=1)
        det = store.detections(day, day)
        clusters = crop_clusters(det, day)
        runs = plan_runs(now, clusters)
        met_needed = sorted({f for r in runs for f in r.met_files})
        present = _met_present(self.bucket, met_needed)
        binary = hysplit_exec()
        plan = {
            "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "fires_day": day.isoformat(),
            "receptors": {k: {"lat": v[0], "lon": v[1]} for k, v in RECEPTORS.items()},
            "runs": [{"kind": r.kind, "name": r.name, "lat": round(r.lat, 4), "lon": round(r.lon, 4), "start_utc": r.start_utc.isoformat() + "Z",
                      "hours": r.hours, "heights_m": list(r.heights), "met_files": r.met_files, "note": r.note} for r in runs],
            "clusters": int(len(clusters)), "met": {"needed": met_needed, "present": [f for f, ok in present.items() if ok],
                                                    "missing": [f for f, ok in present.items() if not ok], "prefix": MET_PREFIX},
            "binary": str(binary) if binary else None, "status": "ran" if (binary and not dry_run) else "dry_run",
            "definitions": DEFINITIONS,
        }
        c = outcome.counts
        c.expected = len(runs)
        with tempfile.TemporaryDirectory() as tmp:
            for r in runs:
                d = Path(tmp) / f"{r.kind}-{r.name}-{r.start_utc:%Y%m%dT%H}"
                d.mkdir()
                (d / "CONTROL").write_text(render_control(r, "/met/gfs0p25/"))
                (d / "SETUP.CFG").write_text(render_setup(ensemble=r.kind == "ensemble"))
                c.attempted += 1
                if binary and not dry_run and all(present.get(f) for f in r.met_files):
                    # execution lands here once the Linux build is installed: stage met, run hyts_std/hyts_ens, parse tdump
                    c.skipped += 1
                else:
                    c.rows_unchanged += 1
            plan["control_example"] = (Path(tmp) / f"{runs[0].kind}-{runs[0].name}-{runs[0].start_utc:%Y%m%dT%H}" / "CONTROL").read_text() if runs else None
        c.completed = c.attempted
        if not dry_run:
            self.bucket.blob(f"{OUT_PREFIX}/plan_latest.json").upload_from_string(json.dumps(plan), content_type="application/json")
        outcome.details.update({"runs": len(runs), "clusters": int(len(clusters)), "met_missing": plan["met"]["missing"],
                                "binary": plan["binary"], "status": plan["status"]})
        self.last_plan = plan


def read_latest(bucket=None) -> Optional[Dict[str, Any]]:
    from app.services.fire_aggregates import _read_json, default_bucket
    return _read_json(bucket or default_bucket(), f"{OUT_PREFIX}/latest.json")


def read_plan(bucket=None) -> Optional[Dict[str, Any]]:
    from app.services.fire_aggregates import _read_json, default_bucket
    return _read_json(bucket or default_bucket(), f"{OUT_PREFIX}/plan_latest.json")


def status(doc: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> str:
    if not doc:
        return "not_run"
    try:
        gen = datetime.fromisoformat(str(doc.get("generated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return "unavailable"
    age = ((now or datetime.now(timezone.utc)) - gen).total_seconds() / 3600.0
    return "ok" if age <= STALE_HOURS else "stale"
