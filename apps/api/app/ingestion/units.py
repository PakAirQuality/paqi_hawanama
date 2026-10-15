"""
Per-provider measurement units.

Units are recorded only where the provider documents them. IQAir reports PM2.5
and PM10 concentrations in µg/m³; the units of its gas concentrations are not
stated clearly enough to assert, so they stay NULL rather than guessed (the
city path used to write 'ppb'/'ppm' for every row). Export routes read
readings.units_* and say 'unknown' when NULL — nothing downstream invents a unit.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

UGM3 = "µg/m³"

PROVIDER_UNITS: Dict[str, Dict[str, str]] = {
    "airvisual": {"pm25": UGM3, "pm10": UGM3},
    "punjab": {},          # endpoint units not attested
    "openaq": {},          # taken verbatim from each measurement's parameter.units instead
}

POLLUTANTS = ("pm25", "pm10", "o3", "no2", "so2", "co")


def units_for(provider: str, pollutant: str) -> Optional[str]:
    return PROVIDER_UNITS.get(provider, {}).get(pollutant)


def apply_units(row: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """Set units_<p> only where the row has a value for p; otherwise leave NULL."""
    for p in POLLUTANTS:
        row[f"units_{p}"] = units_for(provider, p) if row.get(p) is not None else None
    return row
