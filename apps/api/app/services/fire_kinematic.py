"""fire_kinematic: on-demand kinematic air-parcel trajectories on ECMWF IFS 0.25° winds (Open-Meteo).

A kinematic trajectory integrates a parcel through the gridded wind field — what HYSPLIT does
underneath, without its vertical motion, turbulence or terrain. Here the parcel stays on a pressure
level (isobaric) and the winds are hourly ECMWF IFS 0.25° analyses/forecasts read from Open-Meteo's
public API, which serves any hour in the last ~92 days and the next 15 (no key; CC BY 4.0;
non-commercial tier). The answer is a *plausibility screen* of where the air was (backward) or
where it goes (forward), never a smoke-arrival probability or a PM2.5 contribution.

Method
- two passes: a coarse 2° wind grid around the start point gives draft paths; a 0.5° grid in a
  corridor around them gives the final paths (two HTTP requests, ≤ MAX_LOCATIONS points each);
- Petterssen predictor–corrector with a 15-minute step, bilinear in space, linear in time;
- three levels (1000, 925, 850 hPa ≈ 100, 700 and 1,400 m above the plains); agreement across
  levels is reported, disagreement means the pathway is uncertain;
- an ensemble per level in HYSPLIT's hyts_ens manner: the start point shifted by one IFS grid cell
  (±0.25°) sideways and by ±25 hPa vertically (winds interpolated in log-pressure between the fetched
  levels, 700 hPa fetched for the member above 850), 27 members per level (18 at 1000 hPa, where the
  lower offset is clamped), run on the fine corridor with the coarse field as fallback; the members'
  sector counts, the region each is over at 24/48/72 h and their mean distance from the central
  path are the empirical spread; the spread is sensitivity to the wind field, not a probability;
- hourly points are attributed to Pakistan / Indian Punjab / Haryana with the fire store's
  boundaries, and matched to deduplicated fire detections (strict: 10 km, ±1 h, inside the mixed
  layer, as the HYSPLIT job does; loose: 25 km, ±3 h, because the path carries tens of km of error
  by 48 h); fires are matched on the central paths only.

The HYSPLIT job (`fire_trajectories`) remains the preferred engine whenever its output exists.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.services import fire_regions as fr
from app.services import fire_trajectories as ft

log = logging.getLogger(__name__)

ENGINE = "kinematic_ecmwf_ifs025"
STATUS = "kinematic"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs025"
WIND_SOURCE = "ECMWF IFS 0.25° hourly winds via Open-Meteo (CC BY 4.0)"
LEVELS: Tuple[int, ...] = (1000, 925, 850)                # start levels
FETCH_LEVELS: Tuple[int, ...] = (1000, 925, 850, 700)     # fetched: 700 hPa carries the member above 850
LEVEL_AGL_M = {1000: 100.0, 925: 700.0, 850: 1400.0, 700: 2900.0}   # nominal height above the Indus–Ganges plains (~200 m ASL)
ENSEMBLE_DX_DEG = 0.25                                    # one IFS grid cell sideways
ENSEMBLE_DP_HPA = 25.0                                    # vertical offset of the members
ENSEMBLE_AGES: Tuple[int, ...] = (24, 48, 72)
ENSEMBLE_DT_MIN = 30                                      # the members are a sensitivity test: half the central path's resolution
HOURS = 72
MAX_HOURS = 72
DT_MIN = 15
COVERAGE_PAST_DAYS = 88                                   # Open-Meteo past_days ≤ 92; a 72 h run needs the days before the arrival too
COVERAGE_FORECAST_DAYS = 15
COARSE_DEG, COARSE_HALF_LAT, COARSE_HALF_LON = 2.0, 10.0, 12.0
FINE_DEG, CORRIDOR_DEG = 0.5, 1.5
BOX = (5.0, 40.0, 55.0, 95.0)                             # lat min, lat max, lon min, lon max: the wind grid never leaves it
MAX_LOCATIONS = 200
LOOSE_KM, LOOSE_HOURS = 25.0, 3.0
MAX_FIRE_POINTS = 300                                     # fire coordinates carried for the map, by FRP
MEMO_TTL_S = 600.0
MEMO_MAX = 100
CACHE_PREFIX = "forecasts/trajectories/kinematic_v2"      # v2: documents carry the ensemble
FORECAST_REFRESH_H = 6.0
SLOW_RUN_S = 20.0                                         # a run slower than this is logged with its timings
EXTRA_RECEPTORS: Dict[str, Tuple[float, float]] = {       # places the Pakistan registry does not hold
    "Delhi": ft.RECEPTORS["Delhi"], "New Delhi": ft.RECEPTORS["Delhi"],
    "Amritsar": (31.6340, 74.8723), "Chandigarh": (30.7333, 76.7794), "Ludhiana": (30.9010, 75.8573),
}
REGION_LABELS = ("Pakistan Punjab", "other Pakistan", "Indian Punjab", "Haryana", "elsewhere")

DEFINITIONS = {
    "engine": "kinematic isobaric trajectory: the parcel is advected through hourly ECMWF IFS 0.25° winds on a fixed pressure level "
              "(Petterssen predictor–corrector, 15-minute step, bilinear in space, linear in time); no vertical motion, turbulence or terrain",
    "levels": "1000, 925 and 850 hPa, about 100, 700 and 1,400 m above the plains; agreement across levels is reported, disagreement means the pathway is uncertain",
    "error": "position error of roughly 10–20 % of the distance travelled (tens of km by 24 h, up to 100–200 km by 72 h)",
    "ensemble": f"per level, members from start points shifted by ±{ENSEMBLE_DX_DEG:g}° sideways and ±{ENSEMBLE_DP_HPA:g} hPa vertically "
                "(27 per level, 18 at 1000 hPa where the lower offset is clamped), as HYSPLIT's hyts_ens does; the sector counts, the region "
                "each member is over at 24/48/72 h and spread_km (mean distance of the members from the central path) show how sensitive the "
                "path is to the wind field; the spread is not a probability",
    "match_strict": ft.DEFINITIONS["match"],
    "match_loose": f"a trajectory point within {LOOSE_KM:g} km and ±{LOOSE_HOURS:g} h of a detection, any height: the loose match absorbs the path error",
    "residence_hours": "hours the parcel spent over each region along the path, from the hourly points",
    "not_attribution": ft.DEFINITIONS["not_attribution"],
    "forward_vs_backward": ft.DEFINITIONS["forward_vs_backward"],
}
CAVEATS = [
    "Kinematic isobaric trajectory on ECMWF IFS 0.25° winds via Open-Meteo, hourly, no vertical motion or turbulence; "
    "position error of roughly 10–20 % of the distance travelled.",
    "A plausibility screen for where the air was (or goes), not an attribution of PM2.5: say 'transport pathway consistent with', never 'caused'.",
    "The ensemble members show how sensitive the path is to the wind field; their spread is not a probability of where the air was.",
    "Replaced by the HYSPLIT ensemble on GFS 0.25° meteorology when that engine is installed; HYSPLIT output is used whenever it exists.",
]


# ── the wind field ───────────────────────────────────────────────────────────

@dataclass
class WindField:
    """Hourly u/v (m/s) and geopotential height (m) per level on a regular lat/lon grid (missing cells allowed)."""
    lat_axis: np.ndarray            # ascending
    lon_axis: np.ndarray            # ascending
    t0: datetime                    # naive UTC of times[0]
    n_hours: int
    u: Dict[int, np.ndarray]        # (nlat, nlon, T), NaN where the grid cell was not requested
    v: Dict[int, np.ndarray]
    z: Dict[int, np.ndarray]

    def hours_since_t0(self, t: datetime) -> float:
        return (t - self.t0).total_seconds() / 3600.0

    def sample(self, level: int, lat: float, lon: float, th: float) -> Optional[Tuple[float, float, float]]:
        """(u, v, z) at a point and time (hours since t0); None when outside the field or every corner is missing."""
        la, lo = self.lat_axis, self.lon_axis
        if not (la[0] <= lat <= la[-1] and lo[0] <= lon <= lo[-1]) or not (0.0 <= th <= self.n_hours - 1):
            return None
        i = min(int(np.searchsorted(la, lat, side="right")) - 1, len(la) - 2)
        j = min(int(np.searchsorted(lo, lon, side="right")) - 1, len(lo) - 2)
        k = min(int(math.floor(th)), self.n_hours - 2)
        fy = (lat - la[i]) / (la[i + 1] - la[i]) if len(la) > 1 else 0.0
        fx = (lon - lo[j]) / (lo[j + 1] - lo[j]) if len(lo) > 1 else 0.0
        ftt = th - k
        corners = ((i, j, (1 - fy) * (1 - fx)), (i + 1, j, fy * (1 - fx)), (i, j + 1, (1 - fy) * fx), (i + 1, j + 1, fy * fx))
        out = []
        for arr in (self.u[level], self.v[level], self.z[level]):
            num = 0.0
            den = 0.0
            for ci, cj, w in corners:
                if w <= 0.0:
                    continue
                a, b = arr[ci, cj, k], arr[ci, cj, k + 1]
                if np.isnan(a) or np.isnan(b):
                    continue
                num += w * ((1 - ftt) * a + ftt * b)
                den += w
            if den < 0.25:           # fewer than a quarter of the weight on valid cells: the parcel has left the data
                return None
            out.append(num / den)
        return out[0], out[1], out[2]

    def sample_p(self, p_hpa: float, lat: float, lon: float, th: float) -> Optional[Tuple[float, float, float]]:
        """(u, v, z) at any pressure between the fetched levels, linear in log-pressure; clamped beyond them."""
        levels = sorted(self.u, reverse=True)                 # 1000 … 700: pressure falls with height
        p = float(p_hpa)
        if p >= levels[0]:
            return self.sample(levels[0], lat, lon, th)
        if p <= levels[-1]:
            return self.sample(levels[-1], lat, lon, th)
        for hi, lo in zip(levels, levels[1:]):
            if lo <= p <= hi:
                if p == hi:
                    return self.sample(hi, lat, lon, th)
                if p == lo:
                    return self.sample(lo, lat, lon, th)
                a = self.sample(hi, lat, lon, th)
                b = self.sample(lo, lat, lon, th)
                if a is None or b is None:
                    return None
                w = (math.log(hi) - math.log(p)) / (math.log(hi) - math.log(lo))
                return tuple((1 - w) * x + w * y for x, y in zip(a, b))  # type: ignore[return-value]
        return None


class CompositeField:
    """The fine corridor with the coarse field behind it: a parcel off the corridor (or on a thinned cell) keeps moving."""

    def __init__(self, fine: WindField, coarse: WindField):
        self.fine, self.coarse = fine, coarse
        self.t0, self.n_hours = fine.t0, fine.n_hours
        self._shift = (fine.t0 - coarse.t0).total_seconds() / 3600.0   # 0 when both were fetched for the same days

    def hours_since_t0(self, t: datetime) -> float:
        return self.fine.hours_since_t0(t)

    def sample(self, level: int, lat: float, lon: float, th: float) -> Optional[Tuple[float, float, float]]:
        s = self.fine.sample(level, lat, lon, th) if level in self.fine.u else None
        return s if s is not None else self.coarse.sample(level, lat, lon, th + self._shift)

    def sample_p(self, p_hpa: float, lat: float, lon: float, th: float) -> Optional[Tuple[float, float, float]]:
        s = self.fine.sample_p(p_hpa, lat, lon, th)
        return s if s is not None else self.coarse.sample_p(p_hpa, lat, lon, th + self._shift)


def agl_for_p(p_hpa: float) -> float:
    """Nominal height above the plains at a pressure, log-linear between the LEVEL_AGL_M anchors."""
    levels = sorted(LEVEL_AGL_M, reverse=True)
    p = float(p_hpa)
    if p >= levels[0]:
        return LEVEL_AGL_M[levels[0]]
    if p <= levels[-1]:
        return LEVEL_AGL_M[levels[-1]]
    for hi, lo in zip(levels, levels[1:]):
        if lo <= p <= hi:
            w = (math.log(hi) - math.log(p)) / (math.log(hi) - math.log(lo))
            return round((1 - w) * LEVEL_AGL_M[hi] + w * LEVEL_AGL_M[lo])
    return LEVEL_AGL_M[levels[-1]]


def _grid(lat0: float, lon0: float, step: float, half_lat: float, half_lon: float) -> List[Tuple[float, float]]:
    lats = np.arange(math.floor((lat0 - half_lat) / step) * step, lat0 + half_lat + step / 2, step)
    lons = np.arange(math.floor((lon0 - half_lon) / step) * step, lon0 + half_lon + step / 2, step)
    return [(round(float(a), 3), round(float(b), 3)) for a in lats for b in lons
            if BOX[0] <= a <= BOX[1] and BOX[2] <= b <= BOX[3]]


def _corridor(paths: Sequence[pd.DataFrame], step: float, half: float) -> List[Tuple[float, float]]:
    """0.5° grid cells within `half` degrees of any draft path point (plus the start)."""
    cells = set()
    for p in paths:
        for lat, lon in zip(p["lat"].to_numpy(), p["lon"].to_numpy()):
            la0 = math.floor((lat - half) / step) * step
            lo0 = math.floor((lon - half) / step) * step
            a = la0
            while a <= lat + half + 1e-9:
                b = lo0
                while b <= lon + half + 1e-9:
                    if BOX[0] <= a <= BOX[1] and BOX[2] <= b <= BOX[3]:
                        cells.add((round(a, 3), round(b, 3)))
                    b += step
                a += step
    return sorted(cells)


def _thin(points: List[Tuple[float, float]], limit: int) -> List[Tuple[float, float]]:
    if len(points) <= limit:
        return points
    stride = math.ceil(len(points) / limit)
    return points[::stride]


def _hourly_vars(levels: Sequence[int]) -> List[str]:
    out = []
    for lv in levels:
        out += [f"wind_speed_{lv}hPa", f"wind_direction_{lv}hPa", f"geopotential_height_{lv}hPa"]
    return out


async def fetch_winds(http, points: Sequence[Tuple[float, float]], t_start: datetime, t_end: datetime,
                      levels: Sequence[int] = FETCH_LEVELS) -> WindField:
    """One Open-Meteo request for every point over [t_start, t_end] (UTC, whole days) → WindField."""
    pts = list(points)
    params = {"latitude": ",".join(f"{a:.3f}" for a, _ in pts), "longitude": ",".join(f"{b:.3f}" for _, b in pts),
              "hourly": ",".join(_hourly_vars(levels)), "models": MODEL, "timezone": "UTC", "wind_speed_unit": "ms",
              "start_date": t_start.date().isoformat(), "end_date": t_end.date().isoformat()}
    last_exc: Optional[BaseException] = None
    body = None
    for attempt in range(2):
        try:
            resp = await http.get(OPEN_METEO_URL, params=params, timeout=60.0)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            body = resp.json()
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 0:
                await asyncio.sleep(2.0)
    if body is None:
        raise RuntimeError(f"Open-Meteo winds failed: {type(last_exc).__name__}: {last_exc}")
    recs = body if isinstance(body, list) else [body]
    if len(recs) != len(pts):
        raise RuntimeError(f"Open-Meteo returned {len(recs)} locations for {len(pts)} requested")
    times = recs[0]["hourly"]["time"]
    t0 = datetime.fromisoformat(times[0])
    n_hours = len(times)
    lat_axis = np.array(sorted({a for a, _ in pts}))
    lon_axis = np.array(sorted({b for _, b in pts}))
    ii = {float(a): k for k, a in enumerate(lat_axis)}
    jj = {float(b): k for k, b in enumerate(lon_axis)}
    u = {lv: np.full((len(lat_axis), len(lon_axis), n_hours), np.nan) for lv in levels}
    v = {lv: np.full((len(lat_axis), len(lon_axis), n_hours), np.nan) for lv in levels}
    z = {lv: np.full((len(lat_axis), len(lon_axis), n_hours), np.nan) for lv in levels}
    for (a, b), rec in zip(pts, recs):
        h = rec["hourly"]
        i, j = ii[a], jj[b]
        for lv in levels:
            spd = np.array(h.get(f"wind_speed_{lv}hPa") or [np.nan] * n_hours, dtype=float)
            dr = np.array(h.get(f"wind_direction_{lv}hPa") or [np.nan] * n_hours, dtype=float)
            gz = np.array(h.get(f"geopotential_height_{lv}hPa") or [np.nan] * n_hours, dtype=float)
            rad = np.deg2rad(dr)
            u[lv][i, j, :] = -spd * np.sin(rad)        # meteorological "from" direction → vector the air moves along
            v[lv][i, j, :] = -spd * np.cos(rad)
            z[lv][i, j, :] = gz
    return WindField(lat_axis, lon_axis, t0, n_hours, u, v, z)


# ── integration ──────────────────────────────────────────────────────────────

M_PER_DEG = 111_195.0


def _step(lat: float, lon: float, u: float, v: float, dt_s: float) -> Tuple[float, float]:
    return lat + v * dt_s / M_PER_DEG, lon + u * dt_s / (M_PER_DEG * math.cos(math.radians(lat)))


def integrate(field, lat0: float, lon0: float, level: int, t_start: datetime, hours: int,
              direction: str = "backward", dt_min: int = DT_MIN, p_hpa: Optional[float] = None) -> pd.DataFrame:
    """Hourly parcel positions on one level (or at `p_hpa`, between the fetched levels). Stops early when the parcel leaves the field."""
    sign = -1.0 if direction == "backward" else 1.0
    dt_s = sign * dt_min * 60.0
    steps_per_hour = int(round(60 / dt_min))
    lat, lon = float(lat0), float(lon0)
    p = float(level) if p_hpa is None else float(p_hpa)
    agl = LEVEL_AGL_M[level] if p_hpa is None else agl_for_p(p)
    if p_hpa is None or p == float(level):
        def sample(la, lo, t):
            return field.sample(level, la, lo, t)
    else:
        def sample(la, lo, t):
            return field.sample_p(p, la, lo, t)
    th = field.hours_since_t0(t_start)
    s0 = sample(lat, lon, th)
    rows = [{"traj_id": level, "time": t_start, "age_h": 0.0, "lat": lat, "lon": lon, "height_agl": agl,
             "z_msl": s0[2] if s0 else None, "speed_ms": math.hypot(s0[0], s0[1]) if s0 else None}]
    left = s0 is None
    for n in range(1, hours * steps_per_hour + 1):
        if left:
            break
        s = sample(lat, lon, th)
        if s is None:
            left = True
            break
        p_lat, p_lon = _step(lat, lon, s[0], s[1], dt_s)
        th_next = th + sign * dt_min / 60.0
        s2 = sample(p_lat, p_lon, th_next)
        if s2 is None:
            left = True
            break
        for _ in range(2):                                   # Petterssen corrector, twice
            lat_c, lon_c = _step(lat, lon, 0.5 * (s[0] + s2[0]), 0.5 * (s[1] + s2[1]), dt_s)
            s3 = sample(lat_c, lon_c, th_next)
            if s3 is None:
                left = True
                break
            p_lat, p_lon, s2 = lat_c, lon_c, s3
        if left:
            break
        lat, lon, th = p_lat, p_lon, th_next
        if n % steps_per_hour == 0:
            age = sign * n / steps_per_hour
            rows.append({"traj_id": level, "time": t_start + timedelta(hours=age), "age_h": age, "lat": round(lat, 4), "lon": round(lon, 4),
                         "height_agl": agl, "z_msl": round(s2[2], 0) if s2 else None,
                         "speed_ms": round(math.hypot(s2[0], s2[1]), 1) if s2 else None})
    out = pd.DataFrame(rows)
    out.attrs["left_domain"] = left
    out.attrs["p_hpa"] = p
    return out


# ── the ensemble ─────────────────────────────────────────────────────────────

def member_starts(level: int) -> List[Tuple[float, float, float]]:
    """(dlat, dlon, p_hpa) of the members for one start level: the central one first, duplicates (clamped offsets) collapsed."""
    p_max, p_min = max(FETCH_LEVELS), min(FETCH_LEVELS)
    out: List[Tuple[float, float, float]] = []
    for dp in (0.0, -ENSEMBLE_DP_HPA, ENSEMBLE_DP_HPA):
        p = min(p_max, max(p_min, level + dp))
        for dlat in (0.0, -ENSEMBLE_DX_DEG, ENSEMBLE_DX_DEG):
            for dlon in (0.0, -ENSEMBLE_DX_DEG, ENSEMBLE_DX_DEG):
                m = (dlat, dlon, float(p))
                if m not in out:
                    out.append(m)
    return out


def _field_stack(field: WindField) -> Tuple[List[int], np.ndarray]:
    """All levels and variables of a field as one array (L, nlat, nlon, T, 3), built once per field."""
    stack = getattr(field, "_stack", None)
    if stack is None:
        levels = sorted(field.u, reverse=True)
        stack = np.stack([np.stack([field.u[lv], field.v[lv], field.z[lv]], axis=-1) for lv in levels], axis=0)
        field._levels, field._stack = levels, stack          # type: ignore[attr-defined]
    return field._levels, stack                               # type: ignore[attr-defined]


def _sample_stack(field: WindField, lats: np.ndarray, lons: np.ndarray, th: float) -> np.ndarray:
    """Vectorised WindField.sample on every level at once: (L, n, 3) of u, v, z, NaN where a point is outside or on missing cells."""
    levels, S = _field_stack(field)
    la, lo = field.lat_axis, field.lon_axis
    n = len(lats)
    out = np.full((len(levels), n, 3), np.nan)
    if not (0.0 <= th <= field.n_hours - 1):
        return out
    inside = (lats >= la[0]) & (lats <= la[-1]) & (lons >= lo[0]) & (lons <= lo[-1])
    if not inside.any():
        return out
    i = np.clip(np.searchsorted(la, lats, side="right") - 1, 0, max(len(la) - 2, 0))
    j = np.clip(np.searchsorted(lo, lons, side="right") - 1, 0, max(len(lo) - 2, 0))
    k = min(int(math.floor(th)), field.n_hours - 2)
    ftt = th - k
    i1 = np.minimum(i + 1, len(la) - 1)
    j1 = np.minimum(j + 1, len(lo) - 1)
    fy = (lats - la[i]) / (la[i1] - la[i]) if len(la) > 1 else np.zeros(n)
    fx = (lons - lo[j]) / (lo[j1] - lo[j]) if len(lo) > 1 else np.zeros(n)
    num = np.zeros_like(out)
    den = np.zeros_like(out)
    for ci, cj, w in ((i, j, (1 - fy) * (1 - fx)), (i1, j, fy * (1 - fx)), (i, j1, (1 - fy) * fx), (i1, j1, fy * fx)):
        ab = S[:, ci, cj, k:k + 2, :]                         # (L, n, 2, 3): both hours in one gather
        a, b = ab[:, :, 0, :], ab[:, :, 1, :]
        w3 = w[None, :, None]
        ok = (w3 > 0) & ~np.isnan(a) & ~np.isnan(b)
        num += np.where(ok, w3 * ((1 - ftt) * a + ftt * b), 0.0)
        den += np.where(ok, w3, 0.0)
    np.divide(num, den, out=out, where=den >= 0.25)          # fewer than a quarter of the weight on valid cells: left the data
    out[:, ~inside, :] = np.nan
    out[np.isnan(out).any(axis=2)] = np.nan                   # as the scalar sampler: any missing component voids the point
    return out


def _p_weights(levels: List[int], ps: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each pressure the stack indices of the bracketing levels and the log-pressure weight of the upper one."""
    asc = np.array(levels[::-1], dtype=float)                 # ascending pressure
    p = np.clip(ps.astype(float), asc[0], asc[-1])
    pos = np.searchsorted(asc, p, side="left")                # asc[pos] >= p
    below = np.maximum(pos - 1, 0)                            # the lower-pressure (upper) level
    hi_p, lo_p = asc[pos], asc[below]
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(hi_p > lo_p, (np.log(hi_p) - np.log(p)) / (np.log(hi_p) - np.log(lo_p)), 0.0)
    L = len(levels)
    return L - 1 - pos, L - 1 - below, w                      # stack order is descending pressure


