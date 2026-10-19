"""Report data for the public dashboard's Reports page.

Explicit, bounded, timezone-aware queries built for reproducible downloads:

* `GET /reports/cities` and `/reports/cities/{city}/stations`: the filter cascade, scoped by
  province and country, deduplicated, with provider and last-observation facts so a user
  can tell two same-named rows apart;
* `GET /reports/stations/history`: hourly rows for up to 25 stations over at most 31 days,
  for the requested pollutants only, between explicit start/end instants;
* `GET /reports/cities/{city}/average/history`: hourly reporting-station mean for a city,
  scoped by province/country, with the number of stations used per hour.

Everything is PM2.5-first; other pollutants are returned when the readings carry them.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database
from app.utils.timefmt import iso_z

router = APIRouter()

POLLUTANT_COLUMNS = {"pm25": "pm25", "pm10": "pm10", "no2": "no2", "so2": "so2", "co": "co", "o3": "o3"}
UNITS = {"pm25": "µg/m³", "pm10": "µg/m³", "no2": "µg/m³", "so2": "µg/m³", "co": "µg/m³", "o3": "µg/m³"}
MAX_STATIONS = 25
MAX_HOURLY_SPAN = timedelta(days=31)
MAX_ROWS = 25 * 31 * 24
TEST_NAME_RE = re.compile(r"\b(test|demo|dummy|sample)\b", re.I)
STATION_ID_RE = re.compile(r"^[0-9a-f]{16}$")
PK_OFFSET = timedelta(hours=5)


def parse_window(start: Optional[str], end: Optional[str], *, max_span: timedelta = MAX_HOURLY_SPAN) -> tuple[datetime, datetime]:
    """Explicit start/end instants (ISO 8601; naive values are taken as Asia/Karachi)."""
    def _parse(label: str, value: Optional[str]) -> datetime:
        if not value:
            raise HTTPException(status_code=400, detail=f"{label} is required (ISO 8601)")
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{label} must be ISO 8601, e.g. 2026-10-01T00:00:00+05:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(PK_OFFSET))
        return dt.astimezone(timezone.utc)

    s, e = _parse("start", start), _parse("end", end)
    if e <= s:
        raise HTTPException(status_code=400, detail="end must be after start")
    if e - s > max_span:
        raise HTTPException(status_code=400, detail=f"Window too large: at most {max_span.days} days per report")
    if e > datetime.now(timezone.utc) + timedelta(hours=1):
        raise HTTPException(status_code=400, detail="end cannot be in the future")
    return s, e


def parse_parameters(parameters: Optional[str]) -> List[str]:
    if not parameters:
        return ["pm25"]
    keys = [p.strip().lower() for p in parameters.split(",") if p.strip()]
    bad = [k for k in keys if k not in POLLUTANT_COLUMNS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown parameters: {', '.join(bad)}; allowed: {', '.join(POLLUTANT_COLUMNS)}")
    return list(dict.fromkeys(keys))


def parse_station_ids(station_ids: Optional[str]) -> List[str]:
    ids = [s.strip().lower() for s in (station_ids or "").split(",") if s.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="station_ids is required (comma-separated 16-character ids)")
    bad = [s for s in ids if not STATION_ID_RE.match(s)]
    if bad:
        raise HTTPException(status_code=400, detail="station ids are 16-character hex strings")
    if len(ids) > MAX_STATIONS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_STATIONS} stations per report")
    return list(dict.fromkeys(ids))


def _scope_sql(province: Optional[str], country: Optional[str]) -> tuple[str, Dict[str, Any]]:
    """Scope a city/station query by the station's own state and country."""
    sql, params = "", {}
    if province:
        sql += " AND LOWER(st.name) = LOWER(:province)"
        params["province"] = province
    if country:
        sql += " AND LOWER(co.name) = LOWER(:country)"
        params["country"] = country
    return sql, params


@router.get("/cities")
async def report_cities(
    province: Optional[str] = Query(None, description="Province / state name, e.g. Punjab"),
    country: Optional[str] = Query("Pakistan"),
    db: AsyncSession = Depends(get_database),
) -> Dict[str, Any]:
    """Cities with active stations inside the given province and country, one row per name."""
    scope, params = _scope_sql(province, country)
    rows = (await db.execute(text(f"""
        SELECT c.name AS city, st.name AS province, co.name AS country,
               COUNT(DISTINCT s.station_id) AS station_count
        FROM stations s
        JOIN cities c ON c.id = s.city_id
        JOIN states st ON st.id = s.state_id
        JOIN countries co ON co.id = s.country_id
        LEFT JOIN providers p ON p.id = s.provider_id
        WHERE s.active = TRUE AND c.active = TRUE {scope}
        GROUP BY c.name, st.name, co.name
        ORDER BY c.name
    """), params)).mappings().all()
    # Collapse spelling variants that differ only in case/punctuation (Vehari / Vihari stay distinct)
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = re.sub(r"[^a-z0-9]", "", r["city"].lower())
        if key in seen:
            seen[key]["station_count"] += int(r["station_count"])
            seen[key].setdefault("aliases", []).append(r["city"])
        else:
            seen[key] = {"city": r["city"], "province": r["province"], "country": r["country"], "station_count": int(r["station_count"])}
    return {"province": province, "country": country, "cities": list(seen.values())}


