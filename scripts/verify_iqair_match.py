#!/usr/bin/env python3
"""
Read-only check that what hawanama.org shows matches what IQAir reports, station by station.

For every active IQAir-backed station in the database it:
  1. fetches IQAir /v2/station once (paced; never during the :55-:20 ingest window unless --skip-window-check),
     archives the credential-stripped payload in the same layout as scripts/iqair_shift_probe.py
     (so `iqair_shift_probe.py compare --out <out>/probe` works across runs),
  2. compares IQAir `current.pollution` (hour H, aqius, p2.conc) with the public API map row
     (/api/v1/dashboard/stations: aqi_raw, pm25, last_reading) and the popup row
     (/api/v1/dashboard/stations/{id}/current), and classifies the station:
        match            same hour, same AQI, same round(pm25)
        pending_ingest   IQAir hour is newer than the site hour and the :15 run for it has not completed yet
        stale            site hour older than IQAir hour by >= 1 h after the run should have landed
        value_mismatch   same hour, different AQI / PM2.5
        site_ahead       site hour newer than IQAir hour (timestamp shift symptom)
        weather_only_row site shows the station with no PM2.5 although a PM2.5 row exists in the DB
        site_missing     station not on the map (sub-reason in `note`)
        iqair_not_found / iqair_error / iqair_no_current
  3. compares IQAir `history.pollution` entries (T, aqius, p2.conc) with DB rows at T+1h (policy
     iqair_station_v1 stores history shifted +1h) and at T (no-shift hypothesis), tallying
     equal_at_T1 / equal_at_T / both / neither / db_missing — the evidence for the shift question,
  4. checks the read path is an identity: /history and /history/pm25 equal the DB rows (and emits
     RFC 3339 'Z' timestamps),
  5. for the --cities largest cities, IQAir /v2/city vs /api/v1/cities/{slug} and the city-scope DB row.

Output: <out>/stations.csv, cities.csv, summary.json, REPORT.md, probe/<station>/<fetched_at>.json.
Nothing is written to Postgres, GCS or the API. Credentials are read from the repo .env and never printed.

  python scripts/verify_iqair_match.py --label baseline            # Pakistan (default)
  python scripts/verify_iqair_match.py --all --label after-deploy  # every country
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
INGEST_MINUTE = 15          # Cloud Scheduler station-ingestion-hourly fires at :15
INGEST_SETTLE_MIN = 10      # the run takes ~5 min; allow 10 before calling a missing hour "stale"
PUBLIC_API = "https://hawanama-152782825429.asia-south1.run.app"
PROVIDER_CODES = ("airvisual", "airvisual-paqi", "airvisual-urban-unit", "other")

INVENTORY_SQL = """
SELECT st.station_id, st.name, st.lat, st.lon, p.code AS provider_code,
       st.metadata_json->>'iqair_station_name' AS iq_name,
       st.metadata_json->>'iqair_city'         AS iq_city,
       st.metadata_json->>'iqair_state'        AS iq_state,
       st.metadata_json->>'iqair_country'      AS iq_country,
       c.name AS city, c.id AS city_id,
       COALESCE(s_direct.name, s_via_city.name) AS state,
       COALESCE(co_direct.name, co_via_state.name) AS country
