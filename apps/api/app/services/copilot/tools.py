"""PydanticAI tool functions for the analyst desk copilot.

Thin wrappers that delegate to the analytics service layer.
Each tool creates its own DB session (PydanticAI tools run outside
FastAPI's Depends lifecycle) and calls the corresponding analytics
function directly — same process, zero network overhead.
"""

import logging
from typing import Optional

from pydantic_ai import RunContext

from app.routers.analyst_desk import _resolve_latest_date
from .context import CopilotSession

logger = logging.getLogger(__name__)


def _effective_date(ctx: RunContext[CopilotSession]) -> str:
    """Return the session date or resolve latest."""
    return ctx.deps.current_date or _resolve_latest_date()


async def _get_db():
    """Create a standalone async DB session for use in tool functions."""
    from app.core.database import SessionLocal
    return SessionLocal()


def _update_session(
    ctx: RunContext[CopilotSession],
    *,
    tool: str,
    focus_type: str | None = None,
    focused_city: str | None = None,
    focused_station_id: str | None = None,
    comparison_date: str | None = None,
    entities: list[str] | None = None,
) -> None:
    """Write tool-call context into the session for follow-up resolution."""
    sess = ctx.deps
    sess.last_tool = tool
    if focus_type is not None:
        sess.focus_type = focus_type
    if focused_city is not None:
        sess.focused_city = focused_city
    if focused_station_id is not None:
        sess.focused_station_id = focused_station_id
    if comparison_date is not None:
        sess.comparison_date = comparison_date
    if entities is not None:
        sess.last_entities = entities


# ── Tool 1: aq_hotspots_daily ─────────────────────────────────────────────


async def aq_hotspots_daily(
    ctx: RunContext[CopilotSession],
    date: Optional[str] = None,
    geography: str = "city",
    metric: str = "avg_pm25",
    top_k: int = 5,
    country: Optional[str] = None,
) -> dict:
    """Get today's air quality hotspots based on actual station observations.

    Returns the most polluted cities, stations, or provinces ranked by
    current PM2.5 readings, with optional forecast outlook enrichment.

    Args:
        date: Date (YYYY-MM-DD). Defaults to today.
        geography: Group by "city", "station", or "province" (default "city").
        metric: Ranking metric — "avg_pm25" or "max_pm25" (default "avg_pm25").
        top_k: Number of results to return (default 5).
        country: Country name to filter by (e.g. "Pakistan", "India"). Returns all countries if omitted.
    """
    from app.services.analytics import get_hotspots_daily

    dt = date or _effective_date(ctx)
    db = await _get_db()
    try:
        result = await get_hotspots_daily(db, dt, geography, metric, top_k, country)
    finally:
        await db.close()

    hotspots = result.get("data", {}).get("hotspots", [])
    entities = [h["name"] for h in hotspots if h.get("name")][:5]
    _update_session(ctx, tool="aq_hotspots_daily", focus_type="national", entities=entities)
    return result


# ── Tool 2: aq_city_detail ────────────────────────────────────────────────


async def aq_city_detail(
    ctx: RunContext[CopilotSession],
    city_name: str = "",
    date: Optional[str] = None,
    include: Optional[list[str]] = None,
    sensor_id: Optional[str] = None,
) -> dict:
    """Get detailed air quality for a city or a specific station.

    Shows current observed PM2.5 readings, 24h trend, and optional
    forecast outlook. Supports fuzzy city name matching.

    Args:
        city_name: City name (fuzzy matched). Required unless sensor_id is provided.
        date: Date (YYYY-MM-DD). Defaults to today.
        include: Sections to include — any of "stations", "trend", "forecast" (default ["stations", "trend"]).
        sensor_id: Optional station ID (16-char hex). When provided, returns that station's detail.
    """
    from app.services.analytics import get_city_detail

    if include is None:
        include = ["stations", "trend"]

    dt = date or _effective_date(ctx)
    db = await _get_db()
    try:
        result = await get_city_detail(db, city_name, dt, include, sensor_id)
    finally:
        await db.close()

    city = result.get("data", {}).get("city")
    ft = "station" if sensor_id else "city"
    _update_session(ctx, tool="aq_city_detail", focus_type=ft, focused_city=city, entities=[city] if city else [])
    return result


