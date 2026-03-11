"""PydanticAI tool functions for the analyst desk copilot.

Six domain-level facade tools with standard response envelopes.
Each tool maps to a user intention, does heavy computation server-side,
and returns a structured envelope with ui_actions + followups.
"""

import difflib
import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic_ai import RunContext
from fastapi import HTTPException

from app.routers.analyst_desk import (
    _load_forecast,
    _load_summary_safe,
    _load_watchlist_safe,
    _resolve_latest_date,
    _load_drift_report,
)

from .context import CopilotSession

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

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

# ── Internal helpers ───────────────────────────────────────────────────────────


def _date_str(d: str) -> str:
    return d.replace("-", "")


def _effective_date(ctx: RunContext[CopilotSession]) -> str:
    """Return the session date or resolve latest."""
    return ctx.deps.current_date or _resolve_latest_date()


def _load_forecast_safe(dt: str) -> dict:
    """Load forecast JSON, returning empty dict on missing data."""
    try:
        return _load_forecast(dt)
    except (HTTPException, Exception) as e:
        logger.warning(f"Forecast load failed for {dt}: {e}")
        return {}


def _make_envelope(
    date: str,
    data: dict,
    *,
    ui_actions: list | None = None,
    followups: list | None = None,
    data_quality: dict | None = None,
    provenance: str = "forecast_json",
) -> dict:
    """Standard response wrapper for all tools."""
    import json as _json
    actions = ui_actions or []
    # Pre-format ACTION tag so model can copy it verbatim
    action_hint = ""
    if actions:
        action_hint = "{{ACTION:" + _json.dumps(actions[0]) + "}}"
    return {
        "date": date,
        "data": data,
        "action_hint": action_hint,
        "followups": followups or [],
    }


def _all_city_names(entries: list[dict]) -> list[str]:
    """Extract unique city names from forecast entries, preserving order."""
    seen: set[str] = set()
    names: list[str] = []
    for e in entries:
        c = e.get("city_name") or e.get("city") or ""
        if c and c not in seen:
            seen.add(c)
            names.append(c)
    return names


def _fuzzy_city(query: str, entries: list[dict]) -> str | None:
    """Fuzzy match a city name against forecast entries."""
    names = _all_city_names(entries)
    if not names:
        return None
    q = query.lower()
    for n in names:
        if n.lower() == q:
            return n
    matches = difflib.get_close_matches(query, names, n=1, cutoff=0.6)
    return matches[0] if matches else None


# ── Tool 1: aq_hotspots_daily ─────────────────────────────────────────────────


