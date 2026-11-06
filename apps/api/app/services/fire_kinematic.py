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
- hourly points are attributed to Pakistan / Indian Punjab / Haryana with the fire store's
  boundaries, and matched to deduplicated fire detections (strict: 10 km, ±1 h, inside the mixed
  layer, as the HYSPLIT job does; loose: 25 km, ±3 h, because the path carries tens of km of error
  by 48 h).

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
LEVELS: Tuple[int, ...] = (1000, 925, 850)
LEVEL_AGL_M = {1000: 100.0, 925: 700.0, 850: 1400.0}     # nominal height above the Indus–Ganges plains (~200 m ASL)
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
CACHE_PREFIX = "forecasts/trajectories/kinematic"
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
                      levels: Sequence[int] = LEVELS) -> WindField:
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


def integrate(field: WindField, lat0: float, lon0: float, level: int, t_start: datetime, hours: int,
              direction: str = "backward", dt_min: int = DT_MIN) -> pd.DataFrame:
    """Hourly parcel positions on one level. Stops early when the parcel leaves the wind field."""
    sign = -1.0 if direction == "backward" else 1.0
    dt_s = sign * dt_min * 60.0
    steps_per_hour = int(round(60 / dt_min))
    lat, lon = float(lat0), float(lon0)
    th = field.hours_since_t0(t_start)
    s0 = field.sample(level, lat, lon, th)
    rows = [{"traj_id": level, "time": t_start, "age_h": 0.0, "lat": lat, "lon": lon, "height_agl": LEVEL_AGL_M[level],
             "z_msl": s0[2] if s0 else None, "speed_ms": math.hypot(s0[0], s0[1]) if s0 else None}]
    left = s0 is None
    for n in range(1, hours * steps_per_hour + 1):
        if left:
            break
        s = field.sample(level, lat, lon, th)
        if s is None:
            left = True
            break
        p_lat, p_lon = _step(lat, lon, s[0], s[1], dt_s)
        th_next = th + sign * dt_min / 60.0
        s2 = field.sample(level, p_lat, p_lon, th_next)
        if s2 is None:
            left = True
            break
        for _ in range(2):                                   # Petterssen corrector, twice
            lat_c, lon_c = _step(lat, lon, 0.5 * (s[0] + s2[0]), 0.5 * (s[1] + s2[1]), dt_s)
            s3 = field.sample(level, lat_c, lon_c, th_next)
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
                         "height_agl": LEVEL_AGL_M[level], "z_msl": round(s2[2], 0) if s2 else None,
                         "speed_ms": round(math.hypot(s2[0], s2[1]), 1) if s2 else None})
    out = pd.DataFrame(rows)
    out.attrs["left_domain"] = left
    return out


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
    districts: Dict[str, float] = {}
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
    coarse_pts = _thin(_grid(lat, lon, COARSE_DEG, COARSE_HALF_LAT, COARSE_HALF_LON), MAX_LOCATIONS)
    coarse = await fetch_winds(http, coarse_pts, t_start - timedelta(hours=1), t_end + timedelta(hours=1), levels)
    timings["winds_coarse_s"] = round(time.monotonic() - clock, 2)
    drafts = {lv: integrate(coarse, lat, lon, lv, at_utc, hours, direction) for lv in levels}
    # pass 2: fine corridor around the drafts
    fine_pts = _thin(_corridor(list(drafts.values()) + [pd.DataFrame({"lat": [lat], "lon": [lon]})], FINE_DEG, CORRIDOR_DEG), MAX_LOCATIONS)
    clock2 = time.monotonic()
    fine = await fetch_winds(http, fine_pts, t_start - timedelta(hours=1), t_end + timedelta(hours=1), levels)
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
    return {k: doc[k] for k in ("engine", "status", "direction", "hours", "levels_hpa", "origin", "at_utc", "at_pkt", "uses_forecast",
                                "wind_source", "left_domain", "residence_hours", "sectors", "caveats") if k in doc} | {
        "points_6h": pts, "fires": _fires_without_points(doc.get("fires")), "cached": doc.get("cached", False),
        "definitions": {k: doc["definitions"][k] for k in ("engine", "levels", "error", "match_strict", "match_loose", "not_attribution",
                                                           "forward_vs_backward")}}
