"""
Read-side fire analytics for the public "Fire trends" page (routers/fires.py).

Everything here is sync, store-injected (like fire_analytics.fire_trends) and cheap to call
repeatedly: the daily region table is pre-pivoted once per store build into ~140 small
date-indexed frames (RegionTable), and the router memoises whole responses per
(endpoint, params, store build, Pakistan day).

Conventions shared with the copilot tools:
- counts are deduplicated detection clusters with a high- or nominal-confidence detection
  (n_dedup_hn) on basis "all", or NOAA-20 detections alone (n_n20_hn) on basis "n20";
- a day without a file is null (a gap), a day with an empty file is 0; on basis "n20" a day whose
  file has rows from other satellites only is also a gap (a missing NOAA-20 pass);
- windows are Pakistan days and the season-to-date window ends *yesterday* (today's day pass
  is still arriving through the afternoon);
- year comparisons sum the reference years over the same calendar days that are observed in the
  current season, a reference year needs 60 % of those days, and the headline's year-on-year
  figures are always quoted on the NOAA-20-only basis (headline.comparison_n20);
- the cumulative curve is the running sum over observed days (gap days contribute nothing and
  are null); the 10/50/90 % timing dates are given only for complete, adequately observed seasons.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.services import fire_analytics as fa
from app.services import fire_classify as fc
from app.services import fire_regions as fr
from app.services.fire_aggregates import AggStore, agg_store

SEASON_IDS = {"rice": "kharif_rice_residue", "wheat": "rabi_wheat_residue"}
SEASON_LABELS = {"rice": "Rice stubble season (15 Sep – 30 Nov)", "wheat": "Wheat stubble season (15 Apr – 31 May)"}
BBOX_ALIASES = {"bbox", "whole box", "box", "all", "everything"}
R7_MIN_DAYS = 4
REF_COVERAGE = 0.6
TIMING_MAX_MISSING = 0.2             # 10/50/90 % dates need at least 80 % of the season's days observed
MEMO_TTL_S = 600.0
MEMO_MAX = 256
METRICS = fa.SERIES_COLS
BASES = fa.BASES

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
    "Counts are deduplicated detection clusters, not verified fires: detections from different satellites within 1 km and 90 minutes are grouped and counted once, and only clusters with at least one high- or nominal-confidence detection are counted. Neighbouring burning fields can merge into one cluster and one incident can leave several.",
    "A thermal detection does not say what burns. Until the crop-residue classification is in place, these are detections in the burning season, not crop-residue fires.",
    "Year-on-year comparisons use NOAA-20 alone. Deduplication cannot remove the extra fires an added satellite sees, so the comparison holds the satellite fixed: NOAA-20 flew and was processed in every year since 2020, while Suomi NPP (retired 1 November 2026) and NOAA-21 (2026 only in this archive) came and went. The all-satellite count is shown for the fullest picture of today.",
    "Detections are a floor. A satellite sees a field only twice a day (about 13:00 and 01:00 Pakistan time); fires lit and put out between passes, or hidden by cloud and thick smoke, are not counted. A missing pass is shown as a gap, not as zero.",
    "Days are Pakistan calendar days from May 2026; earlier archive days are keyed by UTC date. Season-to-date figures end yesterday because today's afternoon pass is still arriving.",
    "Year comparisons sum each earlier year over the same calendar dates observed this season, so a gap in this year's archive does not make the past look bigger. A cumulative curve part-way through a season cannot tell a late season from a smaller one.",
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
    n20_days: set = field(default_factory=set)        # days observed by NOAA-20 (rows present, or an empty file)
    schema_version: int = 1

    @property
    def has_n20(self) -> bool:
        return self.schema_version >= 2

    def has_basis(self, basis: str) -> bool:
        return self.schema_version >= fa.BASIS_SCHEMA.get(basis, 99)

    def observed(self, basis: str) -> set:
        return self.days_with_file & self.n20_days if basis in fa.N20_BASES else self.days_with_file

    def _group(self, kind: str, region: str) -> Optional[pd.DataFrame]:
        try:
            g = self.frame.loc[(kind, region)]
        except KeyError:
            return None
        return g if isinstance(g, pd.DataFrame) else None

    def series(self, kind: str, region: str, start: date, end: date, basis: str = "all") -> pd.DataFrame:
        """Same columns and semantics as fire_analytics._series; kind 'bbox' sums the three country rows.
        On basis 'n20' a day without NOAA-20 rows is a gap (NaN) for every column."""
        idx = pd.date_range(start, end, freq="D")
        obs = self.observed(basis)
        has_file = np.array([d.date() in obs for d in idx])
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

    def district_sums(self, days: Iterable[date], province: Optional[str] = None, basis: str = "all") -> pd.DataFrame:
        want = pd.DatetimeIndex(sorted(set(days)))
        f = self.district_frame[self.district_frame["pk_day"].isin(want)]
        if province:
            dp = fr.load_region_index().district_province
            f = f[f["region"].map(dp) == province]
        if f.empty:
            return pd.DataFrame(columns=["region", "fires", "frp", "n_day", "n_night", "days_active"]).set_index("region")
        cnt, frpc = fa.COUNT_COL[basis], fa.FRP_COL[basis]
        g = f.groupby("region")
        return pd.DataFrame({"fires": g[cnt].sum(), "frp": g[frpc].sum(), "n_day": g["n_day"].sum(),
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
                         {date.fromisoformat(x["day"]) for x in m.get("suspect_days", []) if x.get("day")},
                         fa.satellite_days(m, fr.CONSISTENT_SATELLITE), int(m.get("schema_version") or 0))
    return _TABLE


def _basis_error(basis: str, t: RegionTable) -> Optional[Dict[str, Any]]:
    if basis not in BASES:
        return {"error": f"basis must be one of {', '.join(BASES)}"}
    if not t.has_basis(basis):
        return {"error": f"the '{basis}' basis needs the rebuilt fire store (schema {fa.BASIS_SCHEMA[basis]}); try again after the next aggregate run"}
    return None


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


def _cumulative(values: pd.Series) -> pd.Series:
    """Running sum over observed days; gap days (NaN) add nothing and stay NaN."""
    cum = values.fillna(0.0).cumsum()
    cum[values.isna()] = np.nan
    return cum


def _timing(s: pd.DataFrame, cnt: str, days: List[date], complete: bool) -> Optional[Dict[str, Any]]:
    """Dates by which 10 %, 50 % and 90 % of a complete season's observed activity had occurred."""
    if not complete or len(s) == 0:
        return None
    missing = int((~s["has_file"]).sum())
    if missing > TIMING_MAX_MISSING * len(s):
        return {"p10": None, "p50": None, "p90": None, "note": f"{missing} of {len(s)} days unobserved; timing not computed"}
    cum = _cumulative(s[cnt])
    total = float(np.nanmax(cum.to_numpy())) if cum.notna().any() else 0.0
    if total <= 0:
        return {"p10": None, "p50": None, "p90": None, "note": "no detections"}
    out: Dict[str, Any] = {}
    for q in (0.1, 0.5, 0.9):
        hit = next((i for i, v in enumerate(cum.tolist()) if v is not None and not np.isnan(v) and v >= q * total), None)
        out[f"p{int(q * 100)}"] = _mmdd(days[hit]) if hit is not None else None
    out["days_unobserved"] = missing
    return out