def _sample_groups(field, ps: np.ndarray, lats: np.ndarray, lons: np.ndarray, th: float) -> np.ndarray:
    """Every member at once: one gather per field, then each member's log-pressure interpolation; the composite falls back to the coarse field."""
    fine, coarse = (field.fine, field.coarse) if isinstance(field, CompositeField) else (field, None)
    n = len(lats)
    ar = np.arange(n)

    def on(f: WindField, idx: np.ndarray, t: float) -> np.ndarray:
        levels, _ = _field_stack(f)
        hi, lo, w = _p_weights(levels, ps[idx])
        S = _sample_stack(f, lats[idx], lons[idx], t)
        sub = np.arange(len(idx))
        return (1 - w)[:, None] * S[hi, sub] + w[:, None] * S[lo, sub]   # (m, 3); NaN in either level voids the point

    val = on(fine, ar, th)
    if coarse is not None:
        miss = np.flatnonzero(np.isnan(val[:, 0]))
        if len(miss):
            val[miss] = on(coarse, miss, th + field._shift)
    return val.T


def integrate_many(field, lats0: np.ndarray, lons0: np.ndarray, ps: np.ndarray, t_start: datetime, hours: int,
                   direction: str = "backward", dt_min: int = ENSEMBLE_DT_MIN) -> Dict[str, np.ndarray]:
    """`integrate` for many parcels at once (the same scheme, vectorised): hourly arrays (hours+1, n), NaN once a parcel has left."""
    sign = -1.0 if direction == "backward" else 1.0
    dt_s = sign * dt_min * 60.0
    steps_per_hour = int(round(60 / dt_min))
    n = len(lats0)
    lat, lon = lats0.astype(float).copy(), lons0.astype(float).copy()
    th = field.hours_since_t0(t_start)
    s0 = _sample_groups(field, ps, lat, lon, th)
    alive = ~np.isnan(s0[0])
    H = hours + 1
    out_lat, out_lon = np.full((H, n), np.nan), np.full((H, n), np.nan)
    out_z, out_spd = np.full((H, n), np.nan), np.full((H, n), np.nan)
    out_lat[0], out_lon[0] = lat, lon
    out_z[0], out_spd[0] = s0[2], np.hypot(s0[0], s0[1])

    def step(la, lo, u, v):
        return la + v * dt_s / M_PER_DEG, lo + u * dt_s / (M_PER_DEG * np.cos(np.radians(la)))

    for k in range(1, hours * steps_per_hour + 1):
        if not alive.any():
            break
        s = _sample_groups(field, ps, lat, lon, th)
        alive &= ~np.isnan(s[0])
        p_lat, p_lon = step(lat, lon, s[0], s[1])
        th_next = th + sign * dt_min / 60.0
        s2 = _sample_groups(field, ps, p_lat, p_lon, th_next)
        alive &= ~np.isnan(s2[0])
        for _ in range(2):                                   # Petterssen corrector, twice
            lat_c, lon_c = step(lat, lon, 0.5 * (s[0] + s2[0]), 0.5 * (s[1] + s2[1]))
            s3 = _sample_groups(field, ps, lat_c, lon_c, th_next)
            alive &= ~np.isnan(s3[0])
            p_lat, p_lon, s2 = lat_c, lon_c, s3
        lat = np.where(alive, p_lat, np.nan)
        lon = np.where(alive, p_lon, np.nan)
        th = th_next
        if k % steps_per_hour == 0:
            h = k // steps_per_hour
            out_lat[h], out_lon[h] = np.round(lat, 4), np.round(lon, 4)
            out_z[h] = np.where(alive, np.round(s2[2], 0), np.nan)
            out_spd[h] = np.where(alive, np.round(np.hypot(s2[0], s2[1]), 1), np.nan)
    return {"lat": out_lat, "lon": out_lon, "z": out_z, "speed": out_spd}


