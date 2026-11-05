"""PydanticAI tool functions for the analyst desk copilot.

Thin wrappers that delegate to the analytics service layer.
Each tool creates its own DB session (PydanticAI tools run outside
FastAPI's Depends lifecycle) and calls the corresponding analytics
function directly — same process, zero network overhead.
"""

import asyncio
import logging
from typing import Optional

from pydantic_ai import RunContext

from app.routers.analyst_desk import _resolve_latest_date
from .context import CopilotSession

logger = logging.getLogger(__name__)


def _effective_date(ctx: RunContext[CopilotSession]) -> str:
    """Return the active historical date, session date, or latest."""
    return ctx.deps.active_historical_date or ctx.deps.current_date or _resolve_latest_date()


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
    historical_date: str | None = None,
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
    if historical_date is not None:
        sess.active_historical_date = historical_date


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
    _update_session(ctx, tool="aq_hotspots_daily", focus_type="national", entities=entities,
                    historical_date=date)
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
    _update_session(ctx, tool="aq_city_detail", focus_type=ft, focused_city=city,
                    entities=[city] if city else [], historical_date=date)
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
    _update_session(ctx, tool="aq_explain_drivers", focus_type="city", focused_city=resolved,
                    entities=[resolved], historical_date=date)
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
    _update_session(ctx, tool="aq_incident_summary", entities=entities, historical_date=date)
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
    date: Optional[str] = None,
) -> dict:
    """Show PM2.5 readings and nearby station comparison for the focused station.

    Uses the station set by a previous aq_station_focus call. If no station is
    focused, asks the user to mention one first.

    Args:
        hours: Number of hours of history to return (default 24, max 744 = 31 days;
               readings are hourly means). For longer periods use aq_period_stats.
        date: Date anchor (YYYY-MM-DD). Window ends at 23:59:59 on this date.
              If omitted, uses the session's active historical date or current time.
    """
    from app.services.analytics import MAX_HISTORY_HOURS, get_station_history, get_station_neighbours

    station_id = ctx.deps.focused_station_id
    if not station_id:
        return {"date": _effective_date(ctx), "data": {"message": "Please mention a station first (e.g. @StationName)."}, "followups": []}

    anchor = date or ctx.deps.active_historical_date
    dt = anchor or _effective_date(ctx)
    if hours > MAX_HISTORY_HOURS:
        return {"date": dt, "data": {"message": f"aq_station_history covers at most {MAX_HISTORY_HOURS} hours (31 days) of hourly "
                                                f"readings. For longer periods call aq_period_stats(entity=\"station\", "
                                                f"name=\"{ctx.deps.focused_station_name or station_id}\", bucket=\"day\" or \"month\")."},
                "followups": []}

    db = await _get_db()
    try:
        history = await get_station_history(db, station_id, hours, anchor_date=anchor)
        neighbours = await get_station_neighbours(db, station_id)
    finally:
        await db.close()

    _update_session(ctx, tool="aq_station_history", historical_date=anchor)

    data: dict = {}
    if history:
        data["history"] = history
    else:
        data["history"] = {"message": f"No readings found in the last {hours} hours."}
    data["neighbours"] = neighbours

    followups = ["Why is it elevated?", "What's the forecast?"]
    if neighbours:
        followups.insert(0, f"Tell me about {neighbours[0]['station_name']}")

    import json as _json
    action_hint = "{{ACTION:" + _json.dumps({
        "type": "show_station_trend",
        "station_id": station_id,
        "station_name": history.get("station_name", "") if history else "",
        "hours": hours,
        **({"anchor_date": anchor} if anchor else {}),
    }) + "}}"

    return {
        "date": dt,
        "data": data,
        "action_hint": action_hint,
        "followups": followups,
    }


# ── Tool 9: aq_data_coverage ──────────────────────────────────────────


async def aq_data_coverage(
    ctx: RunContext[CopilotSession],
    entity_name: str = "",
    geography: str = "city",
    detail_level: str = "summary",
    sort_by: str = "earliest",
    top_k: int = 5,
) -> dict:
    """Check data coverage and availability for any entity in the monitoring network.

    Returns earliest/latest timestamps, observation counts, completeness ratio,
    and station-level detail depending on detail_level.

    Every response includes an oldest_station_preview (top 3) even at summary level,
    so you can always name the oldest station without a follow-up call.

    Args:
        entity_name: City name, station name/ID, province name, or empty for national.
        geography: "city", "station", "province", or "national" (default "city").
        detail_level: Level of station detail to return.
            "summary" — aggregate coverage + top 3 oldest stations preview.
            "preview" — aggregate + top_k stations sorted by sort_by.
            "station_breakdown" — aggregate + full station list (for city/province).
        sort_by: How to sort stations — "earliest", "latest", "reading_count" (default "earliest").
        top_k: Number of stations in preview mode (default 5).
    """
    from app.services.analytics import get_data_coverage

    db = await _get_db()
    try:
        result = await get_data_coverage(
            db, geography, entity_name, detail_level, sort_by, top_k,
        )
    finally:
        await db.close()

    data = result.get("data", {})
    entity = data.get("entity", entity_name)
    _update_session(
        ctx,
        tool="aq_data_coverage",
        focus_type=geography,
        focused_city=entity if geography == "city" else None,
        entities=[entity] if entity else [],
    )

    # Store query signature for deterministic follow-up routing
    ctx.deps.last_coverage_query = {
        "entity": entity,
        "geography": geography,
        "detail_level": detail_level,
    }

    followups = []
    if detail_level == "summary":
        followups.append(f"Show full station breakdown for {entity}")
    if data.get("coverage_days"):
        followups.append(f"Show historical trend for {entity}")
    followups.append("Which cities have the longest history?")

    return {
        "date": _effective_date(ctx),
        "data": data,
        "basis": {
            "description": "Coverage derived from raw observations table",
            "sources": ["station_observations"],
            "coverage_scope": "full_history",
            "history_limit_applied": False,
        },
        "followups": followups,
    }


