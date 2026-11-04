"""
Precise station queries for the copilot: inventory (counts and lists), nearest /
radius, and period statistics. One set of definitions, returned with every result
so the model can state exactly what was counted and over which window.

Definitions
- registered: a `stations` row for Pakistan that is not a shadow provider row
  (OpenAQ, ICIMOD) and not a test station (metadata registry.status = 'test').
- active: registered and stations.active = true.
- reporting: active with at least one valid PM2.5 reading (qc_state not INVALID)
  in the window (last 24 h, or the asked Pakistan day).
- Province/city membership: stations.state_id / city_id when set; else the city's
  province; else the nearest city (station-average centroid) within 25 km. Punjab
  EPA and BAM rows are registered without a state_id, and some without a city_id;
  the database has no province or city polygons (probe 2026-11-04).
- Days are Pakistan days (Asia/Karachi). A station-day needs >= 6 valid hours.
"""

from __future__ import annotations

import difflib
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.export_membership import SHADOW_PROVIDER_CODES

PKT = ZoneInfo("Asia/Karachi")
COUNTRY = "Pakistan"
MIN_HOURS_PER_DAY = 6
MAX_BUCKETS = 120
MAX_LIST = 100
STATEMENT_TIMEOUT_MS = 60_000
LONG_RANGE_DAYS = 62          # beyond this, city/province/national stats read the hourly city aggregate
HISTORY_START = date(2015, 1, 1)

DEFINITIONS = {
    "registered": "a station row for Pakistan that is not a shadow-provider row (OpenAQ, ICIMOD) and not a test station",
    "active": "registered and flagged active by its provider catalogue",
    "reporting": "active with at least one valid PM2.5 reading (qc not INVALID) inside the window",
    "membership": "province/city from the station's registry link, else its city's province, else the nearest city (station-average centroid) within 25 km",
    "day": "Pakistan calendar day (Asia/Karachi); a station-day needs at least 6 valid hours",
    "statistic": "reporting-station mean: unweighted across stations that reported, never an area or population average",
}

_SHADOW_SQL = ", ".join(f"'{c}'" for c in SHADOW_PROVIDER_CODES)
REGISTERED_WHERE = f"""
      co.name = '{COUNTRY}'
      AND COALESCE(p.code, '') NOT IN ({_SHADOW_SQL})
      AND COALESCE(s.metadata_json->>'ingest_mode', '') <> 'shadow'
      AND COALESCE(s.metadata_json->'registry'->>'status', '') <> 'test'
"""
BASE_FROM = """
    FROM stations s
    JOIN countries co ON co.id = s.country_id
    LEFT JOIN providers p ON p.id = s.provider_id
    LEFT JOIN cities c ON c.id = s.city_id
    LEFT JOIN states st ON st.id = s.state_id
"""
VALID_PM25 = "r.pm25 IS NOT NULL AND (r.qc_state IS NULL OR r.qc_state <> 'INVALID')"
REPORTING_EXISTS = f"""
      EXISTS (SELECT 1 FROM readings r
              WHERE r.scope_type = 'station' AND r.scope_key = s.station_id
                AND r.ts_utc >= :w0 AND r.ts_utc < :w1 AND {VALID_PM25})
"""
# Cities have no polygons or centroids in the database, so a city's position is the mean of its
# registered stations. Rows without a city link (Punjab EPA, BAM) are assigned to the nearest
# such centroid within 25 km; rows without a province link take their city's province.
CITY_CENTROIDS_CTE = f"""
    city_centroids AS (
        SELECT c.id AS city_id, c.state_id, c.name AS city_name,
               ST_SetSRID(ST_MakePoint(AVG(s.lon), AVG(s.lat)), 4326)::geography AS g
        FROM cities c
        JOIN countries co ON co.id = c.country_id
        JOIN stations s ON s.city_id = c.id
        WHERE co.name = '{COUNTRY}' AND c.active = true AND s.lat IS NOT NULL AND s.lon IS NOT NULL
          AND COALESCE(s.metadata_json->>'ingest_mode', '') <> 'shadow'
        GROUP BY c.id, c.state_id, c.name)
"""
NEAREST_CITY_M = 25_000
# the nearest city for rows without a city link; joined only when needed
NEAREST_CITY_LATERAL = f"""
    LEFT JOIN LATERAL (
        SELECT cc.city_id, cc.state_id, cc.city_name FROM city_centroids cc
        WHERE ST_DWithin(cc.g, s.geom, {NEAREST_CITY_M})
        ORDER BY ST_Distance(cc.g, s.geom) LIMIT 1
    ) nc ON s.city_id IS NULL
    LEFT JOIN states cst ON cst.id = c.state_id
    LEFT JOIN states ncst ON ncst.id = nc.state_id
"""
PROVINCE_NAME = "COALESCE(st.name, cst.name, ncst.name)"
CITY_NAME = "COALESCE(c.name, nc.city_name)"
NEAREST_CITY_ID = f"(SELECT cc.city_id FROM city_centroids cc WHERE ST_DWithin(cc.g, s.geom, {NEAREST_CITY_M}) ORDER BY ST_Distance(cc.g, s.geom) LIMIT 1)"
NEAREST_CITY_STATE_ID = f"(SELECT cc.state_id FROM city_centroids cc WHERE ST_DWithin(cc.g, s.geom, {NEAREST_CITY_M}) ORDER BY ST_Distance(cc.g, s.geom) LIMIT 1)"