def ensemble_paths(field, lat0: float, lon0: float, levels: Sequence[int], t_start: datetime, hours: int,
                   direction: str) -> Dict[int, List[pd.DataFrame]]:
    """Every member path per level (one vectorised integration for all of them), attributed to regions in one pass."""
    sign = -1.0 if direction == "backward" else 1.0
    starts = [(lv, k, s) for lv in levels for k, s in enumerate(member_starts(lv))]
    lats0 = np.array([lat0 + s[0] for _, _, s in starts])
    lons0 = np.array([lon0 + s[1] for _, _, s in starts])
    ps = np.array([s[2] for _, _, s in starts])
    arrs = integrate_many(field, lats0, lons0, ps, t_start, hours, direction)
    members: Dict[int, List[pd.DataFrame]] = {lv: [] for lv in levels}
    for col, (lv, k, (dlat, dlon, p)) in enumerate(starts):
        valid = ~np.isnan(arrs["lat"][:, col])
        n_rows = int(np.argmin(valid)) if not valid.all() else len(valid)   # rows up to the first NaN
        n_rows = max(n_rows, 1)
        ages = sign * np.arange(n_rows, dtype=float)
        m = pd.DataFrame({
            "traj_id": lv, "time": [t_start + timedelta(hours=float(a)) for a in ages], "age_h": ages,
            "lat": arrs["lat"][:n_rows, col], "lon": arrs["lon"][:n_rows, col], "height_agl": agl_for_p(p),
            "z_msl": arrs["z"][:n_rows, col], "speed_ms": arrs["speed"][:n_rows, col],
        })
        if n_rows == 1 and np.isnan(arrs["lat"][0, col]):   # never sampled: keep the start point, as `integrate` does
            m.loc[0, ["lat", "lon"]] = [lats0[col], lons0[col]]
        m.attrs["left_domain"] = n_rows < hours + 1
        m.attrs["p_hpa"] = float(p)
        m.attrs["member"] = k
        m.attrs["start"] = (dlat, dlon, p)
        members[lv].append(m)
    frames = [m for ms in members.values() for m in ms if not m.empty]
    if frames:
        allpts = pd.concat(frames, ignore_index=True)
        attr = fr.attribute_points(allpts["lat"].to_numpy(), allpts["lon"].to_numpy(), fr.load_region_index())
        regions = np.array([_region_label(c, s) for c, s in zip(attr["country"], attr["province"])], dtype=object)
        i = 0
        for m in frames:
            m["region"] = regions[i:i + len(m)]
            i += len(m)
    return members


