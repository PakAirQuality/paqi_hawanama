"""
Pure geometry for fire analytics: region attribution, grid cells, cross-satellite dedup,
bearings, wind conventions and the upwind cone. No I/O except the one-time load of the
boundary files; everything is numpy/shapely-vectorised so a whole year of VIIRS detections
(~600 k rows) is attributed in a second.

Boundaries
- Pakistan ADM0/ADM1/ADM2: apps/api/data/pakistan_country.geojson, pakistan_provinces.geojson
  (geoBoundaries PAK ADM1 2019, CC0) and pakistan_districts.geojson (geoBoundaries PAK ADM2, 126).
- India Punjab and Haryana: apps/api/data/india_states_pb_hr.geojson — geoBoundaries IND ADM1
  (gbOpen, commit 9469f09), boundary year 2011, source DataMeet India community / Election
  Commission of India, licence CC BY 2.5 IN. Only those two states ship: they are the
  cross-border residue-burning belt upwind of Pakistani Punjab in October–November.

Conventions
- country: 'PK', 'IN' (Punjab or Haryana only) or 'XX' (anything else inside the FIRMS bbox:
  Rajasthan, J&K, Himachal, Afghanistan, Iran, China).
- province: a states.name for Pakistan, 'Punjab (IN)' / 'Haryana (IN)' for India, else None.
- district: Pakistan ADM2 shapeName, else None. district ⊂ province is enforced by mapping each
  district to the province containing its representative point (never by a second polygon test).
- Wind directions are meteorological "from" bearings in degrees clockwise from north. A plume
  travels *downwind*; the fires that can reach a city are *upwind*, i.e. at bearings around the
  wind's "from" direction. (The old trajectory fallback added 180° and looked downwind.)
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from app.services.geo_utils import PROVINCE_SHAPE_TO_STATE

logger = logging.getLogger(__name__)

DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
CELL_DEG = 0.02                 # ~2.2 km N–S, ~1.9 km E–W at 31°N
DEDUP_KM = 1.0                  # two VIIRS pixels (375 m) plus geolocation error
DEDUP_MINUTES = 90              # one inter-satellite gap (~50 min) plus slack
CONE_HALF_DEG = 60.0            # upwind cone half-width
DAY_UTC_HOURS = (3, 15)         # VIIRS day passes ~07:30–09:30 UTC, night ~19:30–21:30 UTC
INDIA_REGIONS = ("Punjab (IN)", "Haryana (IN)")
COUNTRY_LABELS = {"PK": "Pakistan", "IN": "India (Punjab+Haryana)", "XX": "other in bbox"}

# One map for every spelling of a satellite seen in FIRMS CSVs (the `satellite` column: N, N20, N21),
# the legacy archive (1 = NOAA-20), and the product names in the sidecars (VIIRS_NOAA20_NRT …).
SATELLITE_KEYS = {"N": "snpp", "SNPP": "snpp", "VIIRS_SNPP_NRT": "snpp", "VIIRS_SNPP_SP": "snpp",
                  "N20": "n20", "1": "n20", "NOAA-20": "n20", "VIIRS_NOAA20_NRT": "n20", "VIIRS_NOAA20_SP": "n20",
                  "N21": "n21", "2": "n21", "NOAA-21": "n21", "VIIRS_NOAA21_NRT": "n21", "VIIRS_NOAA21_SP": "n21"}
SATELLITE_LABELS = {"snpp": "Suomi NPP", "n20": "NOAA-20", "n21": "NOAA-21"}
CONSISTENT_SATELLITE = "n20"           # flown and processed in every archive year (2020 →): the comparison basis


def satellite_key(code: Any) -> Optional[str]:
    """'snpp' | 'n20' | 'n21' for any spelling; None when unknown."""
    if code is None:
        return None
    return SATELLITE_KEYS.get(str(code).strip())


def satellite_name(code: Any) -> str:
    key = satellite_key(code)
    return SATELLITE_LABELS[key] if key else str(code)


# ── region index ───────────────────────────────────────────────────────────────

@dataclass
class RegionIndex:
    tree: Any                                  # shapely.STRtree over every polygon
    kinds: np.ndarray                          # 'country' | 'province' | 'district' | 'india_state'
    names: np.ndarray                          # region names (province names already mapped to states.name)
    district_province: Dict[str, str]          # ADM2 shapeName -> states.name


_INDEX: Optional[RegionIndex] = None


def _features(path: str) -> List[Dict[str, Any]]:
    with open(os.path.join(DATA_DIR, path)) as f:
        return json.load(f)["features"]


def load_region_index() -> RegionIndex:
    """Build (once per process) the STRtree over PK ADM0/ADM1/ADM2 and IN Punjab/Haryana."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    geoms: List[Any] = []
    kinds: List[str] = []
    names: List[str] = []
    for feat in _features("pakistan_country.geojson"):
        geoms.append(shape(feat["geometry"])); kinds.append("country"); names.append("PK")
    provinces: List[Tuple[str, Any]] = []
    for feat in _features("pakistan_provinces.geojson"):
        name = PROVINCE_SHAPE_TO_STATE.get(feat["properties"]["shapeName"], feat["properties"]["shapeName"])
        g = shape(feat["geometry"])
        provinces.append((name, g))
        geoms.append(g); kinds.append("province"); names.append(name)
    district_province: Dict[str, str] = {}
    for feat in _features("pakistan_districts.geojson"):
        g = shape(feat["geometry"])
        name = feat["properties"]["shapeName"]
        rp = g.representative_point()
        district_province[name] = next((pn for pn, pg in provinces if pg.contains(rp)), "")
        geoms.append(g); kinds.append("district"); names.append(name)
    for feat in _features("india_states_pb_hr.geojson"):
        geoms.append(shape(feat["geometry"])); kinds.append("india_state"); names.append(feat["properties"]["region"])
    _INDEX = RegionIndex(STRtree(geoms), np.array(kinds, dtype=object), np.array(names, dtype=object), district_province)
    return _INDEX