# ── Tool 10: aq_nearest_assets ────────────────────────────────────────


async def aq_nearest_assets(
    ctx: RunContext[CopilotSession],
    lat: float,
    lon: float,
    asset_types: Optional[list[str]] = None,
    radius_m: int = 5000,
    limit: int = 20,
) -> dict:
    """Find hospitals, schools, factories, and other civic assets near a location.

    Use after identifying a fire, hotspot, or station of interest.
    Queries OpenStreetMap for nearby points of interest within the
    specified radius and returns structured results with distances.

    Args:
        lat: Latitude of the anchor point (decimal degrees).
        lon: Longitude of the anchor point (decimal degrees).
        asset_types: Types to search for — any combination of: hospital,
            clinic, school, university, factory, brick_kiln, road,
            settlement, worship, market, bus_station.
            Defaults to ["hospital", "school"].
        radius_m: Search radius in meters (default 5000, max 25000).
        limit: Maximum results to return (default 20).
    """
    from app.services.spatial import get_nearest_assets

    if asset_types is None:
        asset_types = ["hospital", "school"]

    result = await get_nearest_assets(
        lat, lon, asset_types, radius_m, limit,
    )

    _update_session(ctx, tool="aq_nearest_assets")

    counts = result.get("counts_by_type", {})
    followups = []
    if counts:
        followups.append("Show satellite imagery for this area")
    followups.append("What's driving the pollution here?")
    followups.append("Expand search radius to 10 km")

    return {
        "date": _effective_date(ctx),
        "data": result,
        "basis": {
            "description": "Nearby civic assets from pre-seeded OpenStreetMap data (GCS Parquet)",
            "sources": ["OpenStreetMap"],
            "limitations": "OSM coverage varies; some facilities may be unmapped. Data refreshed periodically.",
        },
        "followups": followups,
    }


# ── Tool 11: aq_satellite_image ───────────────────────────────────────


async def aq_satellite_image(
    ctx: RunContext[CopilotSession],
    lat: float,
    lon: float,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_cloud_cover: float = 20.0,
    mode: str = "latest",
) -> dict:
    """Find Sentinel-2 satellite imagery for a location.

    Searches the Copernicus Data Space for cloud-free Sentinel-2 L2A scenes
    intersecting the area of interest. Returns scene metadata and preview URL.
    If no suitable scene exists, returns a clear "no suitable scene" status.

    Args:
        lat: Latitude of the center point (decimal degrees).
        lon: Longitude of the center point (decimal degrees).
        date_from: Start date (YYYY-MM-DD). Defaults to 30 days ago.
        date_to: End date (YYYY-MM-DD). Defaults to today.
        max_cloud_cover: Maximum acceptable cloud cover percent (default 20).
        mode: Selection mode — "latest" (most recent low-cloud scene),
            "nearest_to_date" (closest to date_from),
            or "before_after" (one scene before and after date_from).
    """
    from app.services.spatial import get_sentinel_catalog

    result = await get_sentinel_catalog(
        lat, lon, date_from, date_to, max_cloud_cover, mode=mode,
    )

    _update_session(ctx, tool="aq_satellite_image")

    followups = []
    if result.get("status") == "ok":
        followups.append("What civic assets are near this location?")
        if mode != "before_after":
            followups.append("Show before and after imagery")
    elif result.get("status") == "no_suitable_scene":
        followups.append("Try with higher cloud cover threshold (50%)")
        followups.append("Expand the date range")

    return {
        "date": _effective_date(ctx),
        "data": result,
        "basis": {
            "description": "Sentinel-2 L2A catalog from Copernicus Data Space Ecosystem",
            "sources": ["Copernicus CDSE STAC"],
        },
        "followups": followups,
    }


# ── Tool 12: aq_exposed_population ────────────────────────────────────


