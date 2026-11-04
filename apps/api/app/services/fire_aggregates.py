"""
FIRMS aggregate store: the day files under hindcast/firms/ turned into attributed, deduplicated
detections and daily region rollups, so trends, anomalies and hotspots are answered from a
3 MB table instead of re-reading 2,400 CSVs.

Layout (same bucket as the day files, gs://{OPS_FORECASTS_BUCKET}/hindcast/firms/agg/):
  manifest.json                           built_at, dedup rule, per-day {csv_updated, rows, format,
                                          status, sources, n_dedup_hn}, suspect_days
  detections/year=YYYY/detections.parquet one file per year (pk_day-sorted, 50 k row groups)
  daily_regions.parquet                   pk_day × region_kind × region rollup (only non-zero rows)

Per detection: pk_day, acq_utc (null for the UTC-keyed archive days), lat, lon, frp, confidence
(l|n|h), satellite, day_basis (acq_pkt|acq_utc), daynight (D|N|null), country (PK|IN|XX),
province, district, cell_id (0.02° grid), dup_group, is_primary, grp_hn.

Rules (see fire_regions):
- dedup: different satellites, ≤ 1 km, ≤ 90 min apart = one fire; primary = highest FRP.
- the headline count everywhere is n_dedup_hn — deduplicated fires with at least one high or
  nominal-confidence detection. Raw counts depend on how many satellites flew (SNPP+N20 in
  2020, N21 from 2023, SNPP retired 2026-11-01) and old files carry no low-confidence rows.

Task: FireAggregateTask.run(backfill=…, dry_run=…, since=…) — POST /api/v1/tasks/fires/aggregate.
Incremental runs rebuild only days whose CSV changed (blob `updated`) plus the last 4 Pakistan
days; a backfill rebuilds everything year by year (~2.5 M rows, a few minutes).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.ingestion.runs import RunOutcome, RunRecorder, new_run_id
from app.services import fire_regions as fr
from app.services.fires import PK_TZ, blob_paths, parse_firms_csv

logger = logging.getLogger(__name__)

TASK = "fires-aggregate"
SCHEMA_VERSION = 1
AGG_PREFIX = "hindcast/firms/agg"
MANIFEST_PATH = f"{AGG_PREFIX}/manifest.json"
DAILY_PATH = f"{AGG_PREFIX}/daily_regions.parquet"
DAY_PREFIX = "hindcast/firms/firms_"
RECENT_DAYS = 4                      # always rebuilt on an incremental run (late NRT rows)
ROW_GROUP = 50_000
HN = ("h", "n", "high", "nominal")
PEAK_MONTHS = (4, 5, 10, 11)         # residue-burning seasons
REFERENCE_YEARS = (2020, 2021, 2022, 2023)
DEDUP_RULE = {"different_satellites": True, "max_km": fr.DEDUP_KM, "max_minutes": fr.DEDUP_MINUTES,
              "primary": "highest FRP", "merged_frp": "max"}

DET_COLUMNS = ["pk_day", "acq_utc", "lat", "lon", "frp", "confidence", "satellite", "day_basis", "daynight",
               "country", "province", "district", "cell_id", "dup_group", "is_primary", "grp_hn"]
REGION_METRICS = ["n_raw", "n_hn", "n_dedup", "n_dedup_hn", "n_high", "n_nominal", "n_low", "n_day", "n_night",
                  "frp_raw", "frp_hn", "frp_dedup_hn", "frp_max"]


def year_path(year: int) -> str:
    return f"{AGG_PREFIX}/detections/year={year}/detections.parquet"


# ── per-day build (pure) ─────────────────────────────────────────────────────

@dataclass
class DayBuild:
    day: date
    detections: pd.DataFrame
    regions: pd.DataFrame
    info: Dict[str, Any]


def _confidence(c: str) -> str:
    c = (c or "").strip().lower()
    return {"high": "h", "nominal": "n", "low": "l"}.get(c, c[:1] if c else "")


def build_day(day: date, csv_text: str, meta: Optional[Dict[str, Any]], idx: Optional[fr.RegionIndex] = None) -> DayBuild:
    """Attribute, deduplicate and roll up one day file. Pure: no I/O."""
    header = (csv_text or "").split("\n", 1)[0]
    fmt = "pkt_v2" if "acq_time" in header else "utc_v1"
    rows = parse_firms_csv(csv_text or "")
    n = len(rows)
    lat = np.array([r["latitude"] for r in rows], dtype=float)
    lon = np.array([r["longitude"] for r in rows], dtype=float)
    frp = np.array([r["frp"] for r in rows], dtype=float)
    conf = np.array([_confidence(r["confidence"]) for r in rows], dtype=object)
    sat = np.array([r["satellite"] for r in rows], dtype=object)
    acq = pd.to_datetime([r["acq_datetime_utc"] or None for r in rows], utc=True, errors="coerce")
    minutes = [None if pd.isna(t) else t.timestamp() / 60.0 for t in acq]
    hours = [None if pd.isna(t) else t.hour + t.minute / 60.0 for t in acq]
    attr = fr.attribute_points(lat, lon, idx)
    groups = fr.dedup_groups(lat, lon, sat, minutes)
    primary = fr.primary_mask(groups, frp)
    hn = np.isin(conf, HN)
    grp_hn = np.zeros(n, dtype=bool)
    if n:
        has = pd.Series(hn).groupby(groups).transform("any").to_numpy()
        grp_hn = has.astype(bool)
    det = pd.DataFrame({
        "pk_day": [day] * n, "acq_utc": acq, "lat": lat.astype(np.float32), "lon": lon.astype(np.float32),
        "frp": frp.astype(np.float32), "confidence": conf, "satellite": sat,
        "day_basis": ["acq_pkt" if fmt == "pkt_v2" else "acq_utc"] * n, "daynight": fr.day_night(hours),
        "country": attr["country"], "province": attr["province"], "district": attr["district"],
        "cell_id": fr.cell_id(lat, lon) if n else np.zeros(0, dtype=np.int64),
        "dup_group": groups.astype(np.int32), "is_primary": primary, "grp_hn": grp_hn,
    }, columns=DET_COLUMNS)
    regions = rollup_regions(det)
    meta = meta or {}
    info = {
        "rows": n, "format": fmt, "status": meta.get("status", "archive"),
        "sources": [s.get("source") for s in meta.get("sources", []) if s.get("status") == "ok"] or sorted({s for s in sat.tolist() if s}),
        "observation_period": meta.get("observation_period"), "fetched_at": meta.get("fetched_at"),
        "n_dedup_hn": int((primary & grp_hn).sum()),
    }
    return DayBuild(day, det, regions, info)


def _metrics(g: pd.DataFrame) -> Dict[str, Any]:
    hn = g["confidence"].isin(HN).to_numpy()
    prim = g["is_primary"].to_numpy()
    ghn = g["grp_hn"].to_numpy()
    frp = g["frp"].to_numpy(dtype=float)
    conf = g["confidence"].to_numpy()
    dn = g["daynight"].to_numpy()
    return {
        "n_raw": int(len(g)), "n_hn": int(hn.sum()), "n_dedup": int(prim.sum()), "n_dedup_hn": int((prim & ghn).sum()),
        "n_high": int((conf == "h").sum()), "n_nominal": int((conf == "n").sum()), "n_low": int((conf == "l").sum()),
        "n_day": int((dn == "D").sum()), "n_night": int((dn == "N").sum()),
        "frp_raw": round(float(frp.sum()), 1), "frp_hn": round(float(frp[hn].sum()), 1),
        "frp_dedup_hn": round(float(frp[prim & ghn].sum()), 1), "frp_max": round(float(frp.max()), 1) if len(frp) else 0.0,
    }


def rollup_regions(det: pd.DataFrame) -> pd.DataFrame:
    """pk_day × region_kind × region metrics; country rows use the labels of fire_regions.COUNTRY_LABELS."""
    out: List[Dict[str, Any]] = []
    if det.empty:
        return pd.DataFrame(columns=["pk_day", "region_kind", "region", *REGION_METRICS])
    keyed = det.assign(country_label=det["country"].map(fr.COUNTRY_LABELS))
    for (day, label), g in keyed.groupby(["pk_day", "country_label"], sort=True):
        out.append({"pk_day": day, "region_kind": "country", "region": label, **_metrics(g)})
    prov = keyed[keyed["province"].notna()]
    for (day, country, name), g in prov.groupby(["pk_day", "country", "province"], sort=True):
        out.append({"pk_day": day, "region_kind": "india_state" if country == "IN" else "province", "region": name, **_metrics(g)})
    dist = keyed[keyed["district"].notna()]
    for (day, name), g in dist.groupby(["pk_day", "district"], sort=True):
        out.append({"pk_day": day, "region_kind": "district", "region": name, **_metrics(g)})
    return pd.DataFrame(out, columns=["pk_day", "region_kind", "region", *REGION_METRICS])


# ── planning (pure) ──────────────────────────────────────────────────────────

@dataclass
class BlobInfo:
    name: str
    updated: str          # ISO timestamp
    size: int = 0


def day_of_blob(name: str) -> Optional[date]:
    base = name.rsplit("/", 1)[-1]
    if not (base.startswith("firms_") and base.endswith(".csv")):
        return None
    try:
        return datetime.strptime(base[6:14], "%Y%m%d").date()
    except ValueError:
        return None


def plan_days(blobs: Dict[date, BlobInfo], manifest: Dict[str, Any], *, backfill: bool,
              since: Optional[date] = None, today_pkt: Optional[date] = None) -> List[date]:
    """Days to (re)build: all (backfill), else changed CSVs plus the last RECENT_DAYS Pakistan days."""
    today_pkt = today_pkt or datetime.now(timezone.utc).astimezone(PK_TZ).date()
    known = manifest.get("days", {})
    out: List[date] = []
    for day in sorted(blobs):
        if since and day < since:
            continue
        if backfill:
            out.append(day)
            continue
        rec = known.get(day.isoformat())
        if rec is None or rec.get("csv_updated") != blobs[day].updated or (today_pkt - day).days < RECENT_DAYS:
            out.append(day)
    return out


def suspect_days(daily: pd.DataFrame, *, reference_years: Tuple[int, ...] = REFERENCE_YEARS,
                 min_reference: int = 200, ratio: float = 0.10) -> List[Dict[str, Any]]:
    """Peak-season days after the reference years whose bbox total is under ratio × the reference
    median for the same calendar date (±3 days): a thin re-fetch, not a quiet season."""
    if daily is None or daily.empty:
        return []
    c = daily[daily["region_kind"] == "country"]
    totals = c.groupby("pk_day")["n_raw"].sum()
    totals.index = pd.to_datetime(totals.index)
    ref = totals[totals.index.year.isin(reference_years)]
    by_doy: Dict[int, List[int]] = {}
    for ts, v in ref.items():
        by_doy.setdefault(ts.dayofyear, []).append(int(v))
    out = []
    for ts, v in totals[~totals.index.year.isin(reference_years)].items():
        if ts.month not in PEAK_MONTHS:
            continue
        vals = [x for d in range(ts.dayofyear - 3, ts.dayofyear + 4) for x in by_doy.get(d, [])]
        if not vals:
            continue
        med = float(np.median(vals))
        if med >= min_reference and v < ratio * med:
            out.append({"day": ts.date().isoformat(), "n_raw": int(v), "reference_median": round(med)})
    return out


# ── GCS I/O ──────────────────────────────────────────────────────────────────

def _is_not_found(exc: BaseException) -> bool:
    return type(exc).__name__ in ("NotFound", "KeyError") or getattr(exc, "code", None) == 404


def _read_text(bucket, path: str) -> Optional[str]:
    """One round trip: download, and treat a 404 as absent (no separate exists() call)."""
    try:
        return bucket.blob(path).download_as_text()
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc):
            return None
        raise


def _read_json(bucket, path: str) -> Optional[Dict[str, Any]]:
    t = _read_text(bucket, path)
    try:
        return json.loads(t) if t else None
    except ValueError:
        return None


def _read_parquet(bucket, path: str, filters=None) -> Optional[pd.DataFrame]:
    import pyarrow.parquet as pq
    try:
        raw = bucket.blob(path).download_as_bytes()
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc):
            return None
        raise
    return pq.read_table(io.BytesIO(raw), filters=filters).to_pandas()


def _write_parquet(bucket, path: str, df: pd.DataFrame) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy", row_group_size=ROW_GROUP)
    bucket.blob(path).upload_from_string(buf.getvalue(), content_type="application/octet-stream")


def list_day_blobs(bucket) -> Dict[date, BlobInfo]:
    out: Dict[date, BlobInfo] = {}
    for b in bucket.list_blobs(prefix=DAY_PREFIX):
        d = day_of_blob(b.name)
        if d is None:
            continue
        upd = b.updated.isoformat() if isinstance(b.updated, datetime) else str(b.updated)
        out[d] = BlobInfo(b.name, upd, int(b.size or 0))
    return out


def default_bucket():
    from app.routers.analyst_desk import FORECASTS_BUCKET, _gcs_client
    return _gcs_client().bucket(FORECASTS_BUCKET)


# ── the task ─────────────────────────────────────────────────────────────────

class FireAggregateTask:
    """Build or update the aggregate store from the day files. Blocking work runs in a thread."""

    def __init__(self, *, settings=None, bucket=None, recorder: Optional[RunRecorder] = None, workers: int = 8,
                 today_pkt: Optional[date] = None):
        from app.core.config import settings as _default_settings
        self.settings = settings or _default_settings
        self._bucket = bucket
        self.workers = workers
        self.today_pkt = today_pkt            # tests pin the clock; None = now in Asia/Karachi
        if recorder is None:
            from app.ingestion.db import AsyncSessionLocal
            recorder = RunRecorder(AsyncSessionLocal, Path(self.settings.INGEST_OUT_DIR), required=False)
        self.recorder = recorder

    @property
    def bucket(self):
        if self._bucket is None:
            self._bucket = default_bucket()
        return self._bucket

    async def run(self, *, backfill: bool = False, dry_run: bool = False, since: Optional[date] = None,
                  trigger: str = "http") -> RunOutcome:
        run_id = new_run_id(TASK)
        outcome = RunOutcome(run_id=run_id, task=TASK, provider_code="firms", scope="bbox", trigger=trigger)
        outcome.details.update({"backfill": backfill, "dry_run": dry_run, "since": since.isoformat() if since else None})
        await self.recorder.start(outcome)
        try:
            await asyncio.to_thread(self._run_sync, outcome, backfill, dry_run, since)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s run %s crashed", TASK, run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await self.recorder.finish(outcome)
        return outcome

    # -- blocking --------------------------------------------------------------

    def _run_sync(self, outcome: RunOutcome, backfill: bool, dry_run: bool, since: Optional[date]) -> None:
        bucket = self.bucket
        c = outcome.counts
        manifest = _read_json(bucket, MANIFEST_PATH) or {}
        blobs = list_day_blobs(bucket)
        days = plan_days(blobs, manifest, backfill=backfill, since=since, today_pkt=self.today_pkt)
        by_year: Dict[int, List[date]] = {}
        for d in days:
            by_year.setdefault(d.year, []).append(d)
        outcome.details["plan"] = {"days": len(days), "files": len(blobs), "by_year": {str(y): len(v) for y, v in by_year.items()}}
        c.expected = len(days)
        if dry_run:
            outcome.details["suspect_days"] = manifest.get("suspect_days", [])
            outcome.details["built_at"] = manifest.get("built_at")
            c.rows_unchanged = len(days)
            return
        if not days:
            # nothing changed: an all-clear run, not an empty inventory
            c.expected = c.attempted = c.completed = 1
            outcome.details["note"] = "no day files changed"
            return

        idx = fr.load_region_index()
        day_records: Dict[str, Dict[str, Any]] = dict(manifest.get("days", {}))
        region_frames: List[pd.DataFrame] = []
        touched_days: List[date] = []
        failures: List[Dict[str, str]] = []
        rows_read = rows_written = 0
        years_written: List[int] = []

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for year in sorted(by_year):
                ydays = by_year[year]
                texts = list(pool.map(lambda d: _read_text(bucket, blob_paths(d)[0]), ydays))
                metas = list(pool.map(lambda d: _read_json(bucket, blob_paths(d)[1]), ydays))
                dets: List[pd.DataFrame] = []
                for d, text, meta in zip(ydays, texts, metas):
                    c.attempted += 1
                    try:
                        if text is None:
                            raise FileNotFoundError(blob_paths(d)[0])
                        built = build_day(d, text, meta, idx)
                    except Exception as exc:  # noqa: BLE001
                        c.failed += 1
                        failures.append({"day": d.isoformat(), "error": f"{type(exc).__name__}: {exc}"[:200]})
                        continue
                    c.completed += 1
                    rows_read += built.info["rows"]
                    dets.append(built.detections)
                    region_frames.append(built.regions)
                    touched_days.append(d)
                    day_records[d.isoformat()] = {"csv_updated": blobs[d].updated, **built.info}
                if not touched_days or not any(td.year == year for td in touched_days):
                    continue
                new = pd.concat(dets, ignore_index=True) if dets else pd.DataFrame(columns=DET_COLUMNS)
                if not backfill:
                    old = _read_parquet(bucket, year_path(year))
                    if old is not None and not old.empty:
                        done = {td for td in touched_days if td.year == year}
                        old = old[~pd.to_datetime(old["pk_day"]).dt.date.isin(done)]
                        new = pd.concat([old, new], ignore_index=True)
                new = new.sort_values(["pk_day", "acq_utc"], na_position="last", kind="stable").reset_index(drop=True)
                _write_parquet(bucket, year_path(year), new)
                years_written.append(year)
                rows_written += len(new)

        daily = pd.concat(region_frames, ignore_index=True) if region_frames else pd.DataFrame(columns=["pk_day", "region_kind", "region", *REGION_METRICS])
        if not backfill:
            old = _read_parquet(bucket, DAILY_PATH)
            if old is not None and not old.empty:
                old = old[~pd.to_datetime(old["pk_day"]).dt.date.isin(set(touched_days))]
                daily = pd.concat([old, daily], ignore_index=True)
        daily = daily.sort_values(["pk_day", "region_kind", "region"], kind="stable").reset_index(drop=True)
        _write_parquet(bucket, DAILY_PATH, daily)
        suspects = suspect_days(daily)
        built_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        manifest = {
            "schema_version": SCHEMA_VERSION, "built_at": built_at, "run_id": outcome.run_id,
            "dedup_rule": DEDUP_RULE, "cell_size_deg": fr.CELL_DEG, "day_prefix": DAY_PREFIX,
            "low_confidence_from": min((d for d, r in day_records.items() if r.get("format") == "pkt_v2"), default=None),
            "days": dict(sorted(day_records.items())), "suspect_days": suspects,
        }
        bucket.blob(MANIFEST_PATH).upload_from_string(json.dumps(manifest), content_type="application/json")

        c.rows_fetched = rows_read
        c.rows_written = rows_written
        outcome.details.update({"years_written": years_written, "days_built": len(touched_days), "failures": failures[:50],
                                "suspect_days": suspects, "built_at": built_at, "daily_rows": int(len(daily))})
        if failures and not touched_days:
            outcome.fail("all_days_failed", failures[0]["error"])


# ── reader ───────────────────────────────────────────────────────────────────

class AggStore:
    """Read side of the store with small in-process caches (manifest 10 min, daily table per build)."""

    def __init__(self, bucket=None, *, ttl_s: float = 600.0):
        self._bucket = bucket
        self.ttl_s = ttl_s
        self._manifest: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
        self._daily: Tuple[Optional[str], Optional[pd.DataFrame]] = (None, None)
        self._slices: Dict[Tuple[int, date, date], pd.DataFrame] = {}
        self._csv_days: Dict[date, Tuple[float, Optional[DayBuild]]] = {}     # day -> (monotonic, build or None)

    @property
    def bucket(self):
        if self._bucket is None:
            self._bucket = default_bucket()
        return self._bucket

    def manifest(self) -> Dict[str, Any]:
        import time
        at, m = self._manifest
        if m is not None and time.monotonic() - at < self.ttl_s:
            return m
        m = _read_json(self.bucket, MANIFEST_PATH) or {}
        self._manifest = (time.monotonic(), m)
        return m

    def daily_regions(self) -> pd.DataFrame:
        built = self.manifest().get("built_at")
        key, df = self._daily
        if df is not None and key == built:
            return df
        df = _read_parquet(self.bucket, DAILY_PATH)
        if df is None:
            df = pd.DataFrame(columns=["pk_day", "region_kind", "region", *REGION_METRICS])
        df["pk_day"] = pd.to_datetime(df["pk_day"]).dt.date
        self._daily = (built, df)
        return df

    def detections(self, start: date, end: date) -> pd.DataFrame:
        frames = []
        for year in range(start.year, end.year + 1):
            key = (year, max(start, date(year, 1, 1)), min(end, date(year, 12, 31)))
            df = self._slices.get(key)
            if df is None:
                df = _read_parquet(self.bucket, year_path(year), filters=[("pk_day", ">=", key[1]), ("pk_day", "<=", key[2])])
                if df is None:
                    df = pd.DataFrame(columns=DET_COLUMNS)
                if len(self._slices) >= 4:
                    self._slices.pop(next(iter(self._slices)))
                self._slices[key] = df
            frames.append(df)
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DET_COLUMNS)
        if not out.empty:
            out["pk_day"] = pd.to_datetime(out["pk_day"]).dt.date
        return out

    def day_from_csv(self, day: date) -> Optional[DayBuild]:
        """One day parsed from its CSV + sidecar (None when the file is absent); cached for ttl_s."""
        import time
        hit = self._csv_days.get(day)
        if hit is not None and time.monotonic() - hit[0] < self.ttl_s:
            return hit[1]
        csv_path, meta_path = blob_paths(day)
        text = _read_text(self.bucket, csv_path)
        built = build_day(day, text, _read_json(self.bucket, meta_path)) if text is not None else None
        if len(self._csv_days) >= 20:
            self._csv_days.pop(next(iter(self._csv_days)))
        self._csv_days[day] = (time.monotonic(), built)
        return built


_STORE: Optional[AggStore] = None


def agg_store() -> AggStore:
    global _STORE
    if _STORE is None:
        _STORE = AggStore()
    return _STORE