async def aq_hotspots_daily(
    ctx: RunContext[CopilotSession],
    date: Optional[str] = None,
    geography: str = "city",
    metric: str = "avg_pm25",
    top_k: int = 5,
) -> dict:
    """Get today's air quality hotspots: most polluted cities, stations, or provinces ranked by PM2.5.

    Also returns a national summary with mean/max PM2.5, band counts, and ramp count.

    Args:
        date: Forecast date (YYYY-MM-DD). Defaults to latest available.
        geography: Group by "city", "station", or "province" (default "city").
        metric: Ranking metric — "avg_pm25", "max_pm25", or "max_q90" (default "avg_pm25").
        top_k: Number of results to return (default 5).
    """
    dt = date or _effective_date(ctx)
    forecast = _load_forecast_safe(dt)
    entries = forecast.get("forecasts", [])
    d1 = [e for e in entries if e.get("lead_days") == 1]

    if not d1:
        return _make_envelope(dt, {"message": "No D+1 forecast data available."})

    # National summary
    vals = [e["pm25_forecast"] for e in d1 if e.get("pm25_forecast") is not None]
    band_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    n_ramp = 0
    for e in d1:
        b = e.get("risk_band", "unknown")
        band_counts[b] = band_counts.get(b, 0) + 1
        p = e.get("priority", "unknown")
        priority_counts[p] = priority_counts.get(p, 0) + 1
        if e.get("ramp_detected"):
            n_ramp += 1

    national = {
        "n_stations": len(d1),
        "mean_pm25": round(sum(vals) / len(vals), 1) if vals else None,
        "max_pm25": round(max(vals), 1) if vals else None,
        "band_counts": band_counts,
        "priority_counts": priority_counts,
        "n_ramp": n_ramp,
    }

    # Build hotspot list
    if geography == "station":
        hotspots = []
        for e in d1:
            pm = e.get("pm25_forecast")
            if pm is None:
                continue
            hotspots.append({
                "name": e.get("station_name", ""),
                "sensor_id": e.get("sensor_id"),
                "city": e.get("city_name") or e.get("city", ""),
                "pm25_forecast": round(pm, 1),
                "pm25_q90": round(e["pm25_q90"], 1) if e.get("pm25_q90") is not None else None,
                "risk_band": e.get("risk_band"),
                "ramp_detected": e.get("ramp_detected", False),
                "latitude": e.get("latitude"),
                "longitude": e.get("longitude"),
            })
        sort_key = {
            "avg_pm25": lambda x: x["pm25_forecast"],
            "max_pm25": lambda x: x["pm25_forecast"],
            "max_q90": lambda x: x.get("pm25_q90") or 0,
        }.get(metric, lambda x: x["pm25_forecast"])
        hotspots.sort(key=sort_key, reverse=True)
        hotspots = hotspots[:top_k]
    else:
        # Group by city or province
        group_key = "city_name" if geography == "city" else "state_name"
        fallback_key = "city" if geography == "city" else ""
        groups: dict[str, list[dict]] = {}
        for e in d1:
            g = e.get(group_key) or e.get(fallback_key) or "Unknown"
            groups.setdefault(g, []).append(e)

        hotspots = []
        for name, grp in groups.items():
            pms = [e["pm25_forecast"] for e in grp if e.get("pm25_forecast") is not None]
            q90s = [e["pm25_q90"] for e in grp if e.get("pm25_q90") is not None]
            if not pms:
                continue
            worst_band = max(
                (e.get("risk_band", "unknown") for e in grp),
                key=lambda b: _BAND_ORDER.get(b, 0),
            )
            hotspots.append({
                "name": name,
                "n_stations": len(pms),
                "avg_pm25": round(sum(pms) / len(pms), 1),
                "max_pm25": round(max(pms), 1),
                "max_q90": round(max(q90s), 1) if q90s else None,
                "worst_band": worst_band,
                "n_ramp": sum(1 for e in grp if e.get("ramp_detected")),
            })

        sort_key = {
            "avg_pm25": lambda x: x["avg_pm25"],
            "max_pm25": lambda x: x["max_pm25"],
            "max_q90": lambda x: x.get("max_q90") or 0,
        }.get(metric, lambda x: x["avg_pm25"])
        hotspots.sort(key=sort_key, reverse=True)
        hotspots = hotspots[:top_k]

    # UI action: zoom to worst hotspot
    ui_actions = []
    if hotspots:
        top = hotspots[0]
        if geography == "station" and top.get("latitude"):
            ui_actions.append({
                "type": "zoom_to_station",
                "sensor_id": top["sensor_id"],
                "lat": top["latitude"],
                "lng": top["longitude"],
            })
        elif geography in ("city", "province"):
            ui_actions.append({"type": "zoom_to_city", "city": top["name"]})

    followups = [
        f"Tell me more about {hotspots[0]['name']}" if hotspots else None,
        "What needs attention today?",
        "How accurate are the forecasts?",
    ]
    followups = [f for f in followups if f]

    return _make_envelope(
        dt,
        {
            "national_summary": national,
            "geography": geography,
            "metric": metric,
            "hotspots": hotspots,
        },
        ui_actions=ui_actions,
        followups=followups,
    )


# ── Tool 2: aq_city_detail ────────────────────────────────────────────────────