def ensemble_summary(members: Dict[int, List[pd.DataFrame]], central: Dict[int, pd.DataFrame], lat0: float, lon0: float,
                     ages: Sequence[int] = ENSEMBLE_AGES) -> Dict[str, Any]:
    """Member sector counts, the region each member is over, and the spread around the central path at each age."""
    sectors_out: Dict[str, Any] = {}
    regions_out: Dict[str, Any] = {}
    spread_out: Dict[str, Any] = {}
    for age in ages:
        sec_age: Dict[str, Any] = {}
        reg_age: Dict[str, Any] = {}
        spr_age: Dict[str, Any] = {}
        all_counts: Dict[str, int] = {}
        for lv, ms in members.items():
            lats, lons, regs = [], [], []
            for m in ms:
                row = m[np.isclose(m["age_h"].abs(), age)]
                if row.empty:
                    continue
                lats.append(float(row["lat"].iloc[0]))
                lons.append(float(row["lon"].iloc[0]))
                regs.append(str(row["region"].iloc[0]) if "region" in row else "elsewhere")
            if not lats:
                sec_age[str(lv)] = {"n": 0, "modal": None, "agreement": None, "counts": {}}
                reg_age[str(lv)] = {}
                spr_age[str(lv)] = None
                continue
            secs = [fr.compass(float(b)) for b in fr.bearing_deg(lat0, lon0, lats, lons)]
            counts: Dict[str, int] = {}
            for s_ in secs:
                counts[s_] = counts.get(s_, 0) + 1
                all_counts[s_] = all_counts.get(s_, 0) + 1
            modal = max(counts, key=counts.get)
            sec_age[str(lv)] = {"n": len(secs), "modal": modal, "agreement": round(counts[modal] / len(secs), 2), "counts": counts}
            rc: Dict[str, int] = {}
            for r in regs:
                rc[r] = rc.get(r, 0) + 1
            reg_age[str(lv)] = dict(sorted(rc.items(), key=lambda kv: -kv[1]))
            c = central.get(lv)
            crow = c[np.isclose(c["age_h"].abs(), age)] if c is not None and not c.empty else None
            if crow is not None and not crow.empty:
                d = fr.haversine_km_vec(float(crow["lat"].iloc[0]), float(crow["lon"].iloc[0]), lats, lons)
                spr_age[str(lv)] = round(float(np.mean(d)))
            else:
                spr_age[str(lv)] = None
        if all_counts:
            modal_all = max(all_counts, key=all_counts.get)
            n_all = sum(all_counts.values())
            sec_age["all"] = {"n": n_all, "modal": modal_all, "agreement": round(all_counts[modal_all] / n_all, 2), "counts": all_counts}
        else:
            sec_age["all"] = {"n": 0, "modal": None, "agreement": None, "counts": {}}
        sectors_out[str(age)] = sec_age
        regions_out[str(age)] = reg_age
        spread_out[str(age)] = spr_age
    return {
        "n_members": {str(lv): len(ms) for lv, ms in members.items()},
        "offsets": {"horizontal_deg": ENSEMBLE_DX_DEG, "vertical_hpa": ENSEMBLE_DP_HPA},
        "left_domain": {str(lv): int(sum(1 for m in ms if m.attrs.get("left_domain"))) for lv, ms in members.items()},
        "sectors": sectors_out, "regions_at": regions_out, "spread_km": spread_out,
    }


