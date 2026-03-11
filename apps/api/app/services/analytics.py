"""Analytics service layer — merges DB observations with GCS forecast data.

Six async functions that power both the REST analytics endpoints and
the copilot tools.  Observation-first for "current conditions" queries;
forecast-first for "alert/driver" queries.
"""

import logging
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers.analyst_desk import (
    _load_forecast,
    _load_drift_report,
    _load_summary_safe,
    _load_watchlist_safe,
    _resolve_latest_date,
)

logger = logging.getLogger(__name__)

# ── Risk band thresholds (µg/m³) ─────────────────────────────────────────

_PM25_BANDS = [
    (35, "good"),
    (75, "moderate"),
    (150, "unhealthy"),
    (250, "very_unhealthy"),
]


def _classify_band(pm25: float | None) -> str:
    if pm25 is None:
        return "unknown"
    for threshold, band in _PM25_BANDS:
        if pm25 <= threshold:
            return band
    return "severe"


_BAND_ORDER = {
    "severe": 5,
    "very_unhealthy": 4,
    "unhealthy": 3,
    "moderate": 2,
    "good": 1,
    "unknown": 0,
}

_WATCHLIST_SEVERITY = {
    "ramp_alerts": "critical",
    "high_pm25": "critical",
    "rapid_deterioration": "critical",
    "new_episodes": "warning",
    "anomaly_drivers": "warning",
    "persistent_unhealthy": "warning",
    "confidence_concerns": "info",
    "improving": "info",
}


def _safe_round(val, decimals=1):
    if val is None:
        return None
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return None


def _country_clause(alias: str = "co") -> str:
    """Return SQL clause fragment for optional country filtering.

    When :country param is non-empty, filters stations by country name.
    Requires countries table joined as `alias`.
    """
    return f"AND LOWER({alias}.name) = LOWER(:country)"


def _resolve_date(date_str: str | None) -> str:
    """Return explicit date or resolve latest from GCS."""
    if date_str:
        return date_str
    return _resolve_latest_date()


def _load_forecast_safe(dt: str) -> dict:
    try:
        return _load_forecast(dt)
    except Exception as e:
        logger.warning(f"Forecast load failed for {dt}: {e}")
        return {}


# ── Envelope builder ──────────────────────────────────────────────────────

