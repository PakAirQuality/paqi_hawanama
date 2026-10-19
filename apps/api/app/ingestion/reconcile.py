"""
Field-aware reconciliation of readings.

The old write path first dropped every incoming row whose (scope_key, hour)
already existed, then upserted the rest with `col = EXCLUDED.col` for every
column. Existing hours were therefore never repaired (a weather-only row
blocked PM2.5 for ever), and removing that prefilter alone would have let a
sparse payload NULL out stored values.

reconcile_and_upsert_readings():
  * dedupes in memory on (scope_type, scope_key, hour) with fill-only merging
  * reads the existing rows for the batch, decides qc via merge_qc (curated
    states are never downgraded) and collects revisions (a non-null incoming
    value that differs from a non-null stored one)
  * one batched INSERT ... ON CONFLICT DO UPDATE SET col = COALESCE(EXCLUDED.col,
    readings.col) guarded by WHERE ... IS DISTINCT FROM ..., so an exact replay
    touches no tuple and counts as unchanged
  * applies explicit withdrawals (row['_withdraw'] = {'pm25', ...}) as separate
    NULLing updates with reason='withdrawn'
  * records revisions in ops.reading_revisions inside a savepoint so a missing
    ops schema never poisons the readings transaction
  * never updates `source`
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import text

from app.ingestion.temporal import norm_hour
from app.ingestion.validation import merge_qc

logger = logging.getLogger(__name__)

KEY_COLUMNS = ("scope_type", "scope_key", "ts_utc")
POLLUTION_COLUMNS = ("aqi_us", "aqi_cn", "main_us", "main_cn", "pm25", "pm10", "o3", "no2", "so2", "co")
UNIT_COLUMNS = ("units_pm25", "units_pm10", "units_o3", "units_no2", "units_so2", "units_co")
WEATHER_COLUMNS = ("temp_c", "humidity", "pressure_hpa", "wind_speed_ms", "wind_dir_deg", "weather_icon",
                   "heatindex_c", "pop_pct")
VALUE_COLUMNS = POLLUTION_COLUMNS + UNIT_COLUMNS + WEATHER_COLUMNS
REVISION_COLUMNS = POLLUTION_COLUMNS + WEATHER_COLUMNS
ENUM_COLUMNS = ("main_us", "main_cn")
POLLUTANT_CODES = frozenset({"pm25", "pm10", "o3", "no2", "so2", "co"})
PRIVATE_KEYS = ("_present", "_withdraw")

# Types for jsonb_to_recordset; must match db_schema/initial_schema.sql public.readings.
COLUMN_SQL_TYPES: Dict[str, str] = {
    "scope_type": "text", "scope_key": "text", "ts_utc": "timestamptz",
    "aqi_us": "smallint", "aqi_cn": "smallint", "main_us": "text", "main_cn": "text",
    "pm25": "double precision", "pm10": "double precision", "o3": "double precision", "no2": "double precision",
    "so2": "double precision", "co": "double precision",
    "units_pm25": "text", "units_pm10": "text", "units_o3": "text", "units_no2": "text", "units_so2": "text", "units_co": "text",
    "temp_c": "double precision", "humidity": "double precision", "pressure_hpa": "double precision",
    "wind_speed_ms": "double precision", "wind_dir_deg": "integer", "weather_icon": "text",
    "heatindex_c": "double precision", "pop_pct": "smallint",
    "qc_state": "text", "qc_flags": "text[]", "source": "text", "raw": "jsonb",
}
ALL_COLUMNS = KEY_COLUMNS + VALUE_COLUMNS + ("qc_state", "qc_flags", "source", "raw")


@dataclass(frozen=True)
class ReconcilePolicy:
    source: str
    run_id: Optional[str] = None
    batch_size: int = 500
    record_revisions: bool = True
    allow_withdrawals: bool = True


@dataclass
class ReconcileResult:
    rows_in: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_withdrawn_fields: int = 0
    revisions_recorded: int = 0
    revisions_failed: bool = False

    @property
    def rows_written(self) -> int:
        return self.rows_inserted + self.rows_updated


@dataclass(frozen=True)
class Revision:
    scope_type: str
    scope_key: str
    ts_utc: datetime
    field: str
    old_value: Any
    new_value: Any
    reason: str = "revised"
    payload_sha256: Optional[str] = None


# ------------------------------------------------------------------ pure helpers

def _key(row: Dict[str, Any]) -> Tuple[str, str, datetime]:
    return (row["scope_type"], row["scope_key"], norm_hour(row["ts_utc"]))


def dedupe_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge duplicates of (scope_type, scope_key, hour): first non-null value wins, withdrawals union."""
    by_key: Dict[Tuple[str, str, datetime], Dict[str, Any]] = {}
    for r in rows:
        r = dict(r)
        r["ts_utc"] = norm_hour(r["ts_utc"])
        k = _key(r)
        if k not in by_key:
            by_key[k] = r
            continue
        a = by_key[k]
        for col, v in r.items():
            if col in KEY_COLUMNS or col in PRIVATE_KEYS or v is None:
                continue
            if col == "raw":
                if a.get("raw") is None:
                    a["raw"] = v
                continue
            if col == "qc_flags":
                a["qc_flags"] = sorted(set(a.get("qc_flags") or []) | set(v or []))
                continue
            if a.get(col) is None:
                a[col] = v
        a["_present"] = set(a.get("_present") or ()) | set(r.get("_present") or ())
        if r.get("_withdraw") or a.get("_withdraw"):
            a["_withdraw"] = set(a.get("_withdraw") or ()) | set(r.get("_withdraw") or ())
        if a.get("qc_flags"):
            a["qc_state"] = "INVALID"
    return list(by_key.values())