def _member_coords(members: Dict[int, List[pd.DataFrame]]) -> Dict[str, Any]:
    return {str(lv): [[[round(float(a), 3), round(float(b), 3)] for a, b in zip(m["lat"].to_numpy(), m["lon"].to_numpy())] for m in ms]
            for lv, ms in members.items()}


# ── attribution, sectors, fires ───────────────────────────────────────────────

def _region_label(country: Any, province: Any) -> str:
    if country == "PK":
        return "Pakistan Punjab" if province == "Punjab" else "other Pakistan"
    if country == "IN":
        return "Indian Punjab" if province == "Punjab (IN)" else "Haryana" if province == "Haryana (IN)" else "elsewhere"
    return "elsewhere"


def attribute(paths: Dict[int, pd.DataFrame]) -> Dict[int, pd.DataFrame]:
    idx = fr.load_region_index()
    for lv, p in paths.items():
        if p.empty:
            p["region"] = []
            continue
        attr = fr.attribute_points(p["lat"].to_numpy(), p["lon"].to_numpy(), idx)
        p["country"] = attr["country"]
        p["province"] = attr["province"]
        p["district"] = attr["district"]
        p["region"] = [_region_label(c, s) for c, s in zip(attr["country"], attr["province"])]
    return paths


def residence_hours(p: pd.DataFrame) -> Dict[str, int]:
    out = {k: 0 for k in REGION_LABELS}
    if "region" in p:
        for r in p["region"].tolist()[1:]:                 # hour 0 is the start point itself
            out[r] = out.get(r, 0) + 1
    return out