# ── small helpers ─────────────────────────────────────────────────────────────

def _r(v: Any, nd: int = 1) -> Optional[float]:
    return None if v is None else round(float(v), nd)


def pkt_today() -> date:
    return datetime.now(PKT).date()


def day_window_utc(d: date) -> Tuple[datetime, datetime]:
    """[start, end) of the Pakistan calendar day `d`, in UTC."""
    start = datetime(d.year, d.month, d.day, tzinfo=PKT)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _window_dict(w0: datetime, w1: datetime, label: str) -> Dict[str, Any]:
    return {"label": label,
            "start_pkt": w0.astimezone(PKT).strftime("%Y-%m-%d %H:%M"), "end_pkt": w1.astimezone(PKT).strftime("%Y-%m-%d %H:%M"),
            "start_utc": w0.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ"), "end_utc": w1.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
            "end_exclusive": True}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def _set_timeout(db: AsyncSession) -> None:
    try:
        await db.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
    except Exception:  # noqa: BLE001 — a role without SET rights still gets the query
        pass


# ── area and place resolution ───────────────────────────────────────────────────

@dataclass
class Area:
    kind: str                       # national | province | city | radius
    name: str
    where: str = ""                 # SQL fragment on alias s (and st/c), may be ""
    params: Dict[str, Any] = None   # type: ignore[assignment]
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_km: Optional[float] = None

    def __post_init__(self):
        self.params = dict(self.params or {})


@dataclass
class CityMatch:
    id: int
    name: str
    province: Optional[str]
    lat: Optional[float]
    lon: Optional[float]


async def _pakistan_cities(db: AsyncSession) -> List[CityMatch]:
    rows = (await db.execute(text("""
        SELECT c.id, c.name, st.name AS province,
               ST_Y(c.centroid::geometry) AS lat, ST_X(c.centroid::geometry) AS lon
        FROM cities c JOIN countries co ON co.id = c.country_id
        LEFT JOIN states st ON st.id = c.state_id
        WHERE co.name = :country AND c.active = true
        ORDER BY c.name
    """), {"country": COUNTRY})).fetchall()
    return [CityMatch(r.id, r.name, r.province, _r(r.lat, 5), _r(r.lon, 5)) for r in rows]


