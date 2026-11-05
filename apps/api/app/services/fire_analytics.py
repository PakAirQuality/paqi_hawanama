"""
Fire analytics on the FIRMS aggregate store (fire_aggregates) and the day files:

  fire_exposure  — fires around and upwind of a city on one Pakistan day, with the wind source named
  fire_trends    — daily / weekly series for a region, season-to-date, compared with 2020–2025
  fire_hotspots  — same-day clusters, district league table, persistent thermal sources
  fire_activity  — the old one-day summary, now without the national-numbers-as-city fallback

Every result carries FIRE_DEFINITIONS, the window (Pakistan and UTC), the satellites and pass
window from the day sidecars, and caveats. Counts quoted as the headline are deduplicated
detection clusters with a high- or nominal-confidence detection (see fire_aggregates); year
comparisons also carry the NOAA-20-only series (basis "n20"), the one that does not change with
the satellite roster. Nothing here asserts that fires caused PM2.5; the wording rule is
"consistent with", and the fire–PM2.5 rule flags *candidate smoke-transport episodes*, not
fire-influenced days.
"""

from __future__ import annotations

import difflib
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.services import fire_classify as fc
from app.services import fire_regions as fr
from app.services.fire_aggregates import AggStore, DayBuild, agg_store
from app.services.fires import PK_TZ

logger = logging.getLogger(__name__)

RINGS_KM = (50, 100, 200)
MAX_RING_KM = 200.0
TOP_FIRES = 10
MAX_ROWS = 60
PERSISTENT_WINDOW_DAYS = 30
REFERENCE_YEARS = (2020, 2021, 2022, 2023, 2024, 2025)
SEASONS = {
    "kharif_rice_residue": fc.HARVEST_WINDOWS["rice"],     # rice stubble before wheat sowing: the ISRO/CAQM paddy-residue reporting window
    "rabi_wheat_residue": fc.HARVEST_WINDOWS["wheat"],     # wheat stubble before rice transplanting
}
SEASON_WINDOW_NOTE = ("The rice window follows the ISRO/CAQM paddy-residue protocol (15 Sep – 30 Nov); earlier Hawanama reports "
                      "used 1 Oct – 30 Nov. Pakistan Punjab burning before 1 Oct is shown so the choice can be checked.")
BASES = {"all": "every satellite flown that day (deduplicated across satellites, high/nominal confidence)",
         "n20": "NOAA-20 detections only (high/nominal confidence): the consistent series for year comparisons, since NOAA-20 "
                "flew and was processed in every archive year while Suomi NPP and NOAA-21 came and went",
         "crop": f"likely crop-residue clusters only (class {fc.CLASS_VERSION}: {fc.RULES['crop']}); every satellite, deduplicated",
         "crop_n20": f"likely crop-residue detections (class {fc.CLASS_VERSION}) from NOAA-20 only: the crop series comparable across years"}
BASIS_SCHEMA = {"all": 0, "n20": 2, "crop": 3, "crop_n20": 3}          # store schema a basis needs
COUNT_COL = {"all": "n_dedup_hn", "n20": "n_n20_hn", "crop": "n_crop_hn", "crop_n20": "n_crop_n20_hn"}
FRP_COL = {"all": "frp_dedup_hn", "n20": "frp_n20_hn", "crop": "frp_crop_hn", "crop_n20": "frp_crop_n20_hn"}
SERIES_COLS = ["n_dedup_hn", "n_raw", "frp_dedup_hn", "n_day", "n_night", "n_n20_hn", "frp_n20_hn",
               "n_crop_hn", "n_other_hn", "n_uncertain_hn", "frp_crop_hn", "n_crop_n20_hn", "frp_crop_n20_hn"]
N20_BASES = ("n20", "crop_n20")
SEASON_ALIASES = {"rice": "kharif_rice_residue", "kharif": "kharif_rice_residue", "autumn": "kharif_rice_residue",
                  "october": "kharif_rice_residue", "november": "kharif_rice_residue", "winter": "kharif_rice_residue",
                  "wheat": "rabi_wheat_residue", "rabi": "rabi_wheat_residue", "spring": "rabi_wheat_residue",
                  "april": "rabi_wheat_residue", "may": "rabi_wheat_residue"}

FIRE_DEFINITIONS = {
    "detection": "one VIIRS 375 m pixel flagged as a thermal anomaly by NASA FIRMS; a large field burn is several detections and one burning field can be seen by two satellites",
    "fire": "a deduplicated detection cluster: detections from different satellites within 1 km and 90 minutes are grouped (transitively) and counted once, highest FRP kept. A cluster is not a verified individual fire: neighbouring burning fields can merge and one incident can still leave several clusters",
    "headline_count": "deduplicated detection clusters with at least one high- or nominal-confidence detection; 'fires' in the text means these clusters. Raw detections and low-confidence rows are reported separately",
    "comparison_basis": "year-on-year comparisons use the NOAA-20-only series (basis n20): deduplication cannot remove the extra fires an added satellite sees, so the roster change (Suomi NPP + NOAA-20 in 2020–2025, NOAA-21 added in 2026, Suomi NPP retired 2026-11-01) is handled by holding the satellite fixed",
    "what_burns": f"a thermal detection does not identify what burns. The store classifies each detection (class {fc.CLASS_VERSION}) as likely crop-residue burning, likely other source or uncertain from the cropland share around it, the harvest window, listed kilns and industrial sites, and out-of-season persistence; the classification is unvalidated until the labelled sample is scored, so say 'likely crop-residue detections', never 'crop fires'",
    "classification": f"crop: {fc.RULES['crop']}. other: {fc.RULES['other']}. uncertain: {fc.RULES['uncertain']}. Night is a reason only. Coverage: {fc.RULES['coverage']}.",
    "frp": "fire radiative power in megawatts summed over deduplicated fires: burning intensity, not a PM2.5 contribution",
    "day": "Pakistan calendar day (Asia/Karachi): the ~13:00 PKT day pass and the ~01:00 PKT night pass of that date",
    "day_basis": "acq_pkt = keyed by Pakistan day with pass times; acq_utc = older archive days keyed by UTC date without pass times",
    "country": "PK = Pakistan; IN = Indian Punjab and Haryana only; other = the rest of the 60–78E / 23–37N box (Rajasthan, J&K, Afghanistan, Iran)",
    "upwind": "fires whose bearing from the city lies within ±60° of the wind's 'from' direction on that day; the wind source is named",
    "transport_time": "distance divided by the 10 m wind speed; smoke moves faster aloft, so the hours are an upper bound",
    "not_causation": "fire counts and FRP do not measure a contribution to PM2.5: say 'consistent with smoke transport', never 'caused'",
}

PROVINCE_ALIASES = {
    "kp": "Khyber Pakhtunkhwa", "kpk": "Khyber Pakhtunkhwa", "khyber pakhtunkhwa": "Khyber Pakhtunkhwa", "nwfp": "Khyber Pakhtunkhwa",
    "ict": "Islamabad", "islamabad": "Islamabad", "islamabad capital territory": "Islamabad",
    "ajk": "Azad Kashmir", "azad kashmir": "Azad Kashmir", "azad jammu and kashmir": "Azad Kashmir",
    "gb": "Gilgit-Baltistan", "gilgit": "Gilgit-Baltistan", "gilgit baltistan": "Gilgit-Baltistan", "gilgit-baltistan": "Gilgit-Baltistan",
    "punjab": "Punjab", "pakistan punjab": "Punjab", "pakistani punjab": "Punjab", "west punjab": "Punjab",
    "sindh": "Sindh", "balochistan": "Balochistan", "baluchistan": "Balochistan",
}
INDIA_ALIASES = {
    "india punjab": "Punjab (IN)", "indian punjab": "Punjab (IN)", "punjab (in)": "Punjab (IN)", "punjab india": "Punjab (IN)",
    "east punjab": "Punjab (IN)", "punjab in": "Punjab (IN)",
    "haryana": "Haryana (IN)", "haryana (in)": "Haryana (IN)", "haryāna": "Haryana (IN)",
}
COUNTRY_ALIASES = {
    "pakistan": "Pakistan", "national": "Pakistan", "pk": "Pakistan", "": "Pakistan",
    "india": "India (Punjab+Haryana)", "india (punjab+haryana)": "India (Punjab+Haryana)", "cross-border": "India (Punjab+Haryana)",
    "cross border": "India (Punjab+Haryana)", "across the border": "India (Punjab+Haryana)",
    "other": "other in bbox", "other in bbox": "other in bbox", "rest of bbox": "other in bbox",
}


