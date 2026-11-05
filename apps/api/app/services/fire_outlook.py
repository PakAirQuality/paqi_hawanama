"""
Smoke outlook per city: forecast winds × the fires seen in the last two Pakistan days.

For each city with coordinates and each lead day D+0…D+3 the outlook says where smoke would
come from and how much fire sits in that sector:
- wind: ECMWF IFS 0.25° via Open-Meteo's point API, hourly, aggregated per Pakistan day as a
  speed-weighted vector mean of the "from" direction, at 850 hPa (what the PM2.5 forecast model
  uses for transport) and at 10 m;
- upwind load (MW): the FRP of deduplicated high/nominal fires within 200 km whose bearing from
  the city lies within ±60° of the 850 hPa wind-from direction AND that the air can reach in a
  day at the forecast speed (distance ≤ speed × 24 h, speed floor 1 m/s);
- band: none < 100 MW, low 100–300, elevated 300–1,000 (the forecast model's fire-driver
  threshold), high 1,000–3,000, very_high > 3,000.
The fires are *carried forward*: the outlook assumes the fires seen yesterday and today keep
burning, which crop-residue fires do for days. It is a smoke-source outlook, not a PM2.5
forecast, and never an attribution.

Outputs: forecasts/smoke_outlook/latest.json and a dated copy, in the forecasts bucket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.services import fire_analytics as fa
from app.services import fire_regions as fr
from app.services.fire_aggregates import AggStore, _read_json, agg_store, default_bucket
from app.services.fires import PK_TZ

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs025"
HOURLY = "wind_speed_10m,wind_direction_10m,wind_speed_850hPa,wind_direction_850hPa"
LEADS = 4
FORECAST_DAYS = 4
RADIUS_KM = 200.0
CONE_HALF_DEG = 60.0
SPEED_FLOOR_MS = 1.0
REACH_HOURS = 24.0
DAYTIME_HOURS = range(6, 18)
BANDS: List[Tuple[str, float, float]] = [("none", 0, 100), ("low", 100, 300), ("elevated", 300, 1000), ("high", 1000, 3000), ("very_high", 3000, math.inf)]
ALERT_BANDS = ("high", "very_high")
OUTLOOK_PREFIX = "forecasts/smoke_outlook"
LATEST_PATH = f"{OUTLOOK_PREFIX}/latest.json"
STALE_HOURS = 6.0
FORECAST_MEMO_TTL_S = 600.0
TASK = "fires-outlook"

DEFINITIONS = {
    "wind": "ECMWF IFS 0.25° forecast (Open-Meteo point API), speed-weighted vector mean of the hourly 'from' direction over the Pakistan day; 850 hPa drives the outlook, 10 m is shown alongside",
    "upwind_load": "sum of FRP (MW) of deduplicated high/nominal fires within 200 km, inside ±60° of the 850 hPa wind-from direction, and within one day's transport at the forecast speed (speed floor 1 m/s)",
    "bands": "none < 100 MW; low 100–300; elevated 300–1,000 (the forecast model's fire-driver threshold); high 1,000–3,000; very_high > 3,000",
    "fires_carried_forward": "the fires seen on the latest two Pakistan days are assumed to keep burning through the outlook days; new fires are not predicted",
    "not_pm25": "a smoke-source outlook, not a PM2.5 forecast: stagnation, boundary-layer depth and local sources decide the concentration",
    "not_causation": fa.FIRE_DEFINITIONS["not_causation"],
}

CITIES_SQL = text("""
    SELECT c.id, c.name, st.name AS province, AVG(s.lat) AS lat, AVG(s.lon) AS lon, COUNT(*) AS stations
    FROM cities c
    JOIN countries co ON co.id = c.country_id
    LEFT JOIN states st ON st.id = c.state_id
    JOIN stations s ON s.city_id = c.id AND s.active = true AND s.lat IS NOT NULL AND s.lon IS NOT NULL
    WHERE co.name = 'Pakistan' AND c.active = true
    GROUP BY c.id, c.name, st.name
    HAVING COUNT(*) > 0
    ORDER BY c.name
