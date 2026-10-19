"""
The DB fallback inventory queries must only reference columns that exist in the
authoritative schema dump. The old worker copy selected st.id / st.latitude /
st.longitude and c.latitude / c.longitude, none of which exist.
"""

import re

import pytest

from app.ingestion.tasks.data_ingestion import STATION_FALLBACK_SQL
from app.ingestion.tasks.city_ingest import CITY_FALLBACK_SQL

_CREATE_RE = re.compile(r"CREATE TABLE public\.(\w+) \((.*?)\n\);", re.S)
_FROM_JOIN_RE = re.compile(r"\b(?:FROM|JOIN)\s+(\w+)\s+(\w+)", re.I)
_REF_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b")


def _ddl_columns(dump_text: str) -> dict:
    tables = {}
    for name, body in _CREATE_RE.findall(dump_text):
        cols = set()
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith(("CONSTRAINT", "PRIMARY KEY", "UNIQUE", "CHECK")):
                continue
            cols.add(line.split()[0].strip('"'))
        tables[name] = cols
    return tables


def _check(sql: str, tables: dict):
    aliases = {alias: table for table, alias in _FROM_JOIN_RE.findall(sql)}
    assert aliases, "no FROM/JOIN aliases parsed"
    for alias, table in aliases.items():
        assert table in tables, f"table {table} not in DDL"
    missing = []
    for alias, col in _REF_RE.findall(sql):
        if alias not in aliases:
            continue  # e.g. ST_Y(...) is matched as a function, not alias.col
        if col not in tables[aliases[alias]]:
            missing.append(f"{alias}.{col} ({aliases[alias]})")
    assert not missing, f"columns not in DDL: {missing}"


@pytest.fixture(scope="module")
def ddl_tables(schema_dump):
    tables = _ddl_columns(schema_dump.read_text())
    assert {"stations", "providers", "cities", "states", "countries", "readings"} <= set(tables)
    return tables


def test_station_fallback_columns_exist(ddl_tables):
    _check(STATION_FALLBACK_SQL, ddl_tables)
    assert "st.station_id" in STATION_FALLBACK_SQL
    assert "st.latitude" not in STATION_FALLBACK_SQL and "st.id " not in STATION_FALLBACK_SQL


def test_city_fallback_columns_exist(ddl_tables):
    _check(CITY_FALLBACK_SQL, ddl_tables)
    assert "c.latitude" not in CITY_FALLBACK_SQL
    assert "centroid" in CITY_FALLBACK_SQL


def test_ddl_stations_columns_match_expectation(ddl_tables):
    # Guard against the dump itself drifting from what the code assumes.
    assert {"station_id", "lat", "lon", "source_station_id", "provider_id", "city_id", "state_id", "country_id", "active"} <= ddl_tables["stations"]
    assert {"centroid", "state_id", "country_id", "name", "active"} <= ddl_tables["cities"]