# ── endpoints' payloads ──────────────────────────────────────────────────────

def seasons(region: str = "pakistan", season: str = "rice", basis: str = "all", *, store: Optional[AggStore] = None,
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
    basis = (basis or "all").strip().lower()
    err = _basis_error(basis, t)
    if err:
        return err
    start, end_nominal, end_eff, year = season_bounds(season, today=today)
    days = [start + timedelta(days=i) for i in range((end_nominal - start).days + 1)]
    mmdd = [_mmdd(d) for d in days]
    n_to_date = (end_eff - start).days + 1 if end_eff >= start else 0

    def _block(b: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cnt, frpc = fa.COUNT_COL[b], fa.FRP_COL[b]
        years_out: List[Dict[str, Any]] = []
        cur_series: Optional[pd.DataFrame] = None
        for y in sorted(set(fa.REFERENCE_YEARS) | {year}):
            if y > year:
                continue
            ys, ye = date(y, start.month, start.day), date(y, end_nominal.month, end_nominal.day)
            ydays = [ys + timedelta(days=i) for i in range((ye - ys).days + 1)]
            s = t.series(kind, api, ys, ye, b)
            if y == year:
                # the season-to-date window ends yesterday: today's partial day is not shown as a point
                s.loc[s["pk_day"] > end_eff, [*METRICS, "has_file"]] = [np.nan] * len(METRICS) + [False]
                cur_series = s
            r7 = s[cnt].rolling(7, min_periods=R7_MIN_DAYS).mean()
            r7[s[cnt].isna()] = np.nan          # a day without data has no mean either (no run-on past the last point)
            cum = _cumulative(s[cnt])
            valid = s[s["has_file"]]
            to_date = valid[valid["pk_day"] <= date(y, end_eff.month, end_eff.day)] if n_to_date else valid.iloc[0:0]
            sus = sum(1 for d in s["pk_day"] if d in t.suspect_days)
            complete = y < year or today > end_nominal
            no_pass = int(sum(1 for d, f in zip(s["pk_day"], s["has_file"]) if not f and d in t.days_with_file and d <= (end_eff if y == year else ye)))
            years_out.append({
                "year": y, "role": "current" if y == year else ("last" if y == year - 1 else "reference"),
                "fires": _nullable(s[cnt].tolist()), "r7": _nullable(r7.tolist(), as_int=False), "cum": _nullable(cum.tolist()),
                "total": int(valid[cnt].sum()) if len(valid) else None,
                "total_to_date": int(to_date[cnt].sum()) if len(to_date) else None,
                "days_with_data": int(len(valid)), "days_missing": int((~s["has_file"]).sum()), "days_no_pass": no_pass, "suspect_days": sus,
                "first_day_with_data": valid["pk_day"].iloc[0].isoformat() if len(valid) else None,
                "complete": complete, "timing": _timing(s, cnt, ydays, complete),
            })
        # headline: season-to-date on the days with data, compared with the same calendar dates in earlier years
        cur = cur_series[cur_series["pk_day"] <= end_eff] if cur_series is not None else None
        valid = cur[cur["has_file"]] if cur is not None else None
        mm_with = {_mmdd(d) for d in valid["pk_day"]} if valid is not None else set()
        fires = int(valid[cnt].sum()) if valid is not None and len(valid) else 0
        n_day, n_night = (int(valid["n_day"].sum()), int(valid["n_night"].sum())) if valid is not None and len(valid) else (0, 0)
        def _same_dates(y: int) -> Tuple[Optional[int], int]:
            sy = next((r for r in years_out if r["year"] == y), None)
            if sy is None:
                return None, 0
            vals = [(m, v) for m, v in zip(mmdd, sy["fires"]) if m in mm_with and v is not None]
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
            "basis": b, "basis_label": BASES[b],
            "window": {"start": start.isoformat(), "end": end_eff.isoformat(), "days": n_to_date, "days_with_data": len(mm_with),
                       "days_missing": max(0, n_to_date - len(mm_with)),
                       "compared_dates": (f"{_day_label(valid['pk_day'].iloc[0])} – {_day_label(valid['pk_day'].iloc[-1])}" if valid is not None and len(valid) else None)},
            "fires": fires, "fires_per_day": round(fires / len(mm_with), 1) if mm_with else None,
            "frp_mw": round(float(valid[frpc].sum())) if valid is not None and len(valid) else 0,
            "day": n_day, "night": n_night, "night_share": round(n_night / (n_day + n_night), 2) if (n_day + n_night) else None,
            "last_year": ({"year": year - 1, "fires": last_fires, "pct_change": _pct(fires, last_fires), "days_with_data": last_n}
                          if last_fires is not None and last_n >= need else None),
            "reference": {"years": [r["year"] for r in ref_rows], "used_years": [r["year"] for r in used], "rows": ref_rows,
                          "mean": round(float(np.mean(ref_vals))) if ref_vals else None, "min": min(ref_vals) if ref_vals else None,
                          "max": max(ref_vals) if ref_vals else None, "pct_change": _pct(fires, float(np.mean(ref_vals))) if ref_vals else None,
                          "higher_than_n_of": [sum(1 for v in ref_vals if fires > v), len(ref_vals)] if ref_vals else None,
                          "rank_text": _rank_text(sum(1 for v in ref_vals if fires > v), len(ref_vals)) if ref_vals else None},
        }
        return years_out, headline

    years_out, headline = _block(basis)
    if basis in ("all", "crop") and t.has_n20 and (basis == "all" or t.has_basis("crop_n20")):
        _, h20 = _block("crop_n20" if basis == "crop" else "n20")
        headline["comparison_n20"] = {k: h20[k] for k in ("basis", "basis_label", "fires", "last_year", "reference")}
        headline["comparison_n20"]["days_with_data"] = h20["window"]["days_with_data"]
        headline["comparison_n20"]["note"] = "year-on-year figures on NOAA-20 alone: quote these, not the all-satellite ratio"
    caveats = [fa.FIRE_DEFINITIONS["headline_count"], fa.FIRE_DEFINITIONS["comparison_basis"], fa.FIRE_DEFINITIONS["what_burns"]]
    if headline["window"]["days_missing"]:
        caveats.append(f"{headline['window']['days_missing']} day(s) of this season are unobserved on this basis; comparisons use the "
                       f"{headline['window']['days_with_data']} days with data.")
    thin = [r["year"] for r in years_out if r["suspect_days"]]
    if thin:
        caveats.append(f"Archive looks thin (re-fetched with fewer rows than the 2020–2023 median) on some days in {', '.join(map(str, thin))}.")
    if not headline.get("comparison_n20") and basis == "all":
        caveats.append("The store predates the NOAA-20-only series; year-on-year figures here mix satellite rosters.")
    if basis in ("crop", "crop_n20"):
        caveats.append(fa.FIRE_DEFINITIONS["classification"] + " " + fc.RULES["status"] + ".")
    if season == "rice":
        caveats.append(fa.SEASON_WINDOW_NOTE)
    out = {"region": {"kind": kind, "name": api, "label": label}, "basis": basis, "basis_label": BASES[basis],
           "season": {"id": season, "key": SEASON_IDS[season], "label": SEASON_LABELS[season], "year": year, "start": start.isoformat(),
                      "end": end_nominal.isoformat(), "end_effective": end_eff.isoformat(), "complete": today > end_nominal},
           "days": mmdd, "today_index": (end_eff - start).days if start <= end_eff <= end_nominal and today <= end_nominal else None,
           "years": years_out, "headline": headline,
           "method": {"r7": f"mean of the days observed in the trailing 7-day window; null when fewer than {R7_MIN_DAYS}",
                      "cum": "running sum over observed days; a gap day adds nothing and is null; the curve resumes after it",
                      "timing": f"for complete seasons with at least {int((1 - TIMING_MAX_MISSING) * 100)} % of days observed: the dates by which 10 %, 50 % and 90 % of the season's detections had occurred",
                      "comparison": "earlier years summed over the same calendar dates observed this season; a year needs 60 % of them; headline.comparison_n20 holds the NOAA-20-only figures",
                      "basis": BASES[basis]},
           "caveats": caveats, "store_built_at": t.built_at}
    if note:
        out["note"] = note
    return out


def districts(season: str = "rice", region: str = "pakistan", basis: str = "all", *, limit: int = 40, store: Optional[AggStore] = None,
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
    basis = (basis or "all").strip().lower()
    err = _basis_error(basis, t)
    if err:
        return err
    start, end_nominal, end_eff, year = season_bounds(season, today=today)
    cur_days = [start + timedelta(days=i) for i in range((end_eff - start).days + 1)] if end_eff >= start else []
    obs = t.observed(basis)
    with_data = [d for d in cur_days if d in obs]
    season_info = {"id": season, "year": year, "start": start.isoformat(), "end": end_nominal.isoformat(), "end_effective": end_eff.isoformat()}
    window = {"start": start.isoformat(), "end": end_eff.isoformat(), "days": len(cur_days), "days_with_data": len(with_data),
              "compared_dates": f"{_day_label(with_data[0])} – {_day_label(with_data[-1])}" if with_data else None}
    base = {"season": season_info, "window": window, "last_year": year - 1, "region": {"kind": kind, "name": api, "label": label},
            "basis": basis, "basis_label": BASES[basis], "caveats": [fa.FIRE_DEFINITIONS["headline_count"], fa.FIRE_DEFINITIONS["what_burns"]]}
    if kind in ("india_state",) or api in ("India (Punjab+Haryana)", "other in bbox"):
        return {**base, "rows": [], "districts_total": 0, "totals": None, "note": "District tables cover Pakistan only."}
    province = api if kind == "province" else None
    only_district = api if kind == "district" else None
    cur = t.district_sums(with_data, province, basis)
    last_days = [date(year - 1, d.month, d.day) for d in with_data]
    last = t.district_sums([d for d in last_days if d in obs], province, basis)
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
TWO_PUNJABS = [("pakistan_punjab", "province", "Punjab", "Pakistan Punjab"), ("indian_punjab", "india_state", "Punjab (IN)", "Indian Punjab"),
               ("haryana", "india_state", "Haryana (IN)", "Haryana")]


def split(season: str = "rice", basis: str = "all", *, store: Optional[AggStore] = None, today: Optional[date] = None) -> Dict[str, Any]:
    store = store or agg_store()
    today = today or fa.pkt_today()
    if season not in SEASON_IDS:
        return {"error": f"season must be one of {', '.join(SEASON_IDS)}"}
    t = region_table(store)
    basis = (basis or "all").strip().lower()
    err = _basis_error(basis, t)
    if err:
        return err
    cnt = fa.COUNT_COL[basis]
    start, end_nominal, end_eff, year = season_bounds(season, today=today)
    series: Dict[str, List[Optional[int]]] = {}
    totals: Dict[str, int] = {}
    days_missing = 0
    for sid, kind, api, _ in SPLIT_REGIONS + TWO_PUNJABS[:1]:
        s = t.series(kind, api, start, end_nominal, basis)
        upto = s[s["pk_day"] <= end_eff]
        series[sid] = _nullable(s[cnt].tolist())
        totals[sid] = int(upto[cnt].fillna(0).sum())
        days_missing = int((~upto["has_file"]).sum())
    grand = sum(totals[sid] for sid, *_ in SPLIT_REGIONS)
    classes: Optional[Dict[str, Dict[str, int]]] = None
    if t.has_basis("crop"):
        classes = {}
        for sid, kind, api, _ in SPLIT_REGIONS + TWO_PUNJABS[:1]:
            s = t.series(kind, api, start, end_nominal, "all")
            upto = s[(s["pk_day"] <= end_eff) & s["has_file"]]
            classes[sid] = {c: int(upto[f"n_{c}_hn"].sum()) for c in fc.CLASSES}
    return {"season": {"id": season, "year": year, "start": start.isoformat(), "end": end_nominal.isoformat(), "end_effective": end_eff.isoformat()},
            "basis": basis, "basis_label": BASES[basis],
            "classes": classes, "class_version": (store.manifest().get("classification") or {}).get("class_version") if classes else None,
            "class_labels": fc.CLASS_LABELS,
            "days": [_mmdd(start + timedelta(days=i)) for i in range((end_nominal - start).days + 1)],
            "series": series, "totals": totals, "shares": {sid: round(totals[sid] / grand, 2) if grand else None for sid, *_ in SPLIT_REGIONS},
            "labels": {sid: lab for sid, _, _, lab in SPLIT_REGIONS + TWO_PUNJABS[:1]}, "days_missing": days_missing,
            "note": "pakistan_punjab is a subset of pakistan (shown so the two Punjabs can be read side by side); shares are of the box total",
            "caveats": [fa.FIRE_DEFINITIONS["headline_count"], fa.FIRE_DEFINITIONS["what_burns"]]}


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
    no_pass_by_year: Dict[str, Dict[str, int]] = {}
    for k, rec in days.items():
        y = k[:4]
        for s in rec.get("sources") or []:
            sat_by_year.setdefault(y, set()).add(fr.satellite_name(s))
        rbs = rec.get("rows_by_satellite")
        if rbs is not None and rec.get("rows"):
            for key in ("n20", "snpp", "n21"):
                if rbs.get(key, 0) == 0 and (key != "n21" or y >= "2026") and (key != "snpp" or k < "2026-11-01"):
                    no_pass_by_year.setdefault(y, {}).setdefault(key, 0)
                    no_pass_by_year[y][key] += 1
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
    schema = int(m.get("schema_version") or 0)
    return {
        "store_built_at": m.get("built_at"), "store_schema_version": schema, "today_pkt": today.isoformat(),
        "seasons": {sid: {"key": key, "label": SEASON_LABELS[sid], "start": fa.SEASONS[key][0], "end": fa.SEASONS[key][1]} for sid, key in SEASON_IDS.items()},
        "season_window_note": fa.SEASON_WINDOW_NOTE,
        "current_season": next((sid for sid, key in SEASON_IDS.items() if key == cs), None),
        "reference_years": list(fa.REFERENCE_YEARS),
        "bases": BASES, "consistent_satellite": fr.SATELLITE_LABELS[fr.CONSISTENT_SATELLITE], "n20_basis_available": schema >= 2,
        "bases_available": [b for b in BASES if schema >= fa.BASIS_SCHEMA[b]],
        "classification": {**fc.describe(None), **(m.get("classification") or {}), "available": schema >= 3},
        "regions": [{"id": pid, "label": label, "kind": kind, "api": api} for pid, label, kind, api in REGION_PRESETS],
        "provinces": PROVINCES,
        "districts": sorted([{"name": n, "province": p} for n, p in idx.district_province.items()], key=lambda r: r["name"]),
        "archive": {"first_day": day_keys[0] if day_keys else None, "last_day": day_keys[-1] if day_keys else None, "gaps": gaps,
                    "suspect_days_by_year": suspect_by_year, "low_confidence_from": m.get("low_confidence_from"),
                    "pkt_from": m.get("pkt_from") or m.get("low_confidence_from"), "days_without_pass_by_year": no_pass_by_year},
        "satellites_by_year": {y: sorted(v) for y, v in sorted(sat_by_year.items())},
        "pass_times": {"day": "about 13:00 PKT", "night": "about 01:00 PKT"},
        "dedup_rule": m.get("dedup_rule"), "definitions": fa.FIRE_DEFINITIONS, "notes": NOTES,
    }


# ── the exportable regional report ───────────────────────────────────────────

EXPORT_REGIONS = [("pakistan", "country", "Pakistan", "Pakistan"), *TWO_PUNJABS, ("other", "country", "other in bbox", "Rest of the box")]


def export(season: str = "rice", year: Optional[int] = None, basis: str = "all", *, store: Optional[AggStore] = None,
           today: Optional[date] = None) -> Dict[str, Any]:
    """One season of daily series for the two Punjabs, Haryana, Pakistan and the rest of the box: detections,
    7-day mean, cumulative, gap flags, with the basis, roster, class version and store build in the header.
    `year` picks a past season (default: the latest); the rows are what the CSV export streams."""
    store = store or agg_store()
    today = today or fa.pkt_today()
    if season not in SEASON_IDS:
        return {"error": f"season must be one of {', '.join(SEASON_IDS)}"}
    t = region_table(store)
    basis = (basis or "all").strip().lower()
    err = _basis_error(basis, t)
    if err:
        return err
    start, end_nominal, end_eff, latest = season_bounds(season, today=today)
    y = int(year or latest)
    if y > latest or y < 2020:
        return {"error": f"year must be between 2020 and {latest}"}
    if y != latest:
        start, end_nominal = date(y, start.month, start.day), date(y, end_nominal.month, end_nominal.day)
        end_eff = end_nominal
    cnt, frpc = fa.COUNT_COL[basis], fa.FRP_COL[basis]
    m = store.manifest()
    series: Dict[str, pd.DataFrame] = {}
    for rid, kind, api, _ in EXPORT_REGIONS:
        sdf = t.series(kind, api, start, end_nominal, basis)
        sdf.loc[sdf["pk_day"] > end_eff, [*METRICS, "has_file"]] = [np.nan] * len(METRICS) + [False]
        sdf["r7"] = sdf[cnt].rolling(7, min_periods=R7_MIN_DAYS).mean()
        sdf.loc[sdf[cnt].isna(), "r7"] = np.nan
        sdf["cum"] = _cumulative(sdf[cnt])
        series[rid] = sdf
    days = series["pakistan"]["pk_day"].tolist()
    rows = []
    for i, d in enumerate(days):
        row: Dict[str, Any] = {"day": d.isoformat()}
        for rid, *_ in EXPORT_REGIONS:
            sdf = series[rid]
            obs = bool(sdf["has_file"].iloc[i])
            row[f"{rid}_detections"] = int(sdf[cnt].iloc[i]) if obs else None
            row[f"{rid}_r7"] = round(float(sdf["r7"].iloc[i]), 1) if obs and not np.isnan(sdf["r7"].iloc[i]) else None
            row[f"{rid}_cum"] = int(sdf["cum"].iloc[i]) if obs else None
            row[f"{rid}_frp_mw"] = round(float(sdf[frpc].iloc[i])) if obs else None
            row[f"{rid}_observed"] = obs
            if d > end_eff:
                row[f"{rid}_observed"] = None            # not yet: the season is in progress
        rows.append(row)
    sat_years = sorted({fr.satellite_name(src) for k, rec in m.get("days", {}).items() if k[:4] == str(y) for src in (rec.get("sources") or [])})
    header = {
        "season": {"id": season, "label": SEASON_LABELS[season], "year": y, "start": start.isoformat(), "end": end_nominal.isoformat(),
                   "end_effective": end_eff.isoformat(), "complete": today > end_nominal},
        "basis": basis, "basis_label": BASES[basis], "count_definition": fa.FIRE_DEFINITIONS["headline_count"],
        "regions": {rid: lab for rid, _, _, lab in EXPORT_REGIONS}, "pakistan_punjab_note": "pakistan_punjab is a subset of pakistan",
        "satellites_in_year": sat_years, "class_version": (m.get("classification") or {}).get("class_version") if basis in ("crop", "crop_n20") else None,
        "observed": "false = no file or no rows on this basis that day (a gap, not zero); null = the day has not happened yet",
        "r7": f"trailing 7-day mean over observed days, null when fewer than {R7_MIN_DAYS}", "cum": "running total over observed days",
        "store_built_at": m.get("built_at"), "store_schema_version": int(m.get("schema_version") or 0), "generated_for_pkt_day": today.isoformat(),
        "source": "NASA FIRMS VIIRS (NOAA-20, NOAA-21, Suomi NPP) via the Hawanama fire store; https://hawanama.org/fires",
        "caveats": [fa.FIRE_DEFINITIONS["headline_count"], fa.FIRE_DEFINITIONS["comparison_basis"], fa.FIRE_DEFINITIONS["what_burns"]],
    }
    return {"header": header, "columns": list(rows[0].keys()) if rows else [], "rows": rows}


def export_csv(doc: Dict[str, Any]) -> str:
    """The export as CSV: '#'-prefixed header lines, then the table."""
    import csv
    import io as _io
    h = doc["header"]
    buf = _io.StringIO()
    for k in ("season", "basis", "basis_label", "count_definition", "regions", "pakistan_punjab_note", "satellites_in_year", "class_version",
              "observed", "r7", "cum", "store_built_at", "store_schema_version", "generated_for_pkt_day", "source"):
        buf.write(f"# {k}: {json.dumps(h[k]) if not isinstance(h[k], str) else h[k]}\n")
    for c in h["caveats"]:
        buf.write(f"# caveat: {c}\n")
    w = csv.DictWriter(buf, fieldnames=doc["columns"], lineterminator="\n")
    w.writeheader()
    for r in doc["rows"]:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return buf.getvalue()


# ── observation-quality audit ────────────────────────────────────────────────

PEAK_MONTHS = (4, 5, 10, 11)
AUDIT_MIN_ROWS = 200          # a peak-month day with at least this many rows in the box is "busy": a satellite with 0 rows that day missed its passes


def audit(*, store: Optional[AggStore] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """Per year and satellite, from the manifest alone: files, day keys, products, missing passes on busy
    peak-month days, suspect days. Separates processing gaps and missing passes from a quiet season."""
    store = store or agg_store()
    today = today or fa.pkt_today()
    m = store.manifest()
    days = m.get("days", {})
    years: Dict[str, Dict[str, Any]] = {}
    for k, rec in sorted(days.items()):
        y = k[:4]
        d = date.fromisoformat(k)
        yr = years.setdefault(y, {"days_with_file": 0, "days_empty": 0, "day_basis": {"acq_pkt": 0, "acq_utc": 0}, "products": {},
                                  "peak_days": 0, "peak_days_busy": 0, "satellites": {}, "rows": 0, "clusters_hn": 0})
        rows = int(rec.get("rows") or 0)
        yr["days_with_file"] += 1
        yr["rows"] += rows
        yr["clusters_hn"] += int(rec.get("n_dedup_hn") or 0)
        if rows == 0:
            yr["days_empty"] += 1
        yr["day_basis"]["acq_pkt" if rec.get("format") == "pkt_v2" else "acq_utc"] += 1
        for src in rec.get("sources") or []:
            s_ = str(src)
            prod = "SP" if s_.endswith("_SP") else "NRT" if s_.endswith("_NRT") else "legacy"
            yr["products"][prod] = yr["products"].get(prod, 0) + 1
        peak = d.month in PEAK_MONTHS
        busy = peak and rows >= AUDIT_MIN_ROWS
        yr["peak_days"] += int(peak)
        yr["peak_days_busy"] += int(busy)
        rbs = rec.get("rows_by_satellite")
        if rbs is None:
            continue
        for key in ("snpp", "n20", "n21"):
            if key == "n21" and y < "2026":
                continue
            if key == "snpp" and k >= "2026-11-01":
                continue
            sat = yr["satellites"].setdefault(key, {"label": fr.SATELLITE_LABELS[key], "days_with_rows": 0, "rows": 0, "busy_days_missing": 0, "busy_days_missing_dates": []})
            n = int(rbs.get(key, 0))
            if n:
                sat["days_with_rows"] += 1
                sat["rows"] += n
            elif busy:
                sat["busy_days_missing"] += 1
                if len(sat["busy_days_missing_dates"]) < 12:
                    sat["busy_days_missing_dates"].append(k)
    sus_by_year: Dict[str, List[str]] = {}
    for s_ in m.get("suspect_days", []):
        sus_by_year.setdefault(str(s_.get("day", ""))[:4], []).append(s_["day"])
    for y, yr in years.items():
        yr["suspect_days"] = sus_by_year.get(y, [])
        for sat in yr["satellites"].values():
            sat["share_of_rows"] = round(sat["rows"] / yr["rows"], 2) if yr["rows"] else None
    return {
        "store_built_at": m.get("built_at"), "store_schema_version": int(m.get("schema_version") or 0), "today_pkt": today.isoformat(),
        "years": years,
        "method": {"busy_day": f"a peak-month day ({', '.join(str(x) for x in PEAK_MONTHS)}) with at least {AUDIT_MIN_ROWS} rows in the whole box",
                   "missing_pass": "a busy day on which a satellite that should have flown contributed no rows: a processing or delivery gap, not a quiet day",
                   "suspect_day": "the store's thin-day rule: a peak-month day under 10 % of the 2020–2023 median for the same calendar date ± 3 days (median ≥ 200)",
                   "products": "SP = standard processing (final), NRT = near real time, legacy = the pre-2026 archive without product names",
                   "day_basis": "acq_pkt = Pakistan day with pass times; acq_utc = UTC date without pass times",
                   "limits": "the audit sees what the archive holds: a satellite outage that also left no rows in FIRMS is counted as a missing pass only on busy days; "
                             "it cannot tell cloud or smoke obscuration from a quiet field, and it says nothing about fires lit between passes"},
    }


# ── the two-Punjab lines for the daily brief and the copilot ─────────────────

def brief_lines(*, store: Optional[AggStore] = None, today: Optional[date] = None) -> List[str]:
    """Two or three sentences on the two Punjabs for the season in progress; empty outside a season.
    Counts are all-satellite clusters; the year-on-year figures are NOAA-20 only."""
    store = store or agg_store()
    today = today or fa.pkt_today()
    cs = fa.current_season(today)
    sid = next((k for k, v in SEASON_IDS.items() if v == cs), None)
    if sid is None:
        return []
    out: List[str] = []
    parts: List[str] = []
    for rid, kind, api, label in TWO_PUNJABS:
        d = seasons(api if kind != "province" else "punjab", sid, "all", store=store, today=today)
        if "error" in d:
            continue
        h = d["headline"]
        cur = next((y for y in d["years"] if y["role"] == "current"), None)
        r7 = next((v for v in reversed(cur["r7"]) if v is not None), None) if cur else None
        piece = f"{label} {h['fires']:,} clusters season to date"
        if r7 is not None:
            piece += f" (7-day mean {r7:,.0f} a day)"
        c20 = h.get("comparison_n20")
        if c20 and c20.get("last_year") and c20["last_year"].get("pct_change") is not None:
            ly = c20["last_year"]
            piece += f"; NOAA-20 only {c20['fires']:,} vs {ly['fires']:,} on the same dates in {ly['year']} ({ly['pct_change']:+d} %)"
            if c20["reference"].get("rank_text"):
                piece += f", {c20['reference']['rank_text']}"
        last = next((y for y in d["years"] if y["role"] == "last"), None)
        if last and last.get("total") and cur and cur.get("total_to_date") is not None and not d["season"]["complete"]:
            piece += f"; cumulative so far = {cur['total_to_date'] / last['total']:.0%} of the whole {last['year']} season"
        if d["season"]["complete"] and cur and cur.get("timing") and cur["timing"].get("p50"):
            tm = cur["timing"]
            piece += f"; half of the season's detections by {_day_label(date(d['season']['year'], int(tm['p50'][:2]), int(tm['p50'][3:])))} (10 % by {tm['p10']}, 90 % by {tm['p90']})"
        parts.append(piece)
        if rid == "pakistan_punjab":
            w = h["window"]
            out.append(f"Two Punjabs, {SEASON_LABELS[sid].split(' (')[0].lower()} to date ({w['compared_dates'] or w['start'] + ' – ' + w['end']}, "
                       f"{w['days_with_data']} days observed): deduplicated VIIRS detection clusters, not verified fires.")
    if parts:
        out.append(" ".join(p + "." for p in parts))
        out.append("Year-on-year figures hold the satellite fixed (NOAA-20); a cumulative shortfall part-way through the season can still be a late season rather than a smaller one.")
    return out