def _values_differ(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        try:
            return not math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
        except (TypeError, ValueError):
            return a != b
    return a != b


def diff_for_revisions(existing: Dict[str, Any], incoming: Dict[str, Any], payload_sha256: Optional[str]) -> List[Revision]:
    """Revisions: incoming non-null and different from a stored non-null value. NULL→value is enrichment, not a revision."""
    out: List[Revision] = []
    for f in REVISION_COLUMNS:
        new = incoming.get(f)
        old = existing.get(f)
        if new is None or old is None:
            continue
        if _values_differ(old, new):
            out.append(Revision(incoming["scope_type"], incoming["scope_key"], norm_hour(incoming["ts_utc"]), f, old, new,
                                payload_sha256=payload_sha256))
    return out


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def encode_rows_json(rows: Iterable[Dict[str, Any]], source: str) -> str:
    """JSON for jsonb_to_recordset: fixed column set, ISO datetimes, no private keys, enum codes checked."""
    out = []
    for r in rows:
        o: Dict[str, Any] = {}
        for col in ALL_COLUMNS:
            v = r.get(col)
            if col == "ts_utc":
                v = _iso(v)
            elif col in ENUM_COLUMNS and v is not None and v not in POLLUTANT_CODES:
                v = None
            elif col == "qc_flags":
                v = list(v) if v else None
            elif col == "source":
                v = v or source
            elif col == "qc_state":
                v = v or "raw"
            elif col == "raw" and v is not None and not isinstance(v, dict):
                v = {"legacy": v}
            o[col] = v
        out.append(o)
    return json.dumps(out, default=str, ensure_ascii=False)


def encode_keys_json(rows: Iterable[Dict[str, Any]]) -> str:
    return json.dumps([{"scope_type": r["scope_type"], "scope_key": r["scope_key"], "ts_utc": _iso(norm_hour(r["ts_utc"]))}
                       for r in rows])


def _recordset_cols(cols: Iterable[str]) -> str:
    return ", ".join(f"{c} {COLUMN_SQL_TYPES[c]}" for c in cols)


def build_select_existing_sql() -> str:
    sel = ", ".join(
        ["r.scope_type::text AS scope_type", "r.scope_key", "r.ts_utc"]
        + [f"r.{c}::text AS {c}" if c in ENUM_COLUMNS else f"r.{c}" for c in VALUE_COLUMNS]
        + ["r.qc_state", "r.qc_flags"]
    )
    return f"""
        SELECT {sel}
        FROM readings r
        JOIN jsonb_to_recordset(CAST(:keys AS jsonb)) AS k({_recordset_cols(KEY_COLUMNS)})
          ON r.scope_type = CAST(k.scope_type AS public.scope_type)
         AND r.scope_key = k.scope_key
         AND r.ts_utc = k.ts_utc
    """


def build_upsert_sql() -> str:
    insert_cols = ", ".join(ALL_COLUMNS)
    select_cols = ", ".join(
        "CAST(scope_type AS public.scope_type)" if c == "scope_type"
        else f"CAST({c} AS public.pollutant_code)" if c in ENUM_COLUMNS
        else c
        for c in ALL_COLUMNS
    )
    set_clause = ",\n            ".join(f"{c} = COALESCE(EXCLUDED.{c}, readings.{c})" for c in VALUE_COLUMNS)
    lhs = ", ".join(f"readings.{c}" for c in VALUE_COLUMNS)
    rhs = ", ".join(f"COALESCE(EXCLUDED.{c}, readings.{c})" for c in VALUE_COLUMNS)
    return f"""
        WITH incoming AS (
            SELECT * FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x({_recordset_cols(ALL_COLUMNS)})
        )
        INSERT INTO readings ({insert_cols})
        SELECT {select_cols} FROM incoming
        ON CONFLICT (scope_type, scope_key, ts_utc) DO UPDATE SET
            {set_clause},
            qc_state = EXCLUDED.qc_state,
            qc_flags = EXCLUDED.qc_flags,
            raw = COALESCE(readings.raw, '{{}}'::jsonb) || COALESCE(EXCLUDED.raw, '{{}}'::jsonb),
            ingested_at = now()
        WHERE ({lhs}) IS DISTINCT FROM ({rhs})
           OR readings.qc_state IS DISTINCT FROM EXCLUDED.qc_state
           OR readings.qc_flags IS DISTINCT FROM EXCLUDED.qc_flags
        RETURNING readings.scope_type::text AS scope_type, readings.scope_key, readings.ts_utc
    """


def build_withdraw_sql(fields: Tuple[str, ...]) -> str:
    sets = ", ".join(f"{f} = NULL" for f in fields)
    units = ", ".join(f"units_{f} = NULL" for f in fields if f in POLLUTANT_CODES)
    cond = " OR ".join(f"{f} IS NOT NULL" for f in fields)
    extra = f", {units}" if units else ""
    return f"""
        UPDATE readings
           SET {sets}{extra},
               raw = COALESCE(raw, '{{}}'::jsonb) || CAST(:prov AS jsonb),
               ingested_at = now()
         WHERE scope_type = CAST(:scope_type AS public.scope_type)
           AND scope_key = :scope_key
           AND ts_utc = :ts_utc
           AND ({cond})
        RETURNING scope_key
    """


REVISIONS_INSERT_SQL = text("""
    INSERT INTO ops.reading_revisions
        (scope_type, scope_key, ts_utc, field, old_value, new_value, reason, source, payload_sha256, run_id)
    VALUES
        (:scope_type, :scope_key, :ts_utc, :field, CAST(:old_value AS jsonb), CAST(:new_value AS jsonb),
         :reason, :source, :payload_sha256, :run_id)
""")


# ------------------------------------------------------------------ orchestration

_warned_revisions = False


async def reconcile_and_upsert_readings(session, rows: List[Dict[str, Any]], policy: ReconcilePolicy) -> ReconcileResult:
    """
    Write `rows` into readings with field-aware semantics. The caller owns the
    transaction (commit after). Returns counts; never writes NULL over a value.
    """
    res = ReconcileResult(rows_in=len(rows))
    if not rows:
        return res
    deduped = dedupe_rows(rows)
    select_sql = text(build_select_existing_sql())
    upsert_sql = text(build_upsert_sql())
    revisions: List[Revision] = []
    withdraw_jobs: List[Tuple[Dict[str, Any], Tuple[str, ...], Dict[str, Any]]] = []

    for start in range(0, len(deduped), policy.batch_size):
        batch = deduped[start:start + policy.batch_size]
        existing: Dict[Tuple[str, str, datetime], Dict[str, Any]] = {}
        rs = await session.execute(select_sql, {"keys": encode_keys_json(batch)})
        for row in rs.fetchall():
            m = dict(row._mapping)
            existing[(m["scope_type"], m["scope_key"], norm_hour(m["ts_utc"]))] = m

        for r in batch:
            ex = existing.get(_key(r))
            sha = ((r.get("raw") or {}).get("prov") or {}).get("sha") if isinstance(r.get("raw"), dict) else None
            incoming_flags = r.get("qc_flags") or []
            present = r.get("_present") or {c for c in REVISION_COLUMNS if r.get(c) is not None}
            if ex is not None:
                state, flags = merge_qc(ex.get("qc_state"), ex.get("qc_flags"), incoming_flags, present)
                revisions.extend(diff_for_revisions(ex, r, sha))
                if policy.allow_withdrawals and r.get("_withdraw"):
                    fields = tuple(sorted(f for f in r["_withdraw"] if f in REVISION_COLUMNS))
                    if fields:
                        withdraw_jobs.append((r, fields, ex))
            else:
                state, flags = merge_qc(None, None, incoming_flags, present)
            r["qc_state"], r["qc_flags"] = state, flags

        rs = await session.execute(upsert_sql, {"rows": encode_rows_json(batch, policy.source)})
        touched = {(row[0], row[1], norm_hour(row[2])) for row in rs.fetchall()}
        for r in batch:
            k = _key(r)
            if k not in touched:
                res.rows_unchanged += 1
            elif k in existing:
                res.rows_updated += 1
            else:
                res.rows_inserted += 1

    for r, fields, ex in withdraw_jobs:
        prov = {"withdrawn": {"fields": list(fields), "run": policy.run_id, "sha": None}}
        rs = await session.execute(text(build_withdraw_sql(fields)), {
            "prov": json.dumps(prov), "scope_type": r["scope_type"], "scope_key": r["scope_key"],
            "ts_utc": norm_hour(r["ts_utc"]),
        })
        if rs.fetchall():
            res.rows_withdrawn_fields += len(fields)
            for f in fields:
                if ex.get(f) is not None:
                    revisions.append(Revision(r["scope_type"], r["scope_key"], norm_hour(r["ts_utc"]), f, ex.get(f), None,
                                              reason="withdrawn"))

    if policy.record_revisions and revisions:
        res.revisions_recorded, res.revisions_failed = await _record_revisions(session, revisions, policy)
    return res


async def _record_revisions(session, revisions: List[Revision], policy: ReconcilePolicy) -> Tuple[int, bool]:
    """Insert into ops.reading_revisions inside a savepoint so a missing table cannot abort the readings write."""
    global _warned_revisions
    params = [{
        "scope_type": rv.scope_type, "scope_key": rv.scope_key, "ts_utc": rv.ts_utc, "field": rv.field,
        "old_value": json.dumps(rv.old_value, default=str), "new_value": json.dumps(rv.new_value, default=str),
        "reason": rv.reason, "source": policy.source, "payload_sha256": rv.payload_sha256, "run_id": policy.run_id,
    } for rv in revisions]
    try:
        async with session.begin_nested():
            await session.execute(REVISIONS_INSERT_SQL, params)
        return len(params), False
    except Exception as exc:
        if not _warned_revisions:
            _warned_revisions = True
            logger.warning("ops.reading_revisions write failed (apply migration 002?): %s: %s", type(exc).__name__, exc)
        return 0, True
