#!/usr/bin/env python3
"""Inspect the FIRMS aggregate store without the copilot: manifest, one day, a region series.

    python3 scripts/fire_agg_probe.py                      # manifest summary + suspect days
    python3 scripts/fire_agg_probe.py --day 2026-11-03     # that day's region rollup (from the store and from the CSV)
    python3 scripts/fire_agg_probe.py --region Pakistan --start 2026-10-01 --end 2026-11-04

Needs application default credentials for GCS; no database. Run from apps/api.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.fire_aggregates import AggStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day")
    ap.add_argument("--region", default="Pakistan")
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args()
    store = AggStore()
    m = store.manifest()
    days = m.get("days", {})
    print(f"built_at {m.get('built_at')}  days {len(days)}  low_confidence_from {m.get('low_confidence_from')}")
    print("suspect days:", m.get("suspect_days", [])[:20])
    if a.day:
        d = date.fromisoformat(a.day)
        daily = store.daily_regions()
        sel = daily[(daily["pk_day"] == d) & (daily["region_kind"].isin(["country", "province", "india_state"]))]
        print(sel[["region_kind", "region", "n_raw", "n_dedup_hn", "frp_dedup_hn", "n_day", "n_night"]].to_string(index=False))
        b = store.day_from_csv(d)
        print("from CSV:", b.info if b else None)
    if a.start and a.end:
        daily = store.daily_regions()
        sel = daily[(daily["region"] == a.region) & (daily["pk_day"] >= date.fromisoformat(a.start)) & (daily["pk_day"] <= date.fromisoformat(a.end))]
        print(sel[["pk_day", "n_raw", "n_dedup_hn", "frp_dedup_hn"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
