"""
Read-side fire analytics for the public "Fire trends" page (routers/fires.py).

Everything here is sync, store-injected (like fire_analytics.fire_trends) and cheap to call
repeatedly: the daily region table is pre-pivoted once per store build into ~140 small
date-indexed frames (RegionTable), and the router memoises whole responses per
(endpoint, params, store build, Pakistan day).

Conventions shared with the copilot tools:
- counts are deduplicated fires with a high- or nominal-confidence detection (n_dedup_hn);
- a day without a file is null (a gap), a day with an empty file is 0;
- windows are Pakistan days and the season-to-date window ends *yesterday* (today's day pass
  is still arriving through the afternoon);
- year comparisons sum the reference years over the same calendar days that have data in the
  current season (the 2026 archive lacks 1–15 Oct), and a reference year needs 60 % of those days.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.services import fire_analytics as fa
from app.services import fire_regions as fr
from app.services.fire_aggregates import AggStore, agg_store

SEASON_IDS = {"rice": "kharif_rice_residue", "wheat": "rabi_wheat_residue"}
SEASON_LABELS = {"rice": "Rice stubble season (1 Oct – 30 Nov)", "wheat": "Wheat stubble season (15 Apr – 31 May)"}
BBOX_ALIASES = {"bbox", "whole box", "box", "all", "everything"}
R7_MIN_DAYS = 4
REF_COVERAGE = 0.6
MEMO_TTL_S = 600.0
MEMO_MAX = 256
METRICS = ["n_dedup_hn", "n_raw", "frp_dedup_hn", "n_day", "n_night"]
SATELLITE_NAMES = {"N": "Suomi NPP", "SNPP": "Suomi NPP", "VIIRS_SNPP_NRT": "Suomi NPP", "VIIRS_SNPP_SP": "Suomi NPP",
                   "N20": "NOAA-20", "1": "NOAA-20", "VIIRS_NOAA20_NRT": "NOAA-20", "VIIRS_NOAA20_SP": "NOAA-20",
                   "N21": "NOAA-21", "2": "NOAA-21", "VIIRS_NOAA21_NRT": "NOAA-21"}

# chip presets: (id, label, kind, api region name)
REGION_PRESETS: List[Tuple[str, str, str, str]] = [
    ("pakistan", "Pakistan", "country", "Pakistan"),
    ("india", "Indian Punjab + Haryana", "country", "India (Punjab+Haryana)"),
    ("indian-punjab", "Indian Punjab", "india_state", "Punjab (IN)"),
    ("haryana", "Haryana", "india_state", "Haryana (IN)"),
    ("bbox", "Whole box", "bbox", "bbox"),
    ("punjab", "Punjab", "province", "Punjab"),
    ("sindh", "Sindh", "province", "Sindh"),
    ("kp", "Khyber Pakhtunkhwa", "province", "Khyber Pakhtunkhwa"),
    ("balochistan", "Balochistan", "province", "Balochistan"),
    ("gb", "Gilgit-Baltistan", "province", "Gilgit-Baltistan"),
    ("ajk", "Azad Kashmir", "province", "Azad Kashmir"),
    ("islamabad", "Islamabad", "province", "Islamabad"),
]
PROVINCES = [p[3] for p in REGION_PRESETS if p[2] == "province"]
NOTES = [
    "Counts are deduplicated fires: detections from different satellites within 1 km and 90 minutes are one fire, and only fires with at least one high- or nominal-confidence detection are counted. That is the measure that stays comparable as satellites come and go (see the roster by year; Suomi NPP was retired on 1 November 2026).",
    "Fires are a floor. A satellite sees a field only twice a day (about 13:00 and 01:00 Pakistan time); fires lit and put out between passes, or hidden by cloud and thick smoke, are not counted.",
    "Days are Pakistan calendar days. Season-to-date figures end yesterday because today's afternoon pass is still arriving.",
    "Year comparisons sum each earlier year over the same calendar dates that have data this season, so a gap in this year's archive does not make the past look bigger.",
    "Fire radiative power (FRP, megawatts) is burning intensity, not a PM2.5 contribution. Fire–PM2.5 patterns are 'consistent with' smoke transport; stagnation and local sources can produce the same rise.",
]


# ── memo ──────────────────────────────────────────────────────────────────────

_MEMO: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}


def memo(key: Tuple[Any, ...], fn: Callable[[], Any]) -> Any:
    hit = _MEMO.get(key)
    if hit is not None and time.monotonic() - hit[0] < MEMO_TTL_S:
        return hit[1]
    val = fn()
    if len(_MEMO) >= MEMO_MAX:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[key] = (time.monotonic(), val)
    return val


# ── region table (pre-pivot) ─────────────────────────────────────────────────

@dataclass
class RegionTable:
    built_at: Optional[str]
    frame: pd.DataFrame                               # MultiIndex (region_kind, region, pk_day Timestamp) -> METRICS, sorted
    district_frame: pd.DataFrame                      # pk_day (Timestamp), region, METRICS… (district rows only)
    days_with_file: set
    suspect_days: set

    def _group(self, kind: str, region: str) -> Optional[pd.DataFrame]:
        try:
            g = self.frame.loc[(kind, region)]
        except KeyError:
            return None
        return g if isinstance(g, pd.DataFrame) else None

    def series(self, kind: str, region: str, start: date, end: date) -> pd.DataFrame:
        """Same columns and semantics as fire_analytics._series; kind 'bbox' sums the three country rows."""
        idx = pd.date_range(start, end, freq="D")
        has_file = np.array([d.date() in self.days_with_file for d in idx])
        zero = pd.DataFrame(0.0, index=idx, columns=METRICS)
        if kind == "bbox":
            parts = [self._group("country", lab) for lab in fr.COUNTRY_LABELS.values()]
            vals = sum((p.reindex(idx).fillna(0.0) for p in parts if p is not None), zero)
        else:
            g = self._group(kind, region)
            vals = g.reindex(idx).fillna(0.0) if g is not None else zero
        out = pd.DataFrame({"pk_day": [d.date() for d in idx]})
        for c in METRICS:
            out[c] = np.where(has_file, vals[c].to_numpy(dtype=float), np.nan)
        out["has_file"] = has_file
        return out

    def district_sums(self, days: Iterable[date], province: Optional[str] = None) -> pd.DataFrame:
        want = pd.DatetimeIndex(sorted(set(days)))
        f = self.district_frame[self.district_frame["pk_day"].isin(want)]
        if province:
            dp = fr.load_region_index().district_province
            f = f[f["region"].map(dp) == province]
        if f.empty:
            return pd.DataFrame(columns=["region", "fires", "frp", "n_day", "n_night", "days_active"]).set_index("region")
        g = f.groupby("region")
        return pd.DataFrame({"fires": g["n_dedup_hn"].sum(), "frp": g["frp_dedup_hn"].sum(), "n_day": g["n_day"].sum(),
                             "n_night": g["n_night"].sum(), "days_active": g["pk_day"].nunique()})


_TABLE: Optional[RegionTable] = None


def region_table(store: AggStore) -> RegionTable:
    """The pre-pivot for the store's current build (rebuilt when built_at changes; one sort, well under a second)."""
    global _TABLE
    m = store.manifest()
    built = m.get("built_at")
    if _TABLE is not None and _TABLE.built_at == built:
        return _TABLE
    daily = store.daily_regions()
    pk = pd.to_datetime(daily["pk_day"])
    frame = pd.DataFrame({c: daily[c].to_numpy(dtype=float) for c in METRICS},
                         index=pd.MultiIndex.from_arrays([daily["region_kind"].to_numpy(), daily["region"].to_numpy(), pk],
                                                         names=["region_kind", "region", "pk_day"]))
    frame = frame.groupby(level=["region_kind", "region", "pk_day"]).sum().sort_index()     # older builds may hold split rows
    dmask = (daily["region_kind"] == "district").to_numpy()
    dist = pd.DataFrame({"pk_day": pk[dmask].to_numpy(), "region": daily["region"].to_numpy()[dmask],
                         **{c: daily[c].to_numpy(dtype=float)[dmask] for c in METRICS}})
    _TABLE = RegionTable(built, frame, dist, {date.fromisoformat(k) for k in m.get("days", {})},
                         {date.fromisoformat(x["day"]) for x in m.get("suspect_days", []) if x.get("day")})
    return _TABLE


