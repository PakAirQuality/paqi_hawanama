"""
Source classification of FIRMS detections: likely crop-residue burning, likely other source,
or uncertain. A thermal detection says that something burned hot enough to be seen; it does
not say what. This module adds the evidence a human would use and records why.

Class version wc2021-v1. Inputs are built once by scripts and read from GCS (same bucket as
the day files, hindcast/firms/masks/):
- cropfrac_wc2021_0p005.npz   cropland share of each 0.005° (~500 m) cell from ESA WorldCover
                              2021 v200 class 40 (CC BY 4.0); uint8 percent, 255 = no data.
                              A detection's `crop_frac` is the mean over the 3 × 3 cells around
                              it (~1.5 km), which covers the VIIRS footprint (375 m at nadir,
                              ~800 m at the swath edge) and its geolocation error.
- thermal_sources_v1.parquet  points that burn for reasons other than fields: brick kilns
                              (APAD/Zenodo inventory via the civic-asset table), OSM factories,
                              and the power, cement, steel, sugar, industrial and mining sites
                              of emission_sources.json. Columns lat, lon, kind, name, source.
- persistent_cells_v1.json    0.02° cells with detections on at least 10 distinct days *outside*
                              both harvest windows in at least one calendar year of the archive:
                              flares, landfills, kilns and industry burn all year; fields do not.

Rules (reasons are a bitmask so a row can be audited):
  likely_crop_residue  crop_frac ≥ 0.5 AND inside a harvest window AND no listed source within
                       1 km AND not a persistent out-of-season cell
  likely_other         crop_frac < 0.2 OR a listed source within 1 km OR a persistent cell
  uncertain            everything else: mixed cover, cropland out of season, no mask coverage
A night detection is recorded as a reason, never a verdict (crop fires are mostly afternoon
detections, but a smouldering field is seen at night too). Nothing here is validated yet:
the stratified sample in scripts/fire_class_sample.py is the way to measure precision, and
classification precision says nothing about the fires the satellites never saw.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.services import fire_regions as fr

logger = logging.getLogger(__name__)

CLASS_VERSION = "wc2021-v1"
MASK_PREFIX = "hindcast/firms/masks"
CROPFRAC_PATH = f"{MASK_PREFIX}/cropfrac_wc2021_0p005.npz"
SOURCES_PATH = f"{MASK_PREFIX}/thermal_sources_v1.parquet"
PERSISTENT_PATH = f"{MASK_PREFIX}/persistent_cells_v1.json"

CROP_HI = 0.5                # cropland share at or above which a cell counts as cropland
CROP_LO = 0.2                # below which it counts as not cropland
SOURCE_KM = 1.0              # a listed thermal source within this distance explains the detection
WINDOW_CELLS = 1             # ±1 cell (3 × 3) around the detection for the cropland share
PERSISTENT_MIN_DAYS = 10     # out-of-season days per calendar year that make a cell persistent
HARVEST_WINDOWS: Dict[str, Tuple[str, str]] = {
    "rice": ("09-15", "11-30"),      # paddy residue, the ISRO/CAQM reporting window
    "wheat": ("04-15", "05-31"),     # wheat residue before rice transplanting
}

# reasons bitmask
R_CROPLAND, R_MIXED, R_NONCROP, R_IN_WINDOW, R_NEAR_SOURCE, R_PERSISTENT, R_NIGHT, R_NO_MASK = 1, 2, 4, 8, 16, 32, 64, 128
REASON_NAMES = {R_CROPLAND: "cropland", R_MIXED: "mixed_cover", R_NONCROP: "not_cropland", R_IN_WINDOW: "harvest_window",
                R_NEAR_SOURCE: "listed_source_within_1km", R_PERSISTENT: "persistent_out_of_season_cell", R_NIGHT: "night_detection",
                R_NO_MASK: "no_mask_coverage"}
CLASSES = ("crop", "other", "uncertain")
CLASS_LABELS = {"crop": "likely crop-residue burning", "other": "likely other source", "uncertain": "uncertain"}
RULES = {
    "crop": f"cropland share ≥ {CROP_HI:.0%} in the ~1.5 km window AND inside a harvest window AND no listed thermal source within {SOURCE_KM:g} km AND not a persistent out-of-season cell",
    "other": f"cropland share < {CROP_LO:.0%} OR a listed thermal source within {SOURCE_KM:g} km OR a persistent out-of-season cell (≥ {PERSISTENT_MIN_DAYS} out-of-season days in a year)",
    "uncertain": "everything else: mixed land cover, cropland outside the harvest windows, or no mask coverage",
    "night": "recorded as a reason only; it never decides the class",
    "status": "unvalidated until the stratified sample is labelled; precision is reported per class and region, never as completeness",
}


# ── inputs ───────────────────────────────────────────────────────────────────

@dataclass
class ClassInputs:
    """Everything the classifier needs, loaded once. Any part may be absent (None): the reasons say so."""
    version: str = CLASS_VERSION
    frac: Optional[np.ndarray] = None          # uint8 percent, rows south→north, cols west→east
    lat0: float = 0.0                          # south edge of row 0
    lon0: float = 0.0                          # west edge of col 0
    step: float = 0.005
    src_tree: Any = None                       # shapely STRtree of source points
    src_kinds: Optional[np.ndarray] = None
    persistent: set = field(default_factory=set)
    paths: Dict[str, Optional[str]] = field(default_factory=dict)

    @property
    def has_mask(self) -> bool:
        return self.frac is not None

    def crop_frac(self, lats: Sequence[float], lons: Sequence[float]) -> np.ndarray:
        """Mean cropland share (0–1) over the (2w+1)² cells around each point; NaN off the grid or on no-data."""
        n = len(lats)
        out = np.full(n, np.nan, dtype=np.float32)
        if self.frac is None or n == 0:
            return out
        rows = np.floor((np.asarray(lats, dtype=float) - self.lat0) / self.step).astype(np.int64)
        cols = np.floor((np.asarray(lons, dtype=float) - self.lon0) / self.step).astype(np.int64)
        nr, nc = self.frac.shape
        w = WINDOW_CELLS
        for i in range(n):
            r, c = int(rows[i]), int(cols[i])
            if r < 0 or c < 0 or r >= nr or c >= nc:
                continue
            block = self.frac[max(r - w, 0):r + w + 1, max(c - w, 0):c + w + 1]
            valid = block[block != 255]
            if valid.size:
                out[i] = float(valid.mean()) / 100.0
        return out

    def near_source(self, lats: Sequence[float], lons: Sequence[float], km: float = SOURCE_KM) -> np.ndarray:
        """True where a listed thermal source lies within km of the point."""
        n = len(lats)
        out = np.zeros(n, dtype=bool)
        if self.src_tree is None or n == 0:
            return out
        import shapely
        lat_a, lon_a = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
        pts = shapely.points(lon_a, lat_a)
        # search in degrees wide enough for the box's longitude scale (1° of longitude is ~85 km at 37°N), then confirm in km
        pi, si = self.src_tree.query(pts, predicate="dwithin", distance=km / fr.KM_PER_DEG_MIN)
        if len(pi):
            geoms = self.src_tree.geometries[si]
            d = fr.haversine_pairs(lat_a[pi], lon_a[pi], shapely.get_y(geoms), shapely.get_x(geoms))
            out[pi[d <= km]] = True
        return out


NO_INPUTS = ClassInputs(paths={"cropfrac": None, "sources": None, "persistent": None})


def _in_window(days: Sequence[date]) -> np.ndarray:
    out = np.zeros(len(days), dtype=bool)
    for i, d in enumerate(days):
        mmdd = d.strftime("%m-%d")
        out[i] = any(s <= mmdd <= e for s, e in HARVEST_WINDOWS.values())
    return out


def in_harvest_window(d: date) -> bool:
    return bool(_in_window([d])[0])


def classify(lats: Sequence[float], lons: Sequence[float], days: Sequence[date], daynight: Sequence[Optional[str]],
             cell_ids: Sequence[int], inputs: Optional[ClassInputs]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(source_class, class_reasons, crop_frac) per detection; pure given the inputs."""
    n = len(lats)
    inputs = inputs or NO_INPUTS
    frac = inputs.crop_frac(lats, lons)
    reasons = np.zeros(n, dtype=np.int16)
    if n == 0:
        return np.zeros(0, dtype=object), reasons, frac
    has = ~np.isnan(frac)
    reasons[has & (frac >= CROP_HI)] |= R_CROPLAND
    reasons[has & (frac < CROP_HI) & (frac >= CROP_LO)] |= R_MIXED
    reasons[has & (frac < CROP_LO)] |= R_NONCROP
    reasons[~has] |= R_NO_MASK
    reasons[_in_window(days)] |= R_IN_WINDOW
    reasons[inputs.near_source(lats, lons)] |= R_NEAR_SOURCE
    if inputs.persistent:
        reasons[np.array([int(c) in inputs.persistent for c in cell_ids], dtype=bool)] |= R_PERSISTENT
    reasons[np.array([x == "N" for x in daynight], dtype=bool)] |= R_NIGHT
    other = (reasons & (R_NONCROP | R_NEAR_SOURCE | R_PERSISTENT)) != 0
    crop = ((reasons & R_CROPLAND) != 0) & ((reasons & R_IN_WINDOW) != 0) & ~other
    cls = np.full(n, "uncertain", dtype=object)
    cls[other] = "other"
    cls[crop] = "crop"
    return cls, reasons, frac