async def aq_city_detail(
    ctx: RunContext[CopilotSession],
    city_name: str = "",
    date: Optional[str] = None,
    include: Optional[list[str]] = None,
    sensor_id: Optional[int] = None,
) -> dict:
    """Get detailed air quality for a city or a specific station.

    Supports fuzzy city name matching. Can also look up a single station by
    sensor_id (returns all horizons for that station).

    Args:
        city_name: City name (fuzzy matched). Required unless sensor_id is provided.
        date: Forecast date (YYYY-MM-DD). Defaults to latest available.
        include: Sections to include — any of "summary", "stations", "trajectory" (default ["summary", "stations"]).
        sensor_id: Optional numeric station ID. When provided, returns that single station's multi-horizon forecast.
    """
    if include is None:
        include = ["summary", "stations"]

    dt = date or _effective_date(ctx)
    forecast = _load_forecast_safe(dt)
    entries = forecast.get("forecasts", [])

    # ── Station lookup by sensor_id ──
    if sensor_id is not None:
        rows = [e for e in entries if e.get("sensor_id") == sensor_id]
        if not rows:
            return _make_envelope(dt, {"message": f"Station {sensor_id} not found in forecast."})
        rows.sort(key=lambda e: e.get("lead_days", 0))
        meta = rows[0]
        station_city = meta.get("city_name") or meta.get("city") or ""
        ctx.deps.focused_city = station_city
        ui_actions = []
        if meta.get("latitude"):
            ui_actions.append({
                "type": "zoom_to_station",
                "sensor_id": sensor_id,
                "lat": meta["latitude"],
                "lng": meta["longitude"],
            })
        return _make_envelope(
            dt,
            {
                "city": station_city,
                "station": {
                    "sensor_id": sensor_id,
                    "station_name": meta.get("station_name", ""),
                    "latitude": meta.get("latitude"),
                    "longitude": meta.get("longitude"),
                },
                "horizons": [
                    {
                        "lead_days": r.get("lead_days"),
                        "target_date": r.get("target_date"),
                        "pm25_forecast": round(r["pm25_forecast"], 1) if r.get("pm25_forecast") is not None else None,
                        "pm25_q75": round(r["pm25_q75"], 1) if r.get("pm25_q75") is not None else None,
                        "pm25_q90": round(r["pm25_q90"], 1) if r.get("pm25_q90") is not None else None,
                        "risk_band": r.get("risk_band"),
                        "priority": r.get("priority"),
                        "ramp_detected": r.get("ramp_detected", False),
                    }
                    for r in rows
                ],
            },
            ui_actions=ui_actions,
            followups=[f"Tell me about {station_city}" if station_city else "What needs attention today?"],
        )

    # ── City lookup ──
    # Fuzzy match city
    matched = _fuzzy_city(city_name, entries)
    if not matched:
        available = _all_city_names(entries)[:10]
        return _make_envelope(dt, {
            "message": f"City '{city_name}' not found.",
            "available_cities_sample": available,
        })

    matched_lower = matched.lower()
    city_entries = [
        e for e in entries
        if (e.get("city_name") or e.get("city") or "").lower() == matched_lower
    ]

    result: dict = {"city": matched}

    # Summary section
    if "summary" in include:
        summary_data = _load_summary_safe(dt)
        city_summary = None
        if summary_data:
            for c in summary_data.get("city_summaries", []):
                if (c.get("name") or "").lower() == matched_lower:
                    city_summary = c
                    break
        if city_summary:
            result["summary"] = city_summary
        else:
            # Build summary from forecast entries
            horizons = {}
            for ld in (1, 2, 3):
                h_entries = [e for e in city_entries if e.get("lead_days") == ld]
                pms = [e["pm25_forecast"] for e in h_entries if e.get("pm25_forecast") is not None]
                if pms:
                    worst_band = max(
                        (e.get("risk_band", "unknown") for e in h_entries),
                        key=lambda b: _BAND_ORDER.get(b, 0),
                    )
                    horizons[f"D+{ld}"] = {
                        "pm25_mean": round(sum(pms) / len(pms), 1),
                        "pm25_max": round(max(pms), 1),
                        "worst_band": worst_band,
                        "n_stations": len(pms),
                    }
            result["summary"] = {"horizons": horizons}

    # Stations section (D+1 only, ranked by PM2.5)
    if "stations" in include:
        d1 = [e for e in city_entries if e.get("lead_days") == 1]
        d1.sort(key=lambda e: e.get("pm25_forecast") or 0, reverse=True)
        result["stations"] = [
            {
                "sensor_id": e.get("sensor_id"),
                "station_name": e.get("station_name", ""),
                "pm25_forecast": round(e["pm25_forecast"], 1) if e.get("pm25_forecast") is not None else None,
                "pm25_q90": round(e["pm25_q90"], 1) if e.get("pm25_q90") is not None else None,
                "risk_band": e.get("risk_band"),
                "priority": e.get("priority"),
                "ramp_detected": e.get("ramp_detected", False),
                "latitude": e.get("latitude"),
                "longitude": e.get("longitude"),
            }
            for e in d1[:20]
        ]
        result["n_stations_total"] = len(d1)

    # Trajectory section (all horizons per station)
    if "trajectory" in include:
        by_station: dict[int, list] = {}
        for e in city_entries:
            sid = e.get("sensor_id")
            if sid is None:
                continue
            by_station.setdefault(sid, []).append(e)

        trajectories = []
        for sid, rows in list(by_station.items())[:20]:
            rows.sort(key=lambda e: e.get("lead_days", 0))
            trajectories.append({
                "sensor_id": sid,
                "station_name": rows[0].get("station_name", ""),
                "horizons": [
                    {
                        "lead_days": r.get("lead_days"),
                        "target_date": r.get("target_date"),
                        "pm25_forecast": round(r["pm25_forecast"], 1) if r.get("pm25_forecast") is not None else None,
                        "risk_band": r.get("risk_band"),
                    }
                    for r in rows
                ],
            })
        result["trajectories"] = trajectories

    # Update session
    ctx.deps.focused_city = matched

    ui_actions = [{"type": "zoom_to_city", "city": matched}]
    followups = [
        f"Why is {matched} so polluted?",
        f"How does {matched} compare to yesterday?",
        "What stations need attention?",
    ]

    return _make_envelope(dt, result, ui_actions=ui_actions, followups=followups)


