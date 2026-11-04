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


async def aq_fire_activity(
    ctx: RunContext[CopilotSession],
    date: str,
    city: Optional[str] = None,
) -> dict:
    """Get FIRMS satellite fire detection data for any date.

    Returns fire counts, FRP statistics, high-confidence detections,
    and city-level fire clusters from archived VIIRS satellite data.

    Args:
        date: Date to query (YYYY-MM-DD).
        city: Optional city name — filters fires within ~50km of city.
    """
    from app.services.analytics import get_fire_activity

    db = await _get_db()
    try:
        result = await get_fire_activity(date, city, db=db)
    finally:
        await db.close()

    _update_session(
        ctx, tool="aq_fire_activity",
        focus_type="city" if city else "national",
        focused_city=city,
        historical_date=date,
    )
    return result


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
