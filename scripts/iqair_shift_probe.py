#!/usr/bin/env python3
"""
IQAir history-timestamp probe.

The ingestion code shifts IQAir *history* pollution timestamps forward by one
hour (policy iqair_station_v1, see apps/api/app/ingestion/temporal.py) on an
undocumented assumption. This script collects the paired evidence needed to
confirm or reject that assumption, without touching the database:

  probe  : fetch /v2/station for the given stations now and archive the raw
           payload (credentials stripped) under --out/<station>/<fetched_at>.json
  compare: walk the archived payloads per station in time order and, for every
           consecutive pair, check whether the value that was `current` at hour H
           in the earlier fetch reappears in the later fetch's history labelled
           H (no lag), H-1 (one-hour lag — what the +1h shift assumes) or neither.

Run `probe` hourly (cron or --loop) for a day or two, then `compare`. Only after
the report shows a consistent pattern should a new TemporalPolicy be proposed.
This script never writes to Postgres or GCS.

Usage:
  python scripts/iqair_shift_probe.py probe --out ./probe --station "Name|City|State|Country" [...]
  python scripts/iqair_shift_probe.py probe --out ./probe --loop 3600 --station ...
  python scripts/iqair_shift_probe.py compare --out ./probe
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:80]


def _floor_hour(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


async def probe(args) -> int:
    from app.ingestion.raw_archive import redact
    from app.services.ingestion.iqair_service import IQAirClient, IQAirError

    client = IQAirClient(quota=None)
    out = Path(args.out)
    failures = 0
    for spec in args.station:
        name, city, state, country = (spec.split("|") + [None] * 4)[:4]
        try:
            env = await client.fetch_station(station=name, city=city, state=state, country=country)
        except IQAirError as exc:
            print(f"[probe] {spec}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        d = out / _slug(spec)
        d.mkdir(parents=True, exist_ok=True)
        fn = d / f"{env.fetched_at:%Y%m%dT%H%M%SZ}.json"
        fn.write_text(json.dumps({"fetched_at": env.fetched_at.isoformat(), "station": spec,
                                  "payload": redact(env.data)}, ensure_ascii=False))
        cur = ((env.data or {}).get("current") or {}).get("pollution") or {}
        print(f"[probe] {spec}: archived {fn.name} current.ts={cur.get('ts')} aqius={cur.get('aqius')}")
    return failures


def compare(args) -> int:
    out = Path(args.out)
    verdicts = Counter()
    per_station = defaultdict(Counter)
    same_hour_entries = Counter()
    for d in sorted(p for p in out.iterdir() if p.is_dir()):
        files = sorted(d.glob("*.json"))
        snaps = []
        for f in files:
            try:
                snaps.append(json.loads(f.read_text()))
            except Exception:
                continue
        for earlier, later in zip(snaps, snaps[1:]):
            cur = ((earlier["payload"].get("current") or {}).get("pollution") or {})
            if not cur.get("ts"):
                continue
            H = _floor_hour(_parse(cur["ts"]))
            cur_aqi = cur.get("aqius")
            cur_pm = (cur.get("p2") or {}).get("conc") if isinstance(cur.get("p2"), dict) else None
            hist = {(_floor_hour(_parse(h["ts"]))): h for h in ((later["payload"].get("history") or {}).get("pollution") or [])
                    if isinstance(h, dict) and h.get("ts")}
            # which history label carries the value that was 'current' at H?
            def matches(h):
                if not h:
                    return False
                hp = (h.get("p2") or {}).get("conc") if isinstance(h.get("p2"), dict) else None
                return h.get("aqius") == cur_aqi and (cur_pm is None or hp == cur_pm)
            at_H = matches(hist.get(H))
            at_Hm1 = matches(hist.get(H - timedelta(hours=1)))
            if at_H and not at_Hm1:
                v = "history_label_equals_current_hour (no lag)"
            elif at_Hm1 and not at_H:
                v = "history_label_is_current_minus_1h (lag: +1h shift justified)"
            elif at_H and at_Hm1:
                v = "ambiguous (both match)"
            else:
                v = "no_match (value revised or window moved)"
            verdicts[v] += 1
            per_station[d.name][v] += 1
            if H in hist:
                same_hour_entries[d.name] += 1
    print("== overall ==")
    for k, v in verdicts.most_common():
        print(f"  {v:5d}  {k}")
    print("== per station ==")
    for st, c in per_station.items():
        print(f"  {st}: {dict(c)}  history_entry_at_current_hour={same_hour_entries[st]}")
    print("\nInterpretation: if 'current_minus_1h' dominates, the +1h shift in iqair_station_v1 is")
    print("consistent with the provider; if 'equals_current_hour' dominates, propose iqair_station_v2")
    print("with shift 0 and re-derive ts from raw.prov.src_ts — never rewrite the archive blindly.")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--out", required=True)
    p.add_argument("--station", action="append", required=True, help='"Name|City|State|Country"')
    p.add_argument("--loop", type=int, default=0, help="repeat every N seconds (0 = once)")
    c = sub.add_parser("compare")
    c.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.cmd == "compare":
        return compare(args)
    while True:
        failures = await probe(args)
        if not args.loop:
            return 1 if failures else 0
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