async def resolve_city(db: AsyncSession, name: str) -> Tuple[Optional[CityMatch], List[CityMatch]]:
    """(match, ambiguous candidates). Exact → punctuation/case-insensitive → close matches.

    A single close match (ratio >= 0.75) is accepted; several within 0.05 of the best
    are returned as candidates instead of guessing.
    """
    wanted = (name or "").strip()
    if not wanted:
        return None, []
    cities = await _pakistan_cities(db)
    low = wanted.lower()
    for c in cities:
        if c.name.lower() == low:
            return c, []
    key = _norm(wanted)
    same = [c for c in cities if _norm(c.name) == key]
    if len(same) == 1:
        return same[0], []
    scored = sorted(((difflib.SequenceMatcher(None, low, c.name.lower()).ratio(), c) for c in cities),
                    key=lambda t: -t[0])
    close = [(s, c) for s, c in scored if s >= 0.75]
    if not close:
        return None, []
    best = close[0][0]
    tied = [c for s, c in close if s >= best - 0.05]
    if len(tied) == 1:
        return tied[0], []
    return None, tied[:5]


async def _city_centroid(db: AsyncSession, city: CityMatch) -> Tuple[Optional[float], Optional[float]]:
    if city.lat is not None and city.lon is not None:
        return city.lat, city.lon
    row = (await db.execute(text("""
        SELECT AVG(s.lat) AS lat, AVG(s.lon) AS lon FROM stations s
        WHERE s.city_id = :cid AND s.active = true AND s.lat IS NOT NULL AND s.lon IS NOT NULL
    """), {"cid": city.id})).fetchone()
    if row and row.lat is not None:
        return _r(row.lat, 5), _r(row.lon, 5)
    return None, None


async def resolve_place(db: AsyncSession, place: str) -> Dict[str, Any]:
    """A place name → {lat, lon, name, kind} for nearest/radius questions.

    Order: city (exact or close), then a station name, then a province centroid.
    Returns {"message": …} when nothing matches or the city name is ambiguous.
    """
    from app.services.analytics import _resolve_province, _resolve_station

    city, cands = await resolve_city(db, place)
    if cands:
        return {"message": f"'{place}' matches several cities: {', '.join(c.name for c in cands)}. Which one?"}
    if city:
        lat, lon = await _city_centroid(db, city)
        if lat is not None:
            return {"lat": lat, "lon": lon, "name": city.name, "kind": "city"}
    st = await _resolve_station(db, place)
    if st and st.get("lat") is not None:
        return {"lat": _r(st["lat"], 5), "lon": _r(st["lon"], 5), "name": st["station_name"], "kind": "station",
                "station_id": st["station_id"]}
    sid, sname, _ = await _resolve_province(db, place)
    if sid is not None:
        row = (await db.execute(text("""
            SELECT ST_Y(COALESCE(centroid, ST_Centroid(geom::geometry)::geography)::geometry) AS lat,
                   ST_X(COALESCE(centroid, ST_Centroid(geom::geometry)::geography)::geometry) AS lon
            FROM states WHERE id = :sid"""), {"sid": sid})).fetchone()
        if row and row.lat is not None:
            return {"lat": _r(row.lat, 5), "lon": _r(row.lon, 5), "name": sname, "kind": "province"}
    return {"message": f"Place '{place}' not found as a city, station or province in Pakistan."}


