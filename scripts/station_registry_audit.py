#!/usr/bin/env python3
"""Read-only audit of the station registry against geography and naming.

Reports, for active stations:
  * province mismatch: the station's stored state differs from the admin-1 polygon that
    contains its coordinates (pak_boundaries/pakistan_adm1.geojson, via PostGIS);
  * duplicate names: several active stations with the same normalised name in one city;
  * test devices: names matching test|demo|dummy|sample;
  * stale: no reading in the last 30 days.

Writes verify/registry/<run>/{summary.json, mismatches.csv, duplicates.csv, test_devices.csv,
stale.csv} and prints the summary. Nothing is modified; apply changes with a reviewed one-off
SQL (see db_schema/oneoff/README.md).

Usage: set POSTGRES_* in the environment (root .env) and run
  python3 scripts/station_registry_audit.py [--adm1 pak_boundaries/pakistan_adm1.geojson]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

TEST_RE = re.compile(r"\b(test|demo|dummy|sample)\b", re.I)
ROOT = Path(__file__).resolve().parents[1]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adm1", default=str(ROOT / "pak_boundaries" / "pakistan_adm1.geojson"))
    ap.add_argument("--out", default=str(ROOT / "verify" / "registry"))
    ap.add_argument("--country", default="Pakistan")
    args = ap.parse_args()

    env = os.environ
    conn = psycopg2.connect(
        host=env["POSTGRES_SERVER"], port=env.get("POSTGRES_PORT", "5432"), dbname=env["POSTGRES_DB"],
        user=env["POSTGRES_USER"], password=env["POSTGRES_PASSWORD"], sslmode=env.get("PGSSLMODE", "require"),
    )
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) / run
    out.mkdir(parents=True, exist_ok=True)

    cur.execute("""
        SELECT s.station_id, s.name, s.active, s.lat, s.lon, COALESCE(p.code, '') AS provider,
               c.name AS city, st.name AS state, co.name AS country,
               (SELECT max(ts_utc) FROM readings r WHERE r.scope_type = 'station' AND r.scope_key = s.station_id
                  AND r.ts_utc > now() - interval '30 days') AS last_30d
        FROM stations s
        LEFT JOIN cities c ON c.id = s.city_id
        LEFT JOIN states st ON st.id = s.state_id
        LEFT JOIN countries co ON co.id = s.country_id
        LEFT JOIN providers p ON p.id = s.provider_id
        WHERE s.active = TRUE AND co.name = %s
    """, (args.country,))
    stations = cur.fetchall()

    # Admin-1 containment via PostGIS (geometry built from the GeoJSON shipped in the repo)
    mismatches = []
    adm1_path = Path(args.adm1)
    postgis = True
    try:
        cur.execute("SELECT PostGIS_Version()")
    except Exception:
        postgis = False
    if postgis and adm1_path.exists():
        gj = json.loads(adm1_path.read_text())
        polys = []
        for f in gj.get("features", []):
            name = f.get("properties", {}).get("shapeName") or f.get("properties", {}).get("NAME_1") or ""
            polys.append((name, json.dumps(f["geometry"])))
        for s in stations:
            if s["lat"] is None or s["lon"] is None:
                continue
            found = None
            for name, geom in polys:
                cur.execute("SELECT ST_Contains(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), ST_SetSRID(ST_Point(%s, %s), 4326))", (geom, float(s["lon"]), float(s["lat"])))
                if cur.fetchone()["st_contains"]:
                    found = name
                    break
            stored = norm(s["state"] or "")
            if found and norm(found) != stored and norm(found) not in stored and stored not in norm(found):
                mismatches.append({**s, "polygon_admin1": found})
    else:
        print("note: PostGIS or adm1 file unavailable; province check skipped", file=sys.stderr)

    by_key: dict[tuple[str, str], list] = {}
    for s in stations:
        by_key.setdefault((norm(s["city"] or ""), norm(s["name"])), []).append(s)
    duplicates = [s for group in by_key.values() if len(group) > 1 for s in group]
    tests = [s for s in stations if TEST_RE.search(s["name"] or "")]
    stale = [s for s in stations if s["last_30d"] is None]

    def write(name: str, rows: list, extra: list[str] = []):
        cols = ["station_id", "name", "provider", "city", "state", "country", "lat", "lon", "last_30d"] + extra
        with open(out / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in cols})

    write("mismatches.csv", mismatches, ["polygon_admin1"])
    write("duplicates.csv", duplicates)
    write("test_devices.csv", tests)
    write("stale.csv", stale)
    summary = {
        "run": run, "country": args.country, "active_stations": len(stations),
        "province_mismatches": len(mismatches), "duplicate_name_rows": len(duplicates),
        "test_devices": len(tests), "stale_30d": len(stale), "postgis_check": postgis and adm1_path.exists(),
        "out": str(out),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