def attribute_points(lats: Sequence[float], lons: Sequence[float], idx: Optional[RegionIndex] = None) -> Dict[str, np.ndarray]:
    """country / province / district arrays for every point (see the module conventions)."""
    import shapely
    idx = idx or load_region_index()
    n = len(lats)
    country = np.full(n, "XX", dtype=object)
    province = np.full(n, None, dtype=object)
    district = np.full(n, None, dtype=object)
    if n == 0:
        return {"country": country, "province": province, "district": district}
    pts = shapely.points(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
    pi, gi = idx.tree.query(pts, predicate="within")
    kinds, names = idx.kinds[gi], idx.names[gi]
    # order matters: country first, then province, then district (district wins the province)
    for kind in ("country", "province", "india_state", "district"):
        m = kinds == kind
        if not m.any():
            continue
        rows, vals = pi[m], names[m]
        if kind == "country":
            country[rows] = "PK"
        elif kind == "province":
            province[rows] = vals
            country[rows] = "PK"          # ADM1 wins over slivers of the simplified ADM0 outline
        elif kind == "india_state":
            country[rows] = "IN"
            province[rows] = vals
        else:
            district[rows] = vals
            country[rows] = "PK"
            province[rows] = [idx.district_province.get(v) or province[r] for r, v in zip(rows, vals)]
    return {"country": country, "province": province, "district": district}


# ── grid cells and clusters ─────────────────────────────────────────────────────

def cell_id(lats: Sequence[float], lons: Sequence[float], size_deg: float = CELL_DEG) -> np.ndarray:
    """Stable int64 id of the size_deg × size_deg cell containing each point."""
    row = np.floor((np.asarray(lats, dtype=float) + 90.0) / size_deg).astype(np.int64)
    col = np.floor((np.asarray(lons, dtype=float) + 180.0) / size_deg).astype(np.int64)
    return (row << 20) | col


def cell_center(cid: int, size_deg: float = CELL_DEG) -> Tuple[float, float]:
    row, col = int(cid) >> 20, int(cid) & ((1 << 20) - 1)
    return round((row + 0.5) * size_deg - 90.0, 4), round((col + 0.5) * size_deg - 180.0, 4)


class _UnionFind:
    def __init__(self, n: int):
        self.p = np.arange(n)

    def find(self, a: int) -> int:
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)

    def labels(self) -> np.ndarray:
        roots = np.array([self.find(i) for i in range(len(self.p))])
        _, inv = np.unique(roots, return_inverse=True)
        return inv.astype(np.int32)


def cluster_cells(cell_ids: Sequence[int]) -> np.ndarray:
    """Cluster label per input cell: 8-neighbour connectivity on the grid (same label = same cluster)."""
    cells = np.asarray(cell_ids, dtype=np.int64)
    uniq, inv = np.unique(cells, return_inverse=True)
    pos = {int(c): i for i, c in enumerate(uniq)}
    uf = _UnionFind(len(uniq))
    for i, c in enumerate(uniq):
        c = int(c)
        row, col = c >> 20, c & ((1 << 20) - 1)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                j = pos.get(((row + dr) << 20) | (col + dc))
                if j is not None:
                    uf.union(i, j)
    return uf.labels()[inv]


# ── distances, bearings, dedup ──────────────────────────────────────────────────