# ── shared helpers ────────────────────────────────────────────────────────────

def pkt_today() -> date:
    return datetime.now(timezone.utc).astimezone(PK_TZ).date()


def _window_dict(start: date, end: date) -> Dict[str, Any]:
    return {"start_pkt_day": start.isoformat(), "end_pkt_day": end.isoformat(), "days": (end - start).days + 1,
            "start_utc": (datetime(start.year, start.month, start.day, tzinfo=PK_TZ)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
            "end_utc": (datetime(end.year, end.month, end.day, tzinfo=PK_TZ) + timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")}


def _pass_info(built: Optional[DayBuild]) -> Dict[str, Any]:
    if built is None:
        return {}
    i = built.info
    return {"status": i.get("status"), "day_basis": "acq_pkt" if i.get("format") == "pkt_v2" else "acq_utc",
            "satellites": i.get("sources"), "observation_period": i.get("observation_period"), "fetched_at": i.get("fetched_at")}


def _headline(det: pd.DataFrame) -> pd.DataFrame:
    return det[det["is_primary"] & det["grp_hn"]]


def _pkt(ts) -> Optional[str]:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).tz_convert(PK_TZ).strftime("%Y-%m-%d %H:%M PKT")


def parse_day(s: str) -> Optional[date]:
    try:
        return date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def _r(v, nd=1):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), nd)


# ── wind at a city ────────────────────────────────────────────────────────────

@dataclass
class WindEstimate:
    source: str                 # era5 | pipeline_summary | station_vector_mean | none
    from_deg: Optional[float]
    speed_ms: Optional[float]
    n: int = 0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "from_deg": self.from_deg, "from_compass": fr.compass(self.from_deg),
                "speed_ms": self.speed_ms, "n_observations": self.n, "note": self.note}


@dataclass
class Loaders:
    """Injectable I/O for the context pieces (defaults read GCS through the analyst-desk helpers)."""
    era5_uv: Callable[[float, float, date], Optional[Tuple[float, float]]] = None       # type: ignore[assignment]
    summary: Callable[[date], Optional[Dict[str, Any]]] = None                            # type: ignore[assignment]
    driver_summary: Callable[[date], Optional[Dict[str, Any]]] = None                     # type: ignore[assignment]
    trajectory: Callable[[str, date], Optional[Dict[str, Any]]] = None                    # type: ignore[assignment]

    def __post_init__(self):
        self.era5_uv = self.era5_uv or _default_era5_uv
        self.summary = self.summary or _default_summary
        self.driver_summary = self.driver_summary or _default_driver_summary
        self.trajectory = self.trajectory or _default_trajectory


_MEMO: Dict[Tuple[str, Any], Tuple[float, Any]] = {}
MEMO_TTL_S = 600.0


def _memo(key: Tuple[str, Any], fn: Callable[[], Any]) -> Any:
    """Per-process cache for the pipeline JSONs (immutable once written; the latest day is re-read every 10 min)."""
    import time
    hit = _MEMO.get(key)
    if hit is not None and time.monotonic() - hit[0] < MEMO_TTL_S:
        return hit[1]
    val = fn()
    if len(_MEMO) >= 200:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[key] = (time.monotonic(), val)
    return val


def _default_era5_uv(lat: float, lon: float, day: date) -> Optional[Tuple[float, float]]:
    try:
        from app.routers.ops_pipeline import _get_features_bucket, _sample_cog_at_points
        bucket = _get_features_bucket()
        ds = day.isoformat()
        u = _sample_cog_at_points(bucket, f"cog/u10/date={ds}/u10.tif", [(lon, lat)])[0]
        v = _sample_cog_at_points(bucket, f"cog/v10/date={ds}/v10.tif", [(lon, lat)])[0]
        if u is None or v is None:
            return None
        return float(u), float(v)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ERA5 point sample unavailable for %s: %s", day, exc)
        return None


def _default_summary(day: date) -> Optional[Dict[str, Any]]:
    def load():
        try:
            from app.routers.analyst_desk import _load_summary_safe
            return _load_summary_safe(day.isoformat())
        except Exception:  # noqa: BLE001
            return None
    return _memo(("summary", day), load)


def _default_driver_summary(day: date) -> Optional[Dict[str, Any]]:
    def load():
        try:
            from app.routers.analyst_desk import _load_driver_summary_safe
            return _load_driver_summary_safe(day.isoformat())
        except Exception:  # noqa: BLE001
            return None
    return _memo(("driver_summary", day), load)


def _default_trajectory(city: str, day: date) -> Optional[Dict[str, Any]]:
    def load():
        try:
            from app.routers.analyst_desk import _load_trajectory_safe
            return _load_trajectory_safe(city, day.isoformat())
        except Exception:  # noqa: BLE001
            return None
    return _memo(("trajectory", (city.lower(), day)), load)


def _city_summary(summary: Optional[Dict[str, Any]], city: str) -> Optional[Dict[str, Any]]:
    for row in (summary or {}).get("city_summaries", []) or []:
        name = row.get("name") or row.get("city_name") or ""
        if name.lower() == city.lower():
            return row
    return None


async def station_wind(db, city_id: int, day: date) -> WindEstimate:
    """Speed-weighted vector mean of the city's station winds over the Pakistan day."""
    from sqlalchemy import text
    from app.services.copilot.station_queries import day_window_utc
    w0, w1 = day_window_utc(day)
    rows = (await db.execute(text("""
        SELECT r.wind_dir_deg AS d, r.wind_speed_ms AS s
        FROM readings r JOIN stations s ON s.station_id = r.scope_key
        WHERE r.scope_type = 'station' AND s.city_id = :cid AND s.active = true
          AND r.ts_utc >= :w0 AND r.ts_utc < :w1
          AND r.wind_dir_deg IS NOT NULL AND r.wind_speed_ms IS NOT NULL
    """), {"cid": city_id, "w0": w0, "w1": w1})).fetchall()
    if not rows:
        return WindEstimate("none", None, None, 0, "no station wind observations for this city and day")
    d, s = fr.vector_mean_from_deg([r.d for r in rows], [r.s for r in rows])
    if d is None:
        return WindEstimate("station_vector_mean", None, s, len(rows), "opposing winds cancel out; no dominant direction")
    return WindEstimate("station_vector_mean", d, s, len(rows), "speed-weighted vector mean of surface station observations (10 m, IQAir)")


async def city_wind(db, city_name: str, city_id: Optional[int], lat: float, lon: float, day: date, loaders: Loaders) -> WindEstimate:
    """ERA5 10 m wind at the city when the raster exists, else the forecast pipeline's prevailing wind,
    else the station vector mean. The source is always named in the result."""
    uv = loaders.era5_uv(lat, lon, day)
    if uv is not None:
        u, v = uv
        return WindEstimate("era5", round(fr.wind_from_deg(u, v), 1), round(fr.wind_speed(u, v), 2), 1, "ERA5 10 m daily wind sampled at the city centroid")
    cs = _city_summary(loaders.summary(day), city_name)
    mf = (cs or {}).get("met_fire") or {}
    if mf.get("met_wd10_prevailing") is not None:
        return WindEstimate("pipeline_summary", round(float(mf["met_wd10_prevailing"]), 1),
                            _r(mf.get("met_ws10_mean"), 2), 1, "prevailing 10 m wind from the forecast pipeline's city summary")
    if db is not None and city_id is not None:
        return await station_wind(db, city_id, day)
    return WindEstimate("none", None, None, 0, "no wind source available")