# ── Tool 3: aq_compare_dates ──────────────────────────────────────────────────


async def aq_compare_dates(
    ctx: RunContext[CopilotSession],
    date1: str,
    date2: str,
    geography: str = "national",
) -> dict:
    """Compare PM2.5 forecasts between two dates to identify trends and biggest movers.

    Args:
        date1: First date (YYYY-MM-DD), typically the earlier date.
        date2: Second date (YYYY-MM-DD), typically the later date.
        geography: "national" for country-wide, or a city name to compare that city only (default "national").
    """
    f1 = _load_forecast_safe(date1)
    f2 = _load_forecast_safe(date2)

    e1 = [e for e in f1.get("forecasts", []) if e.get("lead_days") == 1]
    e2 = [e for e in f2.get("forecasts", []) if e.get("lead_days") == 1]

    if geography != "national":
        gl = geography.lower()
        e1 = [e for e in e1 if (e.get("city_name") or e.get("city") or "").lower() == gl]
        e2 = [e for e in e2 if (e.get("city_name") or e.get("city") or "").lower() == gl]

    def _stats(items: list) -> dict:
        vals = [e["pm25_forecast"] for e in items if e.get("pm25_forecast") is not None]
        if not vals:
            return {"n_stations": 0, "mean_pm25": None, "max_pm25": None}
        return {
            "n_stations": len(vals),
            "mean_pm25": round(sum(vals) / len(vals), 1),
            "max_pm25": round(max(vals), 1),
        }

    s1, s2 = _stats(e1), _stats(e2)
    delta_mean = None
    direction = "unchanged"
    if s1["mean_pm25"] is not None and s2["mean_pm25"] is not None:
        delta_mean = round(s2["mean_pm25"] - s1["mean_pm25"], 1)
        if delta_mean > 2:
            direction = "worsening"
        elif delta_mean < -2:
            direction = "improving"

    # Biggest movers (national only)
    biggest_movers: list[dict] = []
    if geography == "national":
        map1 = {e.get("sensor_id"): e for e in e1 if e.get("sensor_id")}
        movers = []
        for e in e2:
            sid = e.get("sensor_id")
            if sid and sid in map1 and e.get("pm25_forecast") is not None:
                old = map1[sid].get("pm25_forecast")
                if old is not None:
                    delta = round(e["pm25_forecast"] - old, 1)
                    movers.append({
                        "sensor_id": sid,
                        "station_name": e.get("station_name", ""),
                        "city": e.get("city_name") or e.get("city", ""),
                        "pm25_date1": round(old, 1),
                        "pm25_date2": round(e["pm25_forecast"], 1),
                        "delta": delta,
                    })
        movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
        biggest_movers = movers[:10]

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
        },
        followups=followups,
    )