def haversine_km_vec(lat0: float, lon0: float, lats: Sequence[float], lons: Sequence[float]) -> np.ndarray:
    lat1, lon1 = math.radians(lat0), math.radians(lon0)
    lat2, lon2 = np.radians(np.asarray(lats, dtype=float)), np.radians(np.asarray(lons, dtype=float))
    a = np.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def bearing_deg(lat0: float, lon0: float, lats: Sequence[float], lons: Sequence[float]) -> np.ndarray:
    """Initial bearing from (lat0, lon0) to each point, degrees clockwise from north [0, 360)."""
    lat1, lon1 = math.radians(lat0), math.radians(lon0)
    lat2, lon2 = np.radians(np.asarray(lats, dtype=float)), np.radians(np.asarray(lons, dtype=float))
    dlon = lon2 - lon1
    x = np.sin(dlon) * np.cos(lat2)
    y = math.cos(lat1) * np.sin(lat2) - math.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    return (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0


def dedup_groups(lats: Sequence[float], lons: Sequence[float], sats: Sequence[str],
                 acq_minutes: Sequence[Optional[float]], *, max_km: float = DEDUP_KM,
                 max_minutes: float = DEDUP_MINUTES) -> np.ndarray:
    """Group id per detection: detections from *different* satellites within max_km and (when
    both times are known) within max_minutes are one fire. Same-satellite detections never merge
    directly (two pixels of one pass are two burning pixels), but groups are transitive: an N21
    pixel between two N20 pixels joins all three."""
    import shapely
    from shapely.strtree import STRtree
    n = len(lats)
    if n == 0:
        return np.zeros(0, dtype=np.int32)
    lat_a, lon_a = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    sat_a = np.asarray(sats, dtype=object)
    t_a = np.array([np.nan if t is None else float(t) for t in acq_minutes], dtype=float)
    pts = shapely.points(lon_a, lat_a)
    tree = STRtree(pts)
    # max_km in degrees of latitude is a safe search radius (longitude degrees are shorter here)
    ai, bi = tree.query(pts, predicate="dwithin", distance=max_km / 111.0 * 1.001)
    m = ai < bi
    ai, bi = ai[m], bi[m]
    if len(ai):
        m = sat_a[ai] != sat_a[bi]
        ai, bi = ai[m], bi[m]
    if len(ai):
        km = haversine_pairs(lat_a[ai], lon_a[ai], lat_a[bi], lon_a[bi])
        both = ~np.isnan(t_a[ai]) & ~np.isnan(t_a[bi])
        dt_ok = ~both | (np.abs(t_a[ai] - t_a[bi]) <= max_minutes)
        m = (km <= max_km) & dt_ok
        ai, bi = ai[m], bi[m]
    uf = _UnionFind(n)
    for a, b in zip(ai.tolist(), bi.tolist()):
        uf.union(a, b)
    return uf.labels()


def haversine_pairs(lat1, lon1, lat2, lon2) -> np.ndarray:
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def primary_mask(groups: np.ndarray, frp: Sequence[float]) -> np.ndarray:
    """True for the highest-FRP member of each group (ties: the first)."""
    frp_a = np.asarray(frp, dtype=float)
    out = np.zeros(len(groups), dtype=bool)
    if len(groups) == 0:
        return out
    order = np.lexsort((-frp_a, groups))            # by group, then FRP descending
    first = np.ones(len(order), dtype=bool)
    first[1:] = groups[order][1:] != groups[order][:-1]
    out[order[first]] = True
    return out


# ── wind ─────────────────────────────────────────────────────────────────────

def wind_from_deg(u: float, v: float) -> float:
    """Meteorological 'from' direction of a (u east, v north) wind vector, degrees from north."""
    return (270.0 - math.degrees(math.atan2(v, u))) % 360.0


def wind_speed(u: float, v: float) -> float:
    return math.hypot(u, v)


def vector_mean_from_deg(dirs_deg: Iterable[float], speeds: Iterable[float]) -> Tuple[Optional[float], Optional[float]]:
    """Vector mean of 'from' directions weighted by speed -> (from_deg, mean speed). None when empty."""
    us, vs, ss = [], [], []
    for d, s in zip(dirs_deg, speeds):
        if d is None or s is None:
            continue
        r = math.radians(float(d))
        # a wind *from* d blows towards d+180: u = -s sin d, v = -s cos d
        us.append(-float(s) * math.sin(r)); vs.append(-float(s) * math.cos(r)); ss.append(float(s))
    if not ss:
        return None, None
    u, v = sum(us) / len(us), sum(vs) / len(vs)
    if math.hypot(u, v) < 1e-9:
        return None, round(sum(ss) / len(ss), 2)
    return round(wind_from_deg(u, v), 1), round(sum(ss) / len(ss), 2)


def angle_diff(a: np.ndarray, b: float) -> np.ndarray:
    """Smallest absolute difference between bearings, degrees in [0, 180]."""
    d = np.abs((np.asarray(a, dtype=float) - b + 180.0) % 360.0 - 180.0)
    return d


def in_cone(bearings: Sequence[float], upwind_from_deg: float, half_width_deg: float = CONE_HALF_DEG) -> np.ndarray:
    """True where a fire's bearing from the city lies within ±half_width of the wind's 'from' direction."""
    return angle_diff(np.asarray(bearings, dtype=float), float(upwind_from_deg)) <= half_width_deg


def compass(deg: Optional[float]) -> Optional[str]:
    if deg is None:
        return None
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((float(deg) + 11.25) // 22.5) % 16]


# ── time ─────────────────────────────────────────────────────────────────────

def day_night(utc_hours: Sequence[Optional[float]]) -> np.ndarray:
    """'D' for a daytime pass (UTC hour in [3, 15)), 'N' otherwise, None when the time is unknown."""
    out = np.full(len(utc_hours), None, dtype=object)
    for i, h in enumerate(utc_hours):
        if h is None or (isinstance(h, float) and math.isnan(h)):
            continue
        out[i] = "D" if DAY_UTC_HOURS[0] <= float(h) < DAY_UTC_HOURS[1] else "N"
    return out