async def resolve_area(db: AsyncSession, area: str, name: str = "", lat: Optional[float] = None,
                       lon: Optional[float] = None, radius_km: Optional[float] = None) -> Dict[str, Any] | Area:
    """Build the membership clause for an area; returns {"message": …} when it cannot."""
    from app.services.analytics import _resolve_province

    kind = (area or "national").strip().lower()
    if kind in ("national", "pakistan", "country", ""):
        return Area("national", COUNTRY)
    if kind in ("province", "state"):
        sid, sname, known = await _resolve_province(db, name)
        if sid is None:
            return {"message": f"Province '{name}' not found. Known provinces/territories: {', '.join(known)}."}
        return Area("province", sname, f"""
            (s.state_id = :area_sid
             OR (s.state_id IS NULL AND c.state_id = :area_sid)
             OR (s.state_id IS NULL AND s.city_id IS NULL AND {NEAREST_CITY_STATE_ID} = :area_sid))
        """, {"area_sid": sid})
    if kind == "city":
        city, cands = await resolve_city(db, name)
        if cands:
            return {"message": f"'{name}' matches several cities: {', '.join(c.name for c in cands)}. Which one?"}
        if city is None:
            return {"message": f"City '{name}' not found among active Pakistan cities."}
        return Area("city", city.name, f"""
            (s.city_id = :area_cid OR (s.city_id IS NULL AND {NEAREST_CITY_ID} = :area_cid))
        """, {"area_cid": city.id}, lat=city.lat, lon=city.lon)
    if kind in ("radius", "near", "around"):
        if lat is None or lon is None:
            if not name:
                return {"message": "A radius query needs a place name or lat/lon."}
            place = await resolve_place(db, name)
            if "message" in place:
                return place
            lat, lon, label = place["lat"], place["lon"], place["name"]
        else:
            label = name or f"{lat:.4f}, {lon:.4f}"
        km = float(radius_km or 10.0)
        km = max(0.5, min(km, 200.0))
        return Area("radius", f"within {km:g} km of {label}",
                    "ST_DWithin(s.geom, ST_SetSRID(ST_MakePoint(:area_lon, :area_lat), 4326)::geography, :area_m)",
                    {"area_lat": lat, "area_lon": lon, "area_m": km * 1000.0}, lat=lat, lon=lon, radius_km=km)
    return {"message": f"Unknown area type '{area}'. Use national, province, city or radius."}


# ── 1. inventory ──────────────────────────────────────────────────────────────

