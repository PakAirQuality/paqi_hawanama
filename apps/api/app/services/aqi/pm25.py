"""
PM2.5 → US AQI, US EPA 2024 breakpoints (89 FR 16202, effective 6 May 2024).

Before this module there were three tables in the repo: utils/normalization.py
(correct), and bam_service.py / routers/punjab_epa.py whose top segment was
225.5–500.4 → 301–500 (a pre-2024/2024 hybrid) so 325.4 µg/m³ mapped to 373
instead of 500. Everything now calls pm25_to_aqi().

Semantics the EPA rule fixes and that callers must not re-invent:
  * concentration is truncated (not rounded) to 0.1 µg/m³ before lookup
  * the index is linearly interpolated within a segment and rounded to an integer
  * above 325.4 µg/m³ the rule extrapolates the last segment; whether a product
    caps at 500 is a display policy, so the caller chooses `above_500`
  * a single hourly concentration mapped through these breakpoints is an hourly
    sub-index, not the daily (24 h) or NowCast AQI; `averaging_basis` records
    what the caller fed in and is never inferred
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

DEFAULT_SCALE = "us_epa_2024"

# (conc_lo, conc_hi, aqi_lo, aqi_hi) in µg/m³ at 0.1 resolution
BREAKPOINTS: Dict[str, List[Tuple[float, float, int, int]]] = {
    "us_epa_2024": [
        (0.0, 9.0, 0, 50),
        (9.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 125.4, 151, 200),
        (125.5, 225.4, 201, 300),
        (225.5, 325.4, 301, 500),
    ],
}

CATEGORIES: List[Tuple[int, int, str]] = [
    (0, 50, "Good"),
    (51, 100, "Moderate"),
    (101, 150, "Unhealthy for Sensitive Groups"),
    (151, 200, "Unhealthy"),
    (201, 300, "Very Unhealthy"),
    (301, 500, "Hazardous"),
]
BEYOND_INDEX = "Beyond Index"
UNKNOWN = "Unknown"

ABOVE_500_POLICIES = ("extrapolate", "cap", "none")


@dataclass(frozen=True)
class AqiResult:
    value: Optional[int]            # None when the input is unusable (None/NaN/inf/negative) or policy 'none' above the table
    category: str
    scale: str
    truncated_conc: Optional[float]
    averaging_basis: str            # e.g. '1h_subindex', '24h', 'nowcast' — declared by the caller
    above_500: str                  # policy applied
    capped: bool                    # True when the true index exceeded 500 and was clamped
    extrapolated_value: Optional[int] = None   # the uncapped index when above 500, whatever the policy


def truncate_1dp(conc: float) -> float:
    """EPA truncation to one decimal place (floor, not round)."""
    return math.floor(conc * 10.0 + 1e-9) / 10.0


def _interp(c: float, lo: float, hi: float, ilo: int, ihi: int) -> int:
    return int(round((ihi - ilo) / (hi - lo) * (c - lo) + ilo))


def pm25_to_aqi(conc, *, scale: str = DEFAULT_SCALE, above_500: str = "extrapolate",
                averaging_basis: str = "1h_subindex") -> AqiResult:
    if scale not in BREAKPOINTS:
        raise ValueError(f"unknown AQI scale {scale!r}")
    if above_500 not in ABOVE_500_POLICIES:
        raise ValueError(f"unknown above_500 policy {above_500!r}")

    def _unusable() -> AqiResult:
        return AqiResult(None, UNKNOWN, scale, None, averaging_basis, above_500, False, None)

    if conc is None:
        return _unusable()
    try:
        c = float(conc)
    except (TypeError, ValueError):
        return _unusable()
    if math.isnan(c) or math.isinf(c) or c < 0:
        # Negative concentrations are quarantined upstream; never coerce them to AQI 0 here.
        return _unusable()

    c = truncate_1dp(c)
    table = BREAKPOINTS[scale]
    for lo, hi, ilo, ihi in table:
        if lo <= c <= hi:
            v = _interp(c, lo, hi, ilo, ihi)
            return AqiResult(v, category_for(v, scale), scale, c, averaging_basis, above_500, False, None)

    # Above the top breakpoint: extrapolate the last segment per the EPA rule.
    lo, hi, ilo, ihi = table[-1]
    extrapolated = _interp(c, lo, hi, ilo, ihi)
    if above_500 == "extrapolate":
        return AqiResult(extrapolated, category_for(extrapolated, scale), scale, c, averaging_basis, above_500, False, extrapolated)
    if above_500 == "cap":
        return AqiResult(500, category_for(500, scale), scale, c, averaging_basis, above_500, True, extrapolated)
    return AqiResult(None, BEYOND_INDEX, scale, c, averaging_basis, above_500, False, extrapolated)


def category_for(aqi: Optional[int], scale: str = DEFAULT_SCALE) -> str:
    if aqi is None:
        return UNKNOWN
    try:
        a = int(aqi)
    except (TypeError, ValueError):
        return UNKNOWN
    if a < 0:
        return UNKNOWN
    for lo, hi, name in CATEGORIES:
        if lo <= a <= hi:
            return name
    return BEYOND_INDEX


# ---------------------------------------------------------------------------
# Health categories ("bands"): the single classification every product uses.
#
# Keys are stable identifiers shared with the front-ends; labels are the EPA names;
# the PM2.5 upper bounds are the 2024 breakpoints (inclusive, after truncation to
# 0.1 µg/m³); colours are the palette the public map already uses
# (apps/web-next/src/components/map/config/aqiStyles.ts). Nothing else in the repo
# may carry its own thresholds: call classify()/band_key() instead.
# ---------------------------------------------------------------------------

BAND_KEYS = ["good", "moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous"]

BANDS: List[dict] = [
    {"key": "good", "label": "Good", "short_label": "Good", "pm25_max": 9.0, "aqi_min": 0, "aqi_max": 50,
     "color": "#6ecc39", "text_color": "#1f2937",
     "description": "Air quality is satisfactory and poses little or no risk."},
    {"key": "moderate", "label": "Moderate", "short_label": "Moderate", "pm25_max": 35.4, "aqi_min": 51, "aqi_max": 100,
     "color": "#f0c20c", "text_color": "#1f2937",
     "description": "Acceptable; unusually sensitive people should consider limiting prolonged exertion."},
    {"key": "unhealthy_sensitive", "label": "Unhealthy for Sensitive Groups", "short_label": "USG", "pm25_max": 55.4,
     "aqi_min": 101, "aqi_max": 150, "color": "#f18017", "text_color": "#ffffff",
     "description": "Members of sensitive groups may experience health effects."},
    {"key": "unhealthy", "label": "Unhealthy", "short_label": "Unhealthy", "pm25_max": 125.4, "aqi_min": 151, "aqi_max": 200,
     "color": "#ef7855", "text_color": "#ffffff",
     "description": "Everyone may begin to experience health effects."},
    {"key": "very_unhealthy", "label": "Very Unhealthy", "short_label": "V. Unhealthy", "pm25_max": 225.4,
     "aqi_min": 201, "aqi_max": 300, "color": "#a070b5", "text_color": "#ffffff",
     "description": "Health alert: everyone may experience more serious health effects."},
    {"key": "hazardous", "label": "Hazardous", "short_label": "Hazardous", "pm25_max": None, "aqi_min": 301, "aqi_max": 500,
     "color": "#991b1b", "text_color": "#ffffff",
     "description": "Emergency conditions: the entire population is likely to be affected."},
]

BAND_ORDER: Dict[str, int] = {b["key"]: i + 1 for i, b in enumerate(BANDS)}
BAND_ORDER["unknown"] = 0
UNKNOWN_BAND = {"key": "unknown", "label": "Unknown", "short_label": "—", "pm25_max": None, "aqi_min": None,
                "aqi_max": None, "color": "#6b7280", "text_color": "#ffffff", "description": "No usable reading."}

# Old house keys still present in stored forecast files and older clients.
_LEGACY_BAND_KEYS = {"severe": "hazardous", "usg": "unhealthy_sensitive", "unhealthy_for_sensitive_groups": "unhealthy_sensitive"}


def band_for_aqi(aqi: Optional[int]) -> str:
    """Band key for a US AQI value ('unknown' when unusable)."""
    if aqi is None:
        return "unknown"
    try:
        a = int(aqi)
    except (TypeError, ValueError):
        return "unknown"
    if a < 0:
        return "unknown"
    for b in BANDS:
        if a <= b["aqi_max"]:
            return b["key"]
    return "hazardous"  # beyond index


def band_key(pm25) -> str:
    """Band key for a PM2.5 concentration in µg/m³ (truncated to 0.1 per EPA)."""
    return band_for_aqi(pm25_to_aqi(pm25).value)


def classify(pm25) -> dict:
    """Full classification of a PM2.5 concentration: band, label, AQI value and colours."""
    r = pm25_to_aqi(pm25)
    key = band_for_aqi(r.value)
    band = UNKNOWN_BAND if key == "unknown" else next(b for b in BANDS if b["key"] == key)
    return {**band, "aqi": r.value, "pm25": r.truncated_conc}


def normalize_band(key: Optional[str]) -> str:
    """Map any legacy or alias band key onto the canonical set."""
    if not key:
        return "unknown"
    k = str(key).strip().lower()
    k = _LEGACY_BAND_KEYS.get(k, k)
    return k if k in BAND_ORDER else "unknown"


def categories_payload() -> dict:
    """What /meta/aqi-categories serves: one table for every client."""
    return {
        "scale": DEFAULT_SCALE,
        "pollutant": "pm25",
        "units": "µg/m³",
        "note": "US EPA 2024 PM2.5 breakpoints; concentrations truncated to 0.1 µg/m³; an hourly value gives an hourly sub-index, not the 24 h AQI.",
        "categories": [dict(b) for b in BANDS],
    }


def aqi_provenance(result: AqiResult, version: int = 1) -> dict:
    """Small dict for readings.raw describing how a stored aqi_us was derived."""
    return {
        "v": version,
        "scale": result.scale,
        "basis": result.averaging_basis,
        "above_500": result.above_500,
        "capped": result.capped,
        "extrapolated": result.extrapolated_value,
        "conc_trunc": result.truncated_conc,
    }
