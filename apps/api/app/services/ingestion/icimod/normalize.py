"""
ICIMOD catalogue and GeoJSON → stations and readings rows.

Timestamp policy `icimod_recent_v1:label_as_given`: the feed labels each hour
"YYYY-MM-DDTHH:30:00+00:00"; ts_utc is the label as given, floored to the hour
by norm_hour. Evidence so far (2026-11-03, 10 stations, 168 hourly values): the
value labelled HH:30+00:00 on recent/geojson is the value the portal's own
gridded-forecast-trend archive labels (HH+5):00 in naive Pakistan time, i.e.
the +00:00 is honest and the floored label is the same UTC hour ICIMOD uses
elsewhere. Whether that hour is the start or the end of EPCCD's averaging
period is still open (Test B/C in the pilot plan). The original label string
is kept in raw.prov.label so every row can be re-keyed from the archived
payload when the policy changes (bump TS_POLICY; never UPDATE ts_utc in place).

Units: the API does not state them. `units.PROVIDER_UNITS["icimod"]` is empty,
so units_pm25 stays NULL until the pilot attests µg/m³. No AQI is computed.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.ingestion.temporal import norm_hour
from app.ingestion.units import apply_units
from app.ingestion.validation import validate_reading

PROVIDER_CODE = "icimod"
PROVIDER_DISPLAY_NAME = "ICIMOD Air Quality Watch (EPCCD Punjab ground stations)"
PROVIDER_METADATA = {
    "origin": "icimod",
    "terms_url": "https://www.icimod.org/wp-content/uploads/2021/02/2013_ICIMOD_DataSharingPolicy.pdf",
    "attribution": "ICIMOD Air Quality Watch – HKH; ground data EPCCD Punjab (aqi.punjab.gov.pk)",
}
PARSER_VERSION = "icimod_rows_v1"
TS_POLICY = "icimod_recent_v1:label_as_given"
DEFAULT_TZ = "Asia/Karachi"


def station_id_for_icimod(native_id: int) -> str:
    """Deterministic char(16) id from the ICIMOD station id; renames never change it."""
    return f"ic_{hashlib.sha256(f'icimod:station:{int(native_id)}'.encode()).hexdigest()[:13]}"


@dataclass
class Station:
    id: int
    name: str
    district: Optional[str]
    city: Optional[str]
    state: Optional[str]
    lat: float
    lon: float


@dataclass
class Feature:
    name: str
    value: Optional[float]
    hourly_data: Dict[str, Any] = field(default_factory=dict)
    lon: Optional[float] = None
    lat: Optional[float] = None


def _float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None   # NaN → None


def parse_stations(payload: Any, *, state: Optional[str] = None) -> Tuple[List[Station], Counter]:
    """Catalogue rows → Station; rows without id/name/coordinates (or outside `state`) are counted, not raised."""
    notes: Counter = Counter()
    out: List[Station] = []
    if not isinstance(payload, list):
        notes["catalogue_not_a_list"] += 1
        return out, notes
    for raw in payload:
        if not isinstance(raw, dict):
            notes["station_not_an_object"] += 1
            continue
        try:
            sid = int(raw.get("id"))
        except (TypeError, ValueError):
            notes["station_missing_id"] += 1
            continue
        name = str(raw.get("station_name") or "").strip()
        lat, lon = _float(raw.get("latitude")), _float(raw.get("longitude"))
        if not name:
            notes["station_missing_name"] += 1
            continue
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            notes["station_missing_coordinates"] += 1
            continue
        st_state = raw.get("state")
        if state and (st_state or "").strip().lower() != state.lower():
            notes["station_outside_state"] += 1
            continue
        out.append(Station(id=sid, name=name, district=raw.get("district_name"), city=raw.get("city"), state=st_state,
                           lat=lat, lon=lon))
    return out, notes


def parse_feature_collection(payload: Any) -> List[Feature]:
    feats = payload.get("features") if isinstance(payload, dict) else None
    out: List[Feature] = []
    for f in feats or []:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or {}
        name = str(props.get("name") or "").strip()
        if not name:
            continue
        hourly = props.get("hourly_data")
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        out.append(Feature(name=name, value=_float(props.get("value")),
                           hourly_data=dict(hourly) if isinstance(hourly, dict) else {},
                           lon=_float(coords[0]) if len(coords) > 0 else None,
                           lat=_float(coords[1]) if len(coords) > 1 else None))
    return out


def parse_label(label: str) -> Optional[datetime]:
    """ISO-8601 label → aware datetime (naive labels are read as UTC under label_as_given)."""
    try:
        dt = datetime.fromisoformat(str(label).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_feature(feature: Feature, *, station_id: str, prov_base: Dict[str, Any],
                      now: Optional[datetime] = None) -> Tuple[List[Dict[str, Any]], Counter]:
    """All hourly values of one feature → readings rows (source='icimod'); per-reason counts for the rest."""
    notes: Counter = Counter()
    rows: List[Dict[str, Any]] = []
    now = now or datetime.now(timezone.utc)
    if not feature.hourly_data:
        notes["no_hourly_data"] += 1
        return rows, notes
    for label, value in feature.hourly_data.items():
        ts = parse_label(label)
        if ts is None:
            notes["label_unparsable"] += 1
            continue
        pm25 = _float(value)
        if pm25 is None:
            notes["value_missing"] += 1
            continue
        row: Dict[str, Any] = {
            "scope_type": "station", "scope_key": station_id, "ts_utc": norm_hour(ts),
            "pm25": pm25, "source": PROVIDER_CODE,
            "raw": {"prov": {**prov_base, "pv": PARSER_VERSION, "tsp": TS_POLICY, "label": str(label),
                             "native_name": feature.name}},
        }
        apply_units(row, PROVIDER_CODE)
        v = validate_reading(row, now=now)
        if not v.ok:
            notes[v.rejected or "rejected"] += 1
            continue
        out = v.row
        if v.quarantined:
            out["raw"]["prov"]["q"] = v.quarantined
            notes["quarantined"] += 1
        rows.append(out)
    return rows, notes
