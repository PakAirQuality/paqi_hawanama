"""
Station identity helpers (stations.metadata_json conventions).

The legacy station_id is sha1(country|state|city|name|lat|lon)[:16], so a
rename or a coordinate correction computes a *different* id. Nothing may
create a second row for the same physical device: discovery looks the station
up by its provider-native id first and keeps the legacy station_id, recording
the change under metadata_json.identity.history.

metadata_json layout (see db_schema/station_metadata.md):
  identity:
    native_ids: [{provider, native_id, since, confidence, evidence}]
    aliases:    [{station_id, provider, relation: same_device|same_site, confidence,
                  evidence, reviewed, reviewed_by, reviewed_at}]   # written by humans/review tooling only
    history:    [{at, run_id, event, from, to, computed_station_id}]
  hardware:     {manufacturer, model, confidence: attested|inferred|unknown, evidence}  # absent = unknown
  export:       {openaq: bool, network, since, set_by}            # explicit export membership

Discovery owns only the keys in DISCOVERY_OWNED_KEYS plus identity.native_ids /
identity.history; everything else (site_type, export, hardware, aliases, ...)
is curated and must survive every discovery run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DISCOVERY_OWNED_KEYS = frozenset({
    "iqair_station_name", "iqair_city", "iqair_state", "iqair_country", "location_type",
    "data_source", "last_updated_utc", "discovery_method",
})
HISTORY_MAX = 50


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def as_dict(metadata: Any) -> Dict[str, Any]:
    """metadata_json may arrive as dict, JSON string or None depending on the driver path."""
    if metadata is None:
        return {}
    if isinstance(metadata, str):
        try:
            v = json.loads(metadata)
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def native_id_entry(provider: str, native_id: str, *, since: Optional[str] = None,
                    confidence: str = "high", evidence: str = "discovery") -> Dict[str, Any]:
    return {"provider": provider, "native_id": str(native_id), "since": since or now_iso(),
            "confidence": confidence, "evidence": evidence}


def ensure_identity(metadata: Dict[str, Any], provider: str, native_id: Optional[str],
                    *, since: Optional[str] = None, evidence: str = "discovery") -> Dict[str, Any]:
    """Guarantee identity.{native_ids,aliases,history} exist and that (provider, native_id) is listed once."""
    md = dict(metadata)
    ident = dict(md.get("identity") or {})
    native_ids: List[Dict[str, Any]] = list(ident.get("native_ids") or [])
    if native_id and not any(n.get("provider") == provider and n.get("native_id") == str(native_id) for n in native_ids):
        native_ids.append(native_id_entry(provider, native_id, since=since, evidence=evidence))
    ident["native_ids"] = native_ids
    ident.setdefault("aliases", [])
    ident.setdefault("history", [])
    md["identity"] = ident
    return md


def append_identity_history(metadata: Dict[str, Any], event: Dict[str, Any], max_len: int = HISTORY_MAX) -> Dict[str, Any]:
    md = ensure_identity(metadata, event.get("provider", ""), None)
    hist = list(md["identity"].get("history") or [])
    hist.append(event)
    md["identity"]["history"] = hist[-max_len:]
    return md


def merge_discovery_metadata(existing: Optional[Dict[str, Any]], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """
    existing ∪ incoming, where incoming may only set discovery-owned keys and
    add identity.native_ids. Curated keys (export, hardware, site_type, aliases,
    history, ...) are kept from `existing` untouched.
    """
    out = as_dict(existing)
    for k, v in (incoming or {}).items():
        if k in DISCOVERY_OWNED_KEYS:
            out[k] = v
    inc_ident = (incoming or {}).get("identity") or {}
    for n in inc_ident.get("native_ids") or []:
        out = ensure_identity(out, n.get("provider", ""), n.get("native_id"), since=n.get("since"),
                              evidence=n.get("evidence", "discovery"))
    return out


def hardware_label(metadata: Any) -> str:
    """Evidence-backed hardware string for exports; 'unknown' unless attested or inferred with a model."""
    hw = as_dict(metadata).get("hardware") or {}
    if not isinstance(hw, dict):
        return "unknown"
    conf = (hw.get("confidence") or "unknown").lower()
    if conf == "unknown":
        return "unknown"
    parts = [p for p in (hw.get("manufacturer"), hw.get("model")) if p]
    return " ".join(parts) if parts else "unknown"