async def station_inventory(db: AsyncSession, area: Area, *, as_of_day: Optional[date] = None,
                            provider: str = "", list_stations: bool = False, limit: int = 50) -> Dict[str, Any]:
    """Counts (registered / active / reporting, by provider, by city) and an optional station list."""
    await _set_timeout(db)
    if as_of_day:
        w0, w1 = day_window_utc(as_of_day)
        label = f"Pakistan day {as_of_day.isoformat()}"
    else:
        w1 = datetime.now(timezone.utc).replace(microsecond=0)
        w0 = w1 - timedelta(hours=24)
        label = "last 24 hours"
    params: Dict[str, Any] = {**area.params, "w0": w0, "w1": w1}
    where = REGISTERED_WHERE + (f" AND {area.where}" if area.where else "")
    if provider:
        where += " AND LOWER(COALESCE(p.code, '')) = LOWER(:prov)"
        params["prov"] = provider

    totals = (await db.execute(text(f"""
        WITH {CITY_CENTROIDS_CTE}
        SELECT COUNT(*) AS registered,
               COUNT(*) FILTER (WHERE s.active) AS active,
               COUNT(*) FILTER (WHERE s.active AND {REPORTING_EXISTS}) AS reporting
        {BASE_FROM}
        WHERE {where}
    """), params)).fetchone()
    by_provider = (await db.execute(text(f"""
        WITH {CITY_CENTROIDS_CTE}
        SELECT COALESCE(p.code, 'unknown') AS code, COALESCE(p.display_name, p.code, 'unknown') AS display_name,
               COUNT(*) AS registered, COUNT(*) FILTER (WHERE s.active) AS active,
               COUNT(*) FILTER (WHERE s.active AND {REPORTING_EXISTS}) AS reporting
        {BASE_FROM}
        WHERE {where}
        GROUP BY 1, 2 ORDER BY registered DESC
    """), params)).fetchall()
    out: Dict[str, Any] = {
        "area": {"kind": area.kind, "name": area.name,
                 **({"lat": area.lat, "lon": area.lon} if area.lat is not None else {}),
                 **({"radius_km": area.radius_km} if area.radius_km else {})},
        "counts": {"registered": int(totals.registered), "active": int(totals.active), "reporting": int(totals.reporting)},
        "by_provider": [{"code": r.code, "display_name": r.display_name, "registered": int(r.registered),
                         "active": int(r.active), "reporting": int(r.reporting)} for r in by_provider],
        "window": _window_dict(w0, w1, label),
        "definitions": DEFINITIONS,
    }
    if area.kind in ("national", "province"):
        by_city = (await db.execute(text(f"""
            WITH {CITY_CENTROIDS_CTE}
            SELECT COALESCE({CITY_NAME}, '(no city within 25 km)') AS city, COUNT(*) AS registered,
                   COUNT(*) FILTER (WHERE s.active) AS active,
                   COUNT(*) FILTER (WHERE s.active AND {REPORTING_EXISTS}) AS reporting
            {BASE_FROM}
            {NEAREST_CITY_LATERAL}
            WHERE {where}
            GROUP BY 1 ORDER BY registered DESC, city LIMIT 40
        """), params)).fetchall()
        out["by_city"] = [{"city": r.city, "registered": int(r.registered), "active": int(r.active), "reporting": int(r.reporting)}
                          for r in by_city]
    if list_stations:
        lim = max(1, min(int(limit or 50), MAX_LIST))
        rows = (await db.execute(text(f"""
            WITH {CITY_CENTROIDS_CTE}
            SELECT s.station_id, s.name, {CITY_NAME} AS city, {PROVINCE_NAME} AS province,
                   COALESCE(p.code, 'unknown') AS provider, s.lat, s.lon, s.active,
                   ({REPORTING_EXISTS}) AS reporting,
                   obs.first_obs, obs.last_obs
            {BASE_FROM}
            {NEAREST_CITY_LATERAL}
            LEFT JOIN LATERAL (
                SELECT MIN(r.ts_utc) AS first_obs, MAX(r.ts_utc) AS last_obs FROM readings r
                WHERE r.scope_type = 'station' AND r.scope_key = s.station_id
            ) obs ON true
            WHERE {where}
            ORDER BY s.active DESC, s.name
            LIMIT :lim
        """), {**params, "lim": lim + 1})).fetchall()
        out["stations"] = [{
            "station_id": r.station_id.strip(), "name": r.name, "city": r.city, "province": r.province,
            "provider": r.provider, "lat": _r(r.lat, 5), "lon": _r(r.lon, 5), "active": bool(r.active),
            "reporting": bool(r.reporting),
            "first_obs": r.first_obs.date().isoformat() if r.first_obs else None,
            "last_obs": r.last_obs.strftime("%Y-%m-%d %H:%MZ") if r.last_obs else None,
        } for r in rows[:lim]]
        out["truncated"] = len(rows) > lim
        out["list_limit"] = lim
    return out


# ── 2. nearest ────────────────────────────────────────────────────────────────

