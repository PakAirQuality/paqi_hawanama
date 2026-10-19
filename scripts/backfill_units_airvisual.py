#!/usr/bin/env python3
"""
Fill units_pm25/units_pm10 = 'µg/m³' on historical airvisual rows that have a
value but NULL units, one UTC day at a time. OPTIONAL and reversible; nothing
else is touched (gas units are not attested and stay NULL).

  python scripts/backfill_units_airvisual.py --dry-run --from 2025-09-01 --to 2026-10-01
  python scripts/backfill_units_airvisual.py --from 2025-09-01 --to 2025-09-08 --yes

Needs DATABASE_URL (postgresql+asyncpg://...) or the POSTGRES_* variables the API uses.
Prints a per-day manifest of affected row counts to stdout for the record.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

COUNT_SQL = text("""
    SELECT
      count(*) FILTER (WHERE pm25 IS NOT NULL AND units_pm25 IS NULL) AS pm25_missing,
      count(*) FILTER (WHERE pm10 IS NOT NULL AND units_pm10 IS NULL) AS pm10_missing
    FROM readings
    WHERE source = 'airvisual' AND ts_utc >= :d0 AND ts_utc < :d1
""")
UPDATE_SQL = {
    "pm25": text("UPDATE readings SET units_pm25 = 'µg/m³' WHERE source = 'airvisual' AND pm25 IS NOT NULL "
                 "AND units_pm25 IS NULL AND ts_utc >= :d0 AND ts_utc < :d1"),
    "pm10": text("UPDATE readings SET units_pm10 = 'µg/m³' WHERE source = 'airvisual' AND pm10 IS NOT NULL "
                 "AND units_pm10 IS NULL AND ts_utc >= :d0 AND ts_utc < :d1"),
}


def _url() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    from app.core.config import settings
    return settings.DATABASE_URL


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="d_from", required=True, type=date.fromisoformat)
    ap.add_argument("--to", dest="d_to", required=True, type=date.fromisoformat, help="exclusive")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="required to write")
    args = ap.parse_args()
    if not args.dry_run and not args.yes:
        print("refusing to write without --yes (or use --dry-run)")
        return 2
    engine = create_async_engine(_url())
    total = {"pm25": 0, "pm10": 0}
    try:
        day = args.d_from
        while day < args.d_to:
            d0 = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            d1 = d0 + timedelta(days=1)
            async with engine.begin() as conn:
                row = (await conn.execute(COUNT_SQL, {"d0": d0, "d1": d1})).first()
                n25, n10 = int(row[0] or 0), int(row[1] or 0)
                if not args.dry_run and (n25 or n10):
                    for k in ("pm25", "pm10"):
                        await conn.execute(UPDATE_SQL[k], {"d0": d0, "d1": d1})
            total["pm25"] += n25
            total["pm10"] += n10
            print(f"{day.isoformat()}  pm25_missing={n25:6d}  pm10_missing={n10:6d}  {'(dry run)' if args.dry_run else 'updated'}")
            day += timedelta(days=1)
    finally:
        await engine.dispose()
    print(f"TOTAL pm25={total['pm25']} pm10={total['pm10']} {'(dry run — nothing written)' if args.dry_run else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