FROM stations st
JOIN providers p ON p.id = st.provider_id
LEFT JOIN cities c ON c.id = st.city_id
LEFT JOIN states s_direct ON s_direct.id = st.state_id
LEFT JOIN states s_via_city ON s_via_city.id = c.state_id
LEFT JOIN countries co_direct ON co_direct.id = st.country_id
LEFT JOIN countries co_via_state ON co_via_state.id = COALESCE(s_direct.country_id, s_via_city.country_id)
WHERE st.active = true AND p.code = ANY($1::text[])
ORDER BY country, city, st.name
"""

READINGS_SQL = """
SELECT scope_key, ts_utc, pm25, aqi_us, temp_c, qc_state, source, raw IS NOT NULL AS has_raw
FROM readings
WHERE scope_type = $1 AND scope_key = ANY($2::text[]) AND ts_utc > now() - interval '72 hours'
ORDER BY scope_key, ts_utc
"""


def load_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def db_url(env: Dict[str, str]) -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return (f"postgresql://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}@{env['POSTGRES_SERVER']}:"
            f"{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}?sslmode=require")


def floor_hour(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def parse_any_ts(s: Any) -> Optional[datetime]:
    """Accept IQAir 'Z', the API's correct 'Z', the API's broken '+00:00Z', and naive isoformat."""
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("+00:00Z"):
        t = t[:-1]
    elif t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:80]


def city_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def num_eq(a: Any, b: Any, nd: int = 0) -> Optional[bool]:
    if a is None or b is None:
        return None
    try:
        return round(float(a), nd) == round(float(b), nd)
    except (TypeError, ValueError):
        return None


def run_landed(h: datetime, now: datetime) -> bool:
    """True once the :15 ingest that would carry IQAir hour `h` should have finished."""
    return now >= h + timedelta(minutes=INGEST_MINUTE + INGEST_SETTLE_MIN)


class Verifier:
    def __init__(self, args):
        self.args = args
        self.now = datetime.now(timezone.utc)
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.env = load_env()
        self.station_rows: List[Dict[str, Any]] = []
        self.city_rows: List[Dict[str, Any]] = []
        self.series = Counter()
        self.api_format = Counter()
        self.errors: List[str] = []

    # ------------------------------------------------------------------ data sources
    async def db(self):
        import asyncpg
        return await asyncpg.connect(db_url(self.env))

    async def inventory(self, conn) -> List[Dict[str, Any]]:
        rows = [dict(r) for r in await conn.fetch(INVENTORY_SQL, list(PROVIDER_CODES))]
        if not self.args.all:
            rows = [r for r in rows if (r["country"] or "").lower() == self.args.country.lower()]
        if self.args.limit:
            rows = rows[: self.args.limit]
        for r in rows:
            r["station_id"] = r["station_id"].strip()
        return rows

    async def readings(self, conn, scope_type: str, keys: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for i in range(0, len(keys), 500):
            for r in await conn.fetch(READINGS_SQL, scope_type, keys[i:i + 500]):
                d = dict(r)
                d["ts_utc"] = d["ts_utc"].astimezone(timezone.utc)
                out[d["scope_key"].strip()].append(d)
        return out

    async def api_get(self, http, path: str, **params) -> Tuple[int, Any]:
        try:
            r = await http.get(f"{self.args.api}/api/v1{path}", params=params or None, timeout=60)
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None
        except Exception as exc:  # network
            self.errors.append(f"GET {path}: {type(exc).__name__}: {exc}")
            return 0, None

    # ------------------------------------------------------------------ station check
    async def check_station(self, st: Dict[str, Any], client, http, site_map: Dict[str, Any],
                            db_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        from app.ingestion.raw_archive import redact
        from app.ingestion.temporal import TEMPORAL_POLICIES, extract_iqair_rows
        from app.services.ingestion.iqair_service import (IQAirError, StationNotFound, FeatureNotAvailable,
                                                          RateLimited, Unauthorized)
        sid = st["station_id"]
        row: Dict[str, Any] = {
            "station_id": sid, "name": st["name"], "provider": st["provider_code"], "city": st["city"],
            "state": st["state"], "country": st["country"], "iqair_name": st["iq_name"] or st["name"],
            "cls": "", "note": "", "iq_hour": "", "iq_aqi": "", "iq_pm25": "", "iq_weather_hour": "",
            "site_hour": "", "site_aqi": "", "site_pm25": "", "popup_hour": "", "popup_aqi": "", "popup_pm25": "",
            "db_hour": "", "db_aqi": "", "db_pm25": "", "db_newest_hour": "", "db_newest_has_pm25": "",
            "hist_n": 0, "eq_T1": 0, "eq_T": 0, "eq_both": 0, "neither": 0, "db_null": 0, "db_missing": 0,
            "policy_rows": 0, "policy_eq": 0, "policy_diff": 0, "policy_missing": 0,
            "api_hist_identity": "", "api_pm25_identity": "", "api_ts_format": "",
            "raw_populated": any(r["has_raw"] for r in db_rows),
        }
        # ---- IQAir (same lookup order as DataIngestionTask._fetch_one: exact state, then state aliases)
        from app.ingestion.tasks.data_ingestion import _state_aliases
        name_, city_, state_, country_ = (st["iq_name"] or st["name"], st["iq_city"] or st["city"],
                                          st["iq_state"] or st["state"], st["iq_country"] or st["country"])
        try:
            env = None
            for state_try in (_state_aliases(state_, country_) or [state_]):
                try:
                    env = await client.fetch_station(station=name_, city=city_, state=state_try, country=country_)
                    if state_try != state_:
                        row["note"] = f"found under state alias '{state_try}'"
                    break
                except StationNotFound:
                    continue
            if env is None:
                raise StationNotFound(f"station_not_found ({name_}, {city_}, {state_})")
        except StationNotFound as exc:
            # Not on IQAir. If the site does not show it either (no row in 6 h) the two agree: absent_both.
            fresh = any(r["ts_utc"] > self.now - timedelta(hours=6) for r in db_rows)
            if sid not in site_map and not fresh:
                row["cls"], row["note"] = "absent_both", "not on IQAir, not on the site, no DB row in 6 h (still active=true)"
            else:
                row["cls"], row["note"] = "iqair_not_found", f"IQAir: {exc}; site shows it={sid in site_map}; fresh db row={fresh}"[:160]
            return row
        except FeatureNotAvailable as exc:
            row["cls"], row["note"] = "iqair_error", f"feature_not_available: {exc}"[:160]; return row
        except (RateLimited, Unauthorized) as exc:
            row["cls"], row["note"] = "iqair_error", f"{type(exc).__name__}: {exc}"[:160]
            self.errors.append(f"{sid}: {type(exc).__name__}: {exc}"); raise
        except IQAirError as exc:
            row["cls"], row["note"] = "iqair_error", f"{type(exc).__name__}: {exc}"[:160]; return row
        data = env.data or {}
        spec = f"{st['iq_name'] or st['name']}|{st['iq_city'] or st['city']}|{st['iq_state'] or st['state']}|{st['iq_country'] or st['country']}"
        d = self.out / "probe" / slug(spec)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{env.fetched_at:%Y%m%dT%H%M%SZ}.json").write_text(json.dumps(
            {"fetched_at": env.fetched_at.isoformat(), "station": spec, "station_id": sid, "payload": redact(data)},
            ensure_ascii=False))
        cur = (data.get("current") or {}).get("pollution") or {}
        curw = (data.get("current") or {}).get("weather") or {}
        iq_ts = parse_any_ts(cur.get("ts"))
        if iq_ts is None:
            row["cls"], row["note"] = "iqair_no_current", "no current.pollution.ts"; return row
        H = floor_hour(iq_ts)
        iq_aqi = cur.get("aqius")
        iq_pm = ((cur.get("p2") or {}).get("conc")) if isinstance(cur.get("p2"), dict) else None
        wts = parse_any_ts(curw.get("ts"))
        row.update(iq_hour=H.isoformat(), iq_aqi=iq_aqi, iq_pm25=iq_pm, iq_weather_hour=floor_hour(wts).isoformat() if wts else "")

        # ---- DB
        by_hour = {floor_hour(r["ts_utc"]): r for r in db_rows}
        pm_rows = [r for r in db_rows if r["pm25"] is not None or r["aqi_us"] is not None]
        newest = db_rows[-1] if db_rows else None
        newest_pm = pm_rows[-1] if pm_rows else None
        if newest:
            row["db_newest_hour"] = floor_hour(newest["ts_utc"]).isoformat()
            row["db_newest_has_pm25"] = newest["pm25"] is not None
        if newest_pm:
            row.update(db_hour=floor_hour(newest_pm["ts_utc"]).isoformat(), db_aqi=newest_pm["aqi_us"], db_pm25=newest_pm["pm25"])

        # ---- history vs DB (shift evidence)
        for h in (data.get("history") or {}).get("pollution") or []:
            T = parse_any_ts(h.get("ts"))
            if T is None:
                continue
            T = floor_hour(T)
            a = h.get("aqius")
            r1, r0 = by_hour.get(T + timedelta(hours=1)), by_hour.get(T)
            e1 = r1 is not None and num_eq(a, r1["aqi_us"]) is True
            e0 = r0 is not None and num_eq(a, r0["aqi_us"]) is True
            row["hist_n"] += 1
            if e1 and e0: row["eq_both"] += 1
            elif e1: row["eq_T1"] += 1
            elif e0: row["eq_T"] += 1
            elif r1 is None and r0 is None: row["db_missing"] += 1
            elif (r1 is None or r1["aqi_us"] is None) and (r0 is None or r0["aqi_us"] is None): row["db_null"] += 1  # weather-only rows only
            else: row["neither"] += 1
        for k in ("hist_n", "eq_T1", "eq_T", "eq_both", "neither", "db_null", "db_missing"):
            self.series[k] += row[k]

        # ---- rows the canonical policy would write vs what the DB holds
        try:
            parsed = client.parse_station_data(data)
            res = extract_iqair_rows(parsed, scope_type="station", scope_key=sid, policy=TEMPORAL_POLICIES["iqair_station_v1"])
            for pr in res.rows:
                ts = floor_hour(pr["ts_utc"])
                if ts > self.now:  # future rows are rejected by validation; ignore
                    continue
                if pr.get("pm25") is None and pr.get("aqi_us") is None:
                    continue
                row["policy_rows"] += 1
                dbr = by_hour.get(ts)
                if dbr is None:
                    row["policy_missing"] += 1
                elif num_eq(pr.get("aqi_us"), dbr["aqi_us"]) is True and (num_eq(pr.get("pm25"), dbr["pm25"], 1) in (True, None)):
                    row["policy_eq"] += 1
                else:
                    row["policy_diff"] += 1
        except Exception as exc:
            row["note"] += f" policy_extract_error:{type(exc).__name__}"

        # ---- site: map row and popup row
        m = site_map.get(sid)
        if m:
            sh = parse_any_ts(m.get("last_reading"))
            row.update(site_hour=floor_hour(sh).isoformat() if sh else "", site_aqi=m.get("aqi_raw"), site_pm25=m.get("pm25"))
        if not self.args.no_popup:
            code, body = await self.api_get(http, f"/dashboard/stations/{sid}/current")
            if code == 200 and body:
                ph = parse_any_ts(body.get("last_update"))
                row.update(popup_hour=floor_hour(ph).isoformat() if ph else "", popup_aqi=body.get("aqi_us"), popup_pm25=body.get("main_value"))
                self.api_format["current_last_update_Z" if Z_RE.match(body.get("last_update") or "") else "current_last_update_bad"] += 1

        # ---- read-path identity: /history & /history/pm25 == DB rows
        if not self.args.no_history:
            code, hist = await self.api_get(http, f"/dashboard/stations/{sid}/history", hours=48)
            code2, hpm = await self.api_get(http, f"/dashboard/stations/{sid}/history/pm25", hours=48)
            if code == 200 and isinstance(hist, list):
                api = {floor_hour(parse_any_ts(x["timestamp_utc"])): x.get("aqi_us") for x in hist if parse_any_ts(x.get("timestamp_utc"))}
                dbm = {floor_hour(r["ts_utc"]): (int(r["aqi_us"]) if r["aqi_us"] is not None else None)
                       for r in db_rows if r["ts_utc"] > self.now - timedelta(hours=48)}
                row["api_hist_identity"] = "ok" if api == dbm else f"diff:{len(set(api.items()) ^ set(dbm.items()))}"
                fmt_ok = all(Z_RE.match(x.get("timestamp_utc") or "") for x in hist)
                row["api_ts_format"] = "Z" if fmt_ok else "bad"
                self.api_format["history_ts_Z" if fmt_ok else "history_ts_bad"] += 1
            if code2 == 200 and isinstance(hpm, list):
                api = {floor_hour(parse_any_ts(x["timestamp_utc"])): (round(float(x["pm25"]), 1) if x.get("pm25") is not None else None)
                       for x in hpm if parse_any_ts(x.get("timestamp_utc"))}
                dbm = {floor_hour(r["ts_utc"]): (round(float(r["pm25"]), 1) if r["pm25"] is not None else None)
                       for r in db_rows if r["ts_utc"] > self.now - timedelta(hours=48)}
                row["api_pm25_identity"] = "ok" if api == dbm else f"diff:{len(set(api.items()) ^ set(dbm.items()))}"

        # ---- classify
        site_h = parse_any_ts(row["site_hour"]) if row["site_hour"] else None
        if not m:
            if newest_pm and newest_pm["ts_utc"] > self.now - timedelta(hours=6):
                row["cls"], row["note"] = "site_missing", "db has a fresh pm25 row but map omits the station"
            elif newest and newest["ts_utc"] > self.now - timedelta(hours=6):
                row["cls"], row["note"] = "site_missing", "only weather-only rows in the last 6 h"
            elif not db_rows:
                row["cls"], row["note"] = "site_missing", "no DB rows in 72 h (not ingested)"
            else:
                row["cls"], row["note"] = "site_missing", f"db newest {row['db_newest_hour']} older than 6 h"
            return row
        if m.get("pm25") is None and m.get("aqi_raw") is None:
            row["cls"], row["note"] = "weather_only_row", "map row has no pm25/aqi (newest DB row is weather-only)"
            return row
        if site_h is None:
            row["cls"], row["note"] = "site_missing", "map row without last_reading"; return row
        if site_h == H:
            if num_eq(iq_aqi, m.get("aqi_raw")) is True and (num_eq(iq_pm, m.get("pm25")) in (True, None)):
                row["cls"] = "match"
            else:
                row["cls"], row["note"] = "value_mismatch", f"iqair aqi={iq_aqi} pm={iq_pm} site aqi={m.get('aqi_raw')} pm={m.get('pm25')}"
        elif site_h < H:
            lag = int((H - site_h).total_seconds() // 3600)
            if not run_landed(H, self.now):
                row["cls"], row["note"] = "pending_ingest", f"iqair {H:%H:%M}Z not yet ingested (next run :15); site at {site_h:%H:%M}Z"
            else:
                # the site may still hold the same value at an older hour: say so
                same = "same values" if num_eq(iq_aqi, m.get("aqi_raw")) else "different values"
                row["cls"], row["note"] = "stale", f"site lags {lag} h ({same})"
        else:
            row["cls"], row["note"] = "site_ahead", f"site {site_h:%H:%M}Z is newer than iqair {H:%H:%M}Z"
        return row

    # ------------------------------------------------------------------ city check
    async def check_city(self, c: Dict[str, Any], client, http, city_db: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        from app.services.ingestion.iqair_service import IQAirError
        key = f"{c['country']}|{c['state']}|{c['city']}".lower()
        row = {"city": c["city"], "state": c["state"], "stations": c["n"], "scope_key": key, "cls": "", "note": "",
               "iq_hour": "", "iq_aqi": "", "iq_pm25": "", "db_hour": "", "db_aqi": "", "db_pm25": "",
               "site_avg_aqi": "", "site_last_update": "", "site_station_count": "", "site_hist_hours": "", "site_hist_format": ""}
        try:
            env = await client.fetch_city(city=c["city"], state=c["state"], country=c["country"])
        except IQAirError as exc:
            row["cls"], row["note"] = "iqair_error", f"{type(exc).__name__}: {exc}"[:160]; return row
        cur = ((env.data or {}).get("current") or {}).get("pollution") or {}
        H = parse_any_ts(cur.get("ts"))
        H = floor_hour(H) if H else None
        iq_pm = ((cur.get("p2") or {}).get("conc")) if isinstance(cur.get("p2"), dict) else None
        row.update(iq_hour=H.isoformat() if H else "", iq_aqi=cur.get("aqius"), iq_pm25=iq_pm)
        rows = [r for r in city_db.get(key, []) if r["aqi_us"] is not None]
        if rows:
            row.update(db_hour=floor_hour(rows[-1]["ts_utc"]).isoformat(), db_aqi=rows[-1]["aqi_us"], db_pm25=rows[-1]["pm25"])
        code, body = await self.api_get(http, f"/cities/{city_slug(c['city'])}")
        if code == 200 and body:
            row.update(site_avg_aqi=body.get("avg_aqi"), site_last_update=body.get("last_update"), site_station_count=body.get("station_count"))
        code, hist = await self.api_get(http, f"/cities/{city_slug(c['city'])}/historical", hours=48)
        if code == 200 and isinstance(hist, dict):
            data = hist.get("data") or hist.get("historical") or []
            row["site_hist_hours"] = len(data) if isinstance(data, list) else ""
        # classify on the city-scope row (what /cities/{slug} uses for avg_aqi when fresh)
        if H is None:
            row["cls"] = "iqair_no_current"
        elif not rows:
            row["cls"], row["note"] = "site_missing", "no city-scope rows in 72 h"
        else:
            dbh = floor_hour(rows[-1]["ts_utc"])
            if dbh == H:
                row["cls"] = "match" if num_eq(cur.get("aqius"), rows[-1]["aqi_us"]) else "value_mismatch"
            elif dbh < H:
                row["cls"] = "pending_ingest" if not run_landed(H, self.now) else "stale"
            else:
                row["cls"] = "site_ahead"
            if body and body.get("avg_aqi") is not None and rows[-1]["ts_utc"] > self.now - timedelta(hours=6):
                if num_eq(body.get("avg_aqi"), rows[-1]["aqi_us"]) is False:
                    row["note"] += f" api avg_aqi={body.get('avg_aqi')} != db {rows[-1]['aqi_us']}"
        return row

    # ------------------------------------------------------------------ driver
    async def run(self) -> int:
        import httpx
        os.environ.setdefault("IQAIR_MAX_CALLS_PER_MIN", str(self.args.rate))
        os.environ.setdefault("IQAIR_CONCURRENCY", str(self.args.concurrency))
        os.environ.setdefault("IQAIR_CREDENTIAL_ALIAS", "verify-local")
        # Settings forbids unknown keys and reads ./.env, so pass only what it needs and run from a
        # directory without a .env. Values are never printed.
        for k in ("POSTGRES_SERVER", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT", "IQAIR_API_KEY"):
            if k in self.env:
                os.environ.setdefault(k, self.env[k])
        os.chdir(self.out)
        from app.services.ingestion.iqair_service import IQAirClient
        from app.ingestion.http import configure_logging
        configure_logging("WARNING", secrets=[self.env.get("IQAIR_API_KEY")])
        client = IQAirClient(quota=None)

        conn = await self.db()
        try:
            stations = await self.inventory(conn)
            print(f"[verify] {len(stations)} active stations ({'all countries' if self.args.all else self.args.country}); now={self.now:%Y-%m-%dT%H:%M}Z")
            minute = self.now.minute
            if not self.args.skip_window_check and (minute >= 55 or minute < 20):
                print("[verify] refusing to start inside the :55-:20 ingest window (use --skip-window-check)"); return 2
            est = len(stations) / max(1, self.args.rate)
            if not self.args.skip_window_check and minute + est > 55:
                print(f"[verify] {est:.1f} min of fetches would cross :55; refusing (use --skip-window-check or --limit)"); return 2
            db_rows = await self.readings(conn, "station", [s["station_id"] for s in stations])
            counts = Counter(s["city"] for s in stations if s["city"])
            cities = []
            for name, n in counts.most_common(self.args.cities):
                s0 = next(s for s in stations if s["city"] == name)
                cities.append({"city": name, "state": s0["state"], "country": s0["country"], "n": n})
            city_db = await self.readings(conn, "city", [f"{c['country']}|{c['state']}|{c['city']}".lower() for c in cities])
        finally:
            await conn.close()

        async with httpx.AsyncClient() as http:
            code, body = await self.api_get(http, "/dashboard/stations")
            if code != 200 or not body:
                print(f"[verify] /dashboard/stations failed: HTTP {code}"); return 1
            site_map = {s["id"].strip(): s for s in body.get("stations", [])}
            code, health = await self.api_get(http, "/health/")
            prov = (health or {}).get("provenance") or {}
            print(f"[verify] site map rows={len(site_map)} api git_sha={prov.get('git_sha')} environment={(health or {}).get('environment')}")

            sem = asyncio.Semaphore(self.args.concurrency)
            t0 = time.time()
            done = 0

            async def one(st):
                nonlocal done
                async with sem:
                    try:
                        r = await self.check_station(st, client, http, site_map, db_rows.get(st["station_id"], []))
                    except Exception as exc:
                        r = {"station_id": st["station_id"], "name": st["name"], "provider": st["provider_code"], "city": st["city"],
                             "state": st["state"], "country": st["country"], "cls": "iqair_error", "note": f"{type(exc).__name__}: {exc}"[:160]}
                    done += 1
                    if done % 100 == 0:
                        print(f"[verify] {done}/{len(stations)} stations in {time.time() - t0:.0f}s")
                    return r

            self.station_rows = await asyncio.gather(*(one(s) for s in stations))
            for c in cities:
                self.city_rows.append(await self.check_city(c, client, http, city_db))
        return self.write(site_map, prov, health)

    def write(self, site_map, prov, health) -> int:
        cls = Counter(r["cls"] for r in self.station_rows)
        by_country = defaultdict(Counter)
        for r in self.station_rows:
            by_country[r.get("country") or "?"][r["cls"]] += 1
        policy = Counter()
        for r in self.station_rows:
            for k in ("policy_rows", "policy_eq", "policy_diff", "policy_missing"):
                policy[k] += r.get(k) or 0
        ident = Counter((r.get("api_hist_identity") or "n/a").split(":")[0] for r in self.station_rows)
        ident_pm = Counter((r.get("api_pm25_identity") or "n/a").split(":")[0] for r in self.station_rows)
        fresh = [r for r in self.station_rows if r.get("iq_hour") and parse_any_ts(r["iq_hour"]) > self.now - timedelta(hours=6)]
        good = sum(1 for r in fresh if r["cls"] in ("match", "pending_ingest"))
        absent = sum(1 for r in self.station_rows if r["cls"] == "absent_both")
        summary = {
            "label": self.args.label, "run_at": self.now.isoformat(), "api": self.args.api,
            "api_git_sha": prov.get("git_sha"), "api_environment": (health or {}).get("environment"),
            "scope": "all" if self.args.all else self.args.country,
            "stations_checked": len(self.station_rows), "site_map_rows": len(site_map),
            "classes": dict(cls), "by_country": {k: dict(v) for k, v in by_country.items()},
            "iqair_fresh_6h": len(fresh), "fresh_match_or_pending": good, "absent_both": absent,
            "fresh_match_pct": round(100.0 * good / len(fresh), 2) if fresh else None,
            "series_vs_db": dict(self.series), "policy_rows_vs_db": dict(policy),
            "api_history_identity": dict(ident), "api_pm25_identity": dict(ident_pm), "api_timestamp_format": dict(self.api_format),
            "raw_populated_stations": sum(1 for r in self.station_rows if r.get("raw_populated")),
            "cities": {"checked": len(self.city_rows), "classes": dict(Counter(r["cls"] for r in self.city_rows))},
            "errors": self.errors[:50],
        }
        (self.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
        if self.station_rows:
            keys = list(self.station_rows[0].keys())
            for r in self.station_rows:
                for k in r:
                    if k not in keys: keys.append(k)
            with (self.out / "stations.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(self.station_rows)
        if self.city_rows:
            with (self.out / "cities.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(self.city_rows[0].keys())); w.writeheader(); w.writerows(self.city_rows)
        self.report(summary)
        print(json.dumps({k: summary[k] for k in ("classes", "fresh_match_pct", "series_vs_db", "policy_rows_vs_db",
                                                   "api_history_identity", "api_timestamp_format")}, indent=1, default=str))
        print(f"[verify] wrote {self.out}")
        return 0 if summary["fresh_match_pct"] == 100.0 else 1

    def report(self, s: Dict[str, Any]) -> None:
        L = [f"# IQAir ↔ hawanama.org verification — {s['label'] or ''}", "",
             f"- run at: `{s['run_at']}` against `{s['api']}` (git_sha `{s['api_git_sha']}`, environment `{s['api_environment']}`)",
             f"- scope: {s['scope']}; stations checked: {s['stations_checked']}; map rows on site: {s['site_map_rows']}",
             f"- stations with IQAir data in the last 6 h: {s['iqair_fresh_6h']}; match or pending_ingest: {s['fresh_match_or_pending']} ({s['fresh_match_pct']} %)",
             "", "## Classes", "", "| class | stations |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in sorted(s["classes"].items(), key=lambda kv: -kv[1])]
        L += ["", "## By country", "", "| country | " + " | ".join(sorted(s["classes"])) + " |", "|---|" + "---|" * len(s["classes"])]
        for c, cc in sorted(s["by_country"].items()):
            L.append(f"| {c} | " + " | ".join(str(cc.get(k, 0)) for k in sorted(s["classes"])) + " |")
        sv = s["series_vs_db"]
        L += ["", "## IQAir history vs DB rows (shift evidence)", "",
              f"- history entries compared: {sv.get('hist_n', 0)}",
              f"- equal only at T+1h (what policy iqair_station_v1 stores): {sv.get('eq_T1', 0)}",
              f"- equal only at T (no shift): {sv.get('eq_T', 0)}",
              f"- equal at both (value repeated): {sv.get('eq_both', 0)}",
              f"- DB row exists but value differs at both: {sv.get('neither', 0)}",
              f"- DB has only weather-only (NULL AQI) rows at T and T+1: {sv.get('db_null', 0)}",
              f"- no DB row at T or T+1: {sv.get('db_missing', 0)}", "",
              f"- rows the canonical policy would write vs DB: {s['policy_rows_vs_db']}", "",
              "## Read path", "",
              f"- /history == DB: {s['api_history_identity']}", f"- /history/pm25 == DB: {s['api_pm25_identity']}",
              f"- timestamp format: {s['api_timestamp_format']}",
              f"- stations whose rows carry `raw` provenance: {s['raw_populated_stations']}", "",
              "## Cities", "", f"- {s['cities']}", ""]
        bad = [r for r in self.station_rows if r["cls"] not in ("match", "pending_ingest", "absent_both")]
        if bad:
            L += ["## Non-matching stations (first 60)", "", "| station | city | class | iqair hour / aqi / pm | site hour / aqi / pm | db hour / aqi / pm | note |", "|---|---|---|---|---|---|---|"]
            for r in bad[:60]:
                L.append(f"| {r.get('name')} ({r.get('station_id')}) | {r.get('city')} | {r['cls']} | {r.get('iq_hour','')[:16]} / {r.get('iq_aqi','')} / {r.get('iq_pm25','')} "
                         f"| {str(r.get('site_hour',''))[:16]} / {r.get('site_aqi','')} / {r.get('site_pm25','')} | {str(r.get('db_hour',''))[:16]} / {r.get('db_aqi','')} / {r.get('db_pm25','')} | {r.get('note','')} |")
        if self.city_rows:
            L += ["", "## City rows", "", "| city | class | iqair hour / aqi | db hour / aqi | site avg_aqi / last_update | note |", "|---|---|---|---|---|---|"]
            for r in self.city_rows:
                L.append(f"| {r['city']} | {r['cls']} | {r['iq_hour'][:16]} / {r['iq_aqi']} | {str(r['db_hour'])[:16]} / {r['db_aqi']} | {r['site_avg_aqi']} / {r['site_last_update']} | {r['note']} |")
        if s["errors"]:
            L += ["", "## Errors", ""] + [f"- {e}" for e in s["errors"]]
        (self.out / "REPORT.md").write_text("\n".join(L) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--country", default="Pakistan")
    ap.add_argument("--all", action="store_true", help="every country instead of --country")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cities", type=int, default=10)
    ap.add_argument("--rate", type=int, default=150, help="IQAir calls per minute (local pacing)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--api", default=PUBLIC_API)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-popup", action="store_true", help="skip /dashboard/stations/{id}/current")
    ap.add_argument("--no-history", action="store_true", help="skip the /history identity checks")
    ap.add_argument("--skip-window-check", action="store_true")
    args = ap.parse_args()
    if not args.out:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.out = str(ROOT / "verify" / (f"{args.label}-{stamp}" if args.label else stamp))
    return asyncio.run(Verifier(args).run())


if __name__ == "__main__":
    sys.exit(main())