# ── 1. exposure ───────────────────────────────────────────────────────────────

async def fire_exposure(db, city: str, day: date, *, radius_km: float = 100.0, cone_half_deg: float = fr.CONE_HALF_DEG,
                        store: Optional[AggStore] = None, loaders: Optional[Loaders] = None) -> Dict[str, Any]:
    """Fires around and upwind of a city on one Pakistan day."""
    from app.services.copilot.station_queries import _city_centroid, resolve_city
    store = store or agg_store()
    loaders = loaders or Loaders()
    match, cands = await resolve_city(db, city)
    if cands:
        return {"message": f"'{city}' matches several cities: {', '.join(c.name for c in cands)}. Which one?"}
    if match is None:
        return {"message": f"City '{city}' not found among active Pakistan cities; fire exposure needs a known city."}
    lat, lon = await _city_centroid(db, match)
    if lat is None or lon is None:
        return {"message": f"{match.name} has no coordinates in the registry (no stations with a position), so fires around it cannot be counted."}
    built = store.day_from_csv(day)
    if built is None:
        return {"message": f"No fire file for the Pakistan day {day.isoformat()}; the archive holds days from 2020-01-01 to about today."}
    if built.info.get("status") == "unavailable":
        return {"message": f"The fire feed had no data for {day.isoformat()} (every satellite source failed); do not infer fire activity.",
                "passes": _pass_info(built)}
    caveats: List[str] = []
    if built.info.get("status") == "partial":
        caveats.append("Partial satellite coverage for this day: one source failed, counts are a lower bound.")
    if built.info.get("format") != "pkt_v2":
        caveats.append("Archive day keyed by UTC date without pass times; the night pass may belong to the neighbouring day.")
    radius_km = float(max(5.0, min(radius_km or 100.0, MAX_RING_KM)))
    det = built.detections
    if det.empty:
        rings = {f"{r}km": {"fires": 0, "detections": 0, "frp_mw": 0.0, "by_country": {}} for r in RINGS_KM}
        wind = await city_wind(db, match.name, match.id, lat, lon, day, loaders)
        return {"city": match.name, "lat": _r(lat, 4), "lon": _r(lon, 4), "day": day.isoformat(), "window": _window_dict(day, day),
                "rings": rings, "wind": wind.to_dict(), "upwind": None, "nearest_fire": None, "top_upwind_fires": [],
                "passes": _pass_info(built), "caveats": caveats + ["No detections at all in the box on this day."],
                "definitions": FIRE_DEFINITIONS}
    km = fr.haversine_km_vec(lat, lon, det["lat"].to_numpy(), det["lon"].to_numpy())
    brg = fr.bearing_deg(lat, lon, det["lat"].to_numpy(), det["lon"].to_numpy())
    d = det.assign(km=km, bearing=brg)
    near = d[d["km"] <= MAX_RING_KM]
    head = _headline(near)
    rings: Dict[str, Any] = {}
    for r in sorted(set(RINGS_KM) | {int(radius_km)}):
        h = head[head["km"] <= r]
        rings[f"{r}km"] = {
            "fires": int(len(h)), "detections": int((near["km"] <= r).sum()), "frp_mw": _r(h["frp"].sum()),
            "by_country": {fr.COUNTRY_LABELS[c]: int(n) for c, n in h["country"].value_counts().items()},
        }
    sel = head[head["km"] <= radius_km]
    top_districts = [{"district": k, "fires": int(v)} for k, v in sel["district"].dropna().value_counts().head(5).items()]
    wind = await city_wind(db, match.name, match.id, lat, lon, day, loaders)
    upwind: Optional[Dict[str, Any]] = None
    top_upwind: List[Dict[str, Any]] = []
    if wind.from_deg is not None:
        cone = head[fr.in_cone(head["bearing"].to_numpy(), wind.from_deg, cone_half_deg)]
        cosw = np.cos(np.radians(fr.angle_diff(cone["bearing"].to_numpy(), wind.from_deg)))
        upwind = {
            "cone_half_width_deg": cone_half_deg, "from_deg": wind.from_deg, "from_compass": fr.compass(wind.from_deg),
            "fires_200km": int(len(cone)), "frp_mw_200km": _r(cone["frp"].sum()), "frp_mw_cos_weighted": _r(float((cone["frp"].to_numpy() * cosw).sum())),
            "fires_100km": int((cone["km"] <= 100).sum()), "frp_mw_100km": _r(cone.loc[cone["km"] <= 100, "frp"].sum()),
            "by_country": {fr.COUNTRY_LABELS[c]: int(n) for c, n in cone["country"].value_counts().items()},
        }
        for _, f in cone.sort_values("frp", ascending=False).head(TOP_FIRES).iterrows():
            top_upwind.append(_fire_row(f, wind.speed_ms))
    nearest = None
    if len(head):
        f = head.sort_values("km").iloc[0]
        nearest = _fire_row(f, wind.speed_ms)
    context: Dict[str, Any] = {}
    traj = loaders.trajectory(match.name, day)
    if traj and traj.get("status") == "ok":
        context["hysplit"] = {"dominant_corridor": traj.get("dominant_corridor"), "corridor_consistent": traj.get("corridor_consistent"),
                              "fire_intersections": len(traj.get("fire_intersections") or []), "note": "cached 72 h back-trajectory for this city and day"}
    cs = _city_summary(loaders.summary(day), match.name)
    if cs and cs.get("met_fire"):
        mf = cs["met_fire"]
        context["pipeline_met_fire"] = {k: mf.get(k) for k in ("fire_count_100km", "fire_frp_sum_100km", "fire_frp_sum_upwind_100km",
                                                               "fire_frp_sum_200km_3d", "fire_frp_sum_200km_7d", "met_blh_mean", "met_stag_frac")
                                        if k in mf}
        context["pipeline_met_fire"]["note"] = "forecast pipeline features (raw detection counts, max across the city's stations)"
    ds = loaders.driver_summary(day)
    for row in (ds or {}).get("driver_summaries", []) or []:
        if (row.get("city_name") or "").lower() == match.name.lower():
            fire_driver = next((dr for dr in row.get("drivers", []) if dr.get("driver") in ("fire", "fire_biomass", "fire_activity")), None)
            if fire_driver:
                context["pipeline_fire_driver"] = {"score": fire_driver.get("score"), "evidence": fire_driver.get("evidence"),
                                                   "primary_driver": row.get("primary_driver")}
            break
    if wind.from_deg is None:
        caveats.append(f"No wind direction for {day.isoformat()} ({wind.note}); upwind figures are not available, rings are.")
    return {
        "city": match.name, "lat": _r(lat, 4), "lon": _r(lon, 4), "day": day.isoformat(), "window": _window_dict(day, day),
        "radius_km": radius_km, "rings": rings, "top_districts_in_radius": top_districts,
        "wind": wind.to_dict(), "upwind": upwind, "top_upwind_fires": top_upwind, "nearest_fire": nearest,
        "context": context, "passes": _pass_info(built), "caveats": caveats, "definitions": FIRE_DEFINITIONS,
    }