def sectors(paths: Dict[int, pd.DataFrame], lat0: float, lon0: float, ages: Sequence[int] = (24, 48, 72)) -> Dict[str, Any]:
    """Compass sector of each level's position at the given ages (bearing from the start point) and their agreement."""
    out: Dict[str, Any] = {}
    for age in ages:
        secs, dists = {}, {}
        for lv, p in paths.items():
            row = p[np.isclose(p["age_h"].abs(), age)]
            if row.empty:
                continue
            b = float(fr.bearing_deg(lat0, lon0, row["lat"].to_numpy(), row["lon"].to_numpy())[0])
            secs[str(lv)] = fr.compass(b)
            dists[str(lv)] = round(float(fr.haversine_km_vec(lat0, lon0, row["lat"].to_numpy(), row["lon"].to_numpy())[0]))
        if not secs:
            out[str(age)] = {"n": 0, "modal": None, "agreement": None, "by_level": {}, "distance_km": {}}
            continue
        counts: Dict[str, int] = {}
        for s_ in secs.values():
            counts[s_] = counts.get(s_, 0) + 1
        modal = max(counts, key=counts.get)
        out[str(age)] = {"n": len(secs), "modal": modal, "agreement": round(counts[modal] / len(secs), 2), "by_level": secs, "distance_km": dists}
    return out


def _match_mask(p: pd.DataFrame, det: pd.DataFrame, km: float, hours: float) -> np.ndarray:
    mask = np.zeros(len(det), dtype=bool)
    if p.empty or det.empty:
        return mask
    acq = pd.to_datetime(det["acq_utc"]).dt.tz_localize(None) if "acq_utc" in det else None
    lat_a, lon_a = det["lat"].to_numpy(dtype=float), det["lon"].to_numpy(dtype=float)
    for r in p.itertuples():
        near = fr.haversine_km_vec(r.lat, r.lon, lat_a, lon_a) <= km
        if acq is not None:
            dt = (acq - pd.Timestamp(r.time)).abs().dt.total_seconds() / 3600.0
            near &= ((dt <= hours) | dt.isna()).to_numpy()
        mask |= near
    return mask