async def aq_exposed_population(
    ctx: RunContext[CopilotSession],
    city_name: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_m: int = 25000,
    lead_days: int = 1,
) -> dict:
    """Estimate exposed population by PM2.5 risk band for a city or area.

    Computes a hazard surface by interpolating station forecasts onto a
    100m population grid, then returns how many people are exposed above
    each WHO/national threshold. Includes population-weighted mean PM2.5
    and a confidence rating based on station density.

    Args:
        city_name: City to analyze (fuzzy matched). Use this OR lat/lon.
        lat: Latitude of center point (use with lon and radius_m).
        lon: Longitude of center point.
        radius_m: Radius in meters when using lat/lon (default 25000).
        lead_days: Forecast horizon — 1, 2, or 3 (default 1).
    """
    from app.routers.analyst_desk import _load_forecast
    from app.services.spatial import get_exposed_population

    dt = _effective_date(ctx)
    forecast = _load_forecast(dt)
    entries = forecast.get("forecasts", [])

    result = get_exposed_population(
        entries, city_name=city_name, lat=lat, lon=lon,
        radius_m=radius_m, lead_days=lead_days,
    )

    _update_session(
        ctx, tool="aq_exposed_population",
        focus_type="city" if city_name else "national",
        focused_city=result.get("area") if city_name else None,
    )

    followups = []
    if result.get("status") == "ok":
        followups.append("What civic assets are in the worst zones?")
        followups.append("Why is it so bad here?")
        if city_name:
            followups.append("Show me the full impact brief")

    return {
        "date": dt,
        "data": result,
        "basis": {
            "description": "IDW-interpolated PM2.5 hazard × WorldPop 2025 population grid (100m)",
            "sources": ["station_forecasts", "WorldPop_2025"],
            "method": "inverse_distance_weighting",
            "limitations": "Hazard field is interpolated from station forecasts; accuracy degrades >10km from nearest station",
        },
        "followups": followups,
    }


# ── Tool 13: aq_impact_brief ─────────────────────────────────────────


async def aq_impact_brief(
    ctx: RunContext[CopilotSession],
    city_name: str = "",
    lead_days: int = 1,
) -> dict:
    """Generate a comprehensive impact brief for a city.

    Combines hazard surface, exposed population, affected civic assets
    (schools, hospitals, kilns), and source attribution into a single
    structured brief for government action.

    Args:
        city_name: City to brief (fuzzy matched). Required.
        lead_days: Forecast horizon — 1, 2, or 3 (default 1).
    """
    from app.routers.analyst_desk import _load_forecast
    from app.services.spatial import (
        get_exposed_population, get_nearest_assets,
        compute_decision_heads, _load_vulnerability_grid,
    )

    dt = _effective_date(ctx)
    forecast = _load_forecast(dt)
    entries = forecast.get("forecasts", [])

    # 1. Exposed population (Layer B)
    exposure = get_exposed_population(
        entries, city_name=city_name, lead_days=lead_days,
    )

    if exposure.get("status") != "ok":
        return {
            "date": dt,
            "data": {"status": exposure.get("status"), "reason": exposure.get("reason")},
            "followups": ["Try a different city"],
        }

    matched_city = exposure.get("area", city_name)

    # 2. Decision heads (Layer D)
    heads = compute_decision_heads(entries, matched_city, lead_days)

    # 3. Find city center for asset queries
    grid = _load_vulnerability_grid()
    city_grid = grid[grid["city_name"] == matched_city]
    if city_grid.empty:
        center_lat, center_lon = 31.52, 74.35
    else:
        center_lat = float(city_grid["lat"].mean())
        center_lon = float(city_grid["lon"].mean())

    # 4. Nearby assets for context
    schools = await get_nearest_assets(
        center_lat, center_lon, ["school"], radius_m=25000, limit=5,
    )
    hospitals = await get_nearest_assets(
        center_lat, center_lon, ["hospital", "clinic"], radius_m=25000, limit=5,
    )
    kilns = await get_nearest_assets(
        center_lat, center_lon, ["brick_kiln"], radius_m=25000, limit=5,
    )

    # 5. Worst stations
    city_forecasts = [
        e for e in entries
        if e.get("lead_days") == lead_days
        and (e.get("city_name") or "").lower() == matched_city.lower()
    ]
    city_forecasts.sort(key=lambda e: e.get("pm25_forecast", 0), reverse=True)
    worst_stations = [
        {
            "station_name": e.get("station_name", ""),
            "pm25_forecast": round(e.get("pm25_forecast", 0), 1),
            "risk_band": e.get("risk_band", "unknown"),
        }
        for e in city_forecasts[:5]
    ]

    brief = {
        "city": matched_city,
        "lead_days": lead_days,
        "date": dt,

        "hazard": {
            "pm25_pop_weighted": exposure["pm25_pop_weighted"],
            "worst_stations": worst_stations,
        },

        "exposure": {
            "population": exposure["population"],
            "exposed_by_band": exposure["exposed_by_band"],
            "confidence": exposure["confidence"],
        },

        # Decision-specific heads
        "school_advisory": heads.get("school_advisory", {}),
        "hospital_preparedness": heads.get("hospital_preparedness", {}),
        "kiln_enforcement": heads.get("kiln_enforcement", {}),
        "monitor_deployment": heads.get("monitor_deployment", {}),

        "affected_institutions": {
            "schools_total": schools.get("counts_by_type", {}).get("school", 0),
            "hospitals_total": (
                hospitals.get("counts_by_type", {}).get("hospital", 0)
                + hospitals.get("counts_by_type", {}).get("clinic", 0)
            ),
            "nearest_schools": [
                {"name": a["name"], "distance_m": a["distance_m"]}
                for a in schools.get("assets", [])[:3]
            ],
            "nearest_hospitals": [
                {"name": a["name"], "distance_m": a["distance_m"]}
                for a in hospitals.get("assets", [])[:3]
            ],
        },

        "source_pressure": {
            "brick_kilns_within_25km": kilns.get("counts_by_type", {}).get("brick_kiln", 0),
            "nearest_kilns": [
                {"name": a["name"], "distance_m": a["distance_m"]}
                for a in kilns.get("assets", [])[:3]
            ],
        },
    }

    _update_session(
        ctx, tool="aq_impact_brief",
        focus_type="city", focused_city=matched_city,
        entities=[matched_city],
    )

    return {
        "date": dt,
        "data": brief,
        "basis": {
            "description": "Impact brief with 4 decision heads: school advisory, hospital preparedness, kiln enforcement, monitor deployment",
            "sources": ["station_forecasts", "WorldPop_2025", "OpenStreetMap", "APAD_brick_kilns"],
            "method": "IDW_hazard × population × decision-specific vulnerability weights",
        },
        "followups": [
            f"Show satellite imagery for {matched_city}",
            f"Why is {matched_city} so polluted?",
            "Which schools are most affected?",
        ],
    }