def _fire_row(f, speed_ms: Optional[float]) -> Dict[str, Any]:
    th = None
    if speed_ms and speed_ms > 0.3:
        th = round(float(f["km"]) / (float(speed_ms) * 3.6), 1)
    return {"lat": _r(f["lat"], 4), "lon": _r(f["lon"], 4), "frp_mw": _r(f["frp"]), "km": _r(f["km"]), "bearing_deg": _r(f["bearing"], 0),
            "direction": fr.compass(float(f["bearing"])), "country": fr.COUNTRY_LABELS.get(f["country"], f["country"]),
            "province": f["province"], "district": f["district"], "confidence": f["confidence"], "satellite": f["satellite"],
            "acq_pkt": _pkt(f["acq_utc"]), "transport_h_at_10m_wind": th}


# ── 2. trends ─────────────────────────────────────────────────────────────────

def resolve_region(name: str, store: Optional[AggStore] = None) -> Tuple[Optional[Tuple[str, str]], Optional[str], List[str]]:
    """(kind, region), note, known districts for a typed name; kind in country|province|india_state|district."""
    key = (name or "").strip().lower()
    if key in COUNTRY_ALIASES:
        return ("country", COUNTRY_ALIASES[key]), None, []
    if key in INDIA_ALIASES:
        return ("india_state", INDIA_ALIASES[key]), None, []
    if key in PROVINCE_ALIASES:
        note = "'Punjab' taken as Pakistan's Punjab; ask for 'Indian Punjab' for the cross-border belt." if key == "punjab" else None
        return ("province", PROVINCE_ALIASES[key]), note, []
    idx = fr.load_region_index()
    districts = sorted(idx.district_province)
    low = {d.lower(): d for d in districts}
    if key in low:
        return ("district", low[key]), None, districts
    close = difflib.get_close_matches(key, list(low), n=1, cutoff=0.8)
    if close:
        return ("district", low[close[0]]), f"'{name}' read as district {low[close[0]]}", districts
    return None, None, districts


def season_window(season: str, *, year: Optional[int] = None, today: Optional[date] = None) -> Optional[Tuple[date, date, str]]:
    """(start, end, season_name) for a season name/alias in `year` (default: the latest occurrence), capped at today."""
    today = today or pkt_today()
    key = (season or "").strip().lower()
    key = SEASON_ALIASES.get(key, key)
    if key not in SEASONS:
        return None
    s_mmdd, e_mmdd = SEASONS[key]
    y = year or today.year
    start = date(y, int(s_mmdd[:2]), int(s_mmdd[3:]))
    end = date(y, int(e_mmdd[:2]), int(e_mmdd[3:]))
    if year is None and start > today:                # this year's season has not started: last year's
        start, end = start.replace(year=y - 1), end.replace(year=y - 1)
    return start, min(end, today), key


def current_season(today: Optional[date] = None) -> Optional[str]:
    today = today or pkt_today()
    for k, (s, e) in SEASONS.items():
        if date(today.year, int(s[:2]), int(s[3:])) <= today <= date(today.year, int(e[:2]), int(e[3:])):
            return k
    return None


def _series(daily: pd.DataFrame, kind: str, region: str, start: date, end: date, days_with_file: set) -> pd.DataFrame:
    """One row per day: SERIES_COLS summed over the region's rows; NaN on days outside `days_with_file`
    (no file, or no rows on the requested satellite basis), 0 on observed days without rows."""
    sel = daily[(daily["region_kind"] == kind) & (daily["region"] == region) & (daily["pk_day"] >= start) & (daily["pk_day"] <= end)]
    sel = sel.groupby("pk_day", as_index=False)[SERIES_COLS].sum()   # older builds may hold split rows
    idx = pd.date_range(start, end, freq="D").date
    out = pd.DataFrame({"pk_day": idx})
    out = out.merge(sel, on="pk_day", how="left")
    out["has_file"] = [d in days_with_file for d in out["pk_day"]]
    for c in SERIES_COLS:
        out[c] = np.where(out["has_file"], out[c].fillna(0), np.nan)
    return out


