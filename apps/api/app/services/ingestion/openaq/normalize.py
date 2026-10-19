"""
OpenAQ measurement → readings row.

Timestamp policy `openaq_measurements_v1`: ts_utc = period.datetimeTo.utc (the
END of the hourly interval), floored to the hour. This matches the inference
behind the IQAir +1h correction (IQAir rows appear to be end-labelled), so the
two sources compare hour-for-hour; both interval boundaries are kept in
raw.prov.period, so the policy is reversible without a refetch.

Only hourly streams (period.interval == '01:00:00') are ingested in this PR;
sub-hourly ones are deferred by the task. Units are stored verbatim; a unit
other than µg/m³ makes the row INVALID (never silently converted). No AQI is
computed for OpenAQ rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.ingestion.validation import validate_reading
from app.services.ingestion.openaq.models import Measurement

TS_POLICY = "openaq_measurements_v1:period_end"
PARSER_VERSION = "openaq_rows_v1"
HOURLY = "01:00:00"
UGM3_ALIASES = {"µg/m³", "ug/m3", "µg/m3", "ug/m³"}


def is_hourly(m: Measurement) -> bool:
    return bool(m.period and (m.period.interval or "") == HOURLY)


def normalize_measurement(m: Measurement, *, station_id: str, stream_key: str, parameter: str,
                          prov_base: Dict[str, Any], now: Optional[datetime] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (row, None) or (None, reason) when the measurement cannot be used."""
    if m.period is None or m.period.datetime_to is None:
        return None, "no_period"
    if not is_hourly(m):
        return None, "interval_not_hourly"
    ts = m.period.datetime_to.utc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    flags = []
    if ts.minute or ts.second or ts.microsecond:
        flags.append("period_misaligned")
        ts = ts.replace(minute=0, second=0, microsecond=0)
    units = (m.parameter.units or "").strip()
    if parameter in ("pm25", "pm10") and units not in UGM3_ALIASES:
        flags.append("units_unexpected")
    row: Dict[str, Any] = {
        "scope_type": "station", "scope_key": station_id, "ts_utc": ts,
        parameter: m.value, f"units_{parameter}": units or None,
        "source": "openaq", "qc_flags": flags,
        "raw": {"prov": {**prov_base, "pv": PARSER_VERSION, "tsp": TS_POLICY, "stream": stream_key,
                         "period": {"from_utc": _iso(m.period.datetime_from.utc) if m.period.datetime_from else None,
                                    "to_utc": _iso(m.period.datetime_to.utc), "interval": m.period.interval,
                                    "label": m.period.label},
                         "coverage": _coverage(m), "has_flags": bool(m.flag_info and m.flag_info.has_flags)}},
    }
    v = validate_reading(row, now=now or datetime.now(timezone.utc))
    if not v.ok:
        return None, v.rejected
    out = v.row
    # validate_reading recomputes qc_flags from value checks; keep the policy flags too.
    merged = sorted(set(out.get("qc_flags") or []) | set(flags))
    out["qc_flags"] = merged
    out["qc_state"] = "INVALID" if merged else "raw"
    if v.quarantined:
        out["raw"]["prov"]["q"] = v.quarantined
    return out, None


def _coverage(m: Measurement) -> Optional[Dict[str, Any]]:
    c = m.coverage
    if c is None:
        return None
    return {"expected": c.expected_count, "observed": c.observed_count, "pct": c.percent_coverage}


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
