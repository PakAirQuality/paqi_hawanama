"""US-EPA AQI sub-indices for the pollutants other than PM2.5 (PM2.5 has its own 2024 table in pm25.py).

Breakpoints as the Punjab EPA router has used them since 2025: PM10 24 h, O3 8 h (ppm), CO 8 h (ppm),
NO2 1 h (ppb), SO2 1 h (ppb). The readings table stores gases in whatever unit the provider sent
(``units_*`` columns; NULL when the provider did not attest one), so a sub-index is only computed from
an attested unit, converting µg/m³ and mg/m³ to the EPA scales at 25 °C and 1 atm.
"""

from __future__ import annotations

from math import floor
from typing import Any, Dict, Optional

from .pm25 import category_for

PM10_BPTS = [  # µg/m³
    (0, 54,    0, 50),
    (55, 154,  51, 100),
    (155, 254, 101, 150),
    (255, 354, 151, 200),
    (355, 424, 201, 300),
    (425, 604, 301, 500),
]
O3_8H_BPTS = [  # ppm
    (0.000, 0.054,   0, 50),
    (0.055, 0.070,  51, 100),
    (0.071, 0.085, 101, 150),
    (0.086, 0.105, 151, 200),
    (0.106, 0.200, 201, 300),
]
CO_8H_BPTS = [  # ppm
    (0.0, 4.4,     0, 50),
    (4.5, 9.4,    51, 100),
    (9.5, 12.4,  101, 150),
    (12.5, 15.4, 151, 200),
    (15.5, 30.4, 201, 300),
    (30.5, 50.4, 301, 500),
]
NO2_1H_BPTS = [  # ppb
    (0, 53,       0, 50),
    (54, 100,    51, 100),
    (101, 360,  101, 150),
    (361, 649,  151, 200),
    (650, 1249, 201, 300),
    (1250, 2049, 301, 500),
]
SO2_1H_BPTS = [  # ppb
    (0, 35,      0, 50),
    (36, 75,    51, 100),
    (76, 185,  101, 150),
    (186, 304, 151, 200),
    (305, 604, 201, 300),
    (605, 1004, 301, 500),
]

# molecular weights for µg/m³ <-> ppb at 25 °C, 1 atm (molar volume 24.45 L)
MOLAR_VOLUME_L = 24.45
MW = {"no2": 46.0055, "so2": 64.066, "o3": 47.998, "co": 28.010}

# pollutant -> (table, EPA unit, decimals of EPA truncation, averaging basis)
SCALES: Dict[str, Dict[str, Any]] = {
    "pm10": {"table": PM10_BPTS, "unit": "µg/m³", "decimals": 0, "basis": "24-hour table applied to the mean"},
    "o3": {"table": O3_8H_BPTS, "unit": "ppm", "decimals": 3, "basis": "8-hour table applied to the mean"},
    "co": {"table": CO_8H_BPTS, "unit": "ppm", "decimals": 1, "basis": "8-hour table applied to the mean"},
    "no2": {"table": NO2_1H_BPTS, "unit": "ppb", "decimals": 0, "basis": "1-hour table applied to the mean"},
    "so2": {"table": SO2_1H_BPTS, "unit": "ppb", "decimals": 0, "basis": "1-hour table applied to the mean"},
}
POLLUTANT_LABELS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2", "o3": "O3", "co": "CO"}


def truncate(x: Optional[float], decimals: int) -> Optional[float]:
    """EPA truncation (not rounding) to the table's precision."""
    if x is None:
        return None
    if decimals == 0:
        return float(int(x))
    factor = 10 ** decimals
    return floor(x * factor) / factor


def interp_aqi(c: Optional[float], table) -> Optional[int]:
    """Piecewise-linear AQI for a concentration already in the table's unit and precision; None outside the table."""
    if c is None:
        return None
    for lo, hi, ilo, ihi in table:
        if lo <= c <= hi:
            return round((ihi - ilo) / (hi - lo) * (c - lo) + ilo)
    return None


def _norm_unit(unit: Optional[str]) -> Optional[str]:
    if not unit:
        return None
    u = unit.strip().lower().replace("µ", "u").replace("μ", "u")
    return {"ug/m3": "ug/m³", "ug/m³": "ug/m³", "mg/m3": "mg/m³", "mg/m³": "mg/m³", "ppb": "ppb", "ppm": "ppm"}.get(u)


def to_epa_units(pollutant: str, value: Optional[float], unit: Optional[str]) -> Optional[float]:
    """The value on the pollutant's EPA scale, or None when the unit is missing or unknown."""
    if value is None or pollutant not in SCALES:
        return None
    u = _norm_unit(unit)
    target = SCALES[pollutant]["unit"]
    if u is None:
        return None
    if pollutant == "pm10":
        return float(value) if u == "ug/m³" else None
    if u == target:
        return float(value)
    mw = MW[pollutant]
    if u == "ug/m³":            # µg/m³ -> ppb, then ppb -> ppm for the ppm tables
        ppb = float(value) * MOLAR_VOLUME_L / mw
        return ppb / 1000.0 if target == "ppm" else ppb
    if u == "mg/m³":
        ppm = float(value) * MOLAR_VOLUME_L / mw
        return ppm if target == "ppm" else ppm * 1000.0
    if u == "ppb" and target == "ppm":
        return float(value) / 1000.0
    if u == "ppm" and target == "ppb":
        return float(value) * 1000.0
    return None


def sub_index(pollutant: str, value: Optional[float], unit: Optional[str]) -> Dict[str, Any]:
    """{"aqi", "category", "scale_value", "scale_unit", "basis"} or a "note" explaining why there is none."""
    if pollutant not in SCALES:
        return {"aqi": None, "note": f"no US-EPA sub-index table for {pollutant}"}
    if value is None:
        return {"aqi": None, "note": "no value"}
    scaled = to_epa_units(pollutant, value, unit)
    if scaled is None:
        return {"aqi": None, "note": "the provider did not attest the unit, so no sub-index is computed; the value is as reported"}
    s = SCALES[pollutant]
    c = truncate(scaled, s["decimals"])
    aqi = interp_aqi(c, s["table"])
    if aqi is None:
        return {"aqi": None, "scale_value": c, "scale_unit": s["unit"], "note": "above the top of the US-EPA table"}
    return {"aqi": int(aqi), "category": category_for(int(aqi)), "scale_value": c, "scale_unit": s["unit"], "basis": s["basis"]}