# ── Tool 4: aq_explain_drivers ────────────────────────────────────────────────


async def aq_explain_drivers(
    ctx: RunContext[CopilotSession],
    city_or_station: str,
    date: Optional[str] = None,
) -> dict:
    """Explain why air quality is poor in a city or station — fire activity, stagnation, transport.

    Reads anomaly driver attribution from watchlists and correlates with forecast
    conditions. Degrades gracefully when driver data is unavailable.

    Args:
        city_or_station: City name or station name to investigate.
        date: Forecast date (YYYY-MM-DD). Defaults to latest available.
    """
    dt = date or _effective_date(ctx)
    target = city_or_station
    target_lower = target.lower()

    # Load watchlist for anomaly drivers
    watchlist_data = _load_watchlist_safe(dt)
    drivers: list[dict] = []
    related_alerts: list[dict] = []

    if watchlist_data:
        watchlists = watchlist_data.get("watchlists", {})

        # Anomaly drivers for this target
        for entry in watchlists.get("anomaly_drivers", []):
            name = (entry.get("city_name") or entry.get("station_name") or entry.get("city") or "").lower()
            station = (entry.get("station_name") or "").lower()
            if target_lower in name or target_lower in station:
                drivers.append(entry)

        # Related alerts from other watchlists
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

    # Forecast conditions for context
    forecast = _load_forecast_safe(dt)
    conditions: list[dict] = []
    for e in forecast.get("forecasts", []):
        if e.get("lead_days") != 1:
            continue
        name = (e.get("city_name") or e.get("city") or "").lower()
        station = (e.get("station_name") or "").lower()
        if target_lower in name or target_lower in station:
            conditions.append({
                "sensor_id": e.get("sensor_id"),
                "station_name": e.get("station_name", ""),
                "pm25_forecast": round(e["pm25_forecast"], 1) if e.get("pm25_forecast") is not None else None,
                "risk_band": e.get("risk_band"),
                "episode_state": e.get("episode_state"),
                "ramp_detected": e.get("ramp_detected", False),
            })

    conditions.sort(key=lambda x: x.get("pm25_forecast") or 0, reverse=True)
    conditions = conditions[:10]

    has_data = bool(drivers or related_alerts or conditions)

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
            "forecast_conditions": conditions,
            "data_available": has_data,
            "note": None if has_data else f"No driver attribution data available for '{target}'. Showing forecast conditions only.",
        },
        ui_actions=ui_actions,
        followups=followups,
        provenance="watchlist_json + forecast_json",
    )


# ── Tool 5: aq_incident_summary ───────────────────────────────────────────────