@router.get("/cities/{city}/stations")
async def report_city_stations(
    city: str,
    province: Optional[str] = Query(None),
    country: Optional[str] = Query("Pakistan"),
    include_punjab: bool = Query(False, description="Include Punjab EPA reference monitors"),
    include_test: bool = Query(False, description="Include stations whose name marks them as test devices"),
    db: AsyncSession = Depends(get_database),
) -> Dict[str, Any]:
    """Stations in a city with the facts needed to tell them apart."""
    scope, params = _scope_sql(province, country)
    params["city"] = city
    rows = (await db.execute(text(f"""
        SELECT s.station_id, s.name AS station_name, COALESCE(p.code, '') AS provider,
               c.name AS city, st.name AS province, co.name AS country,
               lr.ts_utc AS last_observation, lr.pm25 AS last_pm25
        FROM stations s
        JOIN cities c ON c.id = s.city_id
        JOIN states st ON st.id = s.state_id
        JOIN countries co ON co.id = s.country_id
        LEFT JOIN providers p ON p.id = s.provider_id
        LEFT JOIN LATERAL (
            SELECT r.ts_utc, r.pm25 FROM readings r
            WHERE r.scope_type = 'station' AND r.scope_key = s.station_id
              AND r.ts_utc > NOW() - INTERVAL '30 days'
            ORDER BY r.ts_utc DESC LIMIT 1
        ) lr ON TRUE
        WHERE s.active = TRUE AND LOWER(c.name) = LOWER(:city) {scope}
          AND (:include_test OR COALESCE(s.metadata_json->'registry'->>'status', 'active') <> 'test')
        ORDER BY s.name
    """), {**params, "include_test": include_test})).mappings().all()
    out = []
    for r in rows:
        if not include_punjab and r["provider"] == "punjab":
            continue
        if not include_test and TEST_NAME_RE.search(r["station_name"] or ""):
            continue
        out.append({
            "station_id": r["station_id"],
            "station_name": r["station_name"],
            "provider": r["provider"],
            "city": r["city"], "province": r["province"], "country": r["country"],
            "last_observation": iso_z(r["last_observation"]) if r["last_observation"] else None,
            "last_pm25": float(r["last_pm25"]) if r["last_pm25"] is not None else None,
        })
    # Same name twice: keep both, but say so, so the user can pick by provider/last observation
    names: Dict[str, int] = {}
    for s in out:
        names[s["station_name"]] = names.get(s["station_name"], 0) + 1
    for s in out:
        s["duplicate_name"] = names[s["station_name"]] > 1
    return {"city": city, "province": province, "country": country, "stations": out, "count": len(out)}