# ── Tool 14: aq_historical_snapshot ──────────────────────────────────────


async def aq_historical_snapshot(
    ctx: RunContext[CopilotSession],
    date: str,
    city: Optional[str] = None,
    country: Optional[str] = None,
) -> dict:
    """Get a national overview of air quality for any past date from the observations archive.

    Best for broad "what was the national picture on date X" questions. Returns actual
    station PM2.5 observations, top polluted cities, band breakdown, and 7-day context.
    For ranked hotspots on a past date use aq_hotspots_daily(date=...).
    For city station detail use aq_city_detail(date=...).

    Args:
        date: Date to query (YYYY-MM-DD). Must be a specific past date.
        city: Optional city name to get station-level detail for that city on that date.
        country: Country filter (e.g. "Pakistan"). Defaults to all.
    """
    from app.services.analytics import get_historical_snapshot

    db = await _get_db()
    try:
        result = await get_historical_snapshot(db, date, city, country)
    finally:
        await db.close()

    top_cities = result.get("data", {}).get("top_cities", [])
    entities = [c["city"] for c in top_cities if c.get("city")][:5]
    _update_session(
        ctx, tool="aq_historical_snapshot",
        focus_type="city" if city else "national",
        focused_city=city,
        entities=entities,
        historical_date=date,
    )
    return result


# ── Tool 15: aq_fire_activity ────────────────────────────────────────────


def _fire_basis(desc: str, extra: Optional[list] = None) -> dict:
    return {"description": desc, "sources": ["firms_viirs_archive", "fire_aggregate_store"] + (extra or []),
            "limitations": ["FIRMS NRT lags 3–12 h; the last Pakistan day may be incomplete until the night pass arrives",
                            "Fire counts and FRP do not measure a contribution to PM2.5"]}


async def aq_fire_activity(
    ctx: RunContext[CopilotSession],
    date: str,
    city: Optional[str] = None,
) -> dict:
    """FIRMS fire detections for one Pakistan day: national totals with country split and top districts,
    or (with a city) the fires within 50 km of that city and upwind of it.

    Args:
        date: Pakistan day (YYYY-MM-DD).
        city: Optional city name; without it the national picture is returned. For other radii or
            the full upwind analysis use aq_fire_exposure.
    """
    from app.services.fire_analytics import fire_activity, parse_day

    day = parse_day(date)
    if day is None:
        return {"date": date, "data": {"message": "date must be YYYY-MM-DD"}, "followups": []}
    db = await _get_db()
    try:
        data = await fire_activity(db, day, city, radius_km=50.0)
    finally:
        await db.close()
    _update_session(ctx, tool="aq_fire_activity", focus_type="city" if city else "national", focused_city=city, historical_date=date)
    followups = ["How does this fire season compare with earlier years?"]
    if city:
        followups.append(f"What was the air quality in {city} on {date}?")
    else:
        followups.append(f"Where were the biggest fire clusters on {date}?")
    return {"date": date, "data": data, "basis": _fire_basis(f"VIIRS fire detections for the Pakistan day {date}"), "followups": followups}


# ── Tool 15b: aq_fire_exposure ───────────────────────────────────────────