async def aq_incident_summary(
    ctx: RunContext[CopilotSession],
    date: Optional[str] = None,
    severity: str = "all",
) -> dict:
    """Get all active incidents and alerts: ramp events, high PM2.5, rapid deterioration, new episodes.

    Flattens all 8 watchlists into a unified severity-ranked incident list.
    Falls back to forecast data when watchlist is unavailable.

    Args:
        date: Forecast date (YYYY-MM-DD). Defaults to latest available.
        severity: Filter — "all", "critical", or "warning" (default "all").
    """
    dt = date or _effective_date(ctx)
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
    else:
        # Fallback: identify critical stations from forecast data
        forecast = _load_forecast_safe(dt)
        d1 = [e for e in forecast.get("forecasts", []) if e.get("lead_days") == 1]
        for e in d1:
            band = e.get("risk_band", "good")
            if _BAND_ORDER.get(band, 0) >= 3:  # unhealthy or worse
                sev = "critical" if _BAND_ORDER.get(band, 0) >= 4 else "warning"
                if severity != "all" and sev != severity:
                    continue
                incidents.append({
                    "watchlist": "forecast_fallback",
                    "severity": sev,
                    "sensor_id": e.get("sensor_id"),
                    "station_name": e.get("station_name", ""),
                    "city": e.get("city_name") or e.get("city") or "",
                    "pm25_forecast": round(e["pm25_forecast"], 1) if e.get("pm25_forecast") is not None else None,
                    "risk_band": band,
                    "reason": f"{band.replace('_', ' ')} air quality",
                })

    # Sort: critical first, then by PM2.5 descending
    sev_order = {"critical": 3, "warning": 2, "info": 1}
    incidents.sort(
        key=lambda x: (sev_order.get(x["severity"], 0), x.get("pm25_forecast") or 0),
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
        provenance="watchlist_json" if watchlist_data else "forecast_json_fallback",
    )


# ── Tool 6: aq_forecast_audit ─────────────────────────────────────────────────


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
    from datetime import date as date_cls, timedelta

    dt = date or _effective_date(ctx)

    if n_days <= 1:
        # ── Single-day audit ──
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
                        "mae": round(h["mae"], 1) if h.get("mae") is not None else None,
                        "rmse": round(h["rmse"], 1) if h.get("rmse") is not None else None,
                        "bias": round(h["bias"], 1) if h.get("bias") is not None else None,
                        "r2": round(h["r2"], 3) if h.get("r2") is not None else None,
                        "f1_150": round(h["f1_150"], 3) if h.get("f1_150") is not None else None,
                    }
            data["accuracy"] = horizons
        else:
            data["accuracy"] = None
            data["accuracy_note"] = "T-3 verification not yet available (needs 3+ days of forecasts)."

        pred = report.get("prediction_stats")
        if pred:
            data["prediction_stats"] = {
                "mean": round(pred["mean"], 1) if pred.get("mean") is not None else None,
                "median": round(pred["median"], 1) if pred.get("median") is not None else None,
                "p90": round(pred["p90"], 1) if pred.get("p90") is not None else None,
                "n_stations": pred.get("n_stations"),
                "pct_above_150": round(pred["pct_above_150"] * 100, 1) if pred.get("pct_above_150") is not None else None,
            }

        psi = report.get("feature_psi", {})
        if psi:
            drifting = sorted(psi.items(), key=lambda x: x[1], reverse=True)[:5]
            data["top_feature_drift"] = [
                {"feature": f, "psi": round(v, 3)} for f, v in drifting if v > 0
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
        # ── Multi-day trend ──
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
                        entry[f"{key}_mae"] = round(h["mae"], 1) if h.get("mae") is not None else None
                        entry[f"{key}_rmse"] = round(h["rmse"], 1) if h.get("rmse") is not None else None
                entry["n_matched"] = perf.get("n_matched")
            else:
                entry["accuracy"] = None

            pred = report.get("prediction_stats")
            if pred:
                entry["pred_mean"] = round(pred["mean"], 1) if pred.get("mean") is not None else None
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

        # Compute trend direction from D+1 MAE
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