async def nearest_stations(db: AsyncSession, lat: float, lon: float, *, k: int = 5, max_km: float = 50.0,
                           origin_name: str = "") -> Dict[str, Any]:
    await _set_timeout(db)
    k = max(1, min(int(k or 5), 25))
    max_km = max(0.5, min(float(max_km or 50.0), 500.0))
    w1 = datetime.now(timezone.utc).replace(microsecond=0)
    w0 = w1 - timedelta(hours=24)
    rows = (await db.execute(text(f"""
        WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g),
        {CITY_CENTROIDS_CTE}
        SELECT s.station_id, s.name, {CITY_NAME} AS city, {PROVINCE_NAME} AS province,
               COALESCE(p.code, 'unknown') AS provider, s.lat, s.lon, s.active,
               ST_Distance(s.geom, pt.g) AS dist_m,
               degrees(ST_Azimuth(pt.g::geometry, s.geom::geometry)) AS bearing,
               latest.pm25 AS latest_pm25, latest.ts_utc AS latest_ts
        {BASE_FROM}
        {NEAREST_CITY_LATERAL}
        CROSS JOIN pt
        LEFT JOIN LATERAL (
            SELECT r.pm25, r.ts_utc FROM readings r
            WHERE r.scope_type = 'station' AND r.scope_key = s.station_id
              AND r.ts_utc >= :w0 AND r.ts_utc < :w1 AND {VALID_PM25}
            ORDER BY r.ts_utc DESC LIMIT 1
        ) latest ON true
        WHERE {REGISTERED_WHERE}
          AND s.active = true
          AND ST_DWithin(s.geom, pt.g, :max_m)
        ORDER BY dist_m
        LIMIT :k
    """), {"lat": lat, "lon": lon, "max_m": max_km * 1000.0, "k": k, "w0": w0, "w1": w1})).fetchall()
    return {
        "origin": {"name": origin_name or f"{lat:.4f}, {lon:.4f}", "lat": _r(lat, 5), "lon": _r(lon, 5)},
        "max_km": max_km, "k": k,
        "stations": [{
            "station_id": r.station_id.strip(), "name": r.name, "city": r.city, "province": r.province, "provider": r.provider,
            "lat": _r(r.lat, 5), "lon": _r(r.lon, 5), "distance_km": _r(r.dist_m / 1000.0, 2), "bearing_deg": _r(r.bearing, 0),
            "reporting": r.latest_pm25 is not None, "latest_pm25": _r(r.latest_pm25),
            "latest_ts": r.latest_ts.strftime("%Y-%m-%d %H:%MZ") if r.latest_ts else None,
        } for r in rows],
        "window": _window_dict(w0, w1, "latest reading within the last 24 hours"),
        "definitions": {k2: DEFINITIONS[k2] for k2 in ("registered", "active", "reporting")},
        "message": None if rows else f"No active registered station within {max_km:g} km.",
    }


# ── 3. period statistics ───────────────────────────────────────────────────────

def parse_period_date(s: str, *, end: bool = False) -> Optional[date]:
    """'YYYY-MM-DD' | 'YYYY-MM' | 'YYYY' → date (start or end of the period)."""
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}", s):
        y = int(s)
        return date(y, 12, 31) if end else date(y, 1, 1)
    if re.fullmatch(r"\d{4}-\d{2}", s):
        y, m = int(s[:4]), int(s[5:7])
        return date(y, m, monthrange(y, m)[1]) if end else date(y, m, 1)
    return date.fromisoformat(s)


def _bucket_expr(bucket: str) -> str:
    return {"day": "d", "month": "date_trunc('month', d)::date", "year": "date_trunc('year', d)::date",
            "all": "DATE '1900-01-01'"}[bucket]


def _count_buckets(start: date, end: date, bucket: str) -> int:
    if bucket == "all":
        return 1
    if bucket == "day":
        return (end - start).days + 1
    if bucket == "month":
        return (end.year - start.year) * 12 + end.month - start.month + 1
    return end.year - start.year + 1


