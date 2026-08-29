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
    _load_driver_summary_safe,
    _load_firms_nrt_safe,
    _load_forecast,
    _load_drift_report,
    _load_summary_safe,
    _load_trajectory_safe,
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
    tool: str = "",
    target: str = "",
    basis: dict | None = None,
) -> dict:
    """Standard response wrapper for all analytics functions."""
    import json as _json

    actions = ui_actions or []
    action_hint = ""
    if actions:
        action_hint = "{{ACTION:" + _json.dumps(actions[0]) + "}}"
    return {
        "meta": {"tool": tool, "target": target, "provenance": provenance},
        "basis": basis or {},
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
            city = e.get("city_name", "").lower()
            if city in top_names:
                forecast_outlook.append({
                    "city": e.get("city_name", ""),
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

    basis = {
        "description": "Latest station observations (last 24h)"
        + (", enriched with forecast outlook" if forecast_outlook else ""),
        "sources": ["station_observations"]
        + (["forecast_json"] if forecast_outlook else []),
        "observation_window": "24h",
    }
    if forecast_outlook:
        basis["forecast_date"] = dt

    return _make_envelope(
        dt, data,
        ui_actions=ui_actions,
        followups=followups,
        provenance="observations_db + forecast_json",
        tool="aq_hotspots_daily",
        target=geography,
        basis=basis,
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
        }, tool="aq_city_detail", target=city_name)

    matched_city = city_row["name"]
    city_id = city_row["id"]

    result: dict = {"city": matched_city}

    # Stations section — current readings
    if "stations" in include:
        # Recency threshold: recently reporting stations rank first
        recency_cutoff = window_end - timedelta(hours=3)

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
            ORDER BY
                CASE WHEN r.ts_utc >= :recency_cutoff THEN 0 ELSE 1 END,
                r.pm25 DESC
        """)
        station_rows = (await db.execute(stations_query, {
            "city_id": city_id,
            "window_start": window_start,
            "window_end": window_end,
            "recency_cutoff": recency_cutoff,
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

        # City current summary — use only recently reporting stations
        recent_pm = [
            s["pm25"] for s in station_rows
            if s["pm25"] is not None and s["ts_utc"] and s["ts_utc"] >= recency_cutoff
        ]
        # Fall back to all stations if none reported in last 3h
        all_pm = recent_pm or [s["pm25"] for s in station_rows if s["pm25"] is not None]
        if all_pm:
            result["current_summary"] = {
                "mean_pm25": _safe_round(sum(all_pm) / len(all_pm)),
                "max_pm25": _safe_round(max(all_pm)),
                "n_stations": len(all_pm),
                "worst_band": _classify_band(max(all_pm)),
                "source": "observations",
                "recency": "last_3h" if recent_pm else "last_24h",
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
            if e.get("city_name", "").lower() == city_lower
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

    # ── Compact driver summary (when available) ─────────────
    compact_drivers = None
    driver_data = _load_driver_summary_safe(dt)
    if driver_data:
        summaries = driver_data.get("driver_summaries", [])
        matched_city_lower = matched_city.lower()
        city_drivers = next(
            (s for s in summaries if s.get("city_name", "").lower() == matched_city_lower),
            None,
        )
        if city_drivers:
            drivers_sorted = sorted(
                city_drivers.get("drivers", []),
                key=lambda d: d.get("score", 0),
                reverse=True,
            )[:2]
            compact_drivers = {
                "primary_driver": city_drivers.get("primary_driver", ""),
                "top_drivers": [
                    {
                        "driver": d["driver"],
                        "score": d["score"],
                        "evidence": d.get("evidence", [])[:2],
                    }
                    for d in drivers_sorted
                ],
                "narrative": city_drivers.get("narrative", ""),
            }
    if compact_drivers:
        result["compact_drivers"] = compact_drivers

    ui_actions = [{"type": "zoom_to_city", "city": matched_city}]
    followups = [
        f"Why is {matched_city} so polluted?",
        f"How does {matched_city} compare to yesterday?",
        "What stations need attention?",
    ]

    basis = {
        "description": f"Station observations for {matched_city} (last 24h)",
        "sources": ["station_observations"],
        "observation_window": "24h",
    }
    if "forecast" in include and result.get("forecast_outlook"):
        basis["sources"].append("forecast_json")
        basis["forecast_date"] = dt
        basis["forecast_horizons"] = ["D+1", "D+2", "D+3"]
    if compact_drivers:
        basis["sources"].append("driver_summary_json")
        basis["driver_source"] = "driver_summary_json"

    return _make_envelope(dt, result, ui_actions=ui_actions, followups=followups, tool="aq_city_detail", target=matched_city, basis=basis)


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
        return _make_envelope(dt, {"message": f"Station {station_id} not found or no recent data."}, tool="aq_city_detail", target=station_id)

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

    basis = {
        "description": f"Station observation for {station_id} (last 24h)",
        "sources": ["station_observations"] + (["forecast_json"] if data.get("forecast_horizons") else []),
        "observation_window": "24h",
    }
    if data.get("forecast_horizons"):
        basis["forecast_date"] = dt
        basis["forecast_horizons"] = ["D+1", "D+2", "D+3"]

    return _make_envelope(dt, data, ui_actions=ui_actions, followups=followups, tool="aq_city_detail", target=station_id, basis=basis)


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

    # ── Driver explanation for comparison ────────────────────
    driver_deltas = None
    ds1 = _load_driver_summary_safe(date1)
    ds2 = _load_driver_summary_safe(date2)
    if ds1 and ds2:
        summaries1 = {s["city_name"].lower(): s for s in ds1.get("driver_summaries", []) if s.get("city_name")}
        summaries2 = {s["city_name"].lower(): s for s in ds2.get("driver_summaries", []) if s.get("city_name")}

        if geography.lower() != "national":
            target_cities = [geography.lower()]
        elif biggest_movers:
            target_cities = [m["city"].lower() for m in biggest_movers[:3]]
        else:
            target_cities = []

        city_deltas = []
        for tc in target_cities:
            d1_drv = summaries1.get(tc)
            d2_drv = summaries2.get(tc)
            if d1_drv and d2_drv:
                drivers1 = {d["driver"]: d["score"] for d in d1_drv.get("drivers", [])}
                drivers2 = {d["driver"]: d["score"] for d in d2_drv.get("drivers", [])}
                all_drivers = set(drivers1) | set(drivers2)
                deltas = []
                for drv in all_drivers:
                    s1_score = drivers1.get(drv, 0)
                    s2_score = drivers2.get(drv, 0)
                    delta = s2_score - s1_score
                    if abs(delta) >= 10:
                        deltas.append({
                            "driver": drv,
                            "score_date1": s1_score,
                            "score_date2": s2_score,
                            "delta": delta,
                            "direction": "increased" if delta > 0 else "decreased",
                        })
                if deltas:
                    deltas.sort(key=lambda d: abs(d["delta"]), reverse=True)
                    city_deltas.append({
                        "city": d2_drv.get("city_name", tc),
                        "primary_driver_date1": d1_drv.get("primary_driver", ""),
                        "primary_driver_date2": d2_drv.get("primary_driver", ""),
                        "driver_shifts": deltas[:3],
                    })
        if city_deltas:
            driver_deltas = city_deltas

    followups = []
    if direction == "worsening":
        followups.append("What's driving the deterioration?")
    elif direction == "improving":
        followups.append("Which areas improved the most?")
    if driver_deltas:
        followups.append(f"Tell me more about the driver changes in {driver_deltas[0]['city']}")

    basis = {
        "description": f"Station observations compared between {date1} and {date2}",
        "sources": ["station_observations"],
        "observation_window": "24h per date",
    }
    if driver_deltas:
        basis["sources"].append("driver_summary_json")
        basis["driver_source"] = "driver_summary_json"

    data = {
        "date1": date1,
        "date2": date2,
        "geography": geography,
        "stats_date1": s1,
        "stats_date2": s2,
        "delta_mean_pm25": delta_mean,
        "direction": direction,
        "biggest_movers": biggest_movers,
        "source": "observations",
    }
    if driver_deltas:
        data["driver_explanation"] = driver_deltas

    return _make_envelope(
        date2,
        data,
        followups=followups,
        provenance="observations_db",
        tool="aq_compare_dates",
        target=geography,
        basis=basis,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 4. EXPLAIN DRIVERS
# ═══════════════════════════════════════════════════════════════════════════

async def get_explain_drivers(
    db: AsyncSession,
    target: str,
    date: str | None = None,
) -> dict:
    """Explain why air quality is poor — scored driver attribution.

    Primary source: driver_summary_YYYYMMDD.json (scored, structured drivers).
    Enrichment: firms_nrt_latest.json for real-time fire updates.
    Ground-truth: DB observations for current conditions.
    Fallback: watchlist anomaly_drivers when no driver_summary exists.
    """
    dt = _resolve_date(date)
    target_lower = target.lower()

    # ── 1. Load scored driver summary (primary source) ──
    driver_data = _load_driver_summary_safe(dt)
    city_drivers: dict | None = None
    if driver_data:
        for ds in driver_data.get("driver_summaries", []):
            name = (ds.get("city_name") or "").lower()
            if target_lower == name or target_lower in name:
                city_drivers = ds
                break
        # Fuzzy fallback: partial match
        if not city_drivers:
            import difflib
            all_cities = [
                ds.get("city_name", "")
                for ds in driver_data.get("driver_summaries", [])
            ]
            matches = difflib.get_close_matches(target, all_cities, n=1, cutoff=0.6)
            if matches:
                for ds in driver_data.get("driver_summaries", []):
                    if ds.get("city_name") == matches[0]:
                        city_drivers = ds
                        break

    # ── 2. Load NRT fire enrichment ──
    nrt_fire: dict | None = None
    firms_nrt = _load_firms_nrt_safe()
    if firms_nrt:
        for city_entry in firms_nrt.get("cities", []):
            name = (city_entry.get("city_name") or "").lower()
            if target_lower == name or target_lower in name:
                nrt_fire = city_entry
                break

    # ── 3. Current observations from DB ──
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

    # ── 4. Build response ──
    if city_drivers:
        matched_city = city_drivers.get("city_name", target)

        # Load trajectory if available (cached in GCS)
        trajectory = _load_trajectory_safe(matched_city, dt)

        # Enrich driver scores with trajectory evidence
        driver_list = city_drivers.get("drivers", [])
        if trajectory and trajectory.get("status") == "ok":
            from app.services.trajectory import enrich_drivers_with_trajectory
            driver_list = enrich_drivers_with_trajectory(driver_list, trajectory)

        # Scored driver attribution available
        result_data = {
            "target": matched_city,
            "driver_attribution": driver_list,
            "primary_driver": city_drivers.get("primary_driver"),
            "narrative": city_drivers.get("narrative"),
            "pm25_d1_median": city_drivers.get("pm25_d1_median"),
            "risk_band": city_drivers.get("risk_band"),
            "nrt_fire_update": nrt_fire,
            "trajectory": trajectory if trajectory and trajectory.get("status") == "ok" else None,
            "current_conditions": current_conditions,
            "data_available": True,
        }
        provenance = "driver_summary_json + observations_db"
        if trajectory and trajectory.get("status") == "ok":
            provenance += " + hysplit_trajectory"
    else:
        # Fallback 1: on-the-fly driver estimation from forecast data
        forecast = _load_forecast_safe(dt)
        estimated = _estimate_drivers_from_forecast(forecast, target) if forecast.get("forecasts") else None

        # Collect related watchlist alerts for context
        watchlist_data = _load_watchlist_safe(dt)
        related_alerts: list[dict] = []
        if watchlist_data:
            watchlists = watchlist_data.get("watchlists", {})
            for wl_name, wl_entries in watchlists.items():
                for entry in wl_entries:
                    name = (entry.get("city_name") or entry.get("station_name", "")).lower()
                    station = (entry.get("station_name") or "").lower()
                    if target_lower in name or target_lower in station:
                        related_alerts.append({
                            "watchlist": wl_name,
                            "severity": _WATCHLIST_SEVERITY.get(wl_name, "info"),
                            **{k: v for k, v in entry.items() if k not in ("city_name", "station_name")},
                        })

        if estimated:
            # Estimated drivers available — serve with confidence caveat
            result_data = {
                "target": estimated["city_name"],
                "driver_attribution": estimated["drivers"],
                "primary_driver": estimated["primary_driver"],
                "narrative": estimated["narrative"],
                "pm25_d1_median": estimated["pm25_d1_median"],
                "risk_band": estimated["risk_band"],
                "nrt_fire_update": nrt_fire,
                "related_alerts": related_alerts[:10],
                "current_conditions": current_conditions,
                "data_available": True,
                "estimated": True,
                "note": estimated["limitation"],
            }
            provenance = "forecast_estimation + observations_db"
        else:
            # Fallback 2: no forecast data either — conditions only
            has_data = bool(related_alerts or current_conditions)
            result_data = {
                "target": target,
                "driver_attribution": [],
                "related_alerts": related_alerts[:10],
                "nrt_fire_update": nrt_fire,
                "current_conditions": current_conditions,
                "data_available": has_data,
                "note": None if has_data else f"No driver attribution data available for '{target}'. Showing current conditions only.",
            }
            provenance = "watchlist_json + observations_db"

    ui_actions = [{"type": "zoom_to_city", "city": target}]
    followups = [
        f"Show me the full detail for {target}",
        "What other areas need attention?",
    ]

    # Build basis block based on which path was taken
    if city_drivers:
        basis: dict = {
            "description": "Scored driver attribution from forecast pipeline",
            "sources": ["driver_summary_json", "station_observations"],
            "driver_source": "driver_summary_json",
            "forecast_date": dt,
        }
        if nrt_fire:
            basis["sources"].append("firms_nrt")
            basis["fire_source"] = "firms_nrt"
        traj = result_data.get("trajectory")
        if traj:
            basis["trajectory_available"] = True
            basis["sources"].append("hysplit_trajectory")
    elif result_data.get("estimated"):
        basis = {
            "description": "Estimated from forecast patterns (no scored drivers available)",
            "sources": ["forecast_json", "station_observations"],
            "driver_source": "forecast_estimation",
            "limitations": ["Driver scores estimated heuristically from forecast data only"],
        }
    else:
        basis = {
            "description": "Watchlist alerts only (no driver attribution available)",
            "sources": ["watchlist_json", "station_observations"],
            "limitations": ["No driver attribution data for this city/date"],
        }

    return _make_envelope(
        dt,
        result_data,
        ui_actions=ui_actions,
        followups=followups,
        provenance=provenance,
        tool="aq_explain_drivers",
        target=target,
        basis=basis,
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
                    "city": entry.get("city_name", ""),
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

    if watchlist_data:
        basis = {
            "description": "Forecast watchlist alerts enriched with current observations",
            "sources": ["watchlist_json", "station_observations"],
            "observation_window": "24h",
        }
    else:
        basis = {
            "description": "Current station observations only (watchlist unavailable)",
            "sources": ["station_observations"],
            "observation_window": "24h",
            "limitations": ["Watchlist data not available — showing observation-based alerts only"],
        }

    return _make_envelope(
        dt,
        {"incidents": incidents, "counts": counts},
        followups=followups,
        provenance="watchlist_json + observations_db" if watchlist_data else "observations_db_fallback",
        tool="aq_incident_summary",
        target=severity,
        basis=basis,
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
                tool="aq_forecast_audit",
                target=dt,
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
            tool="aq_forecast_audit",
            target=dt,
            basis={
                "description": "Drift verification report (single day)",
                "sources": ["drift_report_json"],
            },
        )

    else:
        # Multi-day trend
        try:
            end = date_cls.fromisoformat(dt)
        except ValueError:
            return _make_envelope(dt, {"message": f"Invalid date: {dt}"}, tool="aq_forecast_audit", target=dt)

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
                tool="aq_forecast_audit",
                target=dt,
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
            tool="aq_forecast_audit",
            target=dt,
            basis={
                "description": f"Drift verification report ({n_days}-day trend)",
                "sources": ["drift_report_json"],
            },
        )


# ── Shared helpers ────────────────────────────────────────────────────────

def _all_city_names(entries: list[dict]) -> list[str]:
    """Extract unique city names from forecast entries."""
    seen: set[str] = set()
    names: list[str] = []
    for e in entries:
        c = e.get("city_name", "")
        if c and c not in seen:
            seen.add(c)
            names.append(c)
    return names


def _estimate_drivers_from_forecast(forecast: dict, target: str) -> dict | None:
    """Heuristic driver estimation from forecast data when no driver_summary exists.

    Infers likely pollution drivers from D+1 forecast signals:
    - Stagnation: many stations elevated + uniform readings → low mixing
    - Fire: ramp_detected flags + very high PM2.5 → biomass burning
    - Transport: high PM2.5 variability across stations → regional transport
    - Local buildup: moderate/uniform PM2.5, residual attribution

    Returns same schema as pre-computed driver_summary entries, or None if
    no forecast data matches the target city.
    """
    entries = forecast.get("forecasts", [])
    target_lower = target.lower()

    # Filter D+1 entries for target city (fuzzy)
    d1 = [
        e for e in entries
        if e.get("lead_days") == 1
        and target_lower in e.get("city_name", "").lower()
    ]
    if not d1:
        # Try fuzzy match on all city names
        import difflib
        all_cities = _all_city_names([e for e in entries if e.get("lead_days") == 1])
        matches = difflib.get_close_matches(target, all_cities, n=1, cutoff=0.6)
        if matches:
            matched = matches[0].lower()
            d1 = [
                e for e in entries
                if e.get("lead_days") == 1
                and e.get("city_name", "").lower() == matched
            ]
            if d1:
                target = matches[0]  # use canonical name

    if not d1:
        return None

    # Compute city-level stats
    pms = [e["pm25_forecast"] for e in d1 if e.get("pm25_forecast") is not None]
    if not pms:
        return None

    median_pm = sorted(pms)[len(pms) // 2]
    mean_pm = sum(pms) / len(pms)
    max_pm = max(pms)
    spread = max_pm - min(pms) if len(pms) > 1 else 0
    cv = (spread / mean_pm) if mean_pm > 0 else 0  # coefficient of variation proxy
    n_ramp = sum(1 for e in d1 if e.get("ramp_detected"))
    frac_ramp = n_ramp / len(d1) if d1 else 0
    n_elevated = sum(1 for pm in pms if pm > 75)
    frac_elevated = n_elevated / len(pms) if pms else 0

    risk_band = _classify_band(median_pm)

    # ── Score drivers (0–1 scale, heuristic) ──
    # Stagnation: uniform high readings → low mixing / boundary layer trapping
    stagnation = 0.0
    if frac_elevated > 0.6 and cv < 0.5:
        stagnation = min(0.9, 0.3 + frac_elevated * 0.5 + (1 - cv) * 0.2)
    elif frac_elevated > 0.3:
        stagnation = 0.2 + frac_elevated * 0.3

    # Fire: ramp detections + very high PM2.5
    fire = 0.0
    if frac_ramp > 0 and max_pm > 150:
        fire = min(0.9, frac_ramp * 0.6 + (max_pm - 150) / 300)
    elif frac_ramp > 0:
        fire = frac_ramp * 0.4

    # Transport: high variability across stations → non-local source
    transport = 0.0
    if cv > 0.6 and median_pm > 50:
        transport = min(0.8, cv * 0.5 + 0.1)
    elif cv > 0.3 and median_pm > 75:
        transport = cv * 0.3

    # Local buildup: residual — moderate PM, low variability, no ramp
    local = max(0.0, 1.0 - stagnation - fire - transport)
    local = min(0.7, local)

    # Normalize so scores sum to ~1
    total = stagnation + fire + transport + local
    if total > 0:
        stagnation /= total
        fire /= total
        transport /= total
        local /= total

    drivers = []
    for name, score, evidence in [
        ("stagnation", stagnation,
         f"{frac_elevated:.0%} of stations above 75 µg/m³, low variability (CV={cv:.2f})"),
        ("fire_biomass", fire,
         f"{n_ramp} ramp detections out of {len(d1)} stations, max PM2.5={max_pm:.0f}"),
        ("regional_transport", transport,
         f"PM2.5 spread={spread:.0f} µg/m³ across {len(pms)} stations (CV={cv:.2f})"),
        ("local_buildup", local,
         f"Median PM2.5={median_pm:.0f} µg/m³, {len(pms)} stations"),
    ]:
        if score >= 0.05:
            drivers.append({
                "driver": name,
                "score": round(score, 2),
                "evidence": evidence,
            })

    drivers.sort(key=lambda d: d["score"], reverse=True)
    primary = drivers[0]["driver"] if drivers else "local_buildup"

    # Build narrative
    primary_label = primary.replace("_", " ")
    narrative = (
        f"{target} D+1 median forecast is {median_pm:.0f} µg/m³ ({risk_band}). "
        f"Primary estimated driver: {primary_label} "
        f"(score {drivers[0]['score']:.0%})."
    )

    return {
        "city_name": target,
        "pm25_d1_median": round(median_pm, 1),
        "risk_band": risk_band,
        "drivers": drivers,
        "primary_driver": primary,
        "narrative": narrative,
        "confidence": "low",
        "limitation": "Estimated from forecast data only — meteorological features not available",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 7. STATION FOCUS HELPERS
# ═══════════════════════════════════════════════════════════════════════════


async def _resolve_station(
    db: AsyncSession,
    name_or_id: str,
) -> dict | None:
    """Resolve a station by station_id (hex) or fuzzy name match.

    Returns {station_id, station_name, city_name, lat, lon} or None.
    """
    cleaned = name_or_id.strip()

    # Hex station_id (16 chars) → direct lookup
    if len(cleaned) == 16 and all(c in "0123456789abcdef" for c in cleaned.lower()):
        query = text("""
            SELECT s.station_id, s.name AS station_name,
                   c.name AS city_name, s.lat, s.lon
            FROM stations s
            LEFT JOIN cities c ON s.city_id = c.id
            WHERE s.station_id = :sid AND s.active = true
            LIMIT 1
        """)
        row = (await db.execute(query, {"sid": cleaned})).mappings().first()
        if row:
            return dict(row)
        return None

    # Text → exact case-insensitive, then fuzzy
    query = text("""
        SELECT s.station_id, s.name AS station_name,
               c.name AS city_name, s.lat, s.lon
        FROM stations s
        LEFT JOIN cities c ON s.city_id = c.id
        WHERE LOWER(s.name) = LOWER(:name) AND s.active = true
        LIMIT 1
    """)
    row = (await db.execute(query, {"name": cleaned})).mappings().first()
    if row:
        return dict(row)

    # Fuzzy fallback
    import difflib
    all_query = text("""
        SELECT s.station_id, s.name AS station_name,
               c.name AS city_name, s.lat, s.lon
        FROM stations s
        LEFT JOIN cities c ON s.city_id = c.id
        WHERE s.active = true AND s.name IS NOT NULL
    """)
    all_rows = (await db.execute(all_query)).mappings().all()
    names = [r["station_name"] for r in all_rows if r["station_name"]]
    matches = difflib.get_close_matches(cleaned, names, n=1, cutoff=0.6)
    if matches:
        for r in all_rows:
            if r["station_name"] == matches[0]:
                return dict(r)
    return None


async def get_station_history(
    db: AsyncSession,
    station_id: str,
    hours: int = 24,
) -> dict | None:
    """Get recent PM2.5 readings for a station.

    Returns {station_name, city, hours, readings, stats} or None.
    """
    query = text("""
        SELECT s.name AS station_name, c.name AS city_name,
               r.pm25, r.ts_utc
        FROM readings r
        JOIN stations s ON r.scope_key = s.station_id
        LEFT JOIN cities c ON s.city_id = c.id
        WHERE r.scope_key = :station_id
          AND r.scope_type = 'station'
          AND r.ts_utc >= NOW() - MAKE_INTERVAL(hours => :hours)
          AND r.pm25 IS NOT NULL
        ORDER BY r.ts_utc ASC
    """)
    rows = (await db.execute(query, {
        "station_id": station_id,
        "hours": hours,
    })).mappings().all()

    if not rows:
        return None

    station_name = rows[0]["station_name"] or ""
    city = rows[0]["city_name"] or ""
    readings = [
        {"timestamp": r["ts_utc"].isoformat(), "pm25": _safe_round(r["pm25"])}
        for r in rows
    ]
    vals = [r["pm25"] for r in rows if r["pm25"] is not None]

    # Trend: compare last 6h mean to previous 6h mean
    trend_direction = "stable"
    if len(rows) >= 4:
        mid = len(rows) // 2
        first_half = [r["pm25"] for r in rows[:mid] if r["pm25"] is not None]
        second_half = [r["pm25"] for r in rows[mid:] if r["pm25"] is not None]
        if first_half and second_half:
            m1 = sum(first_half) / len(first_half)
            m2 = sum(second_half) / len(second_half)
            if m2 > m1 + 5:
                trend_direction = "rising"
            elif m2 < m1 - 5:
                trend_direction = "falling"

    return {
        "station_name": station_name,
        "city": city,
        "hours": hours,
        "readings": readings,
        "stats": {
            "min": _safe_round(min(vals)) if vals else None,
            "max": _safe_round(max(vals)) if vals else None,
            "mean": _safe_round(sum(vals) / len(vals)) if vals else None,
            "current": _safe_round(vals[-1]) if vals else None,
            "trend_direction": trend_direction,
        },
    }


async def get_data_coverage(
    db: AsyncSession,
    geography: str = "city",
    entity_name: str = "",
    detail_level: str = "summary",
    sort_by: str = "earliest",
    top_k: int = 5,
) -> dict:
    """Return data coverage metadata with configurable detail.

    geography: "city", "station", "province", or "national"
    entity_name: city name (fuzzy), station_id (hex), or province name.
    detail_level:
        "summary"            — aggregate coverage + oldest_station_preview (top 3)
        "preview"            — aggregate + top_k stations sorted by sort_by
        "station_breakdown"  — aggregate + full station list (city/province only)
    sort_by: "earliest", "latest", "reading_count", "completeness"
    top_k: number of stations in preview mode (default 5)
    """
    # ── Resolve target stations ──
    if geography == "station":
        station = await _resolve_station(db, entity_name)
        if not station:
            return {"data": {"message": f"Station '{entity_name}' not found."}}
        station_ids = [station["station_id"]]
        target_name = station["station_name"]
    elif geography == "city":
        city_q = text("""
            SELECT c.id, c.name
            FROM cities c
            WHERE LOWER(c.name) = LOWER(:name)
            LIMIT 1
        """)
        city_row = (await db.execute(city_q, {"name": entity_name})).fetchone()
        if not city_row:
            import difflib
            all_q = text("SELECT name FROM cities ORDER BY name")
            all_cities = [r.name for r in (await db.execute(all_q)).fetchall()]
            matches = difflib.get_close_matches(entity_name, all_cities, n=1, cutoff=0.5)
            if matches:
                city_row = (await db.execute(city_q, {"name": matches[0]})).fetchone()
        if not city_row:
            return {"data": {"message": f"City '{entity_name}' not found."}}
        target_name = city_row.name
        q = text("SELECT s.station_id FROM stations s WHERE s.city_id = :cid AND s.active = true")
        rows = (await db.execute(q, {"cid": city_row.id})).fetchall()
        station_ids = [r.station_id for r in rows]
        if not station_ids:
            return {"data": {"message": f"No active stations found in {target_name}."}}
    elif geography == "province":
        target_name = entity_name
        q = text("SELECT s.station_id FROM stations s WHERE LOWER(s.state) = LOWER(:prov) AND s.active = true")
        rows = (await db.execute(q, {"prov": entity_name})).fetchall()
        station_ids = [r.station_id for r in rows]
        if not station_ids:
            return {"data": {"message": f"No active stations found in {entity_name}."}}
    else:
        target_name = "National"
        q = text("SELECT station_id FROM stations WHERE active = true")
        rows = (await db.execute(q)).fetchall()
        station_ids = [r.station_id for r in rows]

    # ── Aggregate coverage ──
    placeholders = ",".join(f":sid{i}" for i in range(len(station_ids)))
    params = {f"sid{i}": sid for i, sid in enumerate(station_ids)}

    agg = (await db.execute(text(f"""
        SELECT MIN(r.ts_utc) AS earliest_ts, MAX(r.ts_utc) AS latest_ts,
               COUNT(*) AS n_obs, COUNT(DISTINCT r.scope_key) AS n_with_data
        FROM readings r
        WHERE r.scope_key IN ({placeholders})
          AND r.scope_type = 'station' AND r.pm25 IS NOT NULL
    """), params)).fetchone()

    if not agg or agg.earliest_ts is None:
        return {"data": {"entity": target_name, "geography": geography,
                         "message": "No PM2.5 observations found."}}

    earliest = agg.earliest_ts
    latest = agg.latest_ts
    total_hours = (latest - earliest).total_seconds() / 3600
    n_stations = len(station_ids)
    expected = n_stations * total_hours if total_hours > 0 else 1
    completeness = min(round(agg.n_obs / expected, 3), 1.0)

    data: dict = {
        "entity": target_name,
        "geography": geography,
        "detail_level": detail_level,
        "earliest_ts_utc": earliest.isoformat() + "Z",
        "latest_ts_utc": latest.isoformat() + "Z",
        "coverage_days": round(total_hours / 24, 1),
        "n_observations": agg.n_obs,
        "n_stations_total": n_stations,
        "n_stations_with_data": agg.n_with_data,
        "completeness_ratio": completeness,
    }

    # ── Station-level query (shared by all detail levels) ──
    sort_col = {
        "earliest": "earliest_ts ASC",
        "latest": "latest_ts DESC",
        "reading_count": "n_readings DESC",
        "completeness": "n_readings DESC",
    }.get(sort_by, "earliest_ts ASC")

    # Determine how many stations to fetch
    if detail_level == "station_breakdown":
        limit_clause = "" if len(station_ids) <= 200 else "LIMIT 200"
    elif detail_level == "preview":
        limit_clause = f"LIMIT {top_k}"
    else:  # summary — always fetch top 3 oldest as preview
        limit_clause = "LIMIT 3"
        sort_col = "earliest_ts ASC"

    bd_q = text(f"""
        SELECT r.scope_key AS station_id, s.name AS station_name,
               MIN(r.ts_utc) AS earliest_ts, MAX(r.ts_utc) AS latest_ts,
               COUNT(*) AS n_readings
        FROM readings r
        JOIN stations s ON r.scope_key = s.station_id
        WHERE r.scope_key IN ({placeholders})
          AND r.scope_type = 'station' AND r.pm25 IS NOT NULL
        GROUP BY r.scope_key, s.name
        ORDER BY {sort_col}
        {limit_clause}
    """)
    bd_rows = (await db.execute(bd_q, params)).fetchall()

    station_list = [
        {
            "station_name": r.station_name,
            "station_id": r.station_id,
            "earliest_ts_utc": r.earliest_ts.isoformat() + "Z",
            "latest_ts_utc": r.latest_ts.isoformat() + "Z",
            "n_readings": r.n_readings,
            "coverage_days": round(
                (r.latest_ts - r.earliest_ts).total_seconds() / 86400, 1
            ),
        }
        for r in bd_rows
    ]

    if detail_level == "station_breakdown":
        data["station_breakdown"] = station_list
    elif detail_level == "preview":
        data["stations"] = station_list
    else:
        # summary — always include a compact preview of oldest stations
        data["oldest_station_preview"] = station_list

    return {"data": data}


async def get_station_neighbours(
    db: AsyncSession,
    station_id: str,
    radius_km: int = 25,
    limit: int = 5,
) -> list[dict]:
    """Find nearby stations with their latest PM2.5 reading.

    Uses PostGIS ST_DWithin for spatial search, sorted by distance.
    """
    radius_m = radius_km * 1000
    query = text("""
        WITH target AS (
            SELECT station_id, lat, lon,
                   ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS geog
            FROM stations
            WHERE station_id = :station_id
            LIMIT 1
        )
        SELECT s.station_id, s.name AS station_name,
               c.name AS city_name,
               ROUND(ST_Distance(
                   ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography,
                   t.geog
               )::numeric / 1000, 1) AS distance_km,
               r.pm25, r.ts_utc
        FROM stations s
        CROSS JOIN target t
        LEFT JOIN cities c ON s.city_id = c.id
        LEFT JOIN LATERAL (
            SELECT pm25, ts_utc
            FROM readings
            WHERE scope_key = s.station_id
              AND scope_type = 'station'
              AND ts_utc >= NOW() - INTERVAL '24 hours'
              AND pm25 IS NOT NULL
            ORDER BY ts_utc DESC
            LIMIT 1
        ) r ON true
        WHERE s.station_id != t.station_id
          AND s.active = true
          AND ST_DWithin(
              ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography,
              t.geog,
              :radius_m
          )
        ORDER BY distance_km ASC
        LIMIT :lim
    """)
    rows = (await db.execute(query, {
        "station_id": station_id,
        "radius_m": radius_m,
        "lim": limit,
    })).mappings().all()

    return [
        {
            "station_name": r["station_name"] or "",
            "station_id": r["station_id"],
            "city": r["city_name"] or "",
            "distance_km": float(r["distance_km"]) if r["distance_km"] is not None else None,
            "latest_pm25": _safe_round(r["pm25"]),
            "latest_timestamp": r["ts_utc"].isoformat() if r["ts_utc"] else None,
        }
        for r in rows
    ]