# ── Tool 3: aq_compare_dates ──────────────────────────────────────────────


async def aq_compare_dates(
    ctx: RunContext[CopilotSession],
    date1: str,
    date2: str,
    geography: str = "national",
    country: Optional[str] = None,
) -> dict:
    """Compare observed PM2.5 between two dates to identify trends and biggest movers.

    Uses actual station observations, not forecast predictions.

    Args:
        date1: First date (YYYY-MM-DD), typically the earlier date.
        date2: Second date (YYYY-MM-DD), typically the later date.
        geography: "national" for country-wide, or a city name to compare that city only (default "national").
        country: Country name to filter by (e.g. "Pakistan", "India"). Returns all countries if omitted.
    """
    from app.services.analytics import get_compare_dates

    db = await _get_db()
    try:
        result = await get_compare_dates(db, date1, date2, geography, country)
    finally:
        await db.close()

    movers = result.get("data", {}).get("biggest_movers", [])
    entities = [m["city"] for m in movers if m.get("city")][:5]
    _update_session(ctx, tool="aq_compare_dates", comparison_date=date1, entities=entities)
    return result


# ── Tool 4: aq_explain_drivers ────────────────────────────────────────────


async def aq_explain_drivers(
    ctx: RunContext[CopilotSession],
    city_or_station: str,
    date: Optional[str] = None,
) -> dict:
    """Explain why air quality is poor in a city or station — fire activity, stagnation, transport.

    Reads anomaly driver attribution from watchlists and correlates with
    current station observations for ground-truth context.

    Args:
        city_or_station: City name or station name to investigate.
        date: Date (YYYY-MM-DD). Defaults to today.
    """
    from app.services.analytics import get_explain_drivers

    dt = date or _effective_date(ctx)
    db = await _get_db()
    try:
        result = await get_explain_drivers(db, city_or_station, dt)
    finally:
        await db.close()

    resolved = result.get("data", {}).get("target", city_or_station)
    _update_session(ctx, tool="aq_explain_drivers", focus_type="city", focused_city=resolved, entities=[resolved])
    return result


# ── Tool 5: aq_incident_summary ───────────────────────────────────────────


async def aq_incident_summary(
    ctx: RunContext[CopilotSession],
    date: Optional[str] = None,
    severity: str = "all",
    country: Optional[str] = None,
) -> dict:
    """Get all active incidents and alerts: ramp events, high PM2.5, rapid deterioration, new episodes.

    Combines watchlist alerts with current station observations.
    Falls back to observation data when watchlist is unavailable.

    Args:
        date: Date (YYYY-MM-DD). Defaults to today.
        severity: Filter — "all", "critical", or "warning" (default "all").
        country: Country name to filter by (e.g. "Pakistan", "India"). Returns all countries if omitted.
    """
    from app.services.analytics import get_incident_summary

    dt = date or _effective_date(ctx)
    db = await _get_db()
    try:
        result = await get_incident_summary(db, dt, severity, country)
    finally:
        await db.close()

    incidents = result.get("data", {}).get("incidents", [])
    entities = list(dict.fromkeys(i["city"] for i in incidents if i.get("city")))[:5]
    _update_session(ctx, tool="aq_incident_summary", entities=entities)
    return result


# ── Tool 6: aq_forecast_audit ─────────────────────────────────────────────


async def aq_forecast_audit(
    ctx: RunContext[CopilotSession],
    date: Optional[str] = None,
    n_days: int = 1,
) -> dict:
    """Audit forecast accuracy: single-day metrics or multi-day trend.

    Shows MAE, RMSE, Bias, R-squared, F1@150, prediction stats, feature drift, and alerts.
    Use n_days=1 for a single day; n_days>1 for a trend view.

    Args:
        date: End date for the audit period (YYYY-MM-DD). Defaults to latest available.
        n_days: Number of days to audit (default 1). Set >1 for trend analysis.
    """
    from app.services.analytics import get_forecast_audit

    dt = date or _effective_date(ctx)
    result = await get_forecast_audit(dt, n_days)
    _update_session(ctx, tool="aq_forecast_audit")
    return result


# ── Tool 7: aq_station_focus ───────────────────────────────────────────