async def aq_fire_exposure(
    ctx: RunContext[CopilotSession],
    city: str = "",
    date: str = "",
    radius_km: float = 100.0,
) -> dict:
    """Fires around and upwind of a city on one Pakistan day: counts and FRP within 50/100/200 km split
    by country (Pakistan, Indian Punjab/Haryana, other), the wind at the city with its source named
    (ERA5, forecast pipeline, or station observations), the ±60° upwind cone, the nearest fire, the ten
    strongest upwind fires with distance, bearing and a transport-time estimate, and the pipeline's own
    fire driver when available.

    Args:
        city: City name (required, fuzzy matched).
        date: Pakistan day (YYYY-MM-DD); defaults to the active date.
        radius_km: Ring for the district breakdown (5–200; the 50/100/200 km rings are always returned).
    """
    from app.services.fire_analytics import fire_exposure, parse_day

    if not city.strip():
        return {"date": date, "data": {"message": "Which city? Fire exposure needs a city name."}, "followups": []}
    dt = date or _effective_date(ctx)
    day = parse_day(dt)
    if day is None:
        return {"date": dt, "data": {"message": "date must be YYYY-MM-DD"}, "followups": []}
    db = await _get_db()
    try:
        data = await fire_exposure(db, city, day, radius_km=radius_km)
    finally:
        await db.close()
    name = data.get("city", city)
    _update_session(ctx, tool="aq_fire_exposure", focus_type="city", focused_city=name, entities=[name], historical_date=dt)
    return {"date": dt, "data": data,
            "basis": _fire_basis(f"VIIRS fires within 200 km of {name} on the Pakistan day {dt}, upwind cone from the named wind source",
                                 ["era5_or_pipeline_or_station_wind"]),
            "followups": [f"Is fire smoke consistent with {name}'s PM2.5 this week?", f"Where are the fire clusters near {name}?",
                          "How does this fire season compare with earlier years?"]}


# ── Tool 15c: aq_fire_trends ─────────────────────────────────────────────


async def aq_fire_trends(
    ctx: RunContext[CopilotSession],
    region: str = "Pakistan",
    start_date: str = "",
    end_date: str = "",
    season: str = "",
    compare_years: bool = True,
    basis: str = "all",
) -> dict:
    """Daily (or weekly, for long windows) counts of deduplicated fire detection clusters and FRP for a
    region, with the same calendar window in 2020–2025 for comparison: totals, peak day, country share,
    top districts, and "higher than k of n reference years". The comparison block always carries
    `noaa20_only` (NOAA-20 detections alone): quote THAT for "more or fewer than last year", because the
    satellite roster changed and deduplication cannot remove the extra fires an added satellite sees.
    Regions: Pakistan, a province (KP, Punjab, Sindh, Balochistan, GB, AJK, Islamabad), a Pakistan
    district, "Indian Punjab", "Haryana", "India", or "other".

    Args:
        region: Region name (default Pakistan; plain "Punjab" means Pakistan's).
        start_date: YYYY-MM-DD, YYYY-MM or YYYY (start of the window).
        end_date: YYYY-MM-DD, YYYY-MM or YYYY (end of the window); defaults to today.
        season: "rice" (15 Sep–30 Nov, the ISRO/CAQM paddy window) or "wheat" (15 Apr–31 May, rabi residue);
            season-to-date when no dates are given. Without dates or a season: the current season, else the last 30 days.
        compare_years: Compare with the same window in 2020–2025.
        basis: "all" (every satellite, deduplicated; the fullest picture of today) or "n20" (NOAA-20 only,
            the series that is comparable across years).
    """
    from app.services.copilot.station_queries import parse_period_date
    from app.services.fire_analytics import REFERENCE_YEARS, fire_trends

    start = parse_period_date(start_date) if start_date else None
    end = parse_period_date(end_date, end=True) if end_date else None
    if (start_date and start is None) or (end_date and end is None):
        return {"date": end_date or start_date, "data": {"message": "dates must be YYYY-MM-DD, YYYY-MM or YYYY"}, "followups": []}
    data = fire_trends(region, start, end, season=season, compare_years=REFERENCE_YEARS if compare_years else (), basis=basis or "all")
    _update_session(ctx, tool="aq_fire_trends", focus_type="national" if region.strip().lower() in ("", "pakistan") else "region",
                    historical_date=(end or start).isoformat() if (end or start) else None)
    return {"date": data.get("window", {}).get("end_pkt_day") or end_date, "data": data,
            "basis": _fire_basis("daily region rollups of deduplicated VIIRS detection clusters from the aggregate store; year-on-year on NOAA-20 alone",
                                 ["a detection cluster is not a verified fire and a thermal detection does not say what burns"]),
            "followups": ["Which districts are burning most?", "Where are the persistent thermal sources?", "What about Indian Punjab in the same window?"]}


# ── Tool 15d: aq_fire_hotspots ───────────────────────────────────────────