async def period_stats(db: AsyncSession, *, entity: str, name: str = "", start: str = "", end: str = "",
                       bucket: str = "day", same_calendar_date: bool = False) -> Dict[str, Any]:
    """Reporting-station PM2.5 statistics per bucket over Pakistan days.

    entity: station | city | province | national. same_calendar_date=True with start
    'MM-DD' (or a full date) returns one row per year for that calendar day.
    """
    from app.services.analytics import _resolve_station

    await _set_timeout(db)
    bucket = (bucket or "day").lower()
    if bucket not in ("day", "month", "year", "all"):
        return {"message": "bucket must be day, month, year or all."}
    today = pkt_today()

    md: Optional[Tuple[int, int]] = None
    if same_calendar_date:
        s = (start or "").strip()
        m = re.fullmatch(r"(?:\d{4}-)?(\d{2})-(\d{2})", s)
        if not m:
            return {"message": "same_calendar_date needs start as 'MM-DD' or 'YYYY-MM-DD'."}
        md = (int(m.group(1)), int(m.group(2)))
        d0, d1, bucket = HISTORY_START, today, "year"      # one row per year over the whole archive
    else:
        try:
            d1 = parse_period_date(end, end=True) or today
            d0 = parse_period_date(start, end=False) or (d1 - timedelta(days=29) if bucket == "day" else
                                                         d1.replace(day=1) - timedelta(days=365) if bucket == "month" else HISTORY_START)
        except ValueError:
            return {"message": "Dates must be YYYY-MM-DD, YYYY-MM or YYYY."}
    d1 = min(d1, today)
    if d0 > d1:
        return {"message": f"Start {d0} is after end {d1}."}
    nb = _count_buckets(d0, d1, bucket)
    if nb > MAX_BUCKETS:
        return {"message": f"{nb} {bucket} buckets requested; the limit is {MAX_BUCKETS}. Use a coarser bucket or a shorter range."}

    w0, _ = day_window_utc(d0)
    _, w1 = day_window_utc(d1)
    kind = (entity or "city").lower()
    params: Dict[str, Any] = {"w0": w0, "w1": w1}
    # Time filter on the readings index: one window for a range, or one window per year for a
    # calendar day across years (never a full scan filtered by EXTRACT()).
    time_filter = "r.ts_utc >= :w0 AND r.ts_utc < :w1"
    md_filter = ""
    if md:
        parts = []
        for i, y in enumerate(range(d0.year, d1.year + 1)):
            try:
                cw0, cw1 = day_window_utc(date(y, md[0], md[1]))
            except ValueError:          # 29 Feb in a non-leap year
                continue
            params[f"cw{i}a"], params[f"cw{i}b"] = cw0, cw1
            parts.append(f"(r.ts_utc >= :cw{i}a AND r.ts_utc < :cw{i}b)")
        if not parts:
            return {"message": f"No valid calendar day {md[0]:02d}-{md[1]:02d}."}
        time_filter = "(" + " OR ".join(parts) + ")"
        md_filter = "AND EXTRACT(month FROM d) = :mm AND EXTRACT(day FROM d) = :dd"
        params.update({"mm": md[0], "dd": md[1]})
    label = name
    span_days = (d1 - d0).days + 1
    per_station = True           # daily rows are per station (n_stations = distinct stations)

    if kind == "station":
        st = await _resolve_station(db, name)
        if not st:
            return {"message": f"Station '{name}' not found."}
        label = st["station_name"]
        params["sid"] = st["station_id"]
        source_sql = f"""
            WITH hourly AS (
                SELECT time_bucket('1 hour', r.ts_utc) AS h, AVG(r.pm25) AS v
                FROM readings r
                WHERE r.scope_type = 'station' AND r.scope_key = :sid
                  AND {time_filter} AND {VALID_PM25}
                GROUP BY 1),
            daily AS (
                SELECT (h AT TIME ZONE 'Asia/Karachi')::date AS d, 'x' AS sk, AVG(v) AS v, COUNT(*) AS n_hours, 1 AS n_st
                FROM hourly GROUP BY 1 HAVING COUNT(*) >= {MIN_HOURS_PER_DAY})
        """
        statistic = "station daily mean of hourly means"
        per_station = False
    else:
        area = await resolve_area(db, "national" if kind in ("national", "pakistan") else kind, name)
        if isinstance(area, dict):
            return area
        label = area.name
        params.update(area.params)
        where = REGISTERED_WHERE + (f" AND {area.where}" if area.where else "")
        if span_days > LONG_RANGE_DAYS and kind != "radius" and not md:
            # long ranges: the continuous aggregate (city-hourly means, station_count-weighted)
            city_where = "" if kind in ("national", "pakistan") else (
                "AND c.state_id = :area_sid" if kind in ("province", "state") else "AND c.id = :area_cid")
            source_sql = f"""
                WITH hourly AS (
                    SELECT h.hour_utc AS h, h.pm25_mean AS v, h.station_count AS n
                    FROM city_hourly_from_stations h
                    JOIN cities c ON c.id = h.city_id JOIN countries co ON co.id = c.country_id
                    WHERE co.name = '{COUNTRY}' {city_where}
                      AND h.hour_utc >= :w0 AND h.hour_utc < :w1 AND h.pm25_mean IS NOT NULL AND h.station_count > 0),
                daily AS (
                    SELECT (h AT TIME ZONE 'Asia/Karachi')::date AS d, 'x' AS sk,
                           SUM(v * n) / SUM(n) AS v, COUNT(*) AS n_hours, MAX(n) AS n_st
                    FROM hourly GROUP BY 1 HAVING COUNT(*) >= {MIN_HOURS_PER_DAY})
            """
            statistic = "daily mean of station-hour means (hourly city aggregate; stations without a city link are not included)"
            per_station = False
        else:
            source_sql = f"""
                WITH {CITY_CENTROIDS_CTE},
                members AS (
                    SELECT s.station_id {BASE_FROM} WHERE {where}),
                hourly AS (
                    SELECT r.scope_key AS sk, time_bucket('1 hour', r.ts_utc) AS h, AVG(r.pm25) AS v
                    FROM readings r JOIN members m ON m.station_id = r.scope_key
                    WHERE r.scope_type = 'station' AND {time_filter} AND {VALID_PM25}
                    GROUP BY 1, 2),
                daily AS (
                    SELECT (h AT TIME ZONE 'Asia/Karachi')::date AS d, sk, AVG(v) AS v, COUNT(*) AS n_hours, 1 AS n_st
                    FROM hourly GROUP BY 1, 2 HAVING COUNT(*) >= {MIN_HOURS_PER_DAY})
            """
            statistic = "reporting-station mean of station daily means"

    bexpr = _bucket_expr(bucket)
    rows = (await db.execute(text(f"""
        {source_sql}
        SELECT {bexpr} AS b, AVG(v) AS mean, percentile_cont(0.5) WITHIN GROUP (ORDER BY v) AS median,
               MAX(v) AS max, MIN(v) AS min, COUNT(*) AS n_station_days, COUNT(DISTINCT sk) AS n_sk,
               MAX(n_st) AS n_st_max, COUNT(DISTINCT d) AS n_days
        FROM daily
        WHERE true {md_filter}
        GROUP BY 1 ORDER BY 1
    """), params)).fetchall()

    def _label(b: date) -> str:
        return {"day": b.isoformat(), "month": b.strftime("%Y-%m"), "year": str(b.year), "all": f"{d0}..{d1}"}[bucket]

    out_rows = [{"bucket": _label(r.b), "mean": _r(r.mean), "median": _r(r.median), "max": _r(r.max), "min": _r(r.min),
                 "n_station_days": int(r.n_station_days), "n_days": int(r.n_days),
                 **({"n_stations": int(r.n_sk)} if per_station else
                    {"max_stations_per_hour": int(r.n_st_max)} if kind != "station" else {})}
                for r in rows]
    if same_calendar_date and md:
        for row in out_rows:
            row["calendar_date"] = f"{row['bucket']}-{md[0]:02d}-{md[1]:02d}"
    return {
        "entity": {"kind": kind, "name": label},
        "bucket": bucket, "same_calendar_date": bool(md),
        "range": {"start_pkt_day": d0.isoformat(), "end_pkt_day": d1.isoformat()},
        "window": _window_dict(w0, w1, f"Pakistan days {d0} to {d1}"),
        "statistic": statistic, "unit": "µg/m³ PM2.5",
        "rows": out_rows, "n_buckets": len(out_rows),
        "definitions": {k2: DEFINITIONS[k2] for k2 in ("day", "statistic", "registered")},
        **({"message": "No station-days with at least 6 valid hours in this range."} if not out_rows else {}),
    }