# ── regions and seasons ──────────────────────────────────────────────────────

def resolve_public_region(name: str) -> Tuple[Optional[Tuple[str, str]], str, Optional[str]]:
    """((kind, api_region), label, note) accepting chip ids, aliases and anything resolve_region takes."""
    key = (name or "pakistan").strip().lower()
    if key in BBOX_ALIASES:
        return ("bbox", "bbox"), "Whole box (Pakistan, North India, Afghanistan, Iran)", None
    for pid, label, kind, api in REGION_PRESETS:
        if key == pid or key == api.lower() or key == label.lower():
            return (kind, api), label, None
    resolved, note, _ = fa.resolve_region(name)
    if resolved is None:
        return None, name, None
    kind, api = resolved
    label = {"Punjab (IN)": "Indian Punjab", "Haryana (IN)": "Haryana", "India (Punjab+Haryana)": "Indian Punjab + Haryana",
             "other in bbox": "Rest of the box"}.get(api, api)
    return (kind, api), label, note


def season_bounds(season_id: str, *, today: date) -> Tuple[date, date, date, int]:
    """(start, nominal end, effective end = min(nominal end, yesterday), season year) for the latest season."""
    key = SEASON_IDS[season_id]
    sw = fa.season_window(key, today=today)
    assert sw is not None
    start, _, _ = sw
    s_mmdd, e_mmdd = fa.SEASONS[key]
    end_nominal = date(start.year, int(e_mmdd[:2]), int(e_mmdd[3:]))
    end_eff = min(end_nominal, today - timedelta(days=1))
    return start, end_nominal, end_eff, start.year