def fire_matches(paths: Dict[int, pd.DataFrame], det: pd.DataFrame) -> Dict[str, Any]:
    """Strict (HYSPLIT-style) matches per level and the loose union with its composition."""
    if det is None or det.empty:
        return {"strict": {"n_points": 0, "n_fires": 0, "frp_mw": 0.0, "by_level": {}}, "loose": {"n_fires": 0, "frp_mw": 0.0},
                "note": "no fire detections in the window"}
    strict_lv: Dict[str, Any] = {}
    n_pts = n_f = 0
    frp = 0.0
    for lv, p in paths.items():
        m = ft.match_fires(p, det)
        if m.empty:
            strict_lv[str(lv)] = {"n_points": 0, "n_fires": 0, "frp_mw": 0.0}
            continue
        strict_lv[str(lv)] = {"n_points": int(len(m)), "n_fires": int(m["n_fires"].sum()), "frp_mw": round(float(m["frp_mw"].sum()), 1),
                              "first_age_h": float(m["age_h"].abs().min()), "districts": sorted({d for ds in m["districts"] for d in ds})[:8]}
        n_pts += int(len(m))
        n_f += int(m["n_fires"].sum())
        frp += float(m["frp_mw"].sum())
    loose = np.zeros(len(det), dtype=bool)
    for p in paths.values():
        loose |= _match_mask(p, det, LOOSE_KM, LOOSE_HOURS)
    sel = det[loose]
    by_country: Dict[str, Any] = {}
    for c, g in sel.groupby("country"):
        by_country[fr.COUNTRY_LABELS.get(str(c), str(c))] = {"n_fires": int(len(g)), "frp_mw": round(float(g["frp"].sum()), 1)}
    top_d = (sel.groupby("district")["frp"].agg(["count", "sum"]).sort_values("sum", ascending=False).head(10)
             if "district" in sel and sel["district"].notna().any() else None)
    classes = sel["source_class"].value_counts().to_dict() if "source_class" in sel and len(sel) else {}
    top = sel.sort_values("frp", ascending=False).head(MAX_FIRE_POINTS) if len(sel) else sel
    points = [{"lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3), "frp": round(float(r.frp), 1),
               "district": (None if pd.isna(r.district) else str(r.district)), "country": str(r.country),
               "source_class": (str(getattr(r, "source_class", "")) or None)} for r in top.itertuples()]
    return {"strict": {"n_points": n_pts, "n_fires": n_f, "frp_mw": round(frp, 1), "by_level": strict_lv},
            "loose": {"n_fires": int(len(sel)), "frp_mw": round(float(sel["frp"].sum()), 1) if len(sel) else 0.0,
                      "points": points, "by_country": by_country,
                      "top_districts": [{"district": str(d), "n_fires": int(r["count"]), "frp_mw": round(float(r["sum"]), 1)}
                                        for d, r in top_d.iterrows()] if top_d is not None else [],
                      "source_classes": {str(k): int(v) for k, v in classes.items()}}}


# ── cache ────────────────────────────────────────────────────────────────────

_MEMO: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def cache_path(lat: float, lon: float, at_utc: datetime, direction: str, hours: int) -> str:
    return f"{CACHE_PREFIX}/{lat:.2f}_{lon:.2f}/{direction}_{at_utc:%Y%m%dT%H}_{hours}h.json"


def _cache_fresh(doc: Dict[str, Any], now: datetime) -> bool:
    if not doc.get("uses_forecast"):
        return True
    try:
        gen = datetime.fromisoformat(str(doc.get("generated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    if gen.tzinfo is not None:
        gen = gen.astimezone(timezone.utc).replace(tzinfo=None)
    return (now - gen).total_seconds() / 3600.0 <= FORECAST_REFRESH_H


def read_cached(bucket, path: str, now: datetime) -> Optional[Dict[str, Any]]:
    hit = _MEMO.get(path)
    if hit and time.monotonic() - hit[0] < MEMO_TTL_S and _cache_fresh(hit[1], now):
        return hit[1]
    if bucket is None:
        return None
    try:
        from app.services.fire_aggregates import _read_json
        doc = _read_json(bucket, path)
    except Exception as exc:  # noqa: BLE001
        log.info("kinematic cache read failed: %s", exc)
        return None
    if doc and _cache_fresh(doc, now):
        _remember(path, doc)
        return doc
    return None


def _remember(path: str, doc: Dict[str, Any]) -> None:
    if len(_MEMO) >= MEMO_MAX:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[path] = (time.monotonic(), doc)


def write_cached(bucket, path: str, doc: Dict[str, Any]) -> None:
    _remember(path, doc)
    if bucket is None:
        return
    try:
        bucket.blob(path).upload_from_string(json.dumps(doc, separators=(",", ":")), content_type="application/json")
    except Exception as exc:  # noqa: BLE001
        log.info("kinematic cache write failed: %s", exc)


# ── the run ──────────────────────────────────────────────────────────────────

def coverage_error(at_utc: datetime, direction: str, hours: int, now: datetime) -> Optional[str]:
    t_start = at_utc - timedelta(hours=hours) if direction == "backward" else at_utc
    t_end = at_utc if direction == "backward" else at_utc + timedelta(hours=hours)
    if t_start < now - timedelta(days=COVERAGE_PAST_DAYS):
        return (f"On-demand trajectories cover arrivals in the last {COVERAGE_PAST_DAYS} days (the wind archive available on demand); "
                f"earlier seasons are in the offline HYSPLIT catalogue, not in the API yet.")
    if t_end > now + timedelta(days=COVERAGE_FORECAST_DAYS):
        return f"The wind forecast reaches {COVERAGE_FORECAST_DAYS} days ahead; the run would need winds beyond that."
    return None


def _pkt(t: datetime) -> str:
    return (t.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=5)))).strftime("%Y-%m-%d %H:%M PKT")


