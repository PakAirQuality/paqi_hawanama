"""
Loop exclusion and cross-platform alias *candidates* for OpenAQ locations.

A location whose provider or owner is us (PAQI / Hawanama) is our own data seen
through OpenAQ: it is marked origin='hawanama_loop' and never fetched. Nearby
stations from other providers are reported as candidates with evidence only;
nothing is merged and no coverage changes until a person promotes a candidate
to identity.aliases (see db_schema/station_metadata.md). The same physical
sensor reached through two platforms is one device, not a calibration pair.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, Iterable, List, Optional

from app.services.ingestion.openaq.models import Location

PROVIDER_HINTS: Dict[str, List[str]] = {
    "punjab": ["epa punjab", "punjab environmental", "epd punjab", "environment protection department"],
    "bam": ["sfl"],
    "airvisual": ["iqair", "airvisual"],
}


def _names(loc: Location) -> List[str]:
    out = []
    for ref in (loc.provider, loc.owner):
        if ref and ref.name:
            out.append(ref.name.lower())
    return out


def is_self_loop(loc: Location, self_names: Iterable[str]) -> bool:
    needles = [n.strip().lower() for n in self_names if n and n.strip()]
    return any(needle in name for name in _names(loc) for needle in needles)


def name_similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio(), 3)


def provider_hint_match(loc: Location, provider_code: str) -> bool:
    hints = PROVIDER_HINTS.get(provider_code, [])
    return any(h in name for name in _names(loc) for h in hints)


def compute_alias_candidates(loc: Location, nearby: Iterable[Dict[str, Any]], *, evaluated_at: str) -> List[Dict[str, Any]]:
    """
    nearby: [{station_id, provider_code, name, distance_m}] from non-openaq stations within the radius.
    Returns evidence-bearing candidates, never a decision.
    """
    out = []
    for n in nearby:
        out.append({
            "station_id": str(n["station_id"]).strip(),
            "provider_code": n.get("provider_code"),
            "distance_m": round(float(n.get("distance_m") or 0.0), 1),
            "name_similarity": name_similarity(loc.name, n.get("name")),
            "provider_hint_match": provider_hint_match(loc, n.get("provider_code") or ""),
            "our_name": n.get("name"), "their_name": loc.name,
            "their_provider": loc.provider.name if loc.provider else None,
            "their_owner": loc.owner.name if loc.owner else None,
            "evaluated_at": evaluated_at, "reviewed": False,
        })
    out.sort(key=lambda c: (c["distance_m"], -c["name_similarity"]))
    return out
