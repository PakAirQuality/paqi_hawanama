"""
Public read endpoints for the "Fire trends" page (hawanama.org/fires), mounted at /api/v1/fires
with the shared per-IP json rate limit. Everything is computed from the FIRMS aggregate store
(services/fire_aggregates) through services/fire_public and fire_analytics; the blocking work
(GCS, pandas) runs in the threadpool and whole responses are memoised per (endpoint, params,
store build, Pakistan day). Cache-Control lets Firebase's CDN serve repeats.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database
from app.services import fire_analytics as fa
from app.services import fire_outlook as fo
from app.services import fire_public as fp
from app.services.fire_aggregates import agg_store

logger = logging.getLogger(__name__)
router = APIRouter()

CC_META = "public, max-age=600, s-maxage=3600, stale-while-revalidate=86400"
CC_LIVE = "public, max-age=300, s-maxage=600, stale-while-revalidate=3600"
CC_ARCHIVE = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400"
CC_CITIES = "public, max-age=3600, s-maxage=86400"
ARCHIVE_START = date(2020, 1, 1)
_INFLIGHT: Dict[Any, "asyncio.Future[Any]"] = {}


def _pkt_today() -> date:
    return fa.pkt_today()


def _cached(name: str, params: tuple, fn: Callable[[Any, date], Dict[str, Any]]) -> Callable[[], Dict[str, Any]]:
    """Blocking: memo lookup (keyed on the store build and the Pakistan day) around fn(store, today)."""
    def run() -> Dict[str, Any]:
        store = agg_store()
        built = store.manifest().get("built_at")
        today = _pkt_today()
        return fp.memo((name, params, built, today), lambda: fn(store, today))
    return run


async def _single_flight(key: Any, run: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Compute once when the same uncached request arrives several times at once."""
    fut = _INFLIGHT.get(key)
    if fut is None:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        _INFLIGHT[key] = fut
        try:
            result = await run_in_threadpool(run)
            fut.set_result(result)
        except BaseException as exc:  # noqa: BLE001
            fut.set_exception(exc)
            raise
        finally:
            _INFLIGHT.pop(key, None)
        return result
    return await asyncio.shield(fut)


def _respond(data: Dict[str, Any], cache: str) -> JSONResponse:
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return JSONResponse(data, headers={"Cache-Control": cache})


def _parse_date(s: Optional[str], *, default: date, today: date) -> date:
    if not s:
        return default
    d = fa.parse_day(s)
    if d is None:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    if d < ARCHIVE_START or d > today:
        raise HTTPException(status_code=400, detail=f"date must be between {ARCHIVE_START} and {today} (Pakistan day)")
    return d


# ── store-only endpoints ──────────────────────────────────────────────────────

@router.get("/meta", summary="Seasons, regions, districts, archive coverage and the data notes for the Fire trends page")
async def get_meta():
    data = await _single_flight(("meta",), _cached("meta", (), lambda s, t: fp.meta(store=s, today=t)))
    return _respond(data, CC_META)


BASIS = Query("all", pattern="^(all|n20|crop|crop_n20)$",
              description="all = every satellite (deduplicated); n20 = NOAA-20 only (comparable across years); crop = likely crop-residue clusters only; crop_n20 = both")


@router.get("/seasons", summary="Every burning season since 2020 as daily, 7-day-mean and cumulative detection counts, with the season-to-date headline")
async def get_seasons(region: str = Query("pakistan", max_length=80, description="Chip id, province, district, 'Indian Punjab', 'Haryana', 'India' or 'bbox'"),
                      season: str = Query("rice", pattern="^(rice|wheat)$"), basis: str = BASIS):
    key = ("seasons", region.strip().lower(), season, basis)
    data = await _single_flight(key, _cached("seasons", key[1:], lambda s, t: fp.seasons(region, season, basis, store=s, today=t)))
    return _respond(data, CC_LIVE)


@router.get("/districts", summary="District league table for the season to date, with the same dates last year")
async def get_districts(season: str = Query("rice", pattern="^(rice|wheat)$"), region: str = Query("pakistan", max_length=80),
                        limit: int = Query(40, ge=1, le=60), basis: str = BASIS):
    key = ("districts", season, region.strip().lower(), limit, basis)
    data = await _single_flight(key, _cached("districts", key[1:], lambda s, t: fp.districts(season, region, basis, limit=limit, store=s, today=t)))
    return _respond(data, CC_LIVE)


@router.get("/split", summary="Daily detections by region for the season: Pakistan, Pakistan Punjab, Indian Punjab, Haryana, rest of the box")
async def get_split(season: str = Query("rice", pattern="^(rice|wheat)$"), basis: str = BASIS):
    key = ("split", season, basis)
    data = await _single_flight(key, _cached("split", key[1:], lambda s, t: fp.split(season, basis, store=s, today=t)))
    return _respond(data, CC_LIVE)


