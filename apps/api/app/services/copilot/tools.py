"""PydanticAI tool functions for the analyst desk copilot.

Each tool reads from GCS using the same helpers as analyst_desk.py.
"""

import logging
from typing import Optional

from pydantic_ai import RunContext

from app.routers.analyst_desk import (
    _gcs_read_json,
    _load_forecast,
    _load_summary_safe,
    _load_watchlist_safe,
    _resolve_latest_date,
)

from .context import CopilotSession

logger = logging.getLogger(__name__)


def _date_str(d: str) -> str:
    return d.replace("-", "")


def _effective_date(ctx: RunContext[CopilotSession]) -> str:
    """Return the session date or resolve latest."""
    return ctx.deps.current_date or _resolve_latest_date()


async def get_national_overview(ctx: RunContext[CopilotSession]) -> dict:
    """Get national-level PM2.5 overview: mean/max forecasts, band counts, priority counts, ramp count.

    Use when the user asks about overall air quality, national summary, or general conditions.
    """
    dt = _effective_date(ctx)
    forecast = _load_forecast(dt)
    entries = forecast.get("forecasts", [])
    d1 = [e for e in entries if e.get("lead_days") == 1]

    if not d1:
        return {"date": dt, "message": "No D+1 forecast data available."}

    forecasts = [e["pm25_forecast"] for e in d1 if e.get("pm25_forecast") is not None]
    band_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    n_ramp = 0

    for e in d1:
        band = e.get("risk_band", "unknown")
        band_counts[band] = band_counts.get(band, 0) + 1
        pri = e.get("priority", "unknown")
        priority_counts[pri] = priority_counts.get(pri, 0) + 1
        if e.get("ramp_detected"):
            n_ramp += 1

    return {
        "date": dt,
        "n_stations": len(d1),
        "mean_pm25": round(sum(forecasts) / len(forecasts), 1) if forecasts else None,
        "max_pm25": round(max(forecasts), 1) if forecasts else None,
        "band_counts": band_counts,
        "priority_counts": priority_counts,
        "n_ramp": n_ramp,
    }


async def get_top_polluted_cities(
    ctx: RunContext[CopilotSession],
    n: int = 5,
    horizon: str = "D+1",
) -> dict:
    """Get the top N most polluted cities ranked by max PM2.5 for a given horizon.

    Args:
        n: Number of cities to return (default 5).
        horizon: Forecast horizon, e.g. "D+1", "D+2", "D+3" (default "D+1").
    """
    dt = _effective_date(ctx)
    summary = _load_summary_safe(dt)
    if not summary:
        return {"date": dt, "message": "No summary data available."}

    cities = summary.get("city_summaries", [])
    ranked = []
    for c in cities:
        h = c.get("horizons", {}).get(horizon)
        if h:
            ranked.append({
                "city": c["name"],
                "state": c.get("state_name", ""),
                "pm25_max": h.get("pm25_max"),
                "pm25_mean": h.get("pm25_mean"),
                "worst_band": h.get("worst_band"),
                "n_stations": h.get("n_stations"),
                "n_ramp": h.get("n_ramp", 0),
                "trend": c.get("trend"),
            })

    ranked.sort(key=lambda x: x.get("pm25_max") or 0, reverse=True)
    return {"date": dt, "horizon": horizon, "cities": ranked[:n]}


async def get_city_detail(
    ctx: RunContext[CopilotSession],
    city_name: str,
) -> dict:
    """Get detailed forecast for a specific city: summary stats and individual station forecasts.

    Args:
        city_name: The city name to look up (case-insensitive).
    """
    dt = _effective_date(ctx)

    # City summary
    summary = _load_summary_safe(dt)
    city_info = None
    if summary:
        for c in summary.get("city_summaries", []):
            if c.get("name", "").lower() == city_name.lower():
                city_info = c
                break

    # Station-level forecasts
    forecast = _load_forecast(dt)
    entries = forecast.get("forecasts", [])
    city_stations = [
        {
            "sensor_id": e["sensor_id"],
            "station_name": e.get("station_name", ""),
            "lead_days": e.get("lead_days"),
            "pm25_forecast": e.get("pm25_forecast"),
            "pm25_q90": e.get("pm25_q90"),
            "risk_band": e.get("risk_band"),
            "priority": e.get("priority"),
            "ramp_detected": e.get("ramp_detected", False),
            "latitude": e.get("latitude"),
            "longitude": e.get("longitude"),
        }
        for e in entries
        if (e.get("city_name") or e.get("city", "")).lower() == city_name.lower()
    ]

    if not city_info and not city_stations:
        return {"message": f"No data found for city '{city_name}'."}

    # Update focused city in session
    ctx.deps.focused_city = city_name

    return {
        "date": dt,
        "city": city_name,
        "summary": city_info,
        "stations": city_stations[:50],
        "n_stations_total": len(city_stations),
    }