async def aq_fire_hotspots(
    ctx: RunContext[CopilotSession],
    area: str = "Pakistan",
    date: str = "",
    end_date: str = "",
    group: str = "cluster",
    min_days: int = 10,
    radius_km: float = 0.0,
) -> dict:
    """Where the fires are: same-day clusters (~2 km cells merged) with FRP, extent, district and country;
    a district league table; or persistent thermal sources (cells burning on >= min_days of the last 30
    days: kilns, flares, landfills, industry rather than field burns). The area is a region (as in
    aq_fire_trends) or a city name with radius_km.

    Args:
        area: Region name, or a city name (then radius_km applies, default 50).
        date: Start Pakistan day (YYYY-MM-DD); defaults to the active date. Ignored for group=persistent.
        end_date: End day (YYYY-MM-DD); defaults to the start day (persistent: the end of the 30-day window).
        group: cluster | district | persistent.
        min_days: For persistent: minimum active days out of 30 (default 10).
        radius_km: Radius when area is a city (default 50).
    """
    from app.services.copilot.station_queries import _city_centroid, resolve_city
    from app.services.fire_analytics import fire_hotspots, parse_day, resolve_region

    dt = date or _effective_date(ctx)
    start = parse_day(dt)
    end = parse_day(end_date) if end_date else start
    if start is None or (end_date and end is None):
        return {"date": dt, "data": {"message": "dates must be YYYY-MM-DD"}, "followups": []}
    resolved, _, _ = resolve_region(area)
    center = None
    focus_city = None
    if resolved is None:
        db = await _get_db()
        try:
            match, cands = await resolve_city(db, area)
            if cands:
                return {"date": dt, "data": {"message": f"'{area}' matches several cities: {', '.join(c.name for c in cands)}. Which one?"}, "followups": []}
            if match is None:
                return {"date": dt, "data": {"message": f"'{area}' is neither a known region nor an active Pakistan city."}, "followups": []}
            lat, lon = await _city_centroid(db, match)
        finally:
            await db.close()
        if lat is None:
            return {"date": dt, "data": {"message": f"{match.name} has no coordinates in the registry."}, "followups": []}
        center, focus_city = (lat, lon, match.name), match.name
    data = fire_hotspots(region=None if center else area, center=center, radius_km=radius_km or 50.0, start=start, end=end,
                         group=group, min_days=min_days)
    _update_session(ctx, tool="aq_fire_hotspots", focus_type="city" if focus_city else "region", focused_city=focus_city,
                    historical_date=end.isoformat() if end else dt)
    return {"date": dt, "data": data, "basis": _fire_basis("deduplicated VIIRS detection clusters on a 0.02° grid from the aggregate store and the day files",
                                                           ["a persistent cell is a flag for investigation (kilns, flares, industry, or fields burning on successive days), never removed from counts"]),
            "followups": ["What is near that fire?", "How does this compare with earlier years?", "Which of these are upwind of Lahore?"]}


# ── Tool 15e: aq_fire_pm25_link ──────────────────────────────────────────