def fire_trends(region: str = "Pakistan", start: Optional[date] = None, end: Optional[date] = None, *, season: str = "",
                compare_years: Sequence[int] = REFERENCE_YEARS, basis: str = "all", store: Optional[AggStore] = None,
                today: Optional[date] = None) -> Dict[str, Any]:
    """Daily (or weekly) series of detection clusters for a region with a same-window comparison against
    earlier years. `basis` 'all' counts every satellite; 'n20' counts NOAA-20 alone (the comparable series).
    Whatever the basis, the comparison block also carries the NOAA-20-only figures."""
    store = store or agg_store()
    today = today or pkt_today()
    resolved, note, districts = resolve_region(region, store)
    if resolved is None:
        return {"message": f"Region '{region}' not recognised. Use Pakistan, a province (Punjab, Sindh, KP, Balochistan, GB, AJK, Islamabad), "
                           f"a Pakistan district, 'Indian Punjab' or 'Haryana'."}
    kind, rname = resolved
    season_name = None
    ends_yesterday = False
    if season:
        sw = season_window(season, year=end.year if end and not start else None, today=today)
        if sw is None:
            return {"message": f"Unknown season '{season}'. Seasons: {', '.join(SEASONS)} (aliases: rice/kharif, wheat/rabi)."}
        start, end, season_name = sw
        ends_yesterday = end >= today
    if start is None and end is None:
        cs = current_season(today)
        if cs:
            start, end, season_name = season_window(cs, today=today)
        else:
            end = today
            start = end - timedelta(days=29)
        ends_yesterday = end >= today
    if ends_yesterday:
        # season-to-date and default windows end yesterday, as on the fires page: today's afternoon pass is
        # still arriving and a partial day against a full day in the reference years would read as a drop
        end = today - timedelta(days=1)
    start = start or (end - timedelta(days=29))
    end = end or min(today, start + timedelta(days=29))
    if end > today:
        end = today
    if start > end:
        return {"message": f"Start {start} is after end {end}."}
    basis = (basis or "all").strip().lower()
    if basis not in BASES:
        return {"message": f"basis must be one of {', '.join(BASES)}."}
    manifest = store.manifest()
    days_with_file = {date.fromisoformat(k) for k in manifest.get("days", {})}
    schema = int(manifest.get("schema_version") or 0)
    has_n20 = schema >= 2
    n20_days = satellite_days(manifest, fr.CONSISTENT_SATELLITE) if has_n20 else set()
    if schema < BASIS_SCHEMA[basis]:
        return {"message": f"The '{basis}' basis needs the rebuilt store (schema {BASIS_SCHEMA[basis]}); ask again after the next aggregate run."}
    observed = days_with_file & n20_days if basis in N20_BASES else days_with_file
    cnt, frpc = COUNT_COL[basis], FRP_COL[basis]
    daily = store.daily_regions()
    s = _series(daily, kind, rname, start, end, observed)
    s["rolling7_fires"] = s[cnt].rolling(7, min_periods=1).mean().round(1)
    s["rolling7_frp_mw"] = s[frpc].rolling(7, min_periods=1).mean().round(0)
    missing = [d.isoformat() for d, f in zip(s["pk_day"], s["has_file"]) if not f]
    valid = s[s["has_file"]]
    total = int(valid[cnt].sum()) if len(valid) else 0
    peak = (valid.sort_values([cnt, frpc], ascending=False).iloc[0]
            if len(valid) and valid[cnt].max() > 0 else None)
    summary: Dict[str, Any] = {
        "basis": basis, "basis_label": BASES[basis],
        "fires": total, "detections": int(valid["n_raw"].sum()) if len(valid) else 0, "frp_mw": _r(valid[frpc].sum()) if len(valid) else 0.0,
        "days_with_data": int(len(valid)), "days_missing": len(missing), "fires_per_day": _r(total / len(valid)) if len(valid) else None,
        "peak_day": {"day": peak["pk_day"].isoformat(), "fires": int(peak[cnt]), "frp_mw": _r(peak[frpc])} if peak is not None else None,
        "night_share": _r(valid["n_night"].sum() / max(valid["n_day"].sum() + valid["n_night"].sum(), 1), 2) if len(valid) else None,
    }
    if has_n20:
        n20_valid = s[s["pk_day"].isin(n20_days) & s["has_file"]]
        summary["noaa20_only"] = {"fires": int(n20_valid["n_n20_hn"].sum()) if len(n20_valid) else 0, "days_with_data": int(len(n20_valid)),
                                  "note": "NOAA-20 detections alone; the series to compare across years"}
    if schema >= 3 and basis in ("all", "n20") and len(valid):
        tot = max(int(valid["n_dedup_hn"].sum()), 1)
        summary["source_classes"] = {"class_version": manifest.get("classification", {}).get("class_version", fc.CLASS_VERSION),
                                     "crop": int(valid["n_crop_hn"].sum()), "other": int(valid["n_other_hn"].sum()),
                                     "uncertain": int(valid["n_uncertain_hn"].sum()),
                                     "crop_share": _r(valid["n_crop_hn"].sum() / tot, 2),
                                     "note": "of the all-satellite headline clusters; unvalidated classification"}
    if kind == "country" and rname == "Pakistan":
        share = {}
        for lab in fr.COUNTRY_LABELS.values():
            cs_ = _series(daily, "country", lab, start, end, observed)
            share[lab] = int(cs_[cnt].fillna(0).sum())
        summary["by_country"] = share
    if kind in ("country", "province") and rname != "other in bbox":
        dsel = daily[(daily["region_kind"] == "district") & (daily["pk_day"] >= start) & (daily["pk_day"] <= end)]
        if kind == "province":
            idx = fr.load_region_index()
            dsel = dsel[dsel["region"].map(idx.district_province) == rname]
        if kind == "country" and rname != "Pakistan":
            dsel = dsel.iloc[0:0]
        top = dsel.groupby("region")[[cnt, frpc]].sum()
        top = top[top[cnt] > 0].sort_values(cnt, ascending=False).head(10)
        summary["top_districts"] = [{"district": k, "fires": int(v[cnt]), "frp_mw": _r(v[frpc])} for k, v in top.iterrows()]
    # rows: daily, or weekly when the window is long
    if len(s) > MAX_ROWS:
        wk = s.assign(week=[d - timedelta(days=d.weekday()) for d in s["pk_day"]])
        g = wk.groupby("week")
        rows_df = pd.DataFrame({
            "week_start": list(g.groups.keys()), "fires": g[cnt].sum(min_count=1).values, "detections": g["n_raw"].sum(min_count=1).values,
            "frp_mw": g[frpc].sum(min_count=1).values, "days_with_data": g["has_file"].sum().values,
        })
        rows = [{"week_start": r.week_start.isoformat(), "fires": _int(r.fires), "detections": _int(r.detections), "frp_mw": _r(r.frp_mw, 0),
                 "days_with_data": int(r.days_with_data)} for r in rows_df.itertuples()]
        bucket = "week"
    else:
        rows = [{"day": r.pk_day.isoformat(), "fires": _int(getattr(r, cnt)), "detections": _int(r.n_raw), "frp_mw": _r(getattr(r, frpc), 0),
                 "rolling7_fires": _r(r.rolling7_fires), "night": _int(r.n_night)} if r.has_file
                else {"day": r.pk_day.isoformat(), "fires": None, "note": "no file" if r.pk_day not in days_with_file else "no NOAA-20 rows"}
                for r in s.itertuples()]
        bucket = "day"
    # same-window comparison with earlier years, on the requested basis and always on NOAA-20 alone
    comparison: Optional[Dict[str, Any]] = None
    if compare_years:
        comparison = compare_years_same_dates(daily, kind, rname, start, end, s, observed, cnt, frpc, compare_years)
        comparison["basis"] = basis
        if has_n20 and basis not in N20_BASES:
            b20 = "crop_n20" if basis == "crop" else "n20"
            s20 = _series(daily, kind, rname, start, end, days_with_file & n20_days)
            c20 = compare_years_same_dates(daily, kind, rname, start, end, s20, days_with_file & n20_days, COUNT_COL[b20], FRP_COL[b20], compare_years)
            c20["basis"] = b20
            comparison["noaa20_only"] = {"fires": int(s20.loc[s20["has_file"], COUNT_COL[b20]].sum()) if s20["has_file"].any() else 0, **c20,
                                         "note": "Quote this block for 'more or fewer than last year': the satellite is held fixed."}
    caveats = [FIRE_DEFINITIONS["headline_count"], FIRE_DEFINITIONS["what_burns"]]
    if ends_yesterday:
        caveats.append(f"The window ends {end.isoformat()} (yesterday): today's afternoon pass is still arriving, so season-to-date "
                       "figures match the fires page and compare whole days only.")
    if any(d.year < 2026 for d in s["pk_day"]) or comparison:
        caveats.append("Archive days before the 2026 ingester are keyed by UTC date and lack pass times; the satellite roster differs by year "
                       "(Suomi NPP + NOAA-20 in 2020–2025, NOAA-21 in the 2026 NRT files, Suomi NPP retired 2026-11-01), so year comparisons "
                       "use the NOAA-20-only series (comparison.noaa20_only or basis='n20').")
    if manifest.get("suspect_days"):
        sus = [x["day"] for x in manifest["suspect_days"] if start.strftime("%m-%d") <= x["day"][5:] <= end.strftime("%m-%d")]
        if sus:
            caveats.append(f"{len(sus)} archive day(s) in this calendar window look thin (re-fetched with fewer rows than the 2020–2023 median): {', '.join(sus[:6])}"
                           + (" …" if len(sus) > 6 else ""))
    if missing:
        caveats.append(f"{len(missing)} day(s) in the window have no fire file: {', '.join(missing[:5])}" + (" …" if len(missing) > 5 else ""))
    out = {"region": {"kind": kind, "name": rname}, "window": _window_dict(start, end), "season": season_name, "bucket": bucket,
           "basis": basis, "summary": summary, "rows": rows, "comparison": comparison, "caveats": caveats, "definitions": FIRE_DEFINITIONS,
           "store_built_at": manifest.get("built_at")}
    if season_name == "kharif_rice_residue":
        out["season_window_note"] = SEASON_WINDOW_NOTE
    if note:
        out["note"] = note
    return out


def compare_years_same_dates(daily: pd.DataFrame, kind: str, rname: str, start: date, end: date, s: pd.DataFrame, observed: set,
                             cnt: str, frpc: str, compare_years: Sequence[int]) -> Dict[str, Any]:
    """Like for like: reference years are summed over the calendar days that have data in the current
    window (on the same basis), and a reference year needs 60 % of those days to be used."""
    total = int(s.loc[s["has_file"], cnt].sum()) if s["has_file"].any() else 0
    mmdd_with_data = {d.strftime("%m-%d") for d, f in zip(s["pk_day"], s["has_file"]) if f}
    ref = []
    for y in compare_years:
        if y >= start.year:
            continue
        try:
            ys, ye = start.replace(year=y), end.replace(year=y)
        except ValueError:                       # 29 Feb
            continue
        rs = _series(daily, kind, rname, ys, ye, observed)
        rv = rs[rs["has_file"] & rs["pk_day"].map(lambda d: d.strftime("%m-%d") in mmdd_with_data)]
        ref.append({"year": y, "fires": int(rv[cnt].sum()) if len(rv) else None, "frp_mw": _r(rv[frpc].sum(), 0) if len(rv) else None,
                    "days_with_data": int(len(rv)), "days_missing": int(len(mmdd_with_data) - len(rv))})
    vals = [r["fires"] for r in ref if r["fires"] is not None and r["days_with_data"] >= max(1, int(0.6 * len(mmdd_with_data)))]
    comparison: Dict[str, Any] = {"window": f"{start.strftime('%m-%d')} to {end.strftime('%m-%d')} in each year",
                                  "days_compared": len(mmdd_with_data), "years": ref}
    if len(mmdd_with_data) < len(s):
        comparison["note"] = (f"Only the {len(mmdd_with_data)} calendar days observed in the current window are summed in each "
                              f"reference year ({len(s) - len(mmdd_with_data)} days of the window have no file or no rows on this basis).")
    if vals:
        comparison.update({
            "reference_mean": _r(float(np.mean(vals)), 0), "reference_min": int(min(vals)), "reference_max": int(max(vals)),
            "ratio_to_mean": _r(total / float(np.mean(vals)), 2) if np.mean(vals) > 0 else None,
            "higher_than_n_of": [sum(1 for v in vals if total > v), len(vals)],
        })
        k, n = comparison["higher_than_n_of"]
        comparison["rank_text"] = ("higher than every reference year" if k == n else
                                   "lower than every reference year" if k == 0 else
                                   f"higher than {k} of the {n} reference years")
    return comparison