@router.get("/persistent", summary="Persistent thermal sources (cells burning on many of the last 30 days) for a region")
async def get_persistent(region: str = Query("pakistan", max_length=80), min_days: int = Query(10, ge=5, le=30),
                         limit: int = Query(30, ge=1, le=60)):
    key = ("persistent", region.strip().lower(), min_days, limit)
    data = await _single_flight(key, _cached("persistent", key[1:], lambda s, t: fp.persistent(region, min_days=min_days, limit=limit, store=s, today=t)))
    return _respond(data, CC_LIVE)


@router.get("/export", summary="One season of daily series for the two Punjabs, Haryana, Pakistan and the rest of the box, as JSON or CSV")
async def get_export(season: str = Query("rice", pattern="^(rice|wheat)$"), year: Optional[int] = Query(None, ge=2020, le=2100),
                     basis: str = BASIS, format: str = Query("json", pattern="^(json|csv)$")):
    key = ("export", season, year, basis)
    data = await _single_flight(key, _cached("export", key[1:], lambda s, t: fp.export(season, year, basis, store=s, today=t)))
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    if format == "csv":
        from fastapi.responses import PlainTextResponse
        name = f"hawanama-fires-{season}-{data['header']['season']['year']}-{basis}.csv"
        return PlainTextResponse(fp.export_csv(data), media_type="text/csv",
                                 headers={"Cache-Control": CC_LIVE, "Content-Disposition": f'attachment; filename="{name}"'})
    return _respond(data, CC_LIVE)


@router.get("/audit", summary="Observation-quality audit by year and satellite: files, day keys, products, missing passes, suspect days")
async def get_audit():
    data = await _single_flight(("audit",), _cached("audit", (), lambda s, t: fp.audit(store=s, today=t)))
    return _respond(data, CC_META)


# ── smoke outlook (read side) ────────────────────────────────────────────────

CC_OUTLOOK = "public, max-age=300, s-maxage=300, stale-while-revalidate=1800"


def _load_outlook() -> Dict[str, Any]:
    doc = fo.read_latest()                      # the bucket client is built inside, lazily (tests patch read_latest)
    return {"doc": doc, "status": fo.outlook_status(doc)}