async def aq_fire_pm25_link(
    ctx: RunContext[CopilotSession],
    city: str = "",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Is fire smoke consistent with a city's PM2.5? Daily upwind fire FRP (±60° cone on that day's
    station wind, 200 km) and whole-ring FRP against the city's daily PM2.5 over the window, Pearson and
    Spearman at lags 0/1/2 days, and "candidate smoke-transport episodes" (upwind FRP above the window's
    75th percentile and PM2.5 ≥ 20 % and ≥ 10 µg/m³ above the prior three days). Never an attribution:
    report as "consistent with smoke transport", call the flagged days candidates, say the correlation is
    exploratory (not controlled for meteorology), and name stagnation and local sources as alternatives.

    Args:
        city: City name (required).
        start_date: YYYY-MM-DD; default 60 days before end_date.
        end_date: YYYY-MM-DD; default today. Window ≤ 120 days.
    """
    from app.services.fire_analytics import fire_pm25_link, parse_day

    if not city.strip():
        return {"date": end_date, "data": {"message": "Which city? The fire–PM2.5 linkage needs a city name."}, "followups": []}
    start = parse_day(start_date) if start_date else None
    end = parse_day(end_date) if end_date else None
    if (start_date and start is None) or (end_date and end is None):
        return {"date": end_date or start_date, "data": {"message": "dates must be YYYY-MM-DD"}, "followups": []}
    db = await _get_db()
    try:
        data = await fire_pm25_link(db, city, start, end)
    finally:
        await db.close()
    name = data.get("city", city)
    _update_session(ctx, tool="aq_fire_pm25_link", focus_type="city", focused_city=name, entities=[name],
                    historical_date=data.get("window", {}).get("end_pkt_day"))
    return {"date": data.get("window", {}).get("end_pkt_day") or end_date, "data": data,
            "basis": _fire_basis(f"daily upwind fire FRP vs reporting-station PM2.5 for {name}", ["station_wind_observations", "readings"]),
            "followups": [f"Which fires were upwind of {name} on the flagged days?", f"What else was driving PM2.5 in {name}?",
                          "How does this fire season compare with earlier years?"]}


# ── Tool 15f: aq_smoke_outlook ───────────────────────────────────────────


async def aq_smoke_outlook(
    ctx: RunContext[CopilotSession],
    city: str = "",
    days: int = 3,
) -> dict:
    """Will smoke reach a city in the coming days? For each lead day D+0…D+3: the ECMWF forecast wind at
    850 hPa (transport) and 10 m, the upwind fire load (FRP of the fires seen in the last two days that
    sit within ±60° of the wind-from direction and within one day's transport), its band (none / low /
    elevated / high / very_high), the country split and the strongest upwind fires. Without a city: the
    D+1 summary across cities. It assumes today's fires keep burning and is not a PM2.5 forecast.

    Args:
        city: City name (optional). Without it the national D+1 summary is returned.
        days: Lead days to include, 1–4 (default 3).
    """
    from app.services import fire_outlook as fo

    doc = await asyncio.to_thread(fo.read_latest)
    status = fo.outlook_status(doc)
    if doc is None:
        return {"date": "", "data": {"message": "No smoke outlook has been generated yet."}, "followups": []}
    base = {"status": status, "generated_at": doc.get("generated_at"), "fires_as_of": doc.get("fires_as_of"), "definitions": doc.get("definitions"),
            "caveats": doc.get("caveats", []) + (["The outlook is older than 6 hours."] if status == "stale" else [])}
    if city.strip():
        view = fo.city_view(doc, city)
        if view is None:
            return {"date": doc.get("today_pkt", ""), "data": {"message": f"No outlook for '{city}'; it is produced for active Pakistan cities with stations."}, "followups": []}
        n = max(1, min(int(days or 3), 4))
        data = {**base, "city": view["city"], "leads": view["leads"][:n],
                "others_at_alert_d1": [h for h in doc.get("summary", {}).get("alert", []) if h["city"].lower() != view["city"].lower()]}
        _update_session(ctx, tool="aq_smoke_outlook", focus_type="city", focused_city=view["city"], entities=[view["city"]])
        followups = [f"Which fires are upwind of {view['city']} today?", f"Is fire smoke consistent with {view['city']}'s PM2.5 this week?"]
    else:
        data = {**base, "summary": doc.get("summary")}
        _update_session(ctx, tool="aq_smoke_outlook", focus_type="national")
        followups = ["Which fires are upwind of Lahore?", "How does this fire season compare with earlier years?"]
    return {"date": doc.get("today_pkt", ""), "data": data,
            "basis": {"description": "ECMWF IFS forecast winds (Open-Meteo) × deduplicated VIIRS fires of the last two Pakistan days, carried forward",
                      "sources": ["open_meteo_ecmwf_ifs025", "firms_viirs_archive"],
                      "limitations": ["fires are assumed to persist; new fires are not predicted", "a smoke-source outlook, not a PM2.5 forecast"]},
            "followups": followups}


# ── Tool 16: aq_trajectory ───────────────────────────────────────────────


async def aq_trajectory(
    ctx: RunContext[CopilotSession],
    city: str,
    date: Optional[str] = None,
) -> dict:
    """Analyse where the air mass came from for a city on a specific date.

    Checks for cached HYSPLIT back-trajectory data first. If unavailable,
    falls back to a wind-based corridor estimate using surface observations
    and checks for upwind fire detections.

    Args:
        city: City name (required). Fuzzy matched.
        date: Date (YYYY-MM-DD). Defaults to today.
    """
    from app.services.trajectory import get_trajectory_for_copilot

    dt = date or _effective_date(ctx)
    db = await _get_db()
    try:
        result = await get_trajectory_for_copilot(db, city, dt)
    finally:
        await db.close()

    _update_session(
        ctx, tool="aq_trajectory",
        focus_type="city",
        focused_city=city,
        entities=[city],
        historical_date=date,
    )

    status = result.get("status", "unavailable")
    followups = []
    if status == "wind_estimated":
        followups.append(f"What was the air quality in {city} on {dt}?")
        followups.append(f"How many fires were there on {dt}?")
    elif status == "ok":
        followups.append(f"What's driving pollution in {city}?")
    else:
        followups.append(f"Tell me about {city}")

    return {
        "date": dt,
        "data": result,
        "basis": {
            "description": (
                "HYSPLIT 72h back-trajectory" if status == "ok"
                else "Wind-based corridor estimate from surface station observations"
            ),
            "sources": (
                ["hysplit_trajectory"] if status == "ok"
                else ["station_wind_observations", "firms_viirs_archive"]
            ),
            "limitations": (
                [] if status == "ok"
                else ["Surface winds may not reflect upper-level transport",
                      "Wind estimate is directional only, not a full trajectory"]
            ),
        },
        "followups": followups,
    }


# ── Tool 17: aq_station_inventory ─────────────────────────────────────────


async def aq_station_inventory(
    ctx: RunContext[CopilotSession],
    area: str = "national",
    name: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 10.0,
    as_of_date: str = "",
    provider: str = "",
    list_stations: bool = False,
    limit: int = 50,
) -> dict:
    """Exact station counts and lists for an area: how many monitors, which ones, where.

    Use for any "how many stations/monitors", "which stations", "list the stations",
    "stations with coordinates", "stations within N km of X" question. Counts come
    back as registered / active / reporting with the definitions and the window
    spelled out — quote them. Shadow providers (OpenAQ, ICIMOD) and test stations
    are never counted; Punjab EPA and BAM monitors are.

    Args:
        area: "national", "province", "city" or "radius".
        name: Province (KP, Sindh, ICT…), city, or the place at the centre of a radius query.
        lat, lon: Centre for area="radius" when no place name is given.
        radius_km: Radius for area="radius" (0.5–200, default 10).
        as_of_date: YYYY-MM-DD → "reporting" means reported on that Pakistan day (default: last 24 h).
        provider: Restrict to one provider code (airvisual, punjab, bam, …).
        list_stations: True to include the station list (id, name, city, province, provider, lat, lon, first/last observation).
        limit: Max stations in the list (default 50, max 100).
    """
    from datetime import date as _date
    from app.services.copilot.station_queries import resolve_area, station_inventory

    day = None
    if as_of_date:
        try:
            day = _date.fromisoformat(as_of_date)
        except ValueError:
            return {"data": {"message": "as_of_date must be YYYY-MM-DD."}, "followups": []}
    db = await _get_db()
    try:
        resolved = await resolve_area(db, area, name, lat, lon, radius_km)
        if isinstance(resolved, dict):
            return {"data": resolved, "followups": []}
        data = await station_inventory(db, resolved, as_of_day=day, provider=provider,
                                       list_stations=list_stations, limit=limit)
    finally:
        await db.close()
    _update_session(ctx, tool="aq_station_inventory",
                    focus_type=resolved.kind if resolved.kind in ("city", "province", "national") else None,
                    focused_city=resolved.name if resolved.kind == "city" else None,
                    entities=[resolved.name])
    followups = [f"List the stations in {resolved.name} with coordinates" if not list_stations else f"Which of these in {resolved.name} are not reporting?",
                 f"How many stations in {resolved.name} were reporting a year ago?",
                 "Which provider operates most of them?"]
    return {"date": _effective_date(ctx), "data": data, "followups": followups}


# ── Tool 18: aq_nearest_stations ──────────────────────────────────────────


async def aq_nearest_stations(
    ctx: RunContext[CopilotSession],
    place: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    k: int = 5,
    max_km: float = 50.0,
) -> dict:
    """The k nearest active stations to a place or coordinate, with distance in km and bearing.

    Use for "nearest station to X", "how far is the closest monitor", "stations near
    X". Resolves `place` as a city (centroid), a station name, or a province.

    Args:
        place: City, station or province name (ignored when lat/lon given).
        lat, lon: Coordinates of the origin.
        k: How many stations (1–25, default 5).
        max_km: Search radius (default 50, max 500).
    """
    from app.services.copilot.station_queries import nearest_stations, resolve_place

    db = await _get_db()
    try:
        origin_name = place
        if lat is None or lon is None:
            if not place:
                return {"data": {"message": "Give a place name or lat/lon."}, "followups": []}
            origin = await resolve_place(db, place)
            if "message" in origin:
                return {"data": origin, "followups": []}
            lat, lon, origin_name = origin["lat"], origin["lon"], f"{origin['name']} ({origin['kind']})"
        data = await nearest_stations(db, lat, lon, k=k, max_km=max_km, origin_name=origin_name)
    finally:
        await db.close()
    _update_session(ctx, tool="aq_nearest_stations", entities=[s["name"] for s in data["stations"][:5]])
    first = data["stations"][0]["name"] if data["stations"] else None
    followups = ([f"Tell me about {first}", f"Show the 24-hour trend at {first}"] if first else []) + \
                [f"How many stations are within {int(max_km)} km of {place or 'here'}?"]
    return {"date": _effective_date(ctx), "data": data, "followups": followups}


# ── Tool 19: aq_period_stats ──────────────────────────────────────────────


async def aq_period_stats(
    ctx: RunContext[CopilotSession],
    entity: str = "city",
    name: str = "",
    start_date: str = "",
    end_date: str = "",
    bucket: str = "day",
    same_calendar_date: bool = False,
) -> dict:
    """PM2.5 statistics over a period: daily, monthly, yearly or whole-range means for a
    station, city, province or the country, on Pakistan calendar days.

    Use for "average in October 2025", "monthly means this year", "2024 vs 2025",
    "worst day last winter", "average on 29 October across all years"
    (same_calendar_date=True, start_date="10-29"). Never for a single current reading.

    Args:
        entity: "station", "city", "province" or "national".
        name: Station, city or province name (empty for national).
        start_date: YYYY-MM-DD, YYYY-MM or YYYY (inclusive). For same_calendar_date: "MM-DD".
        end_date: YYYY-MM-DD, YYYY-MM or YYYY (inclusive, default today).
        bucket: "day", "month", "year" or "all" (one row for the whole range). Max 120 buckets.
        same_calendar_date: One row per year for the calendar day in start_date.
    """
    from app.services.copilot.station_queries import period_stats

    db = await _get_db()
    try:
        data = await period_stats(db, entity=entity, name=name, start=start_date, end=end_date,
                                  bucket=bucket, same_calendar_date=same_calendar_date)
    finally:
        await db.close()
    ent = data.get("entity", {}) if isinstance(data, dict) else {}
    _update_session(ctx, tool="aq_period_stats",
                    focus_type=ent.get("kind") if ent.get("kind") in ("city", "province", "national") else None,
                    focused_city=ent.get("name") if ent.get("kind") == "city" else None,
                    entities=[ent.get("name")] if ent.get("name") else [])
    label = ent.get("name") or name or "Pakistan"
    followups = [f"Which was the worst month for {label}?", f"Compare {label} with the previous year",
                 f"How many stations contributed in {label}?"]
    return {"date": _effective_date(ctx), "data": data, "followups": followups}