@router.get("/stations/history")
async def report_station_history(
    station_ids: str = Query(..., description="Comma-separated 16-character station ids (max 25)"),
    start: str = Query(..., description="ISO 8601 start; naive values are Asia/Karachi"),
    end: str = Query(..., description="ISO 8601 end (exclusive); at most 31 days after start"),
    parameters: Optional[str] = Query("pm25", description="Comma-separated: pm25,pm10,no2,so2,co,o3"),
    include_punjab: bool = Query(True),
    db: AsyncSession = Depends(get_database),
) -> Dict[str, Any]:
    """Hourly rows for the stations, pollutants and window requested; nothing more, nothing less."""
    ids = parse_station_ids(station_ids)
    s_utc, e_utc = parse_window(start, end)
    params = parse_parameters(parameters)
    cols = ", ".join(f"r.{POLLUTANT_COLUMNS[p]} AS {p}" for p in params)
    provider_filter = "" if include_punjab else "AND COALESCE(p.code, '') != 'punjab'"

    stations = (await db.execute(text(f"""
        SELECT s.station_id, s.name, COALESCE(p.code, '') AS provider
        FROM stations s LEFT JOIN providers p ON p.id = s.provider_id
        WHERE s.station_id = ANY(:ids) AND s.active = TRUE {provider_filter}
    """), {"ids": ids})).mappings().all()
    if not stations:
        raise HTTPException(status_code=404, detail="No matching active stations")
    name_by_id = {r["station_id"]: r["name"] for r in stations}

    rows = (await db.execute(text(f"""
        SELECT r.scope_key AS station_id,
               date_trunc('hour', r.ts_utc) AS hour_utc,
               COALESCE(r.qc_state::text, 'OK') AS qc_state,
               {cols}
        FROM readings r
        WHERE r.scope_type = 'station'
          AND r.scope_key = ANY(:ids)
          AND r.ts_utc >= :s AND r.ts_utc < :e
        ORDER BY r.scope_key, r.ts_utc
        LIMIT :lim
    """), {"ids": list(name_by_id), "s": s_utc, "e": e_utc, "lim": MAX_ROWS + 1})).mappings().all()
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    out = []
    for r in rows:
        rec: Dict[str, Any] = {
            "station_id": r["station_id"],
            "station_name": name_by_id.get(r["station_id"], ""),
            "timestamp_utc": iso_z(r["hour_utc"]),
            "timestamp_pk": (r["hour_utc"] + PK_OFFSET).strftime("%Y-%m-%dT%H:%M:%S+05:00"),
            "qc_state": r["qc_state"],
        }
        for p in params:
            rec[p] = float(r[p]) if r[p] is not None else None
        out.append(rec)

    expected_hours = int((e_utc - s_utc).total_seconds() // 3600)
    return {
        "meta": {
            "start_utc": iso_z(s_utc), "end_utc": iso_z(e_utc),
            "start_pk": (s_utc + PK_OFFSET).strftime("%Y-%m-%dT%H:%M:%S+05:00"),
            "end_pk": (e_utc + PK_OFFSET).strftime("%Y-%m-%dT%H:%M:%S+05:00"),
            "tz": "Asia/Karachi",
            "aggregation": "hourly readings as stored (one row per station-hour); each hour is the average of the hour that ended at that label",
            "parameters": params,
            "units": {p: UNITS[p] for p in params},
            "stations": [{"station_id": r["station_id"], "name": r["name"], "provider": r["provider"]} for r in stations],
            "expected_hours_per_station": expected_hours,
            "row_count": len(out),
            "truncated": truncated,
            "limits": {"max_stations": MAX_STATIONS, "max_days": MAX_HOURLY_SPAN.days},
            "qc_note": "qc_state other than OK/raw marks readings flagged by the ingestion checks; they are included so you can exclude them yourself.",
        },
        "rows": out,
    }


@router.get("/cities/{city}/average/history")
async def report_city_average(
    city: str,
    start: str = Query(...),
    end: str = Query(...),
    province: Optional[str] = Query(None),
    country: Optional[str] = Query("Pakistan"),
    include_punjab: bool = Query(False),
    db: AsyncSession = Depends(get_database),
) -> Dict[str, Any]:
    """Hourly reporting-station mean PM2.5 for a city within the window (stations_used per hour)."""
    s_utc, e_utc = parse_window(start, end)
    scope, params = _scope_sql(province, country)
    params.update({"city": city, "s": s_utc, "e": e_utc})
    provider_filter = "" if include_punjab else "AND COALESCE(p.code, '') != 'punjab'"
    rows = (await db.execute(text(f"""
        WITH city_stations AS (
            SELECT s.station_id FROM stations s
            JOIN cities c ON c.id = s.city_id
            JOIN states st ON st.id = s.state_id
            JOIN countries co ON co.id = s.country_id
            LEFT JOIN providers p ON p.id = s.provider_id
            WHERE s.active = TRUE AND LOWER(c.name) = LOWER(:city) {scope} {provider_filter}
        )
        SELECT date_trunc('hour', r.ts_utc) AS hour_utc,
               AVG(r.pm25) AS avg_pm25,
               COUNT(r.pm25) AS stations_used
        FROM readings r JOIN city_stations cs ON cs.station_id = r.scope_key
        WHERE r.scope_type = 'station' AND r.ts_utc >= :s AND r.ts_utc < :e AND r.pm25 IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """), params)).mappings().all()
    n_stations = (await db.execute(text(f"""
        SELECT COUNT(*) FROM stations s
        JOIN cities c ON c.id = s.city_id JOIN states st ON st.id = s.state_id JOIN countries co ON co.id = s.country_id
        LEFT JOIN providers p ON p.id = s.provider_id
        WHERE s.active = TRUE AND LOWER(c.name) = LOWER(:city) {scope} {provider_filter}
    """), {k: v for k, v in params.items() if k in ("city", "province", "country")})).scalar() or 0
    return {
        "meta": {
            "city": city, "province": province, "country": country,
            "start_utc": iso_z(s_utc), "end_utc": iso_z(e_utc), "tz": "Asia/Karachi",
            "aggregation": "reporting-station mean of hourly PM2.5 (unweighted across stations with a reading that hour)",
            "stations_in_scope": int(n_stations),
            "units": {"pm25": "µg/m³"},
        },
        "rows": [
            {
                "timestamp_utc": iso_z(r["hour_utc"]),
                "timestamp_pk": (r["hour_utc"] + PK_OFFSET).strftime("%Y-%m-%dT%H:%M:%S+05:00"),
                "pm25": round(float(r["avg_pm25"]), 1),
                "stations_used": int(r["stations_used"]),
            }
            for r in rows
        ],
    }