@router.get("/outlook", summary="Smoke outlook: forecast wind × current fires for every city (D+1 summary) or one city (D+0…D+3)")
async def get_outlook(city: Optional[str] = Query(None, max_length=80)):
    key = ("outlook", _pkt_today(), datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")[:12])     # memo per 10 min slot
    loaded = await _single_flight(key, lambda: fp.memo(key, _load_outlook))
    doc, status = loaded["doc"], loaded["status"]
    if doc is None:
        return JSONResponse({"status": "unavailable", "message": "No smoke outlook has been generated yet."}, headers={"Cache-Control": CC_OUTLOOK})
    base = {"status": status, "generated_at": doc.get("generated_at"), "model": doc.get("model"), "fires_as_of": doc.get("fires_as_of"),
            "definitions": doc.get("definitions"), "caveats": doc.get("caveats")}
    if city:
        view = fo.city_view(doc, city)
        if view is None:
            raise HTTPException(status_code=404, detail=f"No outlook for city '{city}'")
        others = [h for h in doc.get("summary", {}).get("alert", []) if h["city"].lower() != city.strip().lower()]
        return JSONResponse({**base, **view, "others_at_alert_d1": others}, headers={"Cache-Control": CC_OUTLOOK})
    cities = []
    for c in doc.get("cities", []):
        d1 = next((l for l in c["leads"] if l["lead"] == "D+1"), None)
        cities.append({"city": c["city"], "province": c.get("province"), "lat": c["lat"], "lon": c["lon"],
                       "d1": {k: d1.get(k) for k in ("band", "upwind_load_mw", "by_country", "fires_in_cone")} | {"from_compass": (d1.get("wind_850") or {}).get("from_compass")} if d1 else None})
    return JSONResponse({**base, "summary": doc.get("summary"), "cities": cities}, headers={"Cache-Control": CC_OUTLOOK})


# ── trajectories (read side) ─────────────────────────────────────────────────

@router.get("/trajectories", summary="HYSPLIT trajectories for Lahore and Delhi: the latest run, or the plan while the runner is not installed")
async def get_trajectories(city: Optional[str] = Query(None, max_length=40)):
    from app.services import fire_trajectories as ft
    key = ("trajectories", _pkt_today(), datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")[:12])
    loaded = await _single_flight(key, lambda: fp.memo(key, lambda: {"latest": ft.read_latest(), "plan": ft.read_plan()}))
    latest, plan = loaded["latest"], loaded["plan"]
    base = {"receptors": {k: {"lat": v[0], "lon": v[1]} for k, v in ft.RECEPTORS.items()}, "definitions": ft.DEFINITIONS}
    if latest is None:
        return JSONResponse({**base, "status": "not_run", "message": "No trajectory run has completed yet; the runner needs a Linux HYSPLIT build.",
                             "plan": {k: plan[k] for k in ("generated_at", "fires_day", "clusters", "met", "status") if plan and k in plan} if plan else None},
                            headers={"Cache-Control": CC_OUTLOOK})
    st = ft.status(latest)
    if city:
        view = next((r for r in latest.get("receptors_out", []) if r["city"].lower() == city.strip().lower()), None)
        if view is None:
            raise HTTPException(status_code=404, detail=f"No trajectories for '{city}'")
        return JSONResponse({**base, "status": st, "generated_at": latest.get("generated_at"), **view}, headers={"Cache-Control": CC_OUTLOOK})
    return JSONResponse({**base, "status": st, **{k: v for k, v in latest.items() if k != "receptors_out"},
                         "cities": [r["city"] for r in latest.get("receptors_out", [])]}, headers={"Cache-Control": CC_OUTLOOK})


# ── city endpoints (database) ────────────────────────────────────────────────

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


@router.get("/cities", summary="Active Pakistan cities with coordinates, for the city selector")
async def get_cities(db: AsyncSession = Depends(get_database)):
    rows = (await db.execute(CITIES_SQL)).fetchall()
    cities = [{"id": int(r.id), "name": r.name, "province": r.province, "lat": round(float(r.lat), 4), "lon": round(float(r.lon), 4),
               "stations": int(r.stations)} for r in rows]
    return JSONResponse({"cities": cities, "count": len(cities)}, headers={"Cache-Control": CC_CITIES})


async def _resolve_city(db: AsyncSession, city: str):
    from app.services.copilot.station_queries import _city_centroid, resolve_city
    match, cands = await resolve_city(db, city)
    if cands:
        raise HTTPException(status_code=400, detail=f"'{city}' matches several cities: {', '.join(c.name for c in cands)}")
    if match is None:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found among active Pakistan cities")
    lat, lon = await _city_centroid(db, match)
    if lat is None or lon is None:
        raise HTTPException(status_code=404, detail=f"{match.name} has no coordinates in the registry")
    return match, lat, lon


def _cache_for(end: date, today: date) -> str:
    return CC_ARCHIVE if end < today - timedelta(days=1) else CC_LIVE


@router.get("/exposure", summary="Fires around and upwind of a city on one Pakistan day")
async def get_exposure(city: str = Query(..., min_length=1, max_length=80), date_: Optional[str] = Query(None, alias="date"),
                       radius_km: float = Query(100.0, ge=5.0, le=200.0), db: AsyncSession = Depends(get_database)):
    today = _pkt_today()
    day = _parse_date(date_, default=today - timedelta(days=1), today=today)
    match, lat, lon = await _resolve_city(db, city)
    store = agg_store()
    # pre-warm every blocking reader off the event loop, then hand memoised loaders to the service
    built, era5, summ, drv, traj = await asyncio.gather(
        run_in_threadpool(store.day_from_csv, day),
        run_in_threadpool(fa._default_era5_uv, lat, lon, day),
        run_in_threadpool(fa._default_summary, day),
        run_in_threadpool(fa._default_driver_summary, day),
        run_in_threadpool(fa._default_trajectory, match.name, day),
    )
    if built is None:
        return JSONResponse({"status": "no_file", "city": match.name, "day": day.isoformat(),
                             "message": f"No fire file for the Pakistan day {day.isoformat()}."}, headers={"Cache-Control": CC_LIVE})
    loaders = fa.Loaders(era5_uv=lambda *_: era5, summary=lambda _d: summ, driver_summary=lambda _d: drv, trajectory=lambda *_: traj)
    data = await fa.fire_exposure(db, match.name, day, radius_km=radius_km, store=store, loaders=loaders)
    if "message" in data and "rings" not in data:
        data = {"status": "unavailable", "city": match.name, "day": day.isoformat(), **data}
    else:
        data["status"] = "ok"
    return JSONResponse(data, headers={"Cache-Control": _cache_for(day, today)})


@router.get("/pm25-link", summary="Daily upwind fire intensity against a city's PM2.5 with lagged correlations and flagged days")
async def get_pm25_link(city: str = Query(..., min_length=1, max_length=80), end: Optional[str] = Query(None),
                        days: int = Query(60, ge=14, le=60), db: AsyncSession = Depends(get_database)):
    today = _pkt_today()
    end_d = _parse_date(end, default=today - timedelta(days=1), today=today)
    start_d = end_d - timedelta(days=days - 1)
    match, _, _ = await _resolve_city(db, city)
    store = agg_store()
    await asyncio.gather(run_in_threadpool(store.detections, start_d, end_d),
                         *(run_in_threadpool(store.day_from_csv, d) for d in (end_d, end_d - timedelta(days=1)) if fa.today_recent(d, today)))
    data = await fa.fire_pm25_link(db, match.name, start_d, end_d, store=store, today=today)
    if "message" in data and "rows" not in data:
        data = {"status": "unavailable", "city": match.name, **data}
    else:
        data["status"] = "ok"
    return JSONResponse(data, headers={"Cache-Control": _cache_for(end_d, today)})