def reasons_text(mask: int) -> List[str]:
    return [name for bit, name in REASON_NAMES.items() if mask & bit]


# ── loading ──────────────────────────────────────────────────────────────────

def _read_bytes(bucket, path: str) -> Optional[bytes]:
    try:
        return bucket.blob(path).download_as_bytes()
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ in ("NotFound", "KeyError") or getattr(exc, "code", None) == 404:
            return None
        raise


def inputs_from_parts(frac_npz: Optional[bytes], sources_parquet: Optional[bytes], persistent_json: Optional[bytes],
                      paths: Optional[Dict[str, Optional[str]]] = None) -> ClassInputs:
    ci = ClassInputs(paths=paths or {})
    if frac_npz:
        z = np.load(io.BytesIO(frac_npz))
        ci.frac = z["frac"].astype(np.uint8)
        ci.lat0, ci.lon0, ci.step = float(z["lat0"]), float(z["lon0"]), float(z["step"])
    if sources_parquet:
        import pandas as pd
        import shapely
        from shapely.strtree import STRtree
        df = pd.read_parquet(io.BytesIO(sources_parquet))
        df = df.dropna(subset=["lat", "lon"])
        ci.src_tree = STRtree(shapely.points(df["lon"].to_numpy(dtype=float), df["lat"].to_numpy(dtype=float)))
        ci.src_kinds = df["kind"].to_numpy(dtype=object)
    if persistent_json:
        doc = json.loads(persistent_json)
        ci.persistent = {int(c) for c in doc.get("cells", [])}
        ci.version = doc.get("class_version", ci.version)
    return ci