async def aq_station_focus(
    ctx: RunContext[CopilotSession],
    station_name_or_id: str,
) -> dict:
    """Focus on a specific station — show current reading, forecast, and risk status.

    Resolves the station by name (fuzzy matched) or station_id (hex).
    Sets the session focus so follow-up questions ("show trend", "neighbors")
    automatically target this station.

    Args:
        station_name_or_id: Station name (fuzzy matched) or station_id (hex string).
    """
    from app.services.analytics import _resolve_station, _load_forecast_safe, _safe_round

    dt = _effective_date(ctx)
    db = await _get_db()
    try:
        station = await _resolve_station(db, station_name_or_id)
    finally:
        await db.close()

    if not station:
        return {"date": dt, "data": {"message": f"Station '{station_name_or_id}' not found."}, "followups": []}

    station_id = station["station_id"]  # hex
    station_name = station["station_name"] or ""
    city = station["city_name"] or ""

    # Load forecast for this station (match by station_id hex, then by name)
    forecast = _load_forecast_safe(dt)
    entries = forecast.get("forecasts", [])
    fc_rows = [e for e in entries if e.get("station_id") == station_id]
    if not fc_rows:
        sname = station_name.lower()
        fc_rows = [e for e in entries if (e.get("station_name") or "").lower() == sname and sname]

    fc_by_horizon = {}
    current_pm25 = None
    risk_band = "unknown"
    episode_state = "stable"
    confidence = "medium"
    priority = "monitor"
    for e in fc_rows:
        ld = e.get("lead_days")
        if ld:
            fc_by_horizon[f"D+{ld}"] = {
                "pm25_forecast": _safe_round(e.get("pm25_forecast")),
                "pm25_q90": _safe_round(e.get("pm25_q90")),
                "risk_band": e.get("risk_band"),
                "ramp_detected": e.get("ramp_detected", False),
            }
            if ld == 1:
                current_pm25 = _safe_round(e.get("pm25_forecast"))
                risk_band = e.get("risk_band", "unknown")
                episode_state = e.get("episode_state", "stable")
                confidence = e.get("confidence", "medium")
                priority = e.get("priority", "monitor")

    _update_session(
        ctx, tool="aq_station_focus",
        focus_type="station",
        focused_city=city,
        focused_station_id=station_id,
        entities=[station_name],
    )

    import json as _json
    action_hint = "{{ACTION:" + _json.dumps({
        "type": "zoom_to_station",
        "station_id": station_id,
        "lat": station["lat"],
        "lng": station["lon"],
    }) + "}}"

    return {
        "date": dt,
        "data": {
            "station_name": station_name,
            "city": city,
            "station_id": station_id,
            "current_pm25": current_pm25,
            "forecast": fc_by_horizon,
            "risk_band": risk_band,
            "episode_state": episode_state,
            "confidence": confidence,
            "priority": priority,
        },
        "action_hint": action_hint,
        "followups": [
            "Show 24h trend",
            "Compare with neighbors",
            "Why is it elevated?",
        ],
    }


# ── Tool 8: aq_station_history ─────────────────────────────────────────


async def aq_station_history(
    ctx: RunContext[CopilotSession],
    hours: int = 24,
) -> dict:
    """Show recent PM2.5 readings and nearby station comparison for the focused station.

    Uses the station set by a previous aq_station_focus call. If no station is
    focused, asks the user to mention one first.

    Args:
        hours: Number of hours of history to return (default 24).
    """
    from app.services.analytics import get_station_history, get_station_neighbours

    station_id = ctx.deps.focused_station_id
    if not station_id:
        return {"date": _effective_date(ctx), "data": {"message": "Please mention a station first (e.g. @StationName)."}, "followups": []}

    dt = _effective_date(ctx)

    db = await _get_db()
    try:
        history = await get_station_history(db, station_id, hours)
        neighbours = await get_station_neighbours(db, station_id)
    finally:
        await db.close()

    _update_session(ctx, tool="aq_station_history")

    data: dict = {}
    if history:
        data["history"] = history
    else:
        data["history"] = {"message": f"No readings found in the last {hours} hours."}
    data["neighbours"] = neighbours

    followups = ["Why is it elevated?", "What's the forecast?"]
    if neighbours:
        followups.insert(0, f"Tell me about {neighbours[0]['station_name']}")

    return {
        "date": dt,
        "data": data,
        "followups": followups,
    }