""")


async def load_cities(db) -> List[Dict[str, Any]]:
    rows = (await db.execute(CITIES_SQL)).fetchall()
    return [{"id": int(r.id), "name": r.name, "province": r.province, "lat": round(float(r.lat), 4), "lon": round(float(r.lon), 4),
             "stations": int(r.stations)} for r in rows]


# ── forecast winds ─────────────────────────────────────────────────────────────

@dataclass
class DayWind:
    from_deg: Optional[float]
    speed_ms: Optional[float]
    day_from_deg: Optional[float]       # 06–18 PKT only
    day_speed_ms: Optional[float]
    n_hours: int

    def to_dict(self) -> Dict[str, Any]:
        return {"from_deg": self.from_deg, "from_compass": fr.compass(self.from_deg), "speed_ms": self.speed_ms,
                "day_from_deg": self.day_from_deg, "day_from_compass": fr.compass(self.day_from_deg), "day_speed_ms": self.day_speed_ms,
                "n_hours": self.n_hours}


def aggregate_hourly(times: List[str], speeds_kmh: List[Optional[float]], dirs_deg: List[Optional[float]]) -> Dict[date, DayWind]:
    """Per Pakistan day (the API answers in Asia/Karachi local time): vector means over 24 h and over daytime."""
    by_day: Dict[date, List[Tuple[int, float, float]]] = {}
    for t, s, d in zip(times, speeds_kmh, dirs_deg):
        if s is None or d is None:
            continue
        day = date.fromisoformat(t[:10])
        hour = int(t[11:13])
        by_day.setdefault(day, []).append((hour, float(d), float(s) / 3.6))
    out: Dict[date, DayWind] = {}
    for day, obs in by_day.items():
        fd, sp = fr.vector_mean_from_deg([o[1] for o in obs], [o[2] for o in obs])
        dobs = [o for o in obs if o[0] in DAYTIME_HOURS]
        dfd, dsp = fr.vector_mean_from_deg([o[1] for o in dobs], [o[2] for o in dobs]) if dobs else (None, None)
        out[day] = DayWind(fd, sp, dfd, dsp, len(obs))
    return out


_FORECAST_MEMO: Dict[Tuple[float, float], Tuple[float, Dict[str, Dict[date, DayWind]]]] = {}


async def fetch_city_forecast(http, lat: float, lon: float, *, days: int = FORECAST_DAYS) -> Dict[str, Dict[date, DayWind]]:
    """{'10m': {day: DayWind}, '850hPa': {...}} for the next `days` Pakistan days; memoised 10 min per point."""
    key = (round(lat, 2), round(lon, 2))
    hit = _FORECAST_MEMO.get(key)
    if hit and time.monotonic() - hit[0] < FORECAST_MEMO_TTL_S:
        return hit[1]
    params = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": HOURLY, "models": MODEL,
              "forecast_days": str(days), "timezone": "Asia/Karachi", "wind_speed_unit": "kmh"}
    last_exc: Optional[BaseException] = None
    for attempt in range(2):
        try:
            resp = await http.get(OPEN_METEO_URL, params=params, timeout=60.0)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            body = resp.json()
            h = body["hourly"]
            out = {"10m": aggregate_hourly(h["time"], h["wind_speed_10m"], h["wind_direction_10m"]),
                   "850hPa": aggregate_hourly(h["time"], h["wind_speed_850hPa"], h["wind_direction_850hPa"])}
            if len(_FORECAST_MEMO) >= 400:
                _FORECAST_MEMO.pop(next(iter(_FORECAST_MEMO)))
            _FORECAST_MEMO[key] = (time.monotonic(), out)
            return out
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 0:
                await asyncio.sleep(2.0)
    raise RuntimeError(f"Open-Meteo forecast failed: {type(last_exc).__name__}: {last_exc}")


# ── fires ──────────────────────────────────────────────────────────────────────

def recent_fires(store: AggStore, today: date) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Deduplicated high/nominal fires of today and yesterday (Pakistan days), with the pass window."""
    frames, info = [], {"days": [], "observation_period": None, "satellites": []}
    for d in (today - timedelta(days=1), today):
        built = store.day_from_csv(d)
        if built is None:
            continue
        info["days"].append(d.isoformat())
        op = (built.info.get("observation_period") or {})
        if op.get("end") and (info["observation_period"] is None or op["end"] > info["observation_period"]["end"]):
            info["observation_period"] = op
        info["satellites"] = sorted(set(info["satellites"]) | set(built.info.get("sources") or []))
        det = built.detections
        if len(det):
            frames.append(det[det["is_primary"] & det["grp_hn"]])
    fires = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["lat", "lon", "frp", "country", "district", "acq_utc", "pk_day"])
    return fires, info


# ── the outlook ────────────────────────────────────────────────────────────────

def band_for(load_mw: float) -> str:
    for name, lo, hi in BANDS:
        if lo <= load_mw < hi:
            return name
    return BANDS[-1][0]