def satellite_days(manifest: Dict[str, Any], key: str) -> set:
    """Pakistan days on which satellite `key` ('n20' …) contributed rows, or the file is empty (a
    legitimate zero). A day with rows from other satellites only is a missing pass for `key`."""
    out = set()
    for d, rec in manifest.get("days", {}).items():
        rbs = rec.get("rows_by_satellite")
        if rbs is None:                          # built before schema 2: fall back to the sources list
            srcs = rec.get("sources") or []
            if not rec.get("rows") or any(fr.satellite_key(x) == key for x in srcs):
                out.add(date.fromisoformat(d))
        elif rbs.get(key, 0) > 0 or not rec.get("rows"):
            out.add(date.fromisoformat(d))
    return out


def _int(v) -> Optional[int]:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else int(v)


# ── 3. hotspots ───────────────────────────────────────────────────────────────

def _detections_for(store: AggStore, start: date, end: date) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Detections over the window from the store, with days the store lacks read from their CSVs."""
    det = store.detections(start, end)
    manifest = store.manifest()
    known = {date.fromisoformat(k) for k in manifest.get("days", {})}
    passes: Dict[str, Any] = {"satellites": set(), "day_basis": set(), "first_pass": None, "last_pass": None}
    extra = []
    d = start
    while d <= end:
        rec = manifest.get("days", {}).get(d.isoformat())
        if d not in known or (today_recent(d) and rec):
            b = store.day_from_csv(d)
            if b is not None:
                if d not in known or today_recent(d):
                    extra.append(b.detections)
                rec = b.info
        if rec:
            passes["satellites"].update(rec.get("sources") or [])
            passes["day_basis"].add("acq_pkt" if rec.get("format") == "pkt_v2" else "acq_utc")
            op = rec.get("observation_period") or {}
            if op.get("start") and (passes["first_pass"] is None or op["start"] < passes["first_pass"]):
                passes["first_pass"] = op["start"]
            if op.get("end") and (passes["last_pass"] is None or op["end"] > passes["last_pass"]):
                passes["last_pass"] = op["end"]
        d += timedelta(days=1)
    if extra:
        fresh = pd.concat(extra, ignore_index=True)
        fresh_days = set(fresh["pk_day"])
        det = pd.concat([det[~det["pk_day"].isin(fresh_days)], fresh], ignore_index=True) if len(det) else fresh
    passes["satellites"] = sorted(passes["satellites"])
    passes["day_basis"] = sorted(passes["day_basis"])
    return det, passes


def today_recent(d: date, today: Optional[date] = None) -> bool:
    """The last two Pakistan days are read from their CSVs so the 3-hourly ingest is not waited on."""
    return (today or pkt_today()) - d <= timedelta(days=1)


def fire_hotspots(*, region: Optional[str] = None, center: Optional[Tuple[float, float, str]] = None, radius_km: float = 50.0,
                  start: Optional[date] = None, end: Optional[date] = None, group: str = "cluster", min_days: int = 10,
                  limit: int = 40, store: Optional[AggStore] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """Clusters, district league table or persistent thermal sources for a region or a radius around a point."""
    store = store or agg_store()
    today = today or pkt_today()
    group = (group or "cluster").strip().lower()
    if group not in ("cluster", "district", "persistent"):
        return {"message": "group must be cluster, district or persistent."}
    end = min(end or today, today)
    if group == "persistent":
        start = end - timedelta(days=PERSISTENT_WINDOW_DAYS - 1)
    start = start or end
    if start > end:
        return {"message": f"Start {start} is after end {end}."}
    if (end - start).days > 92 and group != "persistent":
        return {"message": "Hotspot windows are limited to 92 days; use fire_trends for longer periods."}
    area_desc: Dict[str, Any]
    if center is not None:
        lat, lon, label = center
        area_desc = {"kind": "radius", "name": f"within {radius_km:g} km of {label}", "lat": _r(lat, 4), "lon": _r(lon, 4), "radius_km": radius_km}
        kind = rname = None
    elif (region or "").strip().lower() in ("bbox", "whole box", "box"):
        kind, rname = "bbox", "whole box"
        area_desc = {"kind": "bbox", "name": "whole box (Pakistan, North India, Afghanistan, Iran)"}
    else:
        resolved, note, _ = resolve_region(region or "Pakistan", store)
        if resolved is None:
            return {"message": f"Area '{region}' not recognised as a region; pass a city name to search around a city."}
        kind, rname = resolved
        area_desc = {"kind": kind, "name": rname}
        if note:
            area_desc["note"] = note
    det, passes = _detections_for(store, start, end)
    head = _headline(det) if len(det) else det
    if center is not None:
        lat, lon, _ = center
        km = fr.haversine_km_vec(lat, lon, head["lat"].to_numpy(), head["lon"].to_numpy()) if len(head) else np.zeros(0)
        head = head.assign(km=km)
        head = head[head["km"] <= radius_km]
    elif kind == "bbox":
        pass
    elif kind == "country":
        code = {v: k for k, v in fr.COUNTRY_LABELS.items()}[rname]
        head = head[head["country"] == code]
    elif kind in ("province", "india_state"):
        head = head[head["province"] == rname]
    else:
        head = head[head["district"] == rname]
    limit = max(1, min(int(limit or 40), MAX_ROWS))
    base = {"area": area_desc, "window": _window_dict(start, end), "group": group, "fires_in_area": int(len(head)),
            "passes": passes, "definitions": FIRE_DEFINITIONS, "caveats": [FIRE_DEFINITIONS["headline_count"]]}
    if head.empty:
        return {**base, "rows": [], "message": "No deduplicated high/nominal-confidence fires in this area and window."}
    if group == "cluster":
        rows = []
        for day, g in head.groupby("pk_day"):
            labels = fr.cluster_cells(g["cell_id"].to_numpy())
            for lab, c in g.assign(_c=labels).groupby("_c"):
                lat_c, lon_c = float(c["lat"].mean()), float(c["lon"].mean())
                ext = float(fr.haversine_km_vec(float(c["lat"].min()), float(c["lon"].min()), [float(c["lat"].max())], [float(c["lon"].max())])[0])
                rows.append({"day": day.isoformat(), "lat": round(lat_c, 4), "lon": round(lon_c, 4), "fires": int(len(c)),
                             "frp_mw": _r(c["frp"].sum()), "frp_max_mw": _r(c["frp"].max()), "extent_km": round(ext, 1),
                             "district": c["district"].mode().iloc[0] if c["district"].notna().any() else None,
                             "country": fr.COUNTRY_LABELS.get(c["country"].mode().iloc[0]),
                             "satellites": sorted(set(c["satellite"])), "day_night": {"D": int((c["daynight"] == "D").sum()), "N": int((c["daynight"] == "N").sum())},
                             "confidence": {k: int(v) for k, v in c["confidence"].value_counts().items()}})
        rows.sort(key=lambda r: -(r["frp_mw"] or 0))
        return {**base, "clusters_total": len(rows), "rows": rows[:limit],
                "method": "same-day 8-neighbour clusters on a 0.02° (~2 km) grid of deduplicated fires"}
    if group == "district":
        if "district" not in head or head["district"].isna().all():
            return {**base, "rows": [], "message": "No Pakistan districts in this area (district tables cover Pakistan only)."}
        g = head.dropna(subset=["district"]).groupby("district")
        rows = [{"district": k, "province": fr.load_region_index().district_province.get(k), "fires": int(len(c)), "frp_mw": _r(c["frp"].sum()),
                 "days_active": int(c["pk_day"].nunique()), "night_share": _r((c["daynight"] == "N").sum() / max((c["daynight"].notna()).sum(), 1), 2),
                 "confidence": {kk: int(vv) for kk, vv in c["confidence"].value_counts().items()}}
                for k, c in g]
        rows.sort(key=lambda r: -r["fires"])
        return {**base, "districts_total": len(rows), "rows": rows[:limit]}
    # persistent
    g = head.groupby("cell_id")
    cells = pd.DataFrame({"days_active": g["pk_day"].nunique(), "fires": g.size(), "frp_mean": g["frp"].mean(),
                          "night": g["daynight"].apply(lambda s: int((s == "N").sum())), "known": g["daynight"].apply(lambda s: int(s.notna().sum())),
                          "district": g["district"].agg(lambda s: s.mode().iloc[0] if s.notna().any() else None),
                          "country": g["country"].agg(lambda s: s.mode().iloc[0])})
    persistent = cells[cells["days_active"] >= min_days].sort_values(["days_active", "fires"], ascending=False)
    rows = []
    for cid, c in persistent.head(limit).iterrows():
        lat_c, lon_c = fr.cell_center(int(cid))
        rows.append({"lat": lat_c, "lon": lon_c, "days_active": int(c["days_active"]), "fires": int(c["fires"]), "frp_mean_mw": _r(c["frp_mean"]),
                     "night_share": _r(c["night"] / c["known"], 2) if c["known"] else None, "district": c["district"],
                     "country": fr.COUNTRY_LABELS.get(c["country"])})
    n_cells = int(len(cells))
    return {**base, "min_days": min_days, "window_days": PERSISTENT_WINDOW_DAYS, "cells_total": n_cells,
            "persistent_cells": int(len(persistent)), "one_off_share": _r((cells["days_active"] == 1).sum() / max(n_cells, 1), 2),
            "rows": rows, "label": f"persistent thermal source: a ~2 km cell with detections on at least {min_days} of the last {PERSISTENT_WINDOW_DAYS} days. "
                                   "A flag for investigation, not a verdict: kilns, gas flares, landfills and industry burn like this, but so do "
                                   "many fields in one cell burning on successive days. Persistent cells are reported, never removed from counts."}


# ── 4. the old one-day summary, fixed ─────────────────────────────────────────

async def fire_activity(db, day: date, city: Optional[str] = None, *, radius_km: float = 50.0,
                        store: Optional[AggStore] = None, loaders: Optional[Loaders] = None) -> Dict[str, Any]:
    """One day: a city's exposure (never national numbers under a city label) or the national picture."""
    if city:
        return await fire_exposure(db, city, day, radius_km=radius_km, store=store, loaders=loaders)
    out = fire_trends("Pakistan", day, day, compare_years=(), store=store)
    if "message" in out:
        return out
    built = (store or agg_store()).day_from_csv(day)
    out["passes"] = _pass_info(built)
    if built is None:
        out["message"] = f"No fire file for the Pakistan day {day.isoformat()}; say so rather than inferring fire activity."
    return out


