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