def city_outlook(name: str, lat: float, lon: float, winds: Dict[str, Dict[date, DayWind]], fires: pd.DataFrame, *,
                 today: date, leads: int = LEADS) -> Dict[str, Any]:
    if len(fires):
        km = fr.haversine_km_vec(lat, lon, fires["lat"].to_numpy(), fires["lon"].to_numpy())
        brg = fr.bearing_deg(lat, lon, fires["lat"].to_numpy(), fires["lon"].to_numpy())
        near = fires.assign(km=km, bearing=brg)
        near = near[near["km"] <= RADIUS_KM]
    else:
        near = fires.assign(km=np.zeros(0), bearing=np.zeros(0)) if "km" not in fires else fires
    out_leads: List[Dict[str, Any]] = []
    for i in range(leads):
        d = today + timedelta(days=i)
        w850, w10 = winds.get("850hPa", {}).get(d), winds.get("10m", {}).get(d)
        lead: Dict[str, Any] = {"lead": f"D+{i}", "day": d.isoformat(), "wind_850": w850.to_dict() if w850 else None, "wind_10m": w10.to_dict() if w10 else None,
                                "fires_200km": int(len(near))}
        if w850 is None or w850.from_deg is None:
            lead.update({"status": "no_forecast", "band": None, "upwind_load_mw": None})
            out_leads.append(lead)
            continue
        speed = max(float(w850.speed_ms or 0.0), SPEED_FLOOR_MS)
        reach_km = speed * 3.6 * REACH_HOURS
        cone = fr.in_cone(near["bearing"].to_numpy(), w850.from_deg, CONE_HALF_DEG) if len(near) else np.zeros(0, dtype=bool)
        reach = (near["km"].to_numpy() <= reach_km) if len(near) else np.zeros(0, dtype=bool)
        sel = near[cone & reach] if len(near) else near
        load = float(sel["frp"].sum()) if len(sel) else 0.0
        cone10 = None
        if w10 is not None and w10.from_deg is not None and len(near):
            c10 = fr.in_cone(near["bearing"].to_numpy(), w10.from_deg, CONE_HALF_DEG)
            cone10 = round(float(near.loc[c10, "frp"].sum()), 1)
        top = []
        for _, f in sel.sort_values("frp", ascending=False).head(5).iterrows():
            top.append({"lat": round(float(f["lat"]), 4), "lon": round(float(f["lon"]), 4), "frp_mw": round(float(f["frp"]), 1),
                        "km": round(float(f["km"]), 1), "direction": fr.compass(float(f["bearing"])),
                        "district": f.get("district"), "country": fr.COUNTRY_LABELS.get(f["country"], f["country"]),
                        "transport_h": round(float(f["km"]) / (speed * 3.6), 1)})
        lead.update({
            "status": "ok", "upwind_load_mw": round(load, 1), "band": band_for(load),
            "cone_frp_mw": round(float(near.loc[cone, "frp"].sum()), 1) if len(near) else 0.0,
            "cone_frp_mw_10m": cone10, "fires_in_cone": int(cone.sum()) if len(near) else 0, "fires_reachable": int(len(sel)),
            "reach_km": round(reach_km), "by_country": {fr.COUNTRY_LABELS.get(c, c): int(n) for c, n in sel["country"].value_counts().items()} if len(sel) else {},
            "top_fires": top,
        })
        out_leads.append(lead)
    return {"city": name, "lat": lat, "lon": lon, "leads": out_leads}


def summarise(cities: List[Dict[str, Any]]) -> Dict[str, Any]:
    d1 = []
    for c in cities:
        lead = next((l for l in c["leads"] if l["lead"] == "D+1"), None)
        if lead and lead.get("status") == "ok":
            d1.append({"city": c["city"], "province": c.get("province"), "band": lead["band"], "upwind_load_mw": lead["upwind_load_mw"],
                       "from_compass": (lead.get("wind_850") or {}).get("from_compass"), "by_country": lead.get("by_country", {})})
    d1.sort(key=lambda r: -(r["upwind_load_mw"] or 0))
    by_band: Dict[str, List[str]] = {}
    for r in d1:
        by_band.setdefault(r["band"], []).append(r["city"])
    return {"lead": "D+1", "cities_by_band": by_band, "top": d1[:10], "n_cities": len(d1),
            "alert": [r for r in d1 if r["band"] in ALERT_BANDS]}


async def build_outlook(store: AggStore, cities: List[Dict[str, Any]], *, http, today: Optional[date] = None,
                        now_utc: Optional[datetime] = None, concurrency: int = 6) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    today = today or fa.pkt_today()
    now_utc = now_utc or datetime.now(timezone.utc)
    fires, fires_info = recent_fires(store, today)
    sem = asyncio.Semaphore(concurrency)
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    async def one(c: Dict[str, Any]) -> None:
        async with sem:
            try:
                winds = await fetch_city_forecast(http, c["lat"], c["lon"])
            except Exception as exc:  # noqa: BLE001
                failures.append({"city": c["name"], "error": str(exc)[:200]})
                return
            out = city_outlook(c["name"], c["lat"], c["lon"], winds, fires, today=today)
            out["province"] = c.get("province")
            results.append(out)

    await asyncio.gather(*(one(c) for c in cities))
    results.sort(key=lambda r: r["city"])
    doc = {
        "generated_at": now_utc.isoformat().replace("+00:00", "Z"), "today_pkt": today.isoformat(), "model": MODEL,
        "fires_as_of": fires_info, "fires_total_recent": int(len(fires)), "cities": results, "summary": summarise(results),
        "definitions": DEFINITIONS,
        "caveats": [DEFINITIONS["fires_carried_forward"], DEFINITIONS["not_pm25"],
                    "The 850 hPa and 10 m winds can disagree; the band follows 850 hPa, both are shown."],
    }
    return doc, failures