def load_inputs(bucket) -> ClassInputs:
    """Read the three inputs from the bucket; a missing part is tolerated (its reason bit says so)."""
    parts = {"cropfrac": CROPFRAC_PATH, "sources": SOURCES_PATH, "persistent": PERSISTENT_PATH}
    raw = {k: _read_bytes(bucket, p) for k, p in parts.items()}
    ci = inputs_from_parts(raw["cropfrac"], raw["sources"], raw["persistent"], paths={k: (p if raw[k] else None) for k, p in parts.items()})
    missing = [k for k, v in raw.items() if v is None]
    if missing:
        logger.warning("fire classification inputs missing: %s (detections there classify as uncertain)", ", ".join(missing))
    return ci


_DEFAULT: Optional[ClassInputs] = None


def default_inputs() -> ClassInputs:
    """Process-wide inputs from the default bucket; NO_INPUTS when GCS is unreachable (logged once)."""
    global _DEFAULT
    if _DEFAULT is None:
        try:
            from app.services.fire_aggregates import default_bucket
            _DEFAULT = load_inputs(default_bucket())
        except Exception as exc:  # noqa: BLE001
            logger.warning("fire classification inputs unavailable: %s", exc)
            _DEFAULT = NO_INPUTS
    return _DEFAULT


def describe(inputs: Optional[ClassInputs]) -> Dict[str, Any]:
    ci = inputs or NO_INPUTS
    return {"class_version": ci.version, "rules": RULES, "classes": CLASS_LABELS,
            "inputs": {"cropfrac": ci.paths.get("cropfrac"), "sources": ci.paths.get("sources"), "persistent": ci.paths.get("persistent")},
            "constants": {"crop_hi": CROP_HI, "crop_lo": CROP_LO, "source_km": SOURCE_KM, "window_cells": WINDOW_CELLS,
                          "persistent_min_days": PERSISTENT_MIN_DAYS, "harvest_windows": HARVEST_WINDOWS},
            "complete": ci.has_mask and ci.src_tree is not None and bool(ci.persistent)}