# ── 5. fire vs PM2.5 linkage ──────────────────────────────────────────────────

MAX_LINK_DAYS = 120
MIN_PAIRS = 10
RISE_RATIO = 1.2          # PM2.5 ≥ 120 % of the prior three days' mean …
RISE_FLOOR = 10.0         # … and at least 10 µg/m³ above it
P75_QUANTILE = 0.75

LINK_DEFINITIONS = {
    **FIRE_DEFINITIONS,
    "pm25_daily": "reporting-station mean of station daily means over the Pakistan day (station-day needs ≥ 6 valid hours), as aq_period_stats",
    "fire_series": "deduplicated high/nominal fires within 200 km of the city per Pakistan day: upwind FRP uses the ±60° cone on that day's station wind; frp_200 is the whole ring",
    "lag": "lag k pairs the fire day d with the PM2.5 day d+k (k = 0, 1, 2)",
    "correlation": "Pearson and Spearman over the paired days (n given); |r| < 0.3 weak, < 0.6 moderate, else strong; no significance test",
    "candidate_smoke_transport_episode": "upwind FRP on the day or the day before above the window's 75th percentile AND PM2.5 ≥ 120 % of the prior three days' mean AND at least 10 µg/m³ higher. A candidate only: meteorology drives both fire activity and accumulation, so the rule is a screen, not an attribution",
    "fire_influenced_day": "former name of candidate_smoke_transport_episode (kept one release for older readers)",
    "not_causation": FIRE_DEFINITIONS["not_causation"],
}