def _make_envelope(
    date: str,
    data: dict,
    *,
    ui_actions: list | None = None,
    followups: list | None = None,
    provenance: str = "observations_db",
) -> dict:
    """Standard response wrapper for all analytics functions."""
    import json as _json

    actions = ui_actions or []
    action_hint = ""
    if actions:
        action_hint = "{{ACTION:" + _json.dumps(actions[0]) + "}}"
    return {
        "date": date,
        "data": data,
        "action_hint": action_hint,
        "followups": followups or [],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. HOTSPOTS DAILY
# ═══════════════════════════════════════════════════════════════════════════

async def get_hotspots_daily(
    db: AsyncSession,
    date: str | None = None,
    geography: str = "city",
    metric: str = "avg_pm25",
    top_k: int = 5,
    country: str | None = None,
) -> dict:
    """Current air quality hotspots based on actual station observations.

    Queries the DB for the latest PM2.5 reading per station (last 24h),
    groups by city/station/province, ranks by metric, and optionally
    enriches with D+1 forecast outlook from GCS.
    """
    dt = _resolve_date(date)

    # Parse the target date for the observation window
    try:
        target_date = date_cls.fromisoformat(dt)
    except ValueError:
        target_date = date_cls.today()

    window_end = datetime(
        target_date.year, target_date.month, target_date.day,
        23, 59, 59, tzinfo=timezone.utc,
    )
    window_start = window_end - timedelta(hours=24)

    if geography == "station":
        result = await _hotspots_station(db, window_start, window_end, metric, top_k, country)
    elif geography == "province":
        result = await _hotspots_grouped(
            db, window_start, window_end, "state", metric, top_k, country,
        )
    else:
        result = await _hotspots_grouped(
            db, window_start, window_end, "city", metric, top_k, country,
        )

    national = result["national_summary"]
    hotspots = result["hotspots"]

    # Enrich with forecast outlook for top hotspots
    forecast_outlook = []
    forecast = _load_forecast_safe(dt)
    if forecast.get("forecasts"):
        d1 = [e for e in forecast["forecasts"] if e.get("lead_days") == 1]
        top_names = {h["name"].lower() for h in hotspots} if hotspots else set()
        for e in d1:
            city = (e.get("city_name") or e.get("city") or "").lower()
            if city in top_names:
                forecast_outlook.append({
                    "city": e.get("city_name") or e.get("city", ""),
                    "pm25_forecast_d1": _safe_round(e.get("pm25_forecast")),
                    "risk_band": e.get("risk_band"),
                    "ramp_detected": e.get("ramp_detected", False),
                })

    # UI actions
    ui_actions = []
    if hotspots:
        top = hotspots[0]
        if geography == "station" and top.get("latitude"):
            ui_actions.append({
                "type": "zoom_to_station",
                "sensor_id": top.get("sensor_id"),
                "lat": top["latitude"],
                "lng": top["longitude"],
            })
        else:
            ui_actions.append({"type": "zoom_to_city", "city": top["name"]})

    followups = [
        f"Tell me more about {hotspots[0]['name']}" if hotspots else None,
        "What needs attention today?",
        "How accurate are the forecasts?",
    ]
    followups = [f for f in followups if f]

    data = {
        "national_summary": national,
        "geography": geography,
        "metric": metric,
        "hotspots": hotspots,
    }
    if forecast_outlook:
        data["forecast_outlook"] = forecast_outlook

    return _make_envelope(
        dt, data,
        ui_actions=ui_actions,
        followups=followups,
        provenance="observations_db + forecast_json",
    )


async def _hotspots_station(
    db: AsyncSession,
    window_start: datetime,
    window_end: datetime,
    metric: str,
    top_k: int,
    country: str | None = None,
) -> dict:
    """Station-level hotspots from DB observations."""
    country_filter = _country_clause("co") if country else ""
    query = text(f"""
        WITH latest_per_station AS (
            SELECT DISTINCT ON (s.station_id)
                s.station_id, s.name AS station_name,
                c.name AS city_name, st.name AS state_name,
                r.pm25, r.aqi_us, r.ts_utc, s.lat, s.lon
            FROM readings r
            JOIN stations s ON r.scope_key = s.station_id
            LEFT JOIN cities c ON s.city_id = c.id
            LEFT JOIN states st ON s.state_id = st.id
            LEFT JOIN countries co ON s.country_id = co.id
            WHERE r.scope_type = 'station'
              AND r.ts_utc >= :window_start
              AND r.ts_utc <= :window_end
              AND r.pm25 IS NOT NULL
              AND s.active = true
              {country_filter}
            ORDER BY s.station_id, r.ts_utc DESC
        )
        SELECT * FROM latest_per_station
        ORDER BY pm25 DESC
    """)
    params: dict = {"window_start": window_start, "window_end": window_end}
    if country:
        params["country"] = country
    rows = (await db.execute(query, params)).mappings().all()

    # National summary
    vals = [r["pm25"] for r in rows if r["pm25"] is not None]
    national = _build_national_summary(vals, rows)

    # Build hotspots
    hotspots = []
    for r in rows[:top_k]:
        hotspots.append({
            "name": r["station_name"] or "",
            "station_id": r["station_id"],
            "city": r["city_name"] or "",
            "pm25": _safe_round(r["pm25"]),
            "aqi_us": r["aqi_us"],
            "risk_band": _classify_band(r["pm25"]),
            "latitude": r["lat"],
            "longitude": r["lon"],
            "observed_at": r["ts_utc"].isoformat() if r["ts_utc"] else None,
        })

    return {"national_summary": national, "hotspots": hotspots}


async def _hotspots_grouped(
    db: AsyncSession,
    window_start: datetime,
    window_end: datetime,
    group_by: str,
    metric: str,
    top_k: int,
    country: str | None = None,
) -> dict:
    """City or province level hotspots from DB observations."""
    if group_by == "state":
        group_col = "st.name"
        group_alias = "group_name"
    else:
        group_col = "c.name"
        group_alias = "group_name"

    country_filter = _country_clause("co") if country else ""
    query = text(f"""
        WITH latest_per_station AS (
            SELECT DISTINCT ON (s.station_id)
                s.station_id, {group_col} AS {group_alias},
                r.pm25, r.ts_utc
            FROM readings r
            JOIN stations s ON r.scope_key = s.station_id
            LEFT JOIN cities c ON s.city_id = c.id
            LEFT JOIN states st ON s.state_id = st.id
            LEFT JOIN countries co ON s.country_id = co.id
            WHERE r.scope_type = 'station'
              AND r.ts_utc >= :window_start
              AND r.ts_utc <= :window_end
              AND r.pm25 IS NOT NULL
              AND s.active = true
              {country_filter}
            ORDER BY s.station_id, r.ts_utc DESC
        )
        SELECT
            {group_alias},
            COUNT(*) AS n_stations,
            ROUND(AVG(pm25)::numeric, 1) AS avg_pm25,
            ROUND(MAX(pm25)::numeric, 1) AS max_pm25
        FROM latest_per_station
        WHERE {group_alias} IS NOT NULL
        GROUP BY {group_alias}
        ORDER BY {"avg_pm25" if metric == "avg_pm25" else "max_pm25"} DESC
    """)
    params: dict = {"window_start": window_start, "window_end": window_end}
    if country:
        params["country"] = country
    rows = (await db.execute(query, params)).mappings().all()

    # Summary from all rows (scoped to same country filter)
    all_stations_query = text(f"""
        WITH latest_per_station AS (
            SELECT DISTINCT ON (s.station_id)
                s.station_id, r.pm25
            FROM readings r
            JOIN stations s ON r.scope_key = s.station_id
            LEFT JOIN countries co ON s.country_id = co.id
            WHERE r.scope_type = 'station'
              AND r.ts_utc >= :window_start
              AND r.ts_utc <= :window_end
              AND r.pm25 IS NOT NULL
              AND s.active = true
              {country_filter}
            ORDER BY s.station_id, r.ts_utc DESC
        )
        SELECT pm25 FROM latest_per_station
    """)
    all_rows = (await db.execute(all_stations_query, params)).mappings().all()
    all_vals = [r["pm25"] for r in all_rows]
    national = _build_national_summary(all_vals, all_rows)

    hotspots = []
    for r in rows[:top_k]:
        avg = float(r["avg_pm25"]) if r["avg_pm25"] is not None else None
        hotspots.append({
            "name": r["group_name"],
            "n_stations": r["n_stations"],
            "avg_pm25": _safe_round(avg),
            "max_pm25": _safe_round(r["max_pm25"]),
            "worst_band": _classify_band(r["max_pm25"]),
        })

    return {"national_summary": national, "hotspots": hotspots}


def _build_national_summary(
    vals: list[float], rows: list,
) -> dict:
    """Build national summary stats from observation values."""
    band_counts: dict[str, int] = {}
    for v in vals:
        b = _classify_band(v)
        band_counts[b] = band_counts.get(b, 0) + 1

    return {
        "n_stations": len(vals),
        "mean_pm25": _safe_round(sum(vals) / len(vals)) if vals else None,
        "max_pm25": _safe_round(max(vals)) if vals else None,
        "band_counts": band_counts,
        "source": "observations",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. CITY DETAIL
# ═══════════════════════════════════════════════════════════════════════════

async def get_city_detail(
    db: AsyncSession,
    city_name: str = "",
    date: str | None = None,
    include: list[str] | None = None,
    sensor_id: str | None = None,
) -> dict:
    """Detailed air quality for a city or specific station.

    Primary source: DB observations (current readings + 24h trend).
    Enrichment: forecast D+1..D+3 outlook from GCS.
    """
    if include is None:
        include = ["stations", "trend"]
    dt = _resolve_date(date)

    try:
        target_date = date_cls.fromisoformat(dt)
    except ValueError:
        target_date = date_cls.today()

    window_end = datetime(
        target_date.year, target_date.month, target_date.day,
        23, 59, 59, tzinfo=timezone.utc,
    )
    window_start = window_end - timedelta(hours=24)

    # ── Station lookup by station_id (hex) ──
    if sensor_id:
        return await _station_detail(db, sensor_id, dt, window_start, window_end)

    # ── City lookup ──
    # Find matching city (case-insensitive)
    city_query = text("""
        SELECT c.id, c.name
        FROM cities c
        WHERE LOWER(c.name) = LOWER(:city_name)
          AND c.active = true
        LIMIT 1
    """)
    city_row = (await db.execute(city_query, {"city_name": city_name})).mappings().first()

    if not city_row:
        # Try fuzzy: check forecast data for city names
        forecast = _load_forecast_safe(dt)
        entries = forecast.get("forecasts", [])
        available = _all_city_names(entries)[:10]
        return _make_envelope(dt, {
            "message": f"City '{city_name}' not found.",
            "available_cities_sample": available,
        })

    matched_city = city_row["name"]
    city_id = city_row["id"]

    result: dict = {"city": matched_city}

    # Stations section — current readings
    if "stations" in include:
        stations_query = text("""
            SELECT s.station_id, s.name AS station_name, s.lat, s.lon,
                   r.pm25, r.aqi_us, r.ts_utc
            FROM stations s
            JOIN LATERAL (
                SELECT pm25, aqi_us, ts_utc
                FROM readings
                WHERE scope_key = s.station_id
                  AND scope_type = 'station'
                  AND ts_utc >= :window_start
                  AND ts_utc <= :window_end
                  AND pm25 IS NOT NULL
                ORDER BY ts_utc DESC
                LIMIT 1
            ) r ON true
            WHERE s.city_id = :city_id AND s.active = true
            ORDER BY r.pm25 DESC
        """)
        station_rows = (await db.execute(stations_query, {
            "city_id": city_id,
            "window_start": window_start,
            "window_end": window_end,
        })).mappings().all()

        stations = []
        for s in station_rows[:20]:
            stations.append({
                "station_id": s["station_id"],
                "station_name": s["station_name"] or "",
                "pm25": _safe_round(s["pm25"]),
                "aqi_us": s["aqi_us"],
                "risk_band": _classify_band(s["pm25"]),
                "latitude": s["lat"],
                "longitude": s["lon"],
                "observed_at": s["ts_utc"].isoformat() if s["ts_utc"] else None,
            })
        result["stations"] = stations
        result["n_stations_total"] = len(station_rows)

        # City current summary
        all_pm = [s["pm25"] for s in station_rows if s["pm25"] is not None]
        if all_pm:
            result["current_summary"] = {
                "mean_pm25": _safe_round(sum(all_pm) / len(all_pm)),
                "max_pm25": _safe_round(max(all_pm)),
                "n_stations": len(all_pm),
                "worst_band": _classify_band(max(all_pm)),
                "source": "observations",
            }

    # 24h trend
    if "trend" in include:
        trend_query = text("""
            SELECT
                date_trunc('hour', r.ts_utc) AS hour,
                ROUND(AVG(r.pm25)::numeric, 1) AS avg_pm25,
                COUNT(*) AS n_readings
            FROM readings r
            JOIN stations s ON r.scope_key = s.station_id
            WHERE s.city_id = :city_id
              AND s.active = true
              AND r.scope_type = 'station'
              AND r.ts_utc >= :window_start
              AND r.ts_utc <= :window_end
              AND r.pm25 IS NOT NULL
            GROUP BY date_trunc('hour', r.ts_utc)
            ORDER BY hour
        """)
        trend_rows = (await db.execute(trend_query, {
            "city_id": city_id,
            "window_start": window_start,
            "window_end": window_end,
        })).mappings().all()

        result["trend_24h"] = [
            {
                "hour": r["hour"].isoformat() if r["hour"] else None,
                "avg_pm25": float(r["avg_pm25"]) if r["avg_pm25"] is not None else None,
                "n_readings": r["n_readings"],
            }
            for r in trend_rows
        ]

    # Forecast outlook (D+1..D+3)
    if "forecast" in include:
        forecast = _load_forecast_safe(dt)
        entries = forecast.get("forecasts", [])
        city_lower = matched_city.lower()
        city_fc = [
            e for e in entries
            if (e.get("city_name") or e.get("city") or "").lower() == city_lower
        ]
        outlook = {}
        for ld in (1, 2, 3):
            h_entries = [e for e in city_fc if e.get("lead_days") == ld]
            pms = [e["pm25_forecast"] for e in h_entries if e.get("pm25_forecast") is not None]
            if pms:
                worst_band = max(
                    (e.get("risk_band", "unknown") for e in h_entries),
                    key=lambda b: _BAND_ORDER.get(b, 0),
                )
                outlook[f"D+{ld}"] = {
                    "pm25_mean": _safe_round(sum(pms) / len(pms)),
                    "pm25_max": _safe_round(max(pms)),
                    "worst_band": worst_band,
                    "n_stations": len(pms),
                }
        if outlook:
            result["forecast_outlook"] = outlook

    ui_actions = [{"type": "zoom_to_city", "city": matched_city}]
    followups = [
        f"Why is {matched_city} so polluted?",
        f"How does {matched_city} compare to yesterday?",
        "What stations need attention?",
    ]

    return _make_envelope(dt, result, ui_actions=ui_actions, followups=followups)


async def _station_detail(
    db: AsyncSession,
    station_id: str,
    dt: str,
    window_start: datetime,
    window_end: datetime,
) -> dict:
    """Single station detail with current reading + forecast horizons."""
    # Current observation
    obs_query = text("""
        SELECT s.station_id, s.name AS station_name, s.lat, s.lon,
               c.name AS city_name, st.name AS state_name,
               r.pm25, r.aqi_us, r.ts_utc, r.temp_c, r.humidity,
               r.wind_speed_ms, r.wind_dir_deg
        FROM stations s
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN states st ON s.state_id = st.id
        JOIN LATERAL (
            SELECT pm25, aqi_us, ts_utc, temp_c, humidity,
                   wind_speed_ms, wind_dir_deg
            FROM readings
            WHERE scope_key = s.station_id
              AND scope_type = 'station'
              AND ts_utc >= :window_start
              AND ts_utc <= :window_end
            ORDER BY ts_utc DESC
            LIMIT 1
        ) r ON true
        WHERE s.station_id = :station_id
    """)
    row = (await db.execute(obs_query, {
        "station_id": station_id,
        "window_start": window_start,
        "window_end": window_end,
    })).mappings().first()

    if not row:
        return _make_envelope(dt, {"message": f"Station {station_id} not found or no recent data."})

    city = row["city_name"] or ""
    data = {
        "city": city,
        "station": {
            "station_id": row["station_id"],
            "station_name": row["station_name"] or "",
            "latitude": row["lat"],
            "longitude": row["lon"],
        },
        "current_observation": {
            "pm25": _safe_round(row["pm25"]),
            "aqi_us": row["aqi_us"],
            "risk_band": _classify_band(row["pm25"]),
            "observed_at": row["ts_utc"].isoformat() if row["ts_utc"] else None,
            "temp_c": _safe_round(row["temp_c"]),
            "humidity": _safe_round(row["humidity"]),
            "wind_speed_ms": _safe_round(row["wind_speed_ms"]),
            "wind_dir_deg": row["wind_dir_deg"],
        },
    }

    # Enrich with forecast horizons from GCS
    forecast = _load_forecast_safe(dt)
    entries = forecast.get("forecasts", [])
    # Try matching by station_id (hex) first, then fall back to name match
    fc_rows = [
        e for e in entries
        if e.get("station_id") == station_id
    ]
    if not fc_rows:
        # Fallback: match by station name
        sname = (row["station_name"] or "").lower()
        fc_rows = [
            e for e in entries
            if (e.get("station_name") or "").lower() == sname and sname
        ]
    if fc_rows:
        fc_rows.sort(key=lambda e: e.get("lead_days", 0))
        data["forecast_horizons"] = [
            {
                "lead_days": r.get("lead_days"),
                "target_date": r.get("target_date"),
                "pm25_forecast": _safe_round(r.get("pm25_forecast")),
                "pm25_q90": _safe_round(r.get("pm25_q90")),
                "risk_band": r.get("risk_band"),
                "ramp_detected": r.get("ramp_detected", False),
            }
            for r in fc_rows
        ]

    ui_actions = []
    if row["lat"]:
        ui_actions.append({
            "type": "zoom_to_station",
            "station_id": station_id,
            "lat": row["lat"],
            "lng": row["lon"],
        })

    followups = [f"Tell me about {city}" if city else "What needs attention today?"]

    return _make_envelope(dt, data, ui_actions=ui_actions, followups=followups)


# ═══════════════════════════════════════════════════════════════════════════
# 3. COMPARE DATES
# ═══════════════════════════════════════════════════════════════════════════

async def get_compare_dates(
    db: AsyncSession,
    date1: str,
    date2: str,
    geography: str = "national",
    country: str | None = None,
) -> dict:
    """Compare observed PM2.5 between two dates.

    Queries DB for average PM2.5 on each date, computes delta and direction.
    For national scope, identifies biggest movers (cities with largest change).
    """
    country_filter = _country_clause("co") if country else ""

    async def _obs_stats(d: str, city_filter: str | None = None) -> dict:
        try:
            dt = date_cls.fromisoformat(d)
        except ValueError:
            return {"n_stations": 0, "mean_pm25": None, "max_pm25": None, "date": d}

        w_start = datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=timezone.utc)

        if city_filter:
            query = text(f"""
                WITH latest_per_station AS (
                    SELECT DISTINCT ON (s.station_id)
                        s.station_id, r.pm25
                    FROM readings r
                    JOIN stations s ON r.scope_key = s.station_id
                    JOIN cities c ON s.city_id = c.id
                    LEFT JOIN countries co ON s.country_id = co.id
                    WHERE r.scope_type = 'station'
                      AND r.ts_utc >= :w_start AND r.ts_utc <= :w_end
                      AND r.pm25 IS NOT NULL AND s.active = true
                      AND LOWER(c.name) = LOWER(:city)
                      {country_filter}
                    ORDER BY s.station_id, r.ts_utc DESC
                )
                SELECT COUNT(*) AS n, ROUND(AVG(pm25)::numeric, 1) AS avg,
                       ROUND(MAX(pm25)::numeric, 1) AS mx
                FROM latest_per_station
            """)
            params: dict = {"w_start": w_start, "w_end": w_end, "city": city_filter}
            if country:
                params["country"] = country
            row = (await db.execute(query, params)).mappings().first()
        else:
            query = text(f"""
                WITH latest_per_station AS (
                    SELECT DISTINCT ON (s.station_id)
                        s.station_id, r.pm25
                    FROM readings r
                    JOIN stations s ON r.scope_key = s.station_id
                    LEFT JOIN countries co ON s.country_id = co.id
                    WHERE r.scope_type = 'station'
                      AND r.ts_utc >= :w_start AND r.ts_utc <= :w_end
                      AND r.pm25 IS NOT NULL AND s.active = true
                      {country_filter}
                    ORDER BY s.station_id, r.ts_utc DESC
                )
                SELECT COUNT(*) AS n, ROUND(AVG(pm25)::numeric, 1) AS avg,
                       ROUND(MAX(pm25)::numeric, 1) AS mx
                FROM latest_per_station
            """)
            params = {"w_start": w_start, "w_end": w_end}
            if country:
                params["country"] = country
            row = (await db.execute(query, params)).mappings().first()

        if not row or not row["n"]:
            return {"n_stations": 0, "mean_pm25": None, "max_pm25": None, "date": d}
        return {
            "n_stations": row["n"],
            "mean_pm25": float(row["avg"]) if row["avg"] is not None else None,
            "max_pm25": float(row["mx"]) if row["mx"] is not None else None,
            "date": d,
        }

    city_filter = geography if geography != "national" else None
    s1 = await _obs_stats(date1, city_filter)
    s2 = await _obs_stats(date2, city_filter)

    delta_mean = None
    direction = "unchanged"
    if s1["mean_pm25"] is not None and s2["mean_pm25"] is not None:
        delta_mean = _safe_round(s2["mean_pm25"] - s1["mean_pm25"])
        if delta_mean is not None:
            if delta_mean > 2:
                direction = "worsening"
            elif delta_mean < -2:
                direction = "improving"

    # Biggest movers (national only)
    biggest_movers: list[dict] = []
    if geography == "national":
        try:
            dt1 = date_cls.fromisoformat(date1)
            dt2 = date_cls.fromisoformat(date2)
        except ValueError:
            dt1 = dt2 = None

        if dt1 and dt2:
            movers_query = text(f"""
                WITH day1 AS (
                    SELECT DISTINCT ON (s.station_id)
                        c.name AS city_name, s.station_id,
                        r.pm25 AS pm25_d1
                    FROM readings r
                    JOIN stations s ON r.scope_key = s.station_id
                    LEFT JOIN cities c ON s.city_id = c.id
                    LEFT JOIN countries co ON s.country_id = co.id
                    WHERE r.scope_type = 'station'
                      AND r.ts_utc >= :d1_start AND r.ts_utc <= :d1_end
                      AND r.pm25 IS NOT NULL AND s.active = true
                      {country_filter}
                    ORDER BY s.station_id, r.ts_utc DESC
                ),
                day2 AS (
                    SELECT DISTINCT ON (s.station_id)
                        c.name AS city_name, s.station_id,
                        r.pm25 AS pm25_d2
                    FROM readings r
                    JOIN stations s ON r.scope_key = s.station_id
                    LEFT JOIN cities c ON s.city_id = c.id
                    LEFT JOIN countries co ON s.country_id = co.id
                    WHERE r.scope_type = 'station'
                      AND r.ts_utc >= :d2_start AND r.ts_utc <= :d2_end
                      AND r.pm25 IS NOT NULL AND s.active = true
                      {country_filter}
                    ORDER BY s.station_id, r.ts_utc DESC
                )
                SELECT
                    COALESCE(d1.city_name, d2.city_name) AS city,
                    COUNT(*) AS n_stations,
                    ROUND(AVG(d1.pm25_d1)::numeric, 1) AS avg_d1,
                    ROUND(AVG(d2.pm25_d2)::numeric, 1) AS avg_d2,
                    ROUND((AVG(d2.pm25_d2) - AVG(d1.pm25_d1))::numeric, 1) AS delta
                FROM day1 d1
                JOIN day2 d2 ON d1.station_id = d2.station_id
                GROUP BY COALESCE(d1.city_name, d2.city_name)
                HAVING ABS(AVG(d2.pm25_d2) - AVG(d1.pm25_d1)) > 5
                ORDER BY ABS(AVG(d2.pm25_d2) - AVG(d1.pm25_d1)) DESC
                LIMIT 10
            """)
            d1_start = datetime(dt1.year, dt1.month, dt1.day, 0, 0, 0, tzinfo=timezone.utc)
            d1_end = datetime(dt1.year, dt1.month, dt1.day, 23, 59, 59, tzinfo=timezone.utc)
            d2_start = datetime(dt2.year, dt2.month, dt2.day, 0, 0, 0, tzinfo=timezone.utc)
            d2_end = datetime(dt2.year, dt2.month, dt2.day, 23, 59, 59, tzinfo=timezone.utc)

            movers_params: dict = {
                "d1_start": d1_start, "d1_end": d1_end,
                "d2_start": d2_start, "d2_end": d2_end,
            }
            if country:
                movers_params["country"] = country
            mover_rows = (await db.execute(movers_query, movers_params)).mappings().all()

            for m in mover_rows:
                biggest_movers.append({
                    "city": m["city"] or "Unknown",
                    "n_stations": m["n_stations"],
                    "avg_pm25_date1": float(m["avg_d1"]) if m["avg_d1"] is not None else None,
                    "avg_pm25_date2": float(m["avg_d2"]) if m["avg_d2"] is not None else None,
                    "delta": float(m["delta"]) if m["delta"] is not None else None,
                })

    followups = []
    if direction == "worsening":
        followups.append("What's driving the deterioration?")
    elif direction == "improving":
        followups.append("Which areas improved the most?")

    return _make_envelope(
        date2,
        {
            "date1": date1,
            "date2": date2,
            "geography": geography,
            "stats_date1": s1,
            "stats_date2": s2,
            "delta_mean_pm25": delta_mean,
            "direction": direction,
            "biggest_movers": biggest_movers,
            "source": "observations",
        },
        followups=followups,
        provenance="observations_db",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 4. EXPLAIN DRIVERS
# ═══════════════════════════════════════════════════════════════════════════

async def get_explain_drivers(
    db: AsyncSession,
    target: str,
    date: str | None = None,
) -> dict:
    """Explain why air quality is poor — fire activity, stagnation, transport.

    Primary source: watchlist anomaly_drivers from GCS.
    Enrichment: current observations from DB for ground-truth context.
    """
    dt = _resolve_date(date)
    target_lower = target.lower()

    # Load watchlist for anomaly drivers (GCS — primary source)
    watchlist_data = _load_watchlist_safe(dt)
    drivers: list[dict] = []
    related_alerts: list[dict] = []

    if watchlist_data:
        watchlists = watchlist_data.get("watchlists", {})

        for entry in watchlists.get("anomaly_drivers", []):
            name = (entry.get("city_name") or entry.get("station_name") or entry.get("city") or "").lower()
            station = (entry.get("station_name") or "").lower()
            if target_lower in name or target_lower in station:
                drivers.append(entry)

        for wl_name, wl_entries in watchlists.items():
            if wl_name == "anomaly_drivers":
                continue
            for entry in wl_entries:
                name = (entry.get("city_name") or entry.get("station_name") or entry.get("city") or "").lower()
                station = (entry.get("station_name") or "").lower()
                if target_lower in name or target_lower in station:
                    related_alerts.append({
                        "watchlist": wl_name,
                        "severity": _WATCHLIST_SEVERITY.get(wl_name, "info"),
                        **{k: v for k, v in entry.items() if k not in ("city_name", "station_name")},
                    })

    # Current observations from DB for ground-truth context
    try:
        target_date = date_cls.fromisoformat(dt)
    except ValueError:
        target_date = date_cls.today()
    w_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=timezone.utc)
    w_start = w_end - timedelta(hours=24)

    obs_query = text("""
        SELECT s.station_id, s.name AS station_name,
               r.pm25, r.aqi_us, r.ts_utc
        FROM stations s
        JOIN cities c ON s.city_id = c.id
        JOIN LATERAL (
            SELECT pm25, aqi_us, ts_utc
            FROM readings
            WHERE scope_key = s.station_id
              AND scope_type = 'station'
              AND ts_utc >= :w_start AND ts_utc <= :w_end
              AND pm25 IS NOT NULL
            ORDER BY ts_utc DESC
            LIMIT 1
        ) r ON true
        WHERE LOWER(c.name) = LOWER(:target) AND s.active = true
        ORDER BY r.pm25 DESC
        LIMIT 10
    """)
    obs_rows = (await db.execute(obs_query, {
        "target": target, "w_start": w_start, "w_end": w_end,
    })).mappings().all()

    current_conditions = [
        {
            "station_id": r["station_id"],
            "station_name": r["station_name"] or "",
            "pm25": _safe_round(r["pm25"]),
            "aqi_us": r["aqi_us"],
            "risk_band": _classify_band(r["pm25"]),
            "observed_at": r["ts_utc"].isoformat() if r["ts_utc"] else None,
        }
        for r in obs_rows
    ]

    has_data = bool(drivers or related_alerts or current_conditions)

    ui_actions = [{"type": "zoom_to_city", "city": target}]
    followups = [
        f"Show me the full detail for {target}",
        "What other areas need attention?",
    ]

    return _make_envelope(
        dt,
        {
            "target": target,
            "driver_attribution": drivers[:10],
            "related_alerts": related_alerts[:10],
            "current_conditions": current_conditions,
            "data_available": has_data,
            "note": None if has_data else f"No driver attribution data available for '{target}'. Showing current conditions only.",
        },
        ui_actions=ui_actions,
        followups=followups,
        provenance="watchlist_json + observations_db",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5. INCIDENT SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

async def get_incident_summary(
    db: AsyncSession,
    date: str | None = None,
    severity: str = "all",
    country: str | None = None,
) -> dict:
    """Active incidents and alerts from watchlists, enriched with current observations.

    Primary source: watchlist JSON from GCS.
    Enrichment: current PM2.5 from DB where station crosswalk exists.
    Fallback: if no watchlist, identify unhealthy+ stations from DB observations.
    """
    dt = _resolve_date(date)
    watchlist_data = _load_watchlist_safe(dt)

    incidents: list[dict] = []

    if watchlist_data:
        watchlists = watchlist_data.get("watchlists", {})
        for wl_name, wl_entries in watchlists.items():
            sev = _WATCHLIST_SEVERITY.get(wl_name, "info")
            if severity != "all" and sev != severity:
                continue
            for entry in wl_entries:
                incidents.append({
                    "watchlist": wl_name,
                    "severity": sev,
                    "sensor_id": entry.get("sensor_id"),
                    "station_name": entry.get("station_name", ""),
                    "city": entry.get("city_name") or entry.get("city") or "",
                    "pm25_forecast": entry.get("pm25_forecast"),
                    "risk_band": entry.get("risk_band"),
                    "reason": entry.get("reason") or entry.get("label") or wl_name.replace("_", " "),
                })

        # Enrich with current observations where station_id crosswalk exists
        station_ids = [
            e.get("station_id") for e in incidents
            if e.get("station_id") and len(str(e.get("station_id", ""))) == 16
        ]
        if station_ids:
            obs_query = text("""
                SELECT DISTINCT ON (s.station_id)
                    s.station_id, r.pm25
                FROM readings r
                JOIN stations s ON r.scope_key = s.station_id
                WHERE r.scope_type = 'station'
                  AND s.station_id = ANY(:ids)
                  AND r.ts_utc >= NOW() - INTERVAL '24 hours'
                  AND r.pm25 IS NOT NULL
                ORDER BY s.station_id, r.ts_utc DESC
            """)
            obs_rows = (await db.execute(
                obs_query, {"ids": station_ids},
            )).mappings().all()
            obs_map = {r["station_id"]: r["pm25"] for r in obs_rows}
            for inc in incidents:
                sid = inc.get("station_id")
                if sid and sid in obs_map:
                    inc["pm25_observed"] = _safe_round(obs_map[sid])
    else:
        # Fallback: identify unhealthy+ stations from DB observations
        try:
            target_date = date_cls.fromisoformat(dt)
        except ValueError:
            target_date = date_cls.today()

        w_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=timezone.utc)
        w_start = w_end - timedelta(hours=24)

        country_filter = _country_clause("co") if country else ""
        fallback_query = text(f"""
            WITH latest_per_station AS (
                SELECT DISTINCT ON (s.station_id)
                    s.station_id, s.name AS station_name,
                    c.name AS city_name, r.pm25, r.ts_utc
                FROM readings r
                JOIN stations s ON r.scope_key = s.station_id
                LEFT JOIN cities c ON s.city_id = c.id
                LEFT JOIN countries co ON s.country_id = co.id
                WHERE r.scope_type = 'station'
                  AND r.ts_utc >= :w_start AND r.ts_utc <= :w_end
                  AND r.pm25 IS NOT NULL AND s.active = true
                  {country_filter}
                ORDER BY s.station_id, r.ts_utc DESC
            )
            SELECT * FROM latest_per_station
            WHERE pm25 > 75
            ORDER BY pm25 DESC
            LIMIT 30
        """)
        fallback_params: dict = {"w_start": w_start, "w_end": w_end}
        if country:
            fallback_params["country"] = country
        fallback_rows = (await db.execute(fallback_query, fallback_params)).mappings().all()

        for r in fallback_rows:
            band = _classify_band(r["pm25"])
            sev = "critical" if _BAND_ORDER.get(band, 0) >= 4 else "warning"
            if severity != "all" and sev != severity:
                continue
            incidents.append({
                "watchlist": "observation_fallback",
                "severity": sev,
                "station_id": r["station_id"],
                "station_name": r["station_name"] or "",
                "city": r["city_name"] or "",
                "pm25_observed": _safe_round(r["pm25"]),
                "risk_band": band,
                "reason": f"{band.replace('_', ' ')} observed air quality",
            })

    # Sort: critical first, then by PM2.5 descending
    sev_order = {"critical": 3, "warning": 2, "info": 1}
    incidents.sort(
        key=lambda x: (
            sev_order.get(x["severity"], 0),
            x.get("pm25_observed") or x.get("pm25_forecast") or 0,
        ),
        reverse=True,
    )
    incidents = incidents[:30]

    counts = {
        "critical": sum(1 for i in incidents if i["severity"] == "critical"),
        "warning": sum(1 for i in incidents if i["severity"] == "warning"),
        "info": sum(1 for i in incidents if i["severity"] == "info"),
    }

    followups = []
    if incidents:
        top = incidents[0]
        if top.get("city"):
            followups.append(f"Tell me about {top['city']}")
        followups.append("Why is this happening?")

    return _make_envelope(
        dt,
        {"incidents": incidents, "counts": counts},
        followups=followups,
        provenance="watchlist_json + observations_db" if watchlist_data else "observations_db_fallback",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 6. FORECAST AUDIT
# ═══════════════════════════════════════════════════════════════════════════

async def get_forecast_audit(
    date: str | None = None,
    n_days: int = 1,
) -> dict:
    """Audit forecast accuracy — purely GCS-based (drift reports).

    No DB dependency — this is about forecast accuracy metrics, not observations.
    """
    dt = _resolve_date(date)

    if n_days <= 1:
        report = _load_drift_report(dt)
        if not report:
            return _make_envelope(
                dt,
                {"message": "No drift report available for this date."},
                provenance="drift_json",
            )

        data: dict = {}

        perf = report.get("delayed_performance")
        if perf:
            data["check_date"] = perf.get("check_date")
            data["n_matched"] = perf.get("n_matched")
            horizons = {}
            for key in ("D+1", "D+2", "D+3"):
                h = perf.get(key)
                if h:
                    horizons[key] = {
                        "mae": _safe_round(h.get("mae")),
                        "rmse": _safe_round(h.get("rmse")),
                        "bias": _safe_round(h.get("bias")),
                        "r2": _safe_round(h.get("r2"), 3),
                        "f1_150": _safe_round(h.get("f1_150"), 3),
                    }
            data["accuracy"] = horizons
        else:
            data["accuracy"] = None
            data["accuracy_note"] = "T-3 verification not yet available (needs 3+ days of forecasts)."

        pred = report.get("prediction_stats")
        if pred:
            data["prediction_stats"] = {
                "mean": _safe_round(pred.get("mean")),
                "median": _safe_round(pred.get("median")),
                "p90": _safe_round(pred.get("p90")),
                "n_stations": pred.get("n_stations"),
                "pct_above_150": _safe_round(
                    pred["pct_above_150"] * 100, 1
                ) if pred.get("pct_above_150") is not None else None,
            }

        psi = report.get("feature_psi", {})
        if psi:
            drifting = sorted(psi.items(), key=lambda x: x[1], reverse=True)[:5]
            data["top_feature_drift"] = [
                {"feature": f, "psi": _safe_round(v, 3)} for f, v in drifting if v > 0
            ]

        alerts = report.get("alerts", [])
        if alerts:
            data["alerts"] = alerts

        return _make_envelope(
            dt, data,
            provenance="drift_json",
            followups=["Show me accuracy trend over the last 7 days"],
        )

    else:
        # Multi-day trend
        try:
            end = date_cls.fromisoformat(dt)
        except ValueError:
            return _make_envelope(dt, {"message": f"Invalid date: {dt}"})

        daily: list[dict] = []
        for i in range(n_days):
            d = end - timedelta(days=i)
            d_str = d.isoformat()
            report = _load_drift_report(d_str)
            if not report:
                continue

            entry: dict = {"date": d_str}
            perf = report.get("delayed_performance")
            if perf:
                for key in ("D+1", "D+2", "D+3"):
                    h = perf.get(key)
                    if h:
                        entry[f"{key}_mae"] = _safe_round(h.get("mae"))
                        entry[f"{key}_rmse"] = _safe_round(h.get("rmse"))
                entry["n_matched"] = perf.get("n_matched")
            else:
                entry["accuracy"] = None

            pred = report.get("prediction_stats")
            if pred:
                entry["pred_mean"] = _safe_round(pred.get("mean"))
                entry["n_stations"] = pred.get("n_stations")

            entry["n_alerts"] = len(report.get("alerts", []))
            daily.append(entry)

        if not daily:
            return _make_envelope(
                dt,
                {"message": f"No drift reports found in the last {n_days} days."},
                provenance="drift_json",
            )

        daily.sort(key=lambda x: x["date"])

        maes = [d.get("D+1_mae") for d in daily if d.get("D+1_mae") is not None]
        trend_direction = "stable"
        if len(maes) >= 2:
            if maes[-1] > maes[0] + 2:
                trend_direction = "degrading"
            elif maes[-1] < maes[0] - 2:
                trend_direction = "improving"

        return _make_envelope(
            dt,
            {
                "period": f"{daily[0]['date']} to {daily[-1]['date']}",
                "n_reports": len(daily),
                "trend_direction": trend_direction,
                "daily": daily,
            },
            provenance="drift_json",
            followups=["Show me today's detailed accuracy"],
        )


# ── Shared helpers ────────────────────────────────────────────────────────

def _all_city_names(entries: list[dict]) -> list[str]:
    """Extract unique city names from forecast entries."""
    seen: set[str] = set()
    names: list[str] = []
    for e in entries:
        c = e.get("city_name") or e.get("city") or ""
        if c and c not in seen:
            seen.add(c)
            names.append(c)
    return names
