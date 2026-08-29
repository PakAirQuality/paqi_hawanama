"""
South Asia region configuration for IQAir multi-country ingestion.

Centralizes the list of target countries and per-country state alias maps
so that station_discovery, data_ingestion, and city_ingest all share a
single source of truth.

NOTE: Punjab EPA integration is Pakistan-only and is NOT affected by this module.
"""

import os
from typing import Dict, List

# ---------------------------------------------------------------------------
# Target countries – override via IQAIR_COUNTRIES env var (comma-separated).
# Default: all South Asian countries with meaningful IQAir coverage.
# ---------------------------------------------------------------------------
DEFAULT_IQAIR_COUNTRIES: List[str] = [
    "Pakistan",
    "India",
    "Bangladesh",
    "Nepal",
    "Sri Lanka",
]

def get_iqair_countries() -> List[str]:
    """Return the list of countries to ingest from IQAir.

    Reads from IQAIR_COUNTRIES env var (comma-separated) if set,
    otherwise falls back to DEFAULT_IQAIR_COUNTRIES.
    """
    raw = os.getenv("IQAIR_COUNTRIES", "").strip()
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return list(DEFAULT_IQAIR_COUNTRIES)


# ---------------------------------------------------------------------------
# Per-country state alias maps.
#
# IQAir's /states endpoint sometimes returns names that differ from what
# /cities or /station endpoints expect.  These aliases let us retry with
# alternate names when the first attempt fails.
# ---------------------------------------------------------------------------
STATE_ALIAS_MAP: Dict[str, Dict[str, List[str]]] = {
    "Pakistan": {
        "Islamabad": [
            "Islamabad Capital Territory",
            "Islamabad Federal Capital Territory",
        ],
        "Azad Kashmir": ["Azad Jammu and Kashmir"],
        "Khyber Pakhtunkhwa": ["North-West Frontier Province", "NWFP"],
        "FATA": [],  # legacy; no /cities support
    },
    "India": {
        # Union Territories that IQAir sometimes labels differently
        "Delhi": ["New Delhi", "NCT of Delhi"],
        "Jammu and Kashmir": ["Jammu & Kashmir"],
        "Andaman and Nicobar Islands": ["Andaman & Nicobar Islands", "A&N Islands"],
        "Dadra and Nagar Haveli and Daman and Diu": [
            "Dadra & Nagar Haveli",
            "Daman & Diu",
            "Dadra and Nagar Haveli",
        ],
    },
    "Bangladesh": {
        # Divisions – naming is generally consistent, but keep the map for safety
        "Chittagong": ["Chattogram"],
    },
    "Nepal": {
        # Province names changed in 2023 constitution amendments
        "Bagmati": ["Bagmati Province"],
        "Lumbini": ["Lumbini Province"],
    },
    "Sri Lanka": {
        # Generally consistent; placeholder for future fixes
    },
}


def get_state_aliases(country: str, state: str) -> List[str]:
    """Return [state, alias1, alias2, ...] for the given country+state.

    The original state name is always first so callers try it before aliases.
    """
    if not state:
        return []
    base = [state]
    country_map = STATE_ALIAS_MAP.get(country, {})
    extras = country_map.get(state, [])
    # unique while preserving order
    seen, out = set(), []
    for v in base + extras:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
