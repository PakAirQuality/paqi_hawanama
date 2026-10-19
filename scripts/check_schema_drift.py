#!/usr/bin/env python3
"""
Read-only: compare the live database's column lists with db_schema/initial_schema.sql
for the tables the ingestion code writes. Exit 1 if any column the code uses is missing.

  python scripts/check_schema_drift.py            # uses POSTGRES_* from the repo .env (sslmode=require)
  DATABASE_URL=postgresql://... python scripts/check_schema_drift.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import asyncio
import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

TABLES = ["readings", "stations", "providers", "cities", "states", "countries"]
_CREATE_RE = re.compile(r"CREATE TABLE public\.(\w+) \((.*?)\n\);", re.S)


def load_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def db_url() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    e = load_env()
    return f"postgresql://{e['POSTGRES_USER']}:{e['POSTGRES_PASSWORD']}@{e['POSTGRES_SERVER']}:{e['POSTGRES_PORT']}/{e['POSTGRES_DB']}?sslmode=require"


def dump_columns() -> dict:
    out = {}
    for name, body in _CREATE_RE.findall((ROOT / "db_schema/initial_schema.sql").read_text()):
        cols = {}
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith(("CONSTRAINT", "PRIMARY KEY", "UNIQUE", "CHECK")):
                continue
            parts = line.split()
            cols[parts[0].strip('"')] = " ".join(parts[1:])
        out[name] = cols
    return out


async def main() -> int:
    from app.ingestion.reconcile import ALL_COLUMNS
    code_needs = {
        "readings": set(ALL_COLUMNS) | {"ingested_at"},
        "stations": {"station_id", "country_id", "state_id", "city_id", "name", "lat", "lon", "provider_id",
                     "source_station_id", "metadata_json", "timezone", "active", "last_seen_at", "updated_at", "monitor_type"},
        "providers": {"id", "code", "display_name", "metadata", "active"},
        "cities": {"id", "country_id", "state_id", "name", "timezone", "active", "last_seen_at", "centroid"},
        "states": {"id", "country_id", "name", "code", "active", "last_seen_at"},
        "countries": {"id", "name", "iso2", "iso3", "active", "last_seen_at"},
    }
    dump = dump_columns()
    conn = await asyncpg.connect(db_url())
    rc = 0
    try:
        ver = await conn.fetchval("select version()")
        print("live:", ver.split(",")[0])
        ext = await conn.fetch("select extname, extversion from pg_extension order by 1")
        print("extensions:", ", ".join(f"{r['extname']} {r['extversion']}" for r in ext))
        for t in TABLES:
            rows = await conn.fetch("select column_name, data_type, udt_name from information_schema.columns "
                                    "where table_schema='public' and table_name=$1 order by ordinal_position", t)
            live = {r["column_name"]: r["udt_name"] for r in rows}
            d = dump.get(t, {})
            missing_vs_dump = sorted(set(d) - set(live))
            extra_vs_dump = sorted(set(live) - set(d))
            missing_for_code = sorted(code_needs[t] - set(live))
            print(f"\n[{t}] live={len(live)} cols, dump={len(d)} cols")
            if missing_vs_dump: print("  in dump but not live:", missing_vs_dump)
            if extra_vs_dump: print("  live but not in dump:", extra_vs_dump)
            if missing_for_code:
                print("  !! columns the code writes/reads that are MISSING live:", missing_for_code); rc = 1
            if not (missing_vs_dump or extra_vs_dump): print("  identical to dump")
        pk = await conn.fetch("""select conname, pg_get_constraintdef(oid) from pg_constraint
                                 where conrelid in ('public.readings'::regclass, 'public.stations'::regclass, 'public.providers'::regclass)
                                 order by 1""")
        print("\nconstraints:")
        for r in pk: print(" ", r["conname"], r["pg_get_constraintdef"])
        ops = await conn.fetch("select table_name from information_schema.tables where table_schema='ops' order by 1")
        print("\nops schema tables:", [r["table_name"] for r in ops] or "(none — migrations not applied)")
        who = await conn.fetchrow("select current_user, (select rolsuper from pg_roles where rolname=current_user) su, "
                                  "(select tableowner from pg_tables where schemaname='public' and tablename='readings') owner")
        print("role:", who["current_user"], "superuser:", who["su"], "readings owner:", who["owner"])
    finally:
        await conn.close()
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
