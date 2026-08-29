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

    import json as _json
    action_hint = "{{ACTION:" + _json.dumps({
        "type": "show_station_trend",
        "station_id": station_id,
        "station_name": history.get("station_name", "") if history else "",
        "hours": hours,
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