def _mmdd(d: date) -> str:
    return d.strftime("%m-%d")


def _day_label(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _nullable(values: Sequence[float], as_int: bool = True) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for v in values:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out.append(None)
        else:
            out.append(int(v) if as_int else round(float(v), 1))
    return out


def _pct(cur: float, ref: float) -> Optional[int]:
    return None if not ref else int(round((cur - ref) / ref * 100))


def _rank_text(k: int, n: int) -> str:
    return ("higher than every reference year" if k == n else "lower than every reference year" if k == 0
            else f"higher than {k} of the {n} reference years")


# ── endpoints' payloads ──────────────────────────────────────────────────────

def seasons(region: str = "pakistan", season: str = "rice", *, store: Optional[AggStore] = None,
            today: Optional[date] = None) -> Dict[str, Any]:
    store = store or agg_store()
    today = today or fa.pkt_today()
    if season not in SEASON_IDS:
        return {"error": f"season must be one of {', '.join(SEASON_IDS)}"}
    resolved, label, note = resolve_public_region(region)
    if resolved is None:
        return {"error": f"region '{region}' not recognised"}
    kind, api = resolved
    t = region_table(store)
    start, end_nominal, end_eff, year = season_bounds(season, today=today)
    days = [start + timedelta(days=i) for i in range((end_nominal - start).days + 1)]
    mmdd = [_mmdd(d) for d in days]
    n_to_date = (end_eff - start).days + 1 if end_eff >= start else 0
    years_out: List[Dict[str, Any]] = []
    cur_series: Optional[pd.DataFrame] = None
    for y in sorted(set(fa.REFERENCE_YEARS) | {year}):
        if y > year:
            continue
        ys, ye = date(y, start.month, start.day), date(y, end_nominal.month, end_nominal.day)
        s = t.series(kind, api, ys, ye)
        if y == year:
            # the season-to-date window ends yesterday: today's partial day is not shown as a point
            s.loc[s["pk_day"] > end_eff, [*METRICS, "has_file"]] = [np.nan] * len(METRICS) + [False]
            cur_series = s
        r7 = s["n_dedup_hn"].rolling(7, min_periods=R7_MIN_DAYS).mean()
        valid = s[s["has_file"]]
        to_date = valid[valid["pk_day"] <= date(y, end_eff.month, end_eff.day)] if n_to_date else valid.iloc[0:0]
        sus = sum(1 for d in s["pk_day"] if d in t.suspect_days)
        years_out.append({
            "year": y, "role": "current" if y == year else ("last" if y == year - 1 else "reference"),
            "fires": _nullable(s["n_dedup_hn"].tolist()), "r7": _nullable(r7.tolist(), as_int=False),
            "total": int(valid["n_dedup_hn"].sum()) if len(valid) else None,
            "total_to_date": int(to_date["n_dedup_hn"].sum()) if len(to_date) else None,
            "days_with_data": int(len(valid)), "days_missing": int((~s["has_file"]).sum()), "suspect_days": sus,
            "first_day_with_data": valid["pk_day"].iloc[0].isoformat() if len(valid) else None,
        })
    # headline: season-to-date on the days with data, compared with the same calendar dates in earlier years
    cur = cur_series[cur_series["pk_day"] <= end_eff] if cur_series is not None else None
    valid = cur[cur["has_file"]] if cur is not None else None
    mm_with = {_mmdd(d) for d in valid["pk_day"]} if valid is not None else set()
    fires = int(valid["n_dedup_hn"].sum()) if valid is not None and len(valid) else 0
    n_day, n_night = (int(valid["n_day"].sum()), int(valid["n_night"].sum())) if valid is not None and len(valid) else (0, 0)
    def _same_dates(y: int) -> Tuple[Optional[int], int]:
        s = next((r for r in years_out if r["year"] == y), None)
        if s is None:
            return None, 0
        vals = [(m, v) for m, v in zip(mmdd, s["fires"]) if m in mm_with and v is not None]
        return (sum(v for _, v in vals), len(vals)) if vals else (None, 0)
    need = max(1, int(REF_COVERAGE * len(mm_with))) if mm_with else 1
    last_fires, last_n = _same_dates(year - 1)
    ref_rows = []
    for y in fa.REFERENCE_YEARS:
        if y >= year:
            continue
        f, n = _same_dates(y)
        ref_rows.append({"year": y, "fires": f, "days_with_data": n, "used": f is not None and n >= need})
    used = [r for r in ref_rows if r["used"]]
    ref_vals = [r["fires"] for r in used]
    headline: Dict[str, Any] = {
        "window": {"start": start.isoformat(), "end": end_eff.isoformat(), "days": n_to_date, "days_with_data": len(mm_with),
                   "days_missing": max(0, n_to_date - len(mm_with)),
                   "compared_dates": (f"{_day_label(valid['pk_day'].iloc[0])} – {_day_label(valid['pk_day'].iloc[-1])}" if valid is not None and len(valid) else None)},
        "fires": fires, "fires_per_day": round(fires / len(mm_with), 1) if mm_with else None,
        "frp_mw": round(float(valid["frp_dedup_hn"].sum())) if valid is not None and len(valid) else 0,
        "day": n_day, "night": n_night, "night_share": round(n_night / (n_day + n_night), 2) if (n_day + n_night) else None,
        "last_year": ({"year": year - 1, "fires": last_fires, "pct_change": _pct(fires, last_fires), "days_with_data": last_n}
                      if last_fires is not None and last_n >= need else None),
        "reference": {"years": [r["year"] for r in ref_rows], "used_years": [r["year"] for r in used], "rows": ref_rows,
                      "mean": round(float(np.mean(ref_vals))) if ref_vals else None, "min": min(ref_vals) if ref_vals else None,
                      "max": max(ref_vals) if ref_vals else None, "pct_change": _pct(fires, float(np.mean(ref_vals))) if ref_vals else None,
                      "higher_than_n_of": [sum(1 for v in ref_vals if fires > v), len(ref_vals)] if ref_vals else None,
                      "rank_text": _rank_text(sum(1 for v in ref_vals if fires > v), len(ref_vals)) if ref_vals else None},
    }
    caveats = [fa.FIRE_DEFINITIONS["headline_count"],
               "Archive days before the 2026 ingester are keyed by UTC date; the satellite roster differs by year, so deduplicated counts are the comparable ones."]
    if headline["window"]["days_missing"]:
        caveats.append(f"{headline['window']['days_missing']} day(s) of this season have no fire file; comparisons use the {len(mm_with)} days with data.")
    thin = [r["year"] for r in years_out if r["suspect_days"]]
    if thin:
        caveats.append(f"Archive looks thin (re-fetched with fewer rows than the 2020–2023 median) on some days in {', '.join(map(str, thin))}.")
    out = {"region": {"kind": kind, "name": api, "label": label},
           "season": {"id": season, "key": SEASON_IDS[season], "label": SEASON_LABELS[season], "year": year, "start": start.isoformat(),
                      "end": end_nominal.isoformat(), "end_effective": end_eff.isoformat(), "complete": today > end_nominal},
           "days": mmdd, "today_index": (end_eff - start).days if start <= end_eff <= end_nominal and today <= end_nominal else None,
           "years": years_out, "headline": headline,
           "method": {"r7": f"mean of the days with a file in the trailing 7-day window; null when fewer than {R7_MIN_DAYS}",
                      "comparison": "earlier years summed over the same calendar dates that have data this season; a year needs 60 % of them"},
           "caveats": caveats, "store_built_at": t.built_at}
    if note:
        out["note"] = note
    return out


def districts(season: str = "rice", region: str = "pakistan", *, limit: int = 40, store: Optional[AggStore] = None,
              today: Optional[date] = None) -> Dict[str, Any]:
    store = store or agg_store()
    today = today or fa.pkt_today()
    if season not in SEASON_IDS:
        return {"error": f"season must be one of {', '.join(SEASON_IDS)}"}
    resolved, label, _ = resolve_public_region(region)
    if resolved is None:
        return {"error": f"region '{region}' not recognised"}
    kind, api = resolved
    t = region_table(store)
    start, end_nominal, end_eff, year = season_bounds(season, today=today)
    cur_days = [start + timedelta(days=i) for i in range((end_eff - start).days + 1)] if end_eff >= start else []
    with_data = [d for d in cur_days if d in t.days_with_file]
    season_info = {"id": season, "year": year, "start": start.isoformat(), "end": end_nominal.isoformat(), "end_effective": end_eff.isoformat()}
    window = {"start": start.isoformat(), "end": end_eff.isoformat(), "days": len(cur_days), "days_with_data": len(with_data),
              "compared_dates": f"{_day_label(with_data[0])} – {_day_label(with_data[-1])}" if with_data else None}
    base = {"season": season_info, "window": window, "last_year": year - 1, "region": {"kind": kind, "name": api, "label": label},
            "caveats": [fa.FIRE_DEFINITIONS["headline_count"]]}
    if kind in ("india_state",) or api in ("India (Punjab+Haryana)", "other in bbox"):
        return {**base, "rows": [], "districts_total": 0, "totals": None, "note": "District tables cover Pakistan only."}
    province = api if kind == "province" else None
    only_district = api if kind == "district" else None
    cur = t.district_sums(with_data, province)
    last = t.district_sums([date(year - 1, d.month, d.day) for d in with_data], province)
    cents = {name: (lat, lon) for name, lat, lon in _district_centroids()}
    rows = []
    for name, r in cur.iterrows():
        if only_district and name != only_district:
            continue
        fl = int(last.loc[name, "fires"]) if name in last.index else 0
        known = r["n_day"] + r["n_night"]
        lat, lon = cents.get(name, (None, None))
        rows.append({"district": name, "province": fr.load_region_index().district_province.get(name), "fires": int(r["fires"]),
                     "fires_last": fl, "pct_change": _pct(float(r["fires"]), float(fl)), "frp_mw": round(float(r["frp"])),
                     "night_share": round(float(r["n_night"]) / float(known), 2) if known else None, "days_active": int(r["days_active"]),
                     "lat": lat, "lon": lon})
    rows = [r for r in rows if r["fires"] > 0]
    rows.sort(key=lambda r: -r["fires"])
    totals = {"fires": int(cur["fires"].sum()) if len(cur) else 0, "fires_last": int(last["fires"].sum()) if len(last) else 0}
    return {**base, "rows": rows[:max(1, min(int(limit), fa.MAX_ROWS))], "districts_total": len(rows), "totals": totals}


def _district_centroids() -> List[Tuple[str, float, float]]:
    from app.services.copilot.station_queries import district_centroids
    return district_centroids()


SPLIT_REGIONS = [("pakistan", "country", "Pakistan", "Pakistan"), ("indian_punjab", "india_state", "Punjab (IN)", "Indian Punjab"),
                 ("haryana", "india_state", "Haryana (IN)", "Haryana"), ("other", "country", "other in bbox", "Rest of the box (Rajasthan, J&K, Afghanistan, Iran)")]


def split(season: str = "rice", *, store: Optional[AggStore] = None, today: Optional[date] = None) -> Dict[str, Any]:
    store = store or agg_store()
    today = today or fa.pkt_today()
    if season not in SEASON_IDS:
        return {"error": f"season must be one of {', '.join(SEASON_IDS)}"}
    t = region_table(store)
    start, end_nominal, end_eff, year = season_bounds(season, today=today)
    series: Dict[str, List[Optional[int]]] = {}
    totals: Dict[str, int] = {}
    days_missing = 0
    for sid, kind, api, _ in SPLIT_REGIONS:
        s = t.series(kind, api, start, end_nominal)
        upto = s[s["pk_day"] <= end_eff]
        series[sid] = _nullable(s["n_dedup_hn"].tolist())
        totals[sid] = int(upto["n_dedup_hn"].fillna(0).sum())
        days_missing = int((~upto["has_file"]).sum())
    grand = sum(totals.values())
    return {"season": {"id": season, "year": year, "start": start.isoformat(), "end": end_nominal.isoformat(), "end_effective": end_eff.isoformat()},
            "days": [_mmdd(start + timedelta(days=i)) for i in range((end_nominal - start).days + 1)],
            "series": series, "totals": totals, "shares": {k: round(v / grand, 2) if grand else None for k, v in totals.items()},
            "labels": {sid: lab for sid, _, _, lab in SPLIT_REGIONS}, "days_missing": days_missing,
            "caveats": [fa.FIRE_DEFINITIONS["headline_count"]]}


def persistent(region: str = "pakistan", *, min_days: int = 10, limit: int = 30, store: Optional[AggStore] = None,
               today: Optional[date] = None) -> Dict[str, Any]:
    store = store or agg_store()
    today = today or fa.pkt_today()
    resolved, label, _ = resolve_public_region(region)
    if resolved is None:
        return {"error": f"region '{region}' not recognised"}
    kind, api = resolved
    out = fa.fire_hotspots(region=api, end=today - timedelta(days=1), group="persistent", min_days=int(min_days), limit=int(limit),
                           store=store, today=today)
    if "message" in out and "rows" not in out:
        return {"error": out["message"]}
    out["region"] = {"kind": kind, "name": api, "label": label}
    return out


def meta(*, store: Optional[AggStore] = None, today: Optional[date] = None) -> Dict[str, Any]:
    store = store or agg_store()
    today = today or fa.pkt_today()
    m = store.manifest()
    days = m.get("days", {})
    day_keys = sorted(days)
    sat_by_year: Dict[str, set] = {}
    suspect_by_year: Dict[str, int] = {}
    for k, rec in days.items():
        y = k[:4]
        for s in rec.get("sources") or []:
            sat_by_year.setdefault(y, set()).add(SATELLITE_NAMES.get(s, s))
    for s in m.get("suspect_days", []):
        y = str(s.get("day", ""))[:4]
        suspect_by_year[y] = suspect_by_year.get(y, 0) + 1
    with_file = {date.fromisoformat(k) for k in day_keys}
    gaps: Dict[str, Dict[str, List[List[str]]]] = {}
    years = sorted({int(k[:4]) for k in day_keys} | {today.year})
    for sid, key in SEASON_IDS.items():
        s_mmdd, e_mmdd = fa.SEASONS[key]
        gaps[sid] = {}
        for y in years:
            ys, ye = date(y, int(s_mmdd[:2]), int(s_mmdd[3:])), date(y, int(e_mmdd[:2]), int(e_mmdd[3:]))
            if ys > today:
                continue
            ye = min(ye, today - timedelta(days=1))
            runs: List[List[str]] = []
            d = ys
            while d <= ye:
                if d not in with_file:
                    if runs and date.fromisoformat(runs[-1][1]) == d - timedelta(days=1):
                        runs[-1][1] = d.isoformat()
                    else:
                        runs.append([d.isoformat(), d.isoformat()])
                d += timedelta(days=1)
            if runs:
                gaps[sid][str(y)] = runs
    idx = fr.load_region_index()
    cs = fa.current_season(today)
    return {
        "store_built_at": m.get("built_at"), "today_pkt": today.isoformat(),
        "seasons": {sid: {"key": key, "label": SEASON_LABELS[sid], "start": fa.SEASONS[key][0], "end": fa.SEASONS[key][1]} for sid, key in SEASON_IDS.items()},
        "current_season": next((sid for sid, key in SEASON_IDS.items() if key == cs), None),
        "reference_years": list(fa.REFERENCE_YEARS),
        "regions": [{"id": pid, "label": label, "kind": kind, "api": api} for pid, label, kind, api in REGION_PRESETS],
        "provinces": PROVINCES,
        "districts": sorted([{"name": n, "province": p} for n, p in idx.district_province.items()], key=lambda r: r["name"]),
        "archive": {"first_day": day_keys[0] if day_keys else None, "last_day": day_keys[-1] if day_keys else None, "gaps": gaps,
                    "suspect_days_by_year": suspect_by_year, "low_confidence_from": m.get("low_confidence_from")},
        "satellites_by_year": {y: sorted(v) for y, v in sorted(sat_by_year.items())},
        "pass_times": {"day": "about 13:00 PKT", "night": "about 01:00 PKT"},
        "dedup_rule": m.get("dedup_rule"), "definitions": fa.FIRE_DEFINITIONS, "notes": NOTES,
    }
