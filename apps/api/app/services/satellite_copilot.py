"""What the copilot says about satellite columns: window summaries with anomalies and the adjudicated findings.

Pure functions over the satellite store (``satellite_series.SatStore``) and the findings json exported
from air_copilot's atminvest records, so the tools in ``copilot/tools.py`` stay thin and the wording
rules are testable without a database or a bucket.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app.services import satellite_regions as regions
from app.services.satellite_series import CAVEATS, DEFINITIONS, PRODUCTS, SatStore

PRODUCT_ALIASES = {
    "no2": "no2", "nitrogen dioxide": "no2", "co": "co", "carbon monoxide": "co", "so2": "so2", "sulphur dioxide": "so2",
    "sulfur dioxide": "so2", "o3": "o3", "ozone": "o3", "hcho": "hcho", "formaldehyde": "hcho", "aai": "aai",
    "aerosol index": "aai", "uv aerosol index": "aai", "absorbing aerosol": "aai", "aod": "aod550", "aod550": "aod550",
    "aerosol optical depth": "aod550", "aod470": "aod470", "all": "all", "": "all",
}
DEFAULT_PRODUCTS = ["no2", "co", "so2", "hcho", "aai", "aod550"]
PRODUCT_SOURCES = {
    "tropomi": "Sentinel-5P TROPOMI OFFL L3 (Google Earth Engine COPERNICUS/S5P/OFFL/L3_*), daily means, exact zeros masked as gaps",
    "maiac": "MODIS MAIAC MCD19A2.061 granules under the strict QA (clear, land, normal adjacency, best AOD QA), Terra and Aqua",
}


def parse_products(text: str) -> List[str]:
    """'NO2, ozone' -> ['no2', 'o3']; empty -> the default set; unknown words are dropped."""
    if not text or not text.strip():
        return list(DEFAULT_PRODUCTS)
    out: List[str] = []
    for tok in re.split(r"[,;/]+|\band\b", text.lower()):
        key = PRODUCT_ALIASES.get(tok.strip())
        if key == "all":
            return list(PRODUCTS)
        if key and key not in out:
            out.append(key)
    return out or list(DEFAULT_PRODUCTS)


def parse_day(text: str, *, end: bool = False) -> Optional[date]:
    """YYYY-MM-DD, YYYY-MM or YYYY; None when empty; ValueError when malformed."""
    s = (text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}", s):
        return date(int(s), 12, 31) if end else date(int(s), 1, 1)
    if re.fullmatch(r"\d{4}-\d{2}", s):
        y, m = int(s[:4]), int(s[5:7])
        if end:
            nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
            return nxt - timedelta(days=1)
        return date(y, m, 1)
    return date.fromisoformat(s)


def available_range(store: SatStore) -> Dict[str, Any]:
    prods = (store.manifest().get("products") or {})
    firsts = [v.get("first_day") for v in prods.values() if v.get("first_day")]
    lasts = [v.get("last_day") for v in prods.values() if v.get("last_day")]
    return {"first_day": min(firsts) if firsts else None, "last_day": max(lasts) if lasts else None,
            "per_product": {p: {"first_day": v.get("first_day"), "last_day": v.get("last_day"), "pending": v.get("pending") or []}
                            for p, v in prods.items()}}


def _year_shift(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                       # 29 February
        return d.replace(year=d.year - years, day=28)


def columns_summary(store: SatStore, *, place: str, start: Optional[date], end: Optional[date], products: Iterable[str],
                    compare_place: str = "", compare_years: int = 0, today: Optional[date] = None) -> Dict[str, Any]:
    """Window means, coverage and anomalies per product for one region; optional naive comparison with another region
    or the same window in earlier years."""
    region = regions.resolve_place(place) if place else "pk_domain"
    if region is None:
        return {"message": f"I have no satellite region for '{place}'. Known: Pakistan, its provinces, Lahore, Karachi, "
                           "Islamabad/Rawalpindi, Peshawar, Faisalabad, Multan, Quetta, Delhi, Indian Punjab/Haryana, "
                           "eastern Afghanistan, Thar/Rajasthan, the Makran/Sindh coast."}
    rng = available_range(store)
    today = today or datetime.utcnow().date()
    end = end or (date.fromisoformat(rng["last_day"]) if rng["last_day"] else today - timedelta(days=1))
    start = start or (end - timedelta(days=13))
    if start > end:
        return {"message": f"Start {start} is after end {end}."}
    if rng["first_day"] and end < date.fromisoformat(rng["first_day"]):
        return {"message": f"The satellite archive starts on {rng['first_day']}; nothing before that."}
    out: Dict[str, Any] = {
        "place": place or "Pakistan", "region": {"id": region, "label": regions.label(region), "kind": regions.kind_of(region)},
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1},
        "archive": {"first_day": rng["first_day"], "last_day": rng["last_day"]},
        "products": {},
    }
    for p in products:
        if p not in PRODUCTS:
            continue
        w = store.window(p, region, start, end)
        entry = {k: w[k] for k in ("label", "units", "days_with_data", "days_assessable", "mean", "coverage_mean",
                                   "z_mean", "percent_of_normal", "last_day")}
        entry["mean"] = _fmt(w["mean"])
        entry["coverage_mean"] = round(w["coverage_mean"], 2)
        entry["z_mean"] = round(w["z_mean"], 2) if w["z_mean"] is not None else None
        entry["assessable"] = w["days_assessable"] > 0
        if w["days_assessable"] == 0:
            entry["note"] = ("no assessable day: coverage below 0.3 throughout (cloud or no overpass)" if w["days_with_data"]
                             else "no data in this window" + (f"; the last day with data is {rng['per_product'].get(p, {}).get('last_day')}"
                                                              if rng["per_product"].get(p, {}).get("last_day") else ""))
        pend = rng["per_product"].get(p, {}).get("pending") or []
        if pend:
            entry["pending_days"] = pend[-5:]
        if compare_years:
            yrs = []
            for k in range(1, compare_years + 1):
                s2, e2 = _year_shift(start, k), _year_shift(end, k)
                w2 = store.window(p, region, s2, e2)
                yrs.append({"start": s2.isoformat(), "end": e2.isoformat(), "mean": _fmt(w2["mean"]), "days_assessable": w2["days_assessable"],
                            "ratio": (round(w["mean"] / w2["mean"], 2) if w["mean"] and w2["mean"] else None)})
            entry["same_window_earlier_years"] = yrs
        if compare_place:
            r2 = regions.resolve_place(compare_place)
            if r2 is None:
                entry["compare"] = {"message": f"no satellite region for '{compare_place}'"}
            else:
                w2 = store.window(p, r2, start, end)
                entry["compare"] = {"region": {"id": r2, "label": regions.label(r2)}, "mean": _fmt(w2["mean"]),
                                    "days_assessable": w2["days_assessable"], "coverage_mean": round(w2["coverage_mean"], 2),
                                    "ratio": (round(w["mean"] / w2["mean"], 2) if w["mean"] and w2["mean"] else None),
                                    "note": "a naive ratio of window means, not sampling-controlled"}
        out["products"][p] = entry
    if not out["products"]:
        out["message"] = "No known product requested. Products: NO2, CO, SO2, O3, HCHO, aerosol index (AAI), AOD."
    out["definitions"] = {k: DEFINITIONS[k] for k in ("column", "aai", "aod", "coverage", "anomaly", "latency")}
    out["caveats"] = list(CAVEATS)
    out["sources"] = PRODUCT_SOURCES
    return out


def _fmt(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return float(f"{v:.4g}")


# ── adjudicated findings ───────────────────────────────────────────────────────

VERDICT_ORDER = {"supported": 0, "not_supported": 1, "conflicting": 2, "unresolved": 3, "not_assessable": 4}
SETTLED = ("supported", "not_supported")
CLAIM_ALIASES = {
    "column": "column_enhancement", "gas": "column_enhancement", "aod": "aerosol_optical_enhancement",
    "aerosol": "aerosol_optical_enhancement", "smoke": "smoke_transport_consistent", "transport": "transport_from_sector",
    "contrast": "condition_contrast", "comparison": "condition_contrast", "equivalence": "contrast_equivalence",
    "sampling": "sampling_dependent", "episode": "pm_episode", "stagnation": "met_stagnation", "ventilation": "ventilation_absolute",
    "fire": "fire_connectivity", "absorbing": "absorbing_aerosol", "type": "aerosol_type_indication",
}
_CITY_WORDS = {
    "lahore": ("lahore",), "karachi": ("karachi",), "isb_rwp": ("isb_rwp", "islamabad", "rawalpindi"), "peshawar": ("peshawar",),
    "faisalabad": ("faisalabad",), "multan": ("multan",), "quetta": ("quetta",), "delhi": ("delhi",),
}


def _place_words(place: str) -> Optional[tuple]:
    rid = regions.resolve_place(place) if place else None
    if rid and rid.startswith("city:"):
        return _CITY_WORDS.get(rid.split(":")[1], (rid.split(":")[1],))
    if rid:
        return (rid.split(":")[-1],)
    s = re.sub(r"[^a-z0-9]+", " ", (place or "").lower()).strip()
    return (s,) if s else None


def _span_days(window) -> float:
    if not window or len(window) < 2:
        return float("inf")
    try:
        return (date.fromisoformat(str(window[1])[:10]) - date.fromisoformat(str(window[0])[:10])).days
    except ValueError:
        return float("inf")


def findings_for(findings: List[Dict[str, Any]], *, place: str = "", start: Optional[date] = None, end: Optional[date] = None,
                 claim_types: str = "", limit: int = 40) -> Dict[str, Any]:
    """The adjudicated findings that match a place and overlap a period: settled first, episodes before multi-year contrasts."""
    words = _place_words(place) if place else None
    wanted = set()
    for tok in re.split(r"[,; ]+", (claim_types or "").lower()):
        if tok:
            wanted.add(CLAIM_ALIASES.get(tok, tok))
    picked = []
    for f in findings:
        if wanted and f.get("claim_type") not in wanted:
            continue
        hay = f"{f.get('region') or ''} {f.get('statement') or ''}".lower()
        if words and not any(w in hay for w in words):
            continue
        w = f.get("window") or []
        if w and (start or end):
            w0, w1 = str(w[0])[:10], str(w[1])[:10]
            if (end and w0 > end.isoformat()) or (start and w1 < start.isoformat()):
                continue
        picked.append(f)
    picked.sort(key=lambda f: (_span_days(f.get("window")), str((f.get("window") or [""])[0]), VERDICT_ORDER.get(f.get("verdict"), 5)))
    picked = picked[:limit]
    settled = [f for f in picked if f.get("verdict") in SETTLED]
    open_ = [f for f in picked if f.get("verdict") not in SETTLED]
    return {
        "place": place or "any", "n_findings": len(picked), "n_settled": len(settled), "n_open": len(open_),
        "window": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
        "settled": [_brief(f) for f in settled], "open": [_brief(f) for f in open_],
        "wording": {
            "verdicts": {"supported": "supported by the evidence", "not_supported": "not supported by the evidence",
                         "conflicting": "the evidence conflicts", "unresolved": "cannot be settled with the evidence available",
                         "not_assessable": "cannot be assessed: the needed evidence is missing"},
            "rule": "each finding answers one question; verdicts follow fixed rules from the cited evidence; "
                    "these are observational findings: they describe what the data show, not how much any source contributed",
        },
    }


def _brief(f: Dict[str, Any]) -> Dict[str, Any]:
    flags = []
    if f.get("threshold_sensitive"):
        flags.append("depends on the chosen thresholds")
    if f.get("method_sensitive"):
        flags.append("depends on the adjustment method")
    if f.get("processing_epoch"):
        flags.append(f"satellite processing {f['processing_epoch']}")
    q = [{"name": x.get("name"), "value": x.get("value"), "units": x.get("units"), "coverage": x.get("coverage")}
         for x in (f.get("quantities") or [])[:4]]
    return {"claim_type": f.get("claim_type"), "question": f.get("question"), "verdict": f.get("verdict"),
            "statement": f.get("statement"), "region": f.get("region"), "window": f.get("window"),
            "coverage": f.get("coverage"), "flags": flags, "quantities": q, "record_id": f.get("record_id")}