async def get_station_forecast(
    ctx: RunContext[CopilotSession],
    sensor_id: int,
) -> dict:
    """Get all forecast horizons for a single station by sensor_id.

    Args:
        sensor_id: The numeric station sensor ID.
    """
    dt = _effective_date(ctx)
    forecast = _load_forecast(dt)
    entries = forecast.get("forecasts", [])

    rows = [e for e in entries if e.get("sensor_id") == sensor_id]
    if not rows:
        return {"message": f"Station {sensor_id} not found in forecast."}

    rows.sort(key=lambda e: e.get("lead_days", 0))
    meta = rows[0]
    horizons = []
    for r in rows:
        horizons.append({
            "lead_days": r.get("lead_days"),
            "target_date": r.get("target_date"),
            "pm25_forecast": r.get("pm25_forecast"),
            "pm25_q75": r.get("pm25_q75"),
            "pm25_q90": r.get("pm25_q90"),
            "risk_band": r.get("risk_band"),
            "priority": r.get("priority"),
            "ramp_detected": r.get("ramp_detected", False),
        })

    return {
        "date": dt,
        "sensor_id": sensor_id,
        "station_name": meta.get("station_name", ""),
        "city_name": meta.get("city_name", ""),
        "latitude": meta.get("latitude"),
        "longitude": meta.get("longitude"),
        "horizons": horizons,
    }


async def get_watchlist(
    ctx: RunContext[CopilotSession],
    list_name: Optional[str] = None,
) -> dict:
    """Get watchlist data: a specific list by name, or all lists with counts and top 3 entries each.

    Args:
        list_name: Optional watchlist name (e.g. "ramp_alerts", "high_pm25"). If omitted, returns all lists.
    """
    dt = _effective_date(ctx)
    data = _load_watchlist_safe(dt)
    if not data:
        return {"date": dt, "message": "No watchlist data available."}

    watchlists = data.get("watchlists", {})

    if list_name:
        entries = watchlists.get(list_name)
        if entries is None:
            available = list(watchlists.keys())
            return {"message": f"Watchlist '{list_name}' not found. Available: {available}"}
        return {"date": dt, "watchlist": list_name, "count": len(entries), "entries": entries}

    # Return all with counts + top 3 each
    result = {}
    for name, entries in watchlists.items():
        result[name] = {
            "count": len(entries),
            "top_3": entries[:3],
        }
    return {"date": dt, "watchlists": result}


async def compare_dates(
    ctx: RunContext[CopilotSession],
    date1: str,
    date2: str,
    city: Optional[str] = None,
) -> dict:
    """Compare PM2.5 forecasts between two dates to show trends.

    Args:
        date1: First date (YYYY-MM-DD), typically the earlier date.
        date2: Second date (YYYY-MM-DD), typically the later date.
        city: Optional city name to filter comparison.
    """
    f1 = _load_forecast(date1)
    f2 = _load_forecast(date2)

    e1 = [e for e in f1.get("forecasts", []) if e.get("lead_days") == 1]
    e2 = [e for e in f2.get("forecasts", []) if e.get("lead_days") == 1]

    if city:
        cl = city.lower()
        e1 = [e for e in e1 if (e.get("city_name") or "").lower() == cl]
        e2 = [e for e in e2 if (e.get("city_name") or "").lower() == cl]

    def _stats(entries: list) -> dict:
        vals = [e["pm25_forecast"] for e in entries if e.get("pm25_forecast") is not None]
        if not vals:
            return {"n_stations": 0, "mean_pm25": None, "max_pm25": None}
        return {
            "n_stations": len(vals),
            "mean_pm25": round(sum(vals) / len(vals), 1),
            "max_pm25": round(max(vals), 1),
        }

    s1, s2 = _stats(e1), _stats(e2)
    delta_mean = None
    if s1["mean_pm25"] is not None and s2["mean_pm25"] is not None:
        delta_mean = round(s2["mean_pm25"] - s1["mean_pm25"], 1)

    return {
        "date1": date1,
        "date2": date2,
        "city": city,
        "stats_date1": s1,
        "stats_date2": s2,
        "delta_mean_pm25": delta_mean,
    }


async def search_stations(
    ctx: RunContext[CopilotSession],
    query: str,
) -> dict:
    """Search stations by name or city substring match.

    Args:
        query: Search text to match against station names or city names.
    """
    dt = _effective_date(ctx)
    forecast = _load_forecast(dt)
    entries = forecast.get("forecasts", [])

    q = query.lower()
    seen = set()
    matches = []
    for e in entries:
        sid = e.get("sensor_id")
        if sid in seen:
            continue
        name = (e.get("station_name") or "").lower()
        city = (e.get("city_name") or "").lower()
        if q in name or q in city:
            seen.add(sid)
            matches.append({
                "sensor_id": sid,
                "station_name": e.get("station_name", ""),
                "city_name": e.get("city_name", ""),
                "latitude": e.get("latitude"),
                "longitude": e.get("longitude"),
            })
        if len(matches) >= 20:
            break

    return {"date": dt, "query": query, "count": len(matches), "stations": matches}
