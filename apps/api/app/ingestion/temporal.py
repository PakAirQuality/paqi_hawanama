"""
Temporal normalization of IQAir station/city payloads, versioned.

The ingestion code shifts IQAir *history* pollution timestamps forward by one
hour and drops the history entry that overlaps "current − 1 h", on the
(undocumented) assumption that history is labelled one hour behind current.
That shift is NOT changed here: it is captured as policy `iqair_station_v1`
(weather history unshifted) and `iqair_city_v1` (weather shifted with
pollution), recorded on every row (raw.prov.tsp) together with the ORIGINAL
provider timestamps (raw.prov.src_ts) and the shift applied (raw.prov.shift_h),
so it can be evaluated against archived payloads and reversed without a refetch.

What does change: the overlap entry used to be skipped entirely, so when
`current` lacked a field (e.g. PM2.5) the history value for that hour was lost.
Under overlap_mode='fill_current' it fills the fields `current` left empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.ingestion.units import units_for

PARSER_VERSION = "iqair_rows_v2"

POLLUTION_FIELDS = ("aqi_us", "aqi_cn", "main_us", "main_cn", "pm25", "pm10", "o3", "no2", "so2", "co")
WEATHER_FIELDS = ("temp_c", "humidity", "pressure_hpa", "wind_speed_ms", "wind_dir_deg", "weather_icon",
                  "heatindex_c", "pop_pct")
_POLLUTANT_CODES = {"p1": "pm10", "p2": "pm25", "o3": "o3", "n2": "no2", "s2": "so2", "co": "co"}


@dataclass(frozen=True)
class TemporalPolicy:
    policy_id: str
    history_pollution_shift_hours: int = 1
    history_weather_shift_hours: int = 0
    overlap_tolerance_min: int = 10        # |(current − T) − 1 h| within this → the overlap entry
    overlap_mode: str = "fill_current"      # 'fill_current' | 'skip' (legacy behaviour)
    floor_to_hour: bool = True


TEMPORAL_POLICIES: Dict[str, TemporalPolicy] = {
    "iqair_station_v1": TemporalPolicy("iqair_station_v1", history_pollution_shift_hours=1, history_weather_shift_hours=0),
    "iqair_city_v1": TemporalPolicy("iqair_city_v1", history_pollution_shift_hours=1, history_weather_shift_hours=1),
}


@dataclass
class ExtractResult:
    rows: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)   # e.g. 'no_current_pollution_ts', 'unparseable_ts:...'


def norm_hour(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def parse_ts(ts: Any) -> Optional[datetime]:
    """IQAir timestamps: '2026-10-15T09:00:00.000Z' or with an explicit offset."""
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def map_pollutant_code(code: Any) -> Optional[str]:
    if not code:
        return None
    return _POLLUTANT_CODES.get(code, code)


def _conc(obj: Dict[str, Any], key: str) -> Any:
    v = obj.get(key)
    if isinstance(v, dict):
        return v.get("conc")
    if v is None:
        # city payloads sometimes carry flat '<p>_conc' keys
        return obj.get(f"{ {'p2': 'pm25', 'p1': 'pm10'}.get(key, key)}_conc")
    return v


def pollution_fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "aqi_us": obj.get("aqius"), "aqi_cn": obj.get("aqicn"),
        "main_us": map_pollutant_code(obj.get("mainus")), "main_cn": map_pollutant_code(obj.get("maincn")),
        "pm25": _conc(obj, "p2"), "pm10": _conc(obj, "p1"), "o3": _conc(obj, "o3"),
        "no2": _conc(obj, "n2"), "so2": _conc(obj, "s2"), "co": _conc(obj, "co"),
    }


def weather_fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "temp_c": obj.get("tp"), "humidity": obj.get("hu"), "pressure_hpa": obj.get("pr"),
        "wind_speed_ms": obj.get("ws"), "wind_dir_deg": obj.get("wd"), "weather_icon": obj.get("ic"),
        "heatindex_c": obj.get("heatIndex", obj.get("heatindex")),
        "pop_pct": obj.get("pop", obj.get("precipitation_probability")),
    }


class _Bucket:
    """One output row per hour plus the provenance of what landed in it."""

    def __init__(self, scope_type: str, scope_key: str, ts: datetime, provider: str):
        self.row: Dict[str, Any] = {"scope_type": scope_type, "scope_key": scope_key, "ts_utc": ts,
                                    **{f: None for f in POLLUTION_FIELDS},
                                    **{f"units_{p}": None for p in ("pm25", "pm10", "o3", "no2", "so2", "co")},
                                    **{f: None for f in WEATHER_FIELDS},
                                    "source": provider}
        self.src_ts: Dict[str, str] = {}
        self.shift_h: Dict[str, int] = {}
        self.filled_from_history: List[str] = []

    def merge(self, fields: Dict[str, Any], *, fill_only: bool, mark_history: bool) -> None:
        for k, v in fields.items():
            if v is None:
                continue
            if fill_only and self.row.get(k) is not None:
                continue
            self.row[k] = v
            if mark_history and fill_only:
                self.filled_from_history.append(k)


def extract_iqair_rows(parsed: Dict[str, Any], *, scope_type: str, scope_key: str, policy: TemporalPolicy,
                       provider: str = "airvisual", prov_base: Optional[Dict[str, Any]] = None) -> ExtractResult:
    """
    Merge current + history pollution/weather from an IQAirClient.parse_* payload
    into hourly rows under `policy`. Cutoff/future checks and value validation
    are NOT done here (see validation.validate_reading, which also counts them).
    """
    res = ExtractResult()
    buckets: Dict[datetime, _Bucket] = {}

    def bucket(ts: datetime) -> _Bucket:
        ts = norm_hour(ts) if policy.floor_to_hour else ts
        b = buckets.get(ts)
        if b is None:
            b = buckets[ts] = _Bucket(scope_type, scope_key, ts, provider)
        return b

    current = parsed.get("current") or {}
    cur_p = current.get("pollution") if isinstance(current, dict) else None
    cur_w = current.get("weather") if isinstance(current, dict) else None

    # ---- current pollution: anchor hour H ----
    H: Optional[datetime] = None
    if isinstance(cur_p, dict):
        ts = parse_ts(cur_p.get("ts"))
        if ts is None:
            res.notes.append("no_current_pollution_ts")   # no now() fallback: the row is simply not produced
        else:
            H = norm_hour(ts)
            b = bucket(H)
            b.merge(pollution_fields(cur_p), fill_only=False, mark_history=False)
            b.src_ts["p"] = iso_z(ts)
            b.shift_h["p"] = 0

    # ---- current weather ----
    if isinstance(cur_w, dict):
        ts = parse_ts(cur_w.get("ts")) or (H if H is not None else None)
        if ts is None:
            res.notes.append("no_current_weather_ts")
        else:
            b = bucket(ts)
            b.merge(weather_fields(cur_w), fill_only=False, mark_history=False)
            b.src_ts.setdefault("w", iso_z(ts))
            b.shift_h.setdefault("w", 0)

    tol = timedelta(minutes=policy.overlap_tolerance_min)

    def is_overlap(T: datetime) -> bool:
        return H is not None and abs((H - T) - timedelta(hours=1)) <= tol

    # ---- history pollution ----
    hist = parsed.get("history") or {}
    for p in (hist.get("pollution") or []) if isinstance(hist, dict) else []:
        if not isinstance(p, dict):
            continue
        T = parse_ts(p.get("ts"))
        if T is None:
            res.notes.append("unparseable_history_pollution_ts")
            continue
        T = norm_hour(T)
        fields = pollution_fields(p)
        if is_overlap(T):
            if policy.overlap_mode == "skip":
                continue
            # The entry describing the current hour under the lag assumption: fill what current lacks.
            b = bucket(H)
            b.merge(fields, fill_only=True, mark_history=True)
            b.src_ts.setdefault("p_overlap", iso_z(T))
            continue
        shifted = T + timedelta(hours=policy.history_pollution_shift_hours)
        b = bucket(shifted)
        b.merge(fields, fill_only=False, mark_history=False)
        b.src_ts.setdefault("p", iso_z(T))
        b.shift_h.setdefault("p", policy.history_pollution_shift_hours)

    # ---- history weather ----
    for w in (hist.get("weather") or []) if isinstance(hist, dict) else []:
        if not isinstance(w, dict):
            continue
        T = parse_ts(w.get("ts"))
        if T is None:
            res.notes.append("unparseable_history_weather_ts")
            continue
        T = norm_hour(T)
        fields = weather_fields(w)
        if policy.history_weather_shift_hours and is_overlap(T):
            if policy.overlap_mode == "skip":
                continue
            b = bucket(H)
            b.merge(fields, fill_only=True, mark_history=True)
            b.src_ts.setdefault("w_overlap", iso_z(T))
            continue
        shifted = T + timedelta(hours=policy.history_weather_shift_hours)
        b = bucket(shifted)
        b.merge(fields, fill_only=False, mark_history=False)
        b.src_ts.setdefault("w", iso_z(T))
        b.shift_h.setdefault("w", policy.history_weather_shift_hours)

    # ---- emit ----
    for ts in sorted(buckets):
        b = buckets[ts]
        row = b.row
        for pol in ("pm25", "pm10", "o3", "no2", "so2", "co"):
            row[f"units_{pol}"] = units_for(provider, pol) if row.get(pol) is not None else None
        prov: Dict[str, Any] = {"v": 1, "pv": PARSER_VERSION, "tsp": policy.policy_id,
                                "src_ts": b.src_ts, "shift_h": b.shift_h}
        if b.filled_from_history:
            prov["from"] = {k: "history" for k in b.filled_from_history}
        if prov_base:
            prov.update(prov_base)
        row["raw"] = {"prov": prov}
        res.rows.append(row)
    return res