def alert_line(doc: Dict[str, Any]) -> str:
    """One log line per run; the Cloud Monitoring policy matches 'SMOKE OUTLOOK: D+1 high'."""
    hits = doc.get("summary", {}).get("alert", [])
    if not hits:
        return "SMOKE OUTLOOK: no city above elevated for D+1"
    parts = [f"{h['city']} ({h['upwind_load_mw']:,.0f} MW from {h['from_compass']})" for h in hits[:8]]
    return "SMOKE OUTLOOK: D+1 high/very_high: " + ", ".join(parts)


# ── storage ────────────────────────────────────────────────────────────────────

def write_outlook(bucket, doc: Dict[str, Any], now_utc: datetime) -> List[str]:
    body = json.dumps(doc, separators=(",", ":"))
    dated = f"{OUTLOOK_PREFIX}/smoke_outlook_{now_utc:%Y%m%dT%H}.json"
    for path in (LATEST_PATH, dated):
        bucket.blob(path).upload_from_string(body, content_type="application/json")
    return [LATEST_PATH, dated]


def read_latest(bucket=None) -> Optional[Dict[str, Any]]:
    return _read_json(bucket or default_bucket(), LATEST_PATH)


def outlook_status(doc: Optional[Dict[str, Any]], now_utc: Optional[datetime] = None) -> str:
    if not doc or not doc.get("generated_at"):
        return "unavailable"
    now_utc = now_utc or datetime.now(timezone.utc)
    try:
        gen = datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00"))
    except ValueError:
        return "unavailable"
    return "stale" if (now_utc - gen).total_seconds() > STALE_HOURS * 3600 else "ok"


def city_view(doc: Dict[str, Any], city: str) -> Optional[Dict[str, Any]]:
    want = (city or "").strip().lower()
    return next((c for c in doc.get("cities", []) if c["city"].lower() == want), None)


# ── the task ───────────────────────────────────────────────────────────────────

class SmokeOutlookTask:
    def __init__(self, *, settings=None, session_factory=None, bucket=None, recorder=None, http=None, store: Optional[AggStore] = None):
        from pathlib import Path
        from app.core.config import settings as _default_settings
        from app.ingestion.runs import RunRecorder
        self.settings = settings or _default_settings
        if session_factory is None:
            from app.ingestion.db import AsyncSessionLocal
            session_factory = AsyncSessionLocal
        self.session_factory = session_factory
        self._bucket = bucket
        self.recorder = recorder or RunRecorder(self.session_factory, Path(self.settings.INGEST_OUT_DIR), required=False)
        self._http = http
        self._store = store

    async def run(self, *, dry_run: bool = False, trigger: str = "http", today: Optional[date] = None):
        from app.ingestion.runs import RunOutcome, new_run_id
        run_id = new_run_id(TASK)
        outcome = RunOutcome(run_id=run_id, task=TASK, provider_code="open-meteo", scope="Pakistan cities", trigger=trigger)
        outcome.details["dry_run"] = dry_run
        c = outcome.counts
        await self.recorder.start(outcome)
        try:
            async with self.session_factory() as db:
                cities = await load_cities(db)
            c.expected = len(cities)
            store = self._store or agg_store()
            now_utc = datetime.now(timezone.utc)
            if self._http is not None:
                doc, failures = await build_outlook(store, cities, http=self._http, today=today, now_utc=now_utc)
            else:
                import httpx
                async with httpx.AsyncClient(timeout=60.0) as http:
                    doc, failures = await build_outlook(store, cities, http=http, today=today, now_utc=now_utc)
            c.attempted = len(cities)
            c.failed = len(failures)
            c.completed = len(doc["cities"])
            c.rows_fetched = doc["fires_total_recent"]
            outcome.details.update({"summary": doc["summary"], "failures": failures[:20], "fires_as_of": doc["fires_as_of"]})
            line = alert_line(doc)
            outcome.details["alert_line"] = line
            if not dry_run and doc["cities"]:
                bucket = self._bucket or default_bucket()
                written = await asyncio.to_thread(write_outlook, bucket, doc, now_utc)
                c.rows_written = len(doc["cities"])
                outcome.details["written"] = written
            logger.info("%s", line)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s run %s crashed", TASK, run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await self.recorder.finish(outcome)
        return outcome
