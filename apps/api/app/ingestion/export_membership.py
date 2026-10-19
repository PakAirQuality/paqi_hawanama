"""
Export membership, hardware/unit labelling and keyset pagination shared by the
OpenAQ export (routers/openaq_network.py) and the partner API (routers/public.py).

Membership used to be `providers.display_name = 'Airvisual/PAQI'`: a display
string that discovery could (and once did) rewrite, and which no code sets.
Membership is now explicit per station in stations.metadata_json.export.openaq
(set by db_schema/oneoff/2026-10_export_membership.sql). Anything that
originated from OpenAQ — provider code 'openaq', providers.metadata.origin or
stations.metadata_json.origin = 'openaq' — is excluded unconditionally so no
imported OpenAQ data is ever exported back to OpenAQ.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Tuple

from fastapi import HTTPException

from app.ingestion.identity import hardware_label as _hardware_label

# Requires aliases: s = stations, p = providers.
MEMBERSHIP_WHERE = """
      (s.metadata_json->'export'->>'openaq')::boolean IS TRUE
  AND p.code <> 'openaq'
  AND COALESCE(p.metadata->>'origin', '') <> 'openaq'
  AND COALESCE(s.metadata_json->>'origin', '') <> 'openaq'
"""

# Readings whose source is OpenAQ are never exported, whatever station they sit on.
READINGS_NOT_OPENAQ = " AND r.source <> 'openaq'"

POLLUTANT_PARAMS = ("pm25", "pm10", "no2", "so2", "o3", "co")
UNKNOWN_UNIT = "unknown"


def hardware_label(metadata_json: Any) -> str:
    return _hardware_label(metadata_json)


def unit_or_unknown(row: Mapping[str, Any], param: str) -> str:
    """Stored unit for the parameter, or 'unknown' — never a guessed default."""
    v = row.get(f"units_{param}")
    return str(v) if v else UNKNOWN_UNIT


def encode_cursor(ts_utc: datetime, scope_key: str) -> str:
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)
    raw = f"{ts_utc.astimezone(timezone.utc).isoformat()}|{scope_key.strip()}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: Optional[str]) -> Optional[Tuple[datetime, str]]:
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + pad).decode("utf-8")
        ts_s, key = raw.split("|", 1)
        ts = datetime.fromisoformat(ts_s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not key:
            raise ValueError("empty key")
        return ts, key
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


# Keyset predicate and ordering: (ts_utc, scope_key) is unique for scope_type='station',
# so ties at the same timestamp can never be dropped or duplicated across pages.
CURSOR_WHERE = " AND (r.ts_utc, r.scope_key) < (CAST(:c_ts AS timestamptz), :c_key)"
KEYSET_ORDER = " ORDER BY r.ts_utc DESC, r.scope_key DESC LIMIT :limit"


def next_cursor(rows, limit: int) -> Optional[str]:
    """Cursor for the page after `rows` (DB rows ordered by the keyset), or None at the end."""
    if not rows or len(rows) < limit:
        return None
    last = rows[-1]
    return encode_cursor(last["ts_utc"], last["scope_key"] if isinstance(last["scope_key"], str) else str(last["scope_key"]))