async def run(http, store, lat: float, lon: float, at_utc: datetime, *, direction: str = "backward", hours: int = HOURS,
              levels: Sequence[int] = LEVELS, bucket=None, now: Optional[datetime] = None, label: str = "") -> Dict[str, Any]:
    """The full trajectory document for one start point and time (naive UTC, whole hour)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    direction = "forward" if str(direction).lower().startswith("f") else "backward"
    hours = max(6, min(int(hours), MAX_HOURS))
    at_utc = at_utc.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    err = coverage_error(at_utc, direction, hours, now)
    if err:
        return {"status": "unavailable", "message": err, "engine": ENGINE}
    path = cache_path(lat, lon, at_utc, direction, hours)
    cached = read_cached(bucket, path, now)
    if cached:
        return {**cached, "cached": True}
    t_start = at_utc - timedelta(hours=hours) if direction == "backward" else at_utc
    t_end = at_utc if direction == "backward" else at_utc + timedelta(hours=hours)
    timings: Dict[str, float] = {}
    clock = time.monotonic()
    # pass 1: coarse field, draft paths
    fetch_levels = tuple(sorted(set(FETCH_LEVELS) | set(levels), reverse=True))
    coarse_pts = _thin(_grid(lat, lon, COARSE_DEG, COARSE_HALF_LAT, COARSE_HALF_LON), MAX_LOCATIONS)
    coarse = await fetch_winds(http, coarse_pts, t_start - timedelta(hours=1), t_end + timedelta(hours=1), fetch_levels)
    timings["winds_coarse_s"] = round(time.monotonic() - clock, 2)
    drafts = {lv: integrate(coarse, lat, lon, lv, at_utc, hours, direction) for lv in levels}
    # pass 2: fine corridor around the drafts
    fine_pts = _thin(_corridor(list(drafts.values()) + [pd.DataFrame({"lat": [lat], "lon": [lon]})], FINE_DEG, CORRIDOR_DEG), MAX_LOCATIONS)
    clock2 = time.monotonic()
    fine = await fetch_winds(http, fine_pts, t_start - timedelta(hours=1), t_end + timedelta(hours=1), fetch_levels)
    timings["winds_fine_s"] = round(time.monotonic() - clock2, 2)
    paths = {lv: integrate(fine, lat, lon, lv, at_utc, hours, direction) for lv in levels}
    for lv, p in paths.items():                             # a parcel that left the fine corridor keeps its draft beyond that point
        if p.attrs.get("left_domain") and len(drafts[lv]) > len(p):
            tail = drafts[lv].iloc[len(p):].copy()
            tail["from_draft"] = True
            paths[lv] = pd.concat([p, tail], ignore_index=True)
            paths[lv].attrs["left_domain"] = drafts[lv].attrs.get("left_domain", False)
    clock3 = time.monotonic()
    attribute(paths)
    timings["attribution_s"] = round(time.monotonic() - clock3, 2)
    # the ensemble: members on the fine corridor, the coarse field behind it
    clock_e = time.monotonic()
    # 81 integrations are seconds of CPU on Cloud Run: run them off the event loop so other requests keep flowing
    members = await asyncio.to_thread(ensemble_paths, CompositeField(fine, coarse), lat, lon, levels, at_utc, hours, direction)
    ensemble = {**ensemble_summary(members, paths, lat, lon), "starts": {str(lv): [list(m.attrs["start"]) for m in ms] for lv, ms in members.items()},
                "members": _member_coords(members)}
    timings["ensemble_s"] = round(time.monotonic() - clock_e, 2)
    # fires along the path
    det = None
    passes: Dict[str, Any] = {}
    clock4 = time.monotonic()
    if store is not None:
        try:
            from app.services.fire_analytics import _detections_for, _headline
            d0 = (t_start - timedelta(hours=12)).date()
            d1 = (t_end + timedelta(hours=12)).date()
            det_all, passes = _detections_for(store, d0, d1)
            det = _headline(det_all) if len(det_all) else det_all
        except Exception as exc:  # noqa: BLE001
            log.info("kinematic: fire detections unavailable: %s", exc)
            passes = {"note": f"fire detections unavailable: {type(exc).__name__}"}
    fires = fire_matches(paths, det) if det is not None else {"note": "fire store unavailable"}
    timings["fires_s"] = round(time.monotonic() - clock4, 2)
    timings["total_s"] = round(time.monotonic() - clock, 2)
    if timings["total_s"] > SLOW_RUN_S:
        log.warning("kinematic run slow: %s (%s %s %dh, %d+%d locations)", timings, direction, at_utc.isoformat(), hours, len(coarse_pts), len(fine_pts))
    uses_forecast = t_end > now
    doc: Dict[str, Any] = {
        "engine": ENGINE, "status": STATUS, "direction": direction, "hours": hours, "levels_hpa": list(levels),
        "origin": {"lat": round(lat, 4), "lon": round(lon, 4), "label": label or None},
        "at_utc": at_utc.isoformat(), "at_pkt": _pkt(at_utc), "generated_at": now.isoformat() + "Z", "uses_forecast": uses_forecast,
        "wind_source": WIND_SOURCE, "locations_requested": [len(coarse_pts), len(fine_pts)], "timings": timings,
        "paths": {str(lv): [{"age_h": float(r.age_h), "time_utc": r.time.isoformat(), "lat": float(r.lat), "lon": float(r.lon),
                             "height_agl_m": float(r.height_agl), "z_msl_m": (None if r.z_msl is None or pd.isna(r.z_msl) else float(r.z_msl)),
                             "speed_ms": (None if r.speed_ms is None or pd.isna(r.speed_ms) else float(r.speed_ms)),
                             "region": getattr(r, "region", None), "district": getattr(r, "district", None)}
                            for r in p.itertuples()] for lv, p in paths.items()},
        "left_domain": {str(lv): bool(p.attrs.get("left_domain", False)) for lv, p in paths.items()},
        "residence_hours": {str(lv): residence_hours(p) for lv, p in paths.items()},
        "sectors": sectors(paths, lat, lon),
        "ensemble": ensemble,
        "fires": {**fires, "window": {"start_utc": t_start.isoformat(), "end_utc": t_end.isoformat()}, "passes": passes},
        "definitions": DEFINITIONS, "caveats": CAVEATS,
    }
    write_cached(bucket, path, doc)
    return doc


def _fires_without_points(fires: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The model gets the counts and districts, not 300 coordinates."""
    if not fires or "loose" not in fires:
        return fires
    return {**fires, "loose": {k: v for k, v in fires["loose"].items() if k != "points"}}


def copilot_view(doc: Dict[str, Any], every_h: int = 6) -> Dict[str, Any]:
    """The compact form for the model: 6-hourly points per level, residence, sectors, fires, caveats."""
    if doc.get("status") != STATUS:
        return doc
    pts = {lv: [{"age_h": p["age_h"], "time_utc": p["time_utc"], "lat": round(p["lat"], 2), "lon": round(p["lon"], 2), "region": p["region"],
                 "district": p["district"]} for p in path if abs(p["age_h"]) % every_h == 0]
           for lv, path in doc["paths"].items()}
    ens = doc.get("ensemble")
    view = {k: doc[k] for k in ("engine", "status", "direction", "hours", "levels_hpa", "origin", "at_utc", "at_pkt", "uses_forecast",
                                "wind_source", "left_domain", "residence_hours", "sectors", "caveats") if k in doc} | {
        "points_6h": pts, "fires": _fires_without_points(doc.get("fires")), "cached": doc.get("cached", False),
        "definitions": {k: doc["definitions"][k] for k in ("engine", "levels", "error", "ensemble", "match_strict", "match_loose",
                                                           "not_attribution", "forward_vs_backward") if k in doc["definitions"]}}
    if ens:                                                 # the model gets the member counts and spread, not 81 paths
        view["ensemble"] = {k: v for k, v in ens.items() if k not in ("members", "starts")}
    return view
