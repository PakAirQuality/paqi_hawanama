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
        return await get_hotspots_daily(db, dt, geography, metric, top_k, country)
    finally:
        await db.close()


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

    # Update session focused city
    city = result.get("data", {}).get("city")
    if city:
        ctx.deps.focused_city = city

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
        return await get_compare_dates(db, date1, date2, geography, country)
    finally:
        await db.close()


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
        return await get_explain_drivers(db, city_or_station, dt)
    finally:
        await db.close()


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
        return await get_incident_summary(db, dt, severity, country)
    finally:
        await db.close()


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
    return await get_forecast_audit(dt, n_days)
