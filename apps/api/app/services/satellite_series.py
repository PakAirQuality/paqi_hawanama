"""Satellite column series per region: the store on GCS, the daily Earth Engine refresh and the reader.

Layout (gs://{OPS_FORECASTS_BUCKET}/satellite/):
    manifest.json                      schema, built_at, products {first_day, last_day, days, pending}, regions, n_possible
    regions.geojson                    the 24 region polygons the series describe (input to the history export)
    series/<product>.parquet           day, region, platform, value, n_valid, n_possible, coverage, source, fetched_at
    climatology/<product>.parquet      region, season_out, doy, mean, sd, p10, p50, p90, n   (exported once from the archive)
    climatology.json                   period, half_window_d, min_n, built_at, source
    findings/latest.json               per region × product: last day, 7-day mean, coverage, z vs climatology
    findings/adjudicated.json          the rule-adjudicated findings exported from air_copilot (read-only here)

Products: TROPOMI OFFL L3 columns (NO2 tropospheric, CO, SO2, O3, HCHO; mol m⁻²), the UV aerosol
index, and MAIAC AOD at 550 and 470 nm per platform. Values are column amounts and optical
quantities, never surface concentrations. The 2020–2025 history comes from air_copilot's grids
(``source = zarr_export``); days from then on are reduced on Earth Engine (``source = ee_direct``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from app.ingestion.runs import RunOutcome, RunRecorder, new_run_id
from app.services import satellite_climatology as clim
from app.services import satellite_regions as regions
from app.services.fire_aggregates import _read_json, _read_parquet, _write_parquet, default_bucket

logger = logging.getLogger(__name__)

TASK = "satellite-series"
SCHEMA_VERSION = 1
PREFIX = "satellite"
MANIFEST_PATH = f"{PREFIX}/manifest.json"
REGIONS_PATH = f"{PREFIX}/regions.geojson"
CLIM_META_PATH = f"{PREFIX}/climatology.json"
FINDINGS_LATEST_PATH = f"{PREFIX}/findings/latest.json"
FINDINGS_ADJUDICATED_PATH = f"{PREFIX}/findings/adjudicated.json"

HISTORY_START = date(2020, 1, 1)
RECENT_DAYS = 7                       # always re-fetched: OFFL reprocessing and late MAIAC granules
LOOKBACK_DAYS = 30                    # the window a scheduled run looks back over for missing days
MAX_DAYS_PER_RUN = 40                 # per kind; a long outage back-fills over several runs
MIN_COVERAGE = 0.3                    # below this a day's region value is not assessable (atminvest rule)
WINDOW_DAYS = 7                       # the findings' recent window

PRODUCTS: Dict[str, Dict[str, Any]] = {
    "no2": {"kind": "tropomi", "label": "Tropospheric NO2 column", "units": "mol m-2", "platforms": None},
    "co": {"kind": "tropomi", "label": "CO total column", "units": "mol m-2", "platforms": None},
    "so2": {"kind": "tropomi", "label": "SO2 column", "units": "mol m-2", "platforms": None},
    "o3": {"kind": "tropomi", "label": "O3 total column", "units": "mol m-2", "platforms": None},
    "hcho": {"kind": "tropomi", "label": "Tropospheric HCHO column", "units": "mol m-2", "platforms": None},
    "aai": {"kind": "tropomi", "label": "UV aerosol index", "units": "1", "platforms": None},
    "aod550": {"kind": "maiac", "label": "MAIAC AOD 550 nm (strict QA)", "units": "1", "platforms": ("terra", "aqua")},
    "aod470": {"kind": "maiac", "label": "MAIAC AOD 470 nm (strict QA)", "units": "1", "platforms": ("terra", "aqua")},
}
KINDS: Dict[str, List[str]] = {
    "tropomi": [p for p, m in PRODUCTS.items() if m["kind"] == "tropomi"],
    "maiac": [p for p, m in PRODUCTS.items() if m["kind"] == "maiac"],
}
SERIES_COLUMNS = ["day", "region", "platform", "value", "n_valid", "n_possible", "coverage", "source", "fetched_at"]

DEFINITIONS = {
    "column": "TROPOMI values are vertical column amounts (mol m⁻²: NO2 and HCHO tropospheric, CO, SO2 and O3 total), "
              "not surface concentrations; report them relative to the climatology (percent, z), not as µg/m³",
    "aai": "the UV aerosol index responds to dust, ash and smoke alike; it is never evidence of smoke on its own",
    "aod": "MAIAC aerosol optical depth at 550 nm (strict QA: clear, land, normal adjacency, best AOD QA), per Terra and Aqua",
    "coverage": "valid native pixels over the pixels in the region; below 0.3 a day is not assessable (clouds, no overpass)",
    "anomaly": "z = (value − climatology mean) / sd for the same day of year ±15 days in the other July–June seasons, "
               "the target season left out; needs ≥ 10 baseline days",
    "latency": "OFFL L3 products arrive days to two weeks after the overpass; the last days are pending, not zero",
}
CAVEATS = [
    "satellite columns describe the whole atmospheric column over the region: an association with surface air, not a measurement of it",
    "a naive comparison between places or years is not sampling-controlled; cloud cover, boundary layer and wind differ",
]


def series_path(product: str) -> str:
    return f"{PREFIX}/series/{product}.parquet"


def clim_path(product: str) -> str:
    return f"{PREFIX}/climatology/{product}.parquet"


def empty_series() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in zip(
        SERIES_COLUMNS, ["object", "object", "object", "float64", "int64", "int64", "float64", "object", "object"])})


# ── pure pieces ───────────────────────────────────────────────────────────────

def plan_days(have: Dict[str, Set[date]], *, today: date, kinds: Iterable[str], since: Optional[date] = None,
              until: Optional[date] = None, lookback: int = LOOKBACK_DAYS, recent: int = RECENT_DAYS,
              force: bool = False, max_days: int = MAX_DAYS_PER_RUN) -> Dict[str, List[date]]:
    """Days to fetch per kind: any day in the window that a product lacks, every day in the recent window, or all with force."""
    d1 = min(until or (today - timedelta(days=1)), today - timedelta(days=1))
    d0 = max(since or (d1 - timedelta(days=lookback - 1)), HISTORY_START)
    out: Dict[str, List[date]] = {}
    for kind in kinds:
        products = KINDS[kind]
        days: List[date] = []
        d = d0
        while d <= d1:
            due = force or (today - d).days <= recent or any(d not in have.get(p, set()) for p in products)
            if due:
                days.append(d)
            d += timedelta(days=1)
        out[kind] = days[:max_days]
    return out


def rows_from_results(day: date, results: List[Dict[str, Any]], n_possible: Dict[str, int], fetched_at: datetime,
                      source: str = "ee_direct") -> Dict[str, pd.DataFrame]:
    """EE rows {region, product, platform, value, n_valid} -> one SERIES_COLUMNS frame per product."""
    out: Dict[str, pd.DataFrame] = {}
    by_product: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        by_product.setdefault(r["product"], []).append(r)
    for product, rs in by_product.items():
        recs = []
        for r in rs:
            poss = int(n_possible.get(r["region"], 0) or 0)
            n = int(r.get("n_valid") or 0)
            recs.append({"day": day, "region": r["region"], "platform": r.get("platform"),
                         "value": float(r["value"]) if (n > 0 and r.get("value") is not None) else np.nan,
                         "n_valid": n, "n_possible": poss, "coverage": min(n / poss, 1.0) if poss > 0 else 0.0,   # products differ slightly in native grid
                         "source": source, "fetched_at": fetched_at})
        out[product] = pd.DataFrame(recs, columns=SERIES_COLUMNS)
    return out


def merge_series(old: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    """Rows of ``new`` replace ``old`` rows with the same (day, region, platform); sorted by day, region, platform."""
    if old is None or old.empty:
        merged = new.copy()
    else:
        key = ["day", "region", "platform"]
        o = old.copy()
        o["day"] = pd.to_datetime(o["day"]).dt.date
        n = new.copy()
        n["day"] = pd.to_datetime(n["day"]).dt.date
        drop = pd.MultiIndex.from_frame(n[key].fillna("")).unique()
        keep = ~pd.MultiIndex.from_frame(o[key].fillna("")).isin(drop)
        merged = pd.concat([o[keep], n], ignore_index=True)
    merged["day"] = pd.to_datetime(merged["day"]).dt.date
    merged = merged.sort_values(["day", "region", "platform"], na_position="first", kind="stable").reset_index(drop=True)
    return merged[SERIES_COLUMNS]


def days_present(df: Optional[pd.DataFrame]) -> Set[date]:
    if df is None or df.empty:
        return set()
    return set(pd.to_datetime(df["day"]).dt.date.unique())


def combine_platforms(df: pd.DataFrame) -> pd.DataFrame:
    """Terra and Aqua rows of a day -> one row: value = Σv·n/Σn, n_valid = Σn, n_possible = Σ n_possible."""
    if df.empty or df["platform"].isna().all():
        return df
    g = df.copy()
    g["vn"] = g["value"].fillna(0.0) * g["n_valid"]
    agg = g.groupby(["day", "region"], as_index=False).agg(vn=("vn", "sum"), n_valid=("n_valid", "sum"),
                                                            n_possible=("n_possible", "sum"), source=("source", "first"),
                                                            fetched_at=("fetched_at", "max"))
    agg["value"] = np.where(agg["n_valid"] > 0, agg["vn"] / agg["n_valid"].replace(0, np.nan), np.nan)
    agg["coverage"] = np.where(agg["n_possible"] > 0, agg["n_valid"] / agg["n_possible"].replace(0, np.nan), 0.0)
    agg["platform"] = None
    return agg[SERIES_COLUMNS]


def _write_json(bucket, path: str, doc: Dict[str, Any]) -> None:
    bucket.blob(path).upload_from_string(json.dumps(doc, default=str), content_type="application/json")


def _read_text(bucket, path: str) -> Optional[str]:
    from app.services.fire_aggregates import _read_text as _rt
    return _rt(bucket, path)


# ── the task ──────────────────────────────────────────────────────────────────

class SatelliteSeriesTask:
    """Fetch the missing and recent days from Earth Engine into the series store. Blocking work runs in a thread."""

    def __init__(self, *, settings=None, bucket=None, recorder: Optional[RunRecorder] = None, ee_client=None,
                 workers: int = 4, today: Optional[date] = None, retries: int = 3, backoff_s: float = 10.0):
        from app.core.config import settings as _default_settings
        self.settings = settings or _default_settings
        self._bucket = bucket
        self._ee = ee_client
        self.workers = workers
        self.today = today                      # tests pin the clock; None = today in UTC
        self.retries = retries
        self.backoff_s = backoff_s
        if recorder is None:
            from app.ingestion.db import AsyncSessionLocal
            recorder = RunRecorder(AsyncSessionLocal, Path(self.settings.INGEST_OUT_DIR), required=False)
        self.recorder = recorder

    @property
    def bucket(self):
        if self._bucket is None:
            self._bucket = default_bucket()
        return self._bucket

    @property
    def ee(self):
        if self._ee is None:
            from app.services.satellite_ee import EEClient
            self._ee = EEClient(getattr(self.settings, "EE_PROJECT", "hawanama-2"))
        return self._ee

    async def run(self, *, kind: str = "all", days: int = LOOKBACK_DAYS, since: Optional[date] = None,
                  until: Optional[date] = None, dry_run: bool = False, force: bool = False,
                  trigger: str = "http") -> RunOutcome:
        run_id = new_run_id(TASK)
        outcome = RunOutcome(run_id=run_id, task=TASK, provider_code="earth-engine", scope=kind, trigger=trigger)
        outcome.details.update({"kind": kind, "lookback_days": days, "since": since.isoformat() if since else None,
                                "until": until.isoformat() if until else None, "dry_run": dry_run, "force": force})
        await self.recorder.start(outcome)
        try:
            await asyncio.to_thread(self._run_sync, outcome, kind, days, since, until, dry_run, force)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s run %s crashed", TASK, run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await self.recorder.finish(outcome)
        return outcome

    # -- blocking ----------------------------------------------------------------

    def _run_sync(self, outcome: RunOutcome, kind: str, lookback: int, since: Optional[date], until: Optional[date],
                  dry_run: bool, force: bool) -> None:
        bucket = self.bucket
        c = outcome.counts
        today = self.today or datetime.now(timezone.utc).date()
        kinds = list(KINDS) if kind == "all" else [kind]
        if any(k not in KINDS for k in kinds):
            outcome.fail("bad_kind", f"kind must be all, tropomi or maiac (got {kind!r})")
            return

        manifest = _read_json(bucket, MANIFEST_PATH) or {}
        series: Dict[str, Optional[pd.DataFrame]] = {}
        have: Dict[str, Set[date]] = {}
        for k in kinds:
            for p in KINDS[k]:
                series[p] = _read_parquet(bucket, series_path(p))
                have[p] = days_present(series[p])
        plan = plan_days(have, today=today, kinds=kinds, since=since, until=until, lookback=lookback, force=force)
        outcome.details["plan"] = {k: {"days": len(v), "first": v[0].isoformat() if v else None,
                                       "last": v[-1].isoformat() if v else None} for k, v in plan.items()}
        c.expected = sum(len(v) for v in plan.values())

        # the region polygons: written when they change (the history export reads them)
        geo = regions.to_geojson()
        hashes = {f["properties"]["id"]: f["properties"]["geom_hash"] for f in geo["features"]}
        regions_changed = manifest.get("regions") != hashes

        if dry_run:
            outcome.details["ee_ping"] = self.ee.ping()
            outcome.details["regions_changed"] = regions_changed
            outcome.details["note"] = "dry run: nothing written"
            c.skipped = c.expected
            return
        if regions_changed:
            _write_json(bucket, REGIONS_PATH, geo)

        n_possible = dict(manifest.get("n_possible") or {}) if not regions_changed else {}
        fetched_at = datetime.now(timezone.utc)
        new_rows: Dict[str, List[pd.DataFrame]] = {}
        pending: Dict[str, List[str]] = {k: [] for k in kinds}
        failures: List[Dict[str, str]] = []
        touched: Set[str] = set()

        for k in kinds:
            days_k = plan[k]
            if not days_k:
                continue
            if not n_possible.get(k):
                try:
                    n_possible[k] = self.ee.n_possible(k, days_k[-1])
                except Exception as exc:  # noqa: BLE001  (one kind's grid sizing must not sink the other kind's days)
                    logger.exception("%s: n_possible(%s) failed", TASK, k)
                    failures.append({"kind": k, "day": "n_possible", "error": f"{type(exc).__name__}: {exc}"[:200]})
                    c.failed += len(days_k)
                    c.attempted += len(days_k)
                    continue
            poss = n_possible[k]
            with ThreadPoolExecutor(self.workers) as ex:
                results = list(ex.map(lambda d: (d, self._fetch_day(k, d)), days_k))
            for d, (rows, err) in results:
                c.attempted += 1
                if err:
                    c.failed += 1
                    failures.append({"kind": k, "day": d.isoformat(), "error": err[:200]})
                    continue
                if not rows:
                    pending[k].append(d.isoformat())      # not published yet: retried on the next run
                    c.skipped += 1
                    continue
                c.completed += 1
                for p, df in rows_from_results(d, rows, poss, fetched_at).items():
                    new_rows.setdefault(p, []).append(df)
                    touched.add(p)

        products_meta = dict(manifest.get("products") or {})
        for p in touched:
            merged = merge_series(series.get(p), pd.concat(new_rows[p], ignore_index=True))
            _write_parquet(bucket, series_path(p), merged)
            series[p] = merged
            c.rows_written += sum(len(df) for df in new_rows[p])
        for p in series:
            df = series.get(p)
            ds = days_present(df)
            products_meta[p] = {"first_day": min(ds).isoformat() if ds else None, "last_day": max(ds).isoformat() if ds else None,
                                "days": len(ds), "rows": int(len(df)) if df is not None else 0,
                                "pending": pending.get(PRODUCTS[p]["kind"], [])}
        built_at = fetched_at.isoformat()
        manifest.update({"schema_version": SCHEMA_VERSION, "built_at": built_at, "run_id": outcome.run_id,
                         "ee_project": getattr(self.settings, "EE_PROJECT", "hawanama-2"), "products": products_meta,
                         "regions": hashes, "n_possible": n_possible,
                         "pending": {k: v for k, v in pending.items()}})
        _write_json(bucket, MANIFEST_PATH, manifest)

        store = SatStore(bucket)
        store._manifest = (time.monotonic(), manifest)
        for p, df in series.items():
            if df is not None:
                store._series[p] = (built_at, df)
        findings = build_findings(store, today=today)
        _write_json(bucket, FINDINGS_LATEST_PATH, findings)

        outcome.details.update({"products_written": sorted(touched), "pending": pending, "failures": failures[:50],
                                "built_at": built_at, "regions_changed": regions_changed})
        if failures and c.completed:
            outcome.partial_reason = outcome.error_class = "some_days_failed"
        if failures and not c.completed and not c.skipped:
            outcome.fail("all_days_failed", failures[0]["error"])
        if c.expected and not c.completed and not failures:
            outcome.details["note"] = "every planned day is still pending at the source"

    def _fetch_day(self, kind: str, day: date) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        last = None
        for attempt in range(self.retries):
            try:
                return self.ee.day_regions(kind, day), None
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.backoff_s * (attempt + 1))
        return [], f"{type(last).__name__}: {last}"


# ── the reader ────────────────────────────────────────────────────────────────

class SatStore:
    """Read side with small in-process caches (manifest 10 min, series per build, climatology once)."""

    def __init__(self, bucket=None, *, ttl_s: float = 600.0):
        self._bucket = bucket
        self.ttl_s = ttl_s
        self._manifest: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
        self._series: Dict[str, Tuple[Optional[str], pd.DataFrame]] = {}
        self._clim: Dict[str, Optional[pd.DataFrame]] = {}
        self._clim_meta: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
        self._findings: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
        self._adjudicated: Tuple[float, Optional[Any]] = (0.0, None)

    @property
    def bucket(self):
        if self._bucket is None:
            self._bucket = default_bucket()
        return self._bucket

    def manifest(self) -> Dict[str, Any]:
        at, m = self._manifest
        if m is not None and time.monotonic() - at < self.ttl_s:
            return m
        m = _read_json(self.bucket, MANIFEST_PATH) or {}
        self._manifest = (time.monotonic(), m)
        return m

    def series(self, product: str) -> pd.DataFrame:
        built = self.manifest().get("built_at")
        key, df = self._series.get(product, (None, None))
        if df is not None and key == built:
            return df
        df = _read_parquet(self.bucket, series_path(product))
        if df is None:
            df = empty_series()
        else:
            df["day"] = pd.to_datetime(df["day"]).dt.date
        self._series[product] = (built, df)
        return df

    def climatology(self, product: str) -> Optional[pd.DataFrame]:
        if product not in self._clim:
            self._clim[product] = _read_parquet(self.bucket, clim_path(product))
        return self._clim[product]

    def clim_meta(self) -> Dict[str, Any]:
        at, m = self._clim_meta
        if m is not None and time.monotonic() - at < self.ttl_s:
            return m
        m = _read_json(self.bucket, CLIM_META_PATH) or {}
        self._clim_meta = (time.monotonic(), m)
        return m

    def findings(self) -> Dict[str, Any]:
        at, m = self._findings
        if m is not None and time.monotonic() - at < self.ttl_s:
            return m
        m = _read_json(self.bucket, FINDINGS_LATEST_PATH) or {}
        self._findings = (time.monotonic(), m)
        return m

    def adjudicated(self) -> List[Dict[str, Any]]:
        at, m = self._adjudicated
        if m is not None and time.monotonic() - at < self.ttl_s * 6:
            return m
        doc = _read_json(self.bucket, FINDINGS_ADJUDICATED_PATH) or {}
        m = doc.get("findings") if isinstance(doc, dict) else (doc or [])
        self._adjudicated = (time.monotonic(), m or [])
        return m or []

    # -- queries --------------------------------------------------------------------

    def daily(self, product: str, region: str, start: date, end: date, *, platform: str = "both") -> pd.DataFrame:
        """Day rows of one region (platforms combined unless one is named) with the z-anomaly against the climatology."""
        df = self.series(product)
        sel = df[(df["region"] == region) & (df["day"] >= start) & (df["day"] <= end)]
        if PRODUCTS[product]["platforms"]:
            sel = combine_platforms(sel) if platform == "both" else sel[sel["platform"] == platform]
        sel = sel.sort_values("day").reset_index(drop=True)
        table = self.climatology(product)
        if table is not None and not sel.empty:
            t = table[table["region"] == region] if "region" in table.columns else table
            sel = sel.copy()
            sel["z"] = clim.zscores(t, [pd.Timestamp(d) for d in sel["day"]], sel["value"].to_numpy(float)) if not t.empty else np.nan
            e = clim.expected(t, [pd.Timestamp(d) for d in sel["day"]]) if not t.empty else None
            sel["expected"] = e["mean"].to_numpy(float) if e is not None and not e.empty else np.nan
        else:
            sel = sel.copy()
            sel["z"] = np.nan
            sel["expected"] = np.nan
        return sel

    def window(self, product: str, region: str, start: date, end: date, *, platform: str = "both",
               min_cov: float = MIN_COVERAGE) -> Dict[str, Any]:
        """Window summary: mean over assessable days, coverage, mean z, percent of the climatology, last day with data."""
        d = self.daily(product, region, start, end, platform=platform)
        ok = d[(d["coverage"] >= min_cov) & d["value"].notna()] if not d.empty else d
        out: Dict[str, Any] = {
            "product": product, "region": region, "start": start.isoformat(), "end": end.isoformat(),
            "days_requested": (end - start).days + 1, "days_with_data": int(d["value"].notna().sum()) if not d.empty else 0,
            "days_assessable": int(len(ok)), "min_coverage": min_cov,
            "mean": float(ok["value"].mean()) if len(ok) else None,
            "coverage_mean": float(d["coverage"].mean()) if not d.empty else 0.0,
            "last_day": max(d.loc[d["value"].notna(), "day"]).isoformat() if (not d.empty and d["value"].notna().any()) else None,
            "z_mean": float(ok["z"].mean()) if len(ok) and ok["z"].notna().any() else None,
            "percent_of_normal": None, "units": PRODUCTS[product]["units"], "label": PRODUCTS[product]["label"],
        }
        if len(ok) and ok["expected"].notna().any():
            exp = float(ok["expected"].mean())
            if exp and np.isfinite(exp) and exp != 0:
                out["percent_of_normal"] = round(100.0 * out["mean"] / exp, 1)
        return out


_STORE: Optional[SatStore] = None


def sat_store() -> SatStore:
    global _STORE
    if _STORE is None:
        _STORE = SatStore()
    return _STORE


# ── findings ──────────────────────────────────────────────────────────────────

def build_findings(store: SatStore, *, today: date, window_days: int = WINDOW_DAYS,
                   region_ids: Optional[Iterable[str]] = None, products: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """The current picture per region × product: last available day, the recent-window mean, coverage and anomaly."""
    region_ids = list(region_ids or regions.REGION_IDS)
    products = list(products or PRODUCTS)
    end = today - timedelta(days=1)
    start = end - timedelta(days=window_days - 1)
    out: Dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "window": {"start": start.isoformat(),
                           "end": end.isoformat(), "days": window_days}, "regions": {}, "definitions": DEFINITIONS,
                           "caveats": CAVEATS, "products": {p: {"label": m["label"], "units": m["units"]} for p, m in PRODUCTS.items()}}
    manifest = store.manifest()
    out["products_available"] = {p: v for p, v in (manifest.get("products") or {}).items()}
    for rid in region_ids:
        row: Dict[str, Any] = {"label": regions.label(rid), "kind": regions.kind_of(rid)}
        for p in products:
            df = store.series(p)
            if df.empty or not (df["region"] == rid).any():
                continue
            w = store.window(p, rid, start, end)
            last_day = max(df.loc[(df["region"] == rid) & df["value"].notna(), "day"], default=None)
            row[p] = {"last_day": last_day.isoformat() if last_day else None, "window_mean": w["mean"],
                      "days_assessable": w["days_assessable"], "coverage_mean": round(w["coverage_mean"], 3),
                      "z_mean": round(w["z_mean"], 2) if w["z_mean"] is not None else None,
                      "percent_of_normal": w["percent_of_normal"]}
        out["regions"][rid] = row
    return out