def _rank(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(1, len(a) + 1, dtype=float)
    # average ties
    vals = a[order]
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return ranks


def correlations(x_: Sequence[float], y_: Sequence[float]) -> Dict[str, Any]:
    a = np.asarray(x_, dtype=float)
    b = np.asarray(y_, dtype=float)
    m = ~np.isnan(a) & ~np.isnan(b)
    a, b = a[m], b[m]
    n = int(len(a))
    if n < MIN_PAIRS or a.std() == 0 or b.std() == 0:
        return {"n": n, "pearson": None, "spearman": None, "strength": "insufficient" if n < MIN_PAIRS else "undefined"}
    pear = float(np.corrcoef(a, b)[0, 1])
    spear = float(np.corrcoef(_rank(a), _rank(b))[0, 1])
    r = abs(spear)
    return {"n": n, "pearson": round(pear, 2), "spearman": round(spear, 2), "strength": "weak" if r < 0.3 else ("moderate" if r < 0.6 else "strong")}


async def city_wind_by_day(db, city_id: int, start: date, end: date) -> Dict[date, Tuple[Optional[float], Optional[float], int]]:
    """Pakistan day -> (from_deg, speed_ms, n) from the city's station observations, one query."""
    from sqlalchemy import text
    from app.services.copilot.station_queries import day_window_utc
    w0, _ = day_window_utc(start)
    _, w1 = day_window_utc(end)
    rows = (await db.execute(text("""
        SELECT (r.ts_utc AT TIME ZONE 'Asia/Karachi')::date AS d, r.wind_dir_deg AS wd, r.wind_speed_ms AS ws
        FROM readings r JOIN stations s ON s.station_id = r.scope_key
        WHERE r.scope_type = 'station' AND s.city_id = :cid AND s.active = true
          AND r.ts_utc >= :w0 AND r.ts_utc < :w1
          AND r.wind_dir_deg IS NOT NULL AND r.wind_speed_ms IS NOT NULL
    """), {"cid": city_id, "w0": w0, "w1": w1})).fetchall()
    by_day: Dict[date, List[Tuple[float, float]]] = {}
    for r in rows:
        by_day.setdefault(r.d, []).append((float(r.wd), float(r.ws)))
    out: Dict[date, Tuple[Optional[float], Optional[float], int]] = {}
    for d, obs in by_day.items():
        fd, sp = fr.vector_mean_from_deg([o[0] for o in obs], [o[1] for o in obs])
        out[d] = (fd, sp, len(obs))
    return out


async def fire_pm25_link(db, city: str, start: Optional[date] = None, end: Optional[date] = None, *,
                         store: Optional[AggStore] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """Daily upwind fire FRP against the city's daily PM2.5 with lagged correlations and flagged days."""
    from app.services.copilot.station_queries import _city_centroid, period_stats, resolve_city
    store = store or agg_store()
    today = today or pkt_today()
    end = min(end or today, today)
    start = start or (end - timedelta(days=59))
    if start > end:
        return {"message": f"Start {start} is after end {end}."}
    if (end - start).days + 1 > MAX_LINK_DAYS:
        return {"message": f"The window is limited to {MAX_LINK_DAYS} days; ask for a shorter one."}
    match, cands = await resolve_city(db, city)
    if cands:
        return {"message": f"'{city}' matches several cities: {', '.join(c.name for c in cands)}. Which one?"}
    if match is None:
        return {"message": f"City '{city}' not found among active Pakistan cities."}
    lat, lon = await _city_centroid(db, match)
    if lat is None or lon is None:
        return {"message": f"{match.name} has no coordinates in the registry."}
    pm = await period_stats(db, entity="city", name=match.name, start=start.isoformat(), end=end.isoformat(), bucket="day")
    if "message" in pm and not pm.get("rows"):
        return {"message": f"No PM2.5 for {match.name}: {pm['message']}"}
    pm_by_day = {date.fromisoformat(r["bucket"]): (r["mean"], r.get("n_stations")) for r in pm.get("rows", []) if r.get("mean") is not None}
    det, passes = _detections_for(store, start, end)
    head = _headline(det) if len(det) else det
    if len(head):
        km = fr.haversine_km_vec(lat, lon, head["lat"].to_numpy(), head["lon"].to_numpy())
        brg = fr.bearing_deg(lat, lon, head["lat"].to_numpy(), head["lon"].to_numpy())
        head = head.assign(km=km, bearing=brg)
        head = head[head["km"] <= MAX_RING_KM]
    wind = await city_wind_by_day(db, match.id, start, end)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    manifest_days = {date.fromisoformat(k) for k in store.manifest().get("days", {})}
    series = []
    for d in days:
        g = head[head["pk_day"] == d] if len(head) else head
        has_file = d in manifest_days or (store.day_from_csv(d) is not None if today_recent(d, today) else False)
        wd, ws, n = wind.get(d, (None, None, 0))
        up = None
        if wd is not None and has_file:
            up = float(g.loc[fr.in_cone(g["bearing"].to_numpy(), wd), "frp"].sum()) if len(g) else 0.0
        series.append({"day": d, "pm25": pm_by_day.get(d, (None, None))[0], "n_stations": pm_by_day.get(d, (None, None))[1],
                       "fires_100": int((g["km"] <= 100).sum()) if len(g) else (0 if has_file else None),
                       "frp_100": round(float(g.loc[g["km"] <= 100, "frp"].sum()), 1) if len(g) else (0.0 if has_file else None),
                       "frp_200": round(float(g["frp"].sum()), 1) if len(g) else (0.0 if has_file else None),
                       "frp_upwind": round(up, 1) if up is not None else None, "wind_from": wd, "wind_ms": ws, "wind_obs": n, "has_fire_file": has_file})
    pm_arr = np.array([np.nan if r["pm25"] is None else r["pm25"] for r in series], dtype=float)
    up_arr = np.array([np.nan if r["frp_upwind"] is None else r["frp_upwind"] for r in series], dtype=float)
    r200 = np.array([np.nan if r["frp_200"] is None else r["frp_200"] for r in series], dtype=float)
    corr = {}
    for name, arr in (("frp_upwind", up_arr), ("frp_200", r200)):
        corr[name] = {}
        for lag in (0, 1, 2):
            xs = arr[: len(arr) - lag] if lag else arr
            ys = pm_arr[lag:] if lag else pm_arr
            corr[name][f"lag{lag}"] = correlations(xs, ys)
    finite_up = up_arr[~np.isnan(up_arr)]
    p75 = float(np.quantile(finite_up, P75_QUANTILE)) if len(finite_up) >= 4 else None
    flagged = []
    for i, r in enumerate(series):
        r["flag"] = False
        if p75 is None or r["pm25"] is None or i < 3:
            continue
        prior = [series[j]["pm25"] for j in range(i - 3, i) if series[j]["pm25"] is not None]
        if len(prior) < 2:
            continue
        base = float(np.mean(prior))
        fire_hit = any(series[j]["frp_upwind"] is not None and series[j]["frp_upwind"] > p75 for j in (i, i - 1))
        if fire_hit and r["pm25"] >= RISE_RATIO * base and r["pm25"] - base >= RISE_FLOOR:
            r["flag"] = True
            r["pm25_prior3"] = round(base, 1)
            flagged.append(r["day"])
    n_pm = int(sum(1 for r in series if r["pm25"] is not None))
    n_wind = int(sum(1 for r in series if r["frp_upwind"] is not None))
    best = max(((k, lag, v) for k, lags in corr.items() for lag, v in lags.items() if v["spearman"] is not None),
               key=lambda t: abs(t[2]["spearman"]), default=None)
    if n_pm and flagged:
        summary = (f"{len(flagged)} of {n_pm} days with PM2.5 are candidate smoke-transport episodes: upwind fire FRP above the window's "
                   f"75th percentile and PM2.5 ≥ 20 % (and ≥ 10 µg/m³) above the prior three days' mean, a pattern consistent with smoke "
                   f"transport; stagnation, a shallow boundary layer and local sources produce the same rise, so this is a screen, not an attribution.")
    elif n_pm:
        summary = "No candidate smoke-transport episode in this window: upwind fires did not coincide with a PM2.5 rise on the prior three days."
    else:
        summary = f"No PM2.5 reporting days for {match.name} in this window."
    if best:
        series_name = {"frp_upwind": "upwind fire FRP", "frp_200": "fire FRP within 200 km (any direction)"}[best[0]]
        lag_name = {"lag0": "the same day", "lag1": "the next day", "lag2": "two days later"}[best[1]]
        summary += (f" Strongest association: {series_name} with PM2.5 {lag_name}, Spearman {best[2]['spearman']} "
                    f"({best[2]['strength']}, n={best[2]['n']}).")
    rows = series if len(series) <= MAX_ROWS else sorted(series, key=lambda r: (not r["flag"], r["day"]))[:MAX_ROWS]
    rows = sorted(rows, key=lambda r: r["day"])
    out_rows = [{**{k: v for k, v in r.items() if k not in ("has_fire_file",)}, "day": r["day"].isoformat()} for r in rows]
    caveats = [LINK_DEFINITIONS["not_causation"],
               "The lagged correlation is exploratory: it is not controlled for wind, boundary-layer depth, humidity or the prior PM2.5, "
               "and it has not been tested against a meteorology-only baseline."]
    if n_wind < n_pm:
        caveats.append(f"Upwind FRP is defined on {n_wind} of {len(series)} days (station wind or fire file missing on the others); frp_200 covers the whole ring regardless of wind.")
    if passes.get("day_basis") and "acq_utc" in passes["day_basis"]:
        caveats.append("Some days in the window are UTC-keyed archive days without pass times.")
    return {"city": match.name, "window": _window_dict(start, end), "pm25_statistic": pm.get("statistic"), "days": len(series),
            "days_with_pm25": n_pm, "days_with_upwind": n_wind, "upwind_p75_mw": _r(p75), "correlations": corr,
            "candidate_episodes": [d.isoformat() for d in flagged],
            "fire_influenced_days": [d.isoformat() for d in flagged],       # deprecated alias, one release
            "rows": out_rows, "rows_truncated": len(series) > MAX_ROWS,
            "summary": summary, "passes": passes, "caveats": caveats, "definitions": LINK_DEFINITIONS}
