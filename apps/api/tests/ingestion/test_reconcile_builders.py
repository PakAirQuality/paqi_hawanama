"""Pure checks on the reconcile SQL builders and in-memory helpers (no database)."""

import json
import re
from datetime import datetime, timezone

from app.ingestion import reconcile as rc

T = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


def _row(**kw):
    base = {"scope_type": "station", "scope_key": "s1", "ts_utc": T, "pm25": 10.0, "qc_state": "raw", "qc_flags": [],
            "source": "airvisual", "raw": {"prov": {"sha": "abc"}}}
    base.update(kw)
    return base


def test_dedupe_keys_include_scope_type_and_fill_only():
    a = _row(pm25=10.0, temp_c=None, raw={"prov": {"sha": "a"}})
    b = _row(pm25=99.0, temp_c=30.0, ts_utc=T.replace(minute=30))   # same hour
    c = _row(scope_type="city", pm25=5.0)
    out = rc.dedupe_rows([a, b, c])
    assert len(out) == 2
    st = next(r for r in out if r["scope_type"] == "station")
    assert st["pm25"] == 10.0 and st["temp_c"] == 30.0 and st["ts_utc"] == T and st["raw"]["prov"]["sha"] == "a"


def test_dedupe_unions_flags_withdrawals_and_marks_invalid():
    a = _row(qc_flags=["v:pm25:negative"], pm25=None, _withdraw={"o3"})
    b = _row(qc_flags=[], pm25=None, _withdraw={"no2"}, _present={"temp_c"})
    out = rc.dedupe_rows([a, b])[0]
    assert out["qc_flags"] == ["v:pm25:negative"] and out["qc_state"] == "INVALID"
    assert out["_withdraw"] == {"o3", "no2"} and out["_present"] == {"temp_c"}


def test_diff_for_revisions_only_non_null_changes():
    existing = {"pm25": 11.0, "temp_c": None, "aqi_us": 50}
    incoming = _row(pm25=12.0, temp_c=30.0, aqi_us=50, humidity=None)
    revs = rc.diff_for_revisions(existing, incoming, "sha1")
    assert [(r.field, r.old_value, r.new_value, r.payload_sha256) for r in revs] == [("pm25", 11.0, 12.0, "sha1")]
    assert rc.diff_for_revisions({"pm25": 12.0000000001}, _row(pm25=12.0), None) == []


def test_encode_rows_json_strips_private_keys_and_bad_enums():
    row = _row(main_us="p3", main_cn="pm10", qc_flags=[], _present={"pm25"}, _withdraw={"o3"})
    [o] = json.loads(rc.encode_rows_json([row], "airvisual"))
    assert set(o) == set(rc.ALL_COLUMNS)
    assert o["main_us"] is None and o["main_cn"] == "pm10" and o["qc_flags"] is None
    assert o["ts_utc"].startswith("2026-10-15T10:00:00") and o["raw"] == {"prov": {"sha": "abc"}}
    assert "_present" not in o and "_withdraw" not in o


def test_upsert_sql_shape():
    sql = rc.build_upsert_sql()
    for c in rc.VALUE_COLUMNS:
        assert f"{c} = COALESCE(EXCLUDED.{c}, readings.{c})" in sql
    assert "source = EXCLUDED.source" not in sql
    assert "ON CONFLICT (scope_type, scope_key, ts_utc) DO UPDATE" in sql
    assert "IS DISTINCT FROM" in sql and "readings.qc_state IS DISTINCT FROM EXCLUDED.qc_state" in sql
    assert "raw = COALESCE(readings.raw, '{}'::jsonb) || COALESCE(EXCLUDED.raw, '{}'::jsonb)" in sql
    assert "CAST(scope_type AS public.scope_type)" in sql and "CAST(main_us AS public.pollutant_code)" in sql
    assert "RETURNING readings.scope_type::text AS scope_type, readings.scope_key, readings.ts_utc" in sql
    assert "qc_flags text[]" in sql and "raw jsonb" in sql


def test_select_existing_sql_joins_on_full_key():
    sql = rc.build_select_existing_sql()
    assert "r.scope_type = CAST(k.scope_type AS public.scope_type)" in sql
    assert "r.scope_key = k.scope_key" in sql and "r.ts_utc = k.ts_utc" in sql
    assert "r.main_us::text AS main_us" in sql


def test_withdraw_sql_nulls_fields_units_and_merges_prov():
    sql = rc.build_withdraw_sql(("pm25", "temp_c"))
    assert "pm25 = NULL, temp_c = NULL, units_pm25 = NULL" in sql
    assert "raw = COALESCE(raw, '{}'::jsonb) || CAST(:prov AS jsonb)" in sql
    assert "(pm25 IS NOT NULL OR temp_c IS NOT NULL)" in sql


def test_value_columns_exist_in_schema_dump(schema_dump):
    body = re.search(r"CREATE TABLE public\.readings \((.*?)\n\);", schema_dump.read_text(), re.S).group(1)
    cols = {line.strip().split()[0] for line in body.splitlines() if line.strip()}
    assert set(rc.ALL_COLUMNS) <= cols, set(rc.ALL_COLUMNS) - cols
