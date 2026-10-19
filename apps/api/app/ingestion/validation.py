"""
Reading validation and the qc_state machine for raw ingest.

Before this module the station path wrote qc_state='raw' for everything and the
city path hardcoded 'OK', with no check for negative, non-finite, implausible or
future values. Now:

  * each measured field is checked; a failing field is NULLed in the row, the
    original value kept in the row's quarantine dict (→ readings.raw.prov.q)
    and a flag 'v:<field>:<reason>' added
  * the row itself is rejected (never written, but counted) when its timestamp
    is missing, in the future, or before the backfill cutoff
  * raw ingest assigns qc_state 'INVALID' when any flag fired, else 'raw'; it
    never assigns 'OK' — that is a curated state (BAM QC, exports QC)
  * merge_qc() decides the stored state when a row already exists: curated
    states are never downgraded by raw ingest, and an INVALID row heals when a
    corrected replay supplies valid values for every flagged field
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

QC_RAW = "raw"
QC_INVALID = "INVALID"
QC_OK = "OK"
QC_SUSPECT = "SUSPECT"
CURATED_STATES = frozenset({QC_OK, QC_SUSPECT})
VALIDATION_FLAG_PREFIX = "v:"

POLLUTANT_FIELDS = ("pm25", "pm10", "o3", "no2", "so2", "co")
AQI_FIELDS = ("aqi_us", "aqi_cn")
WEATHER_FIELDS = ("temp_c", "humidity", "pressure_hpa", "wind_speed_ms", "wind_dir_deg", "heatindex_c",
                  "dewpoint_c", "visibility_km", "uv_index", "pop_pct")
NUMERIC_FIELDS = POLLUTANT_FIELDS + AQI_FIELDS + WEATHER_FIELDS

# Only a flag on a field the site and the exports actually show makes the whole row INVALID
# (the map/popup QC gate hides INVALID rows). A flag on any other field quarantines that
# field (value -> NULL, flag kept in qc_flags / raw.prov.q) but leaves the row 'raw'.
# Lesson from the 2026-10-15 rollout: a CO bound in the wrong unit flagged 26k rows and
# removed 316 stations from the map although their PM2.5 was fine.
PRIMARY_FIELDS = frozenset({"pm25", "aqi_us"})

# Fields that cannot be negative. Temperatures, dew point and heat index can.
NON_NEGATIVE = frozenset(POLLUTANT_FIELDS + AQI_FIELDS + ("humidity", "pressure_hpa", "wind_speed_ms",
                                                          "wind_dir_deg", "visibility_km", "uv_index", "pop_pct"))

# Generous physical plausibility bounds (anything beyond is a sensor/encoding fault, not air).
PLAUSIBLE_MAX: Dict[str, float] = {
    # No upper bound for CO: IQAir reports it in an unattested unit (values up to ~10,000 seen);
    # a ppm-scale bound flagged almost every row. Only finite/non-negative is checked.
    "pm25": 2000.0, "pm10": 5000.0, "o3": 1000.0, "no2": 2000.0, "so2": 2000.0,
    "aqi_us": 5000.0, "aqi_cn": 1000.0,
    "temp_c": 80.0, "humidity": 100.0, "pressure_hpa": 1100.0, "wind_speed_ms": 150.0, "wind_dir_deg": 360.0,
    "heatindex_c": 100.0, "dewpoint_c": 60.0, "visibility_km": 500.0, "uv_index": 25.0, "pop_pct": 100.0,
}
PLAUSIBLE_MIN: Dict[str, float] = {"temp_c": -60.0, "pressure_hpa": 300.0, "dewpoint_c": -80.0, "heatindex_c": -60.0}

FUTURE_TOLERANCE = timedelta(hours=1)


@dataclass
class ValidationOutcome:
    row: Dict[str, Any]
    flags: List[str] = field(default_factory=list)
    rejected: Optional[str] = None            # 'ts_missing' | 'ts_future' | 'ts_before_cutoff'
    quarantined: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.rejected is None


def _flag(field_name: str, reason: str) -> str:
    return f"{VALIDATION_FLAG_PREFIX}{field_name}:{reason}"


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_reading(row: Dict[str, Any], *, now: Optional[datetime] = None,
                     cutoff: Optional[datetime] = None) -> ValidationOutcome:
    """
    Validate (and mutate a copy of) one normalized reading row.
    Sets row['qc_state'], row['qc_flags'] and row['_present'] (fields with a value after validation).
    """
    now = now or datetime.now(timezone.utc)
    out = ValidationOutcome(row=dict(row))
    r = out.row

    ts = r.get("ts_utc")
    if ts is None:
        out.rejected = "ts_missing"
    else:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
            r["ts_utc"] = ts
        if ts > now + FUTURE_TOLERANCE:
            out.rejected = "ts_future"
        elif cutoff is not None and ts < cutoff:
            out.rejected = "ts_before_cutoff"

    for f in NUMERIC_FIELDS:
        v = r.get(f)
        if v is None:
            continue
        fv = _as_float(v)
        reason: Optional[str] = None
        if fv is None or math.isnan(fv) or math.isinf(fv):
            reason = "nonfinite"
        elif f in NON_NEGATIVE and fv < 0:
            reason = "negative"
        elif f in PLAUSIBLE_MAX and fv > PLAUSIBLE_MAX[f]:
            reason = "above_max"
        elif f in PLAUSIBLE_MIN and fv < PLAUSIBLE_MIN[f]:
            reason = "below_min"
        if reason:
            out.flags.append(_flag(f, reason))
            out.quarantined[f] = v
            r[f] = None
            if f in POLLUTANT_FIELDS:
                r[f"units_{f}"] = None

    present: Set[str] = {f for f in NUMERIC_FIELDS if r.get(f) is not None}
    r["_present"] = present
    r["qc_flags"] = sorted(set(out.flags))
    # Raw ingest never produces a curated state.
    r["qc_state"] = state_for_flags(out.flags)
    return out


def state_for_flags(flags: Iterable[str]) -> str:
    """INVALID only when a validation flag names a primary field; otherwise 'raw' (flags are still kept)."""
    return QC_INVALID if any(is_validation_flag(f) and _flag_field(f) in PRIMARY_FIELDS for f in flags) else QC_RAW


def is_validation_flag(flag: str) -> bool:
    return flag.startswith(VALIDATION_FLAG_PREFIX)


def _flag_field(flag: str) -> Optional[str]:
    if not is_validation_flag(flag):
        return None
    rest = flag[len(VALIDATION_FLAG_PREFIX):]
    return rest.split(":", 1)[0] if rest else None


def merge_qc(existing_state: Optional[str], existing_flags: Optional[Iterable[str]],
             incoming_flags: Iterable[str], incoming_present: Iterable[str]) -> Tuple[str, List[str]]:
    """
    Decide the stored qc_state/qc_flags when an incoming raw row meets an existing row.

      1. existing is curated (OK/SUSPECT)      → keep it; flags = existing ∪ incoming
      2. existing INVALID by something other than
         raw validation (e.g. BAM QC)          → leave it alone (flags = existing ∪ incoming)
      3. otherwise: existing validation flags for fields the incoming row now supplies validly
         are dropped (the row heals), incoming flags are added, and the state is INVALID only
         when a remaining flag names a primary field (pm25 / aqi_us); else 'raw' with the
         remaining flags kept for the record.
    """
    ex_flags = set(existing_flags or [])
    in_flags = set(incoming_flags or [])
    present = set(incoming_present or [])

    if existing_state in CURATED_STATES:
        return existing_state, sorted(ex_flags | in_flags)
    if existing_state == QC_INVALID and ex_flags and not all(is_validation_flag(f) for f in ex_flags):
        return QC_INVALID, sorted(ex_flags | in_flags)
    remaining = {f for f in ex_flags if not (is_validation_flag(f) and _flag_field(f) in present)} | in_flags
    return state_for_flags(remaining), sorted(remaining)
