"""Bench-level fixtures: mock agent, mock analytics, session factory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from .fixtures.tool_outputs import MOCK_OUTPUTS


# ---------------------------------------------------------------------------
# Lightweight stand-ins so tests run WITHOUT pydantic-ai installed
# (Level A uses these; Level B imports real PydanticAI)
# ---------------------------------------------------------------------------

@dataclass
class FakeToolCallPart:
    tool_name: str
    args: dict
    tool_call_id: str = "fake-001"


@dataclass
class FakeTextPart:
    content: str


@dataclass
class FakeModelResponse:
    parts: list

    @property
    def role(self):
        return "model-response"


@dataclass
class FakeSession:
    """Minimal stand-in for CopilotSession for Level A tests."""
    session_id: str = "bench-test"
    current_date: str = "2026-03-06"
    focused_city: str | None = None
    focused_station_id: str | None = None
    focus_type: str = "national"
    comparison_date: str | None = None
    last_tool: str | None = None
    last_entities: list[str] | None = None
    last_coverage_query: dict | None = None
    message_history: list = None

    def __post_init__(self):
        if self.message_history is None:
            self.message_history = []
        if self.last_entities is None:
            self.last_entities = []


def build_scripted_response(
    tool_name: str | None,
    tool_args: dict,
    mock_output_key: str,
    agent_text: str = "",
) -> list:
    """Build a scripted sequence of messages as if the agent ran.

    Returns a list of FakeModelResponse objects containing tool calls and text.
    If tool_name is None, returns a text-only response (for abstention/decline cases).
    """
    if tool_name is None:
        # Text-only response for safety / abstention cases
        if not agent_text:
            agent_text = (
                "I don't have the tools or data to answer that question. "
                "This capability is not available in my current set of tools. "
                "I cannot provide that information."
            )
        return [FakeModelResponse(parts=[FakeTextPart(content=agent_text)])]

    mock_output = MOCK_OUTPUTS.get(mock_output_key, {"data": {}})

    # Model response: tool call
    tool_response = FakeModelResponse(parts=[
        FakeToolCallPart(tool_name=tool_name, args=tool_args),
    ])

    # If no explicit agent_text, generate a default from mock output
    if not agent_text:
        agent_text = _generate_text_from_output(tool_name, mock_output)

    # Model response: text
    text_response = FakeModelResponse(parts=[
        FakeTextPart(content=agent_text),
    ])

    return [tool_response, text_response]


def _generate_text_from_output(tool_name: str, output: dict) -> str:
    """Generate plausible agent text from tool output for Level A testing.

    This is deliberately simple — just enough to pass graders.
    Real LLM text (Level B) will be richer.
    """
    data = output.get("data", {})

    if tool_name == "aq_hotspots_daily":
        hotspots = data.get("hotspots", [])
        lines = ["Based on station observations from the last 24 hours, here are the most polluted cities:\n"]
        for i, h in enumerate(hotspots, 1):
            lines.append(f"{i}. **{h['name']}** — {h['avg_pm25']} µg/m³ ({h.get('risk_band', '')})")
        return "\n".join(lines)

    if tool_name == "aq_city_detail":
        city = data.get("city", "Unknown")
        avg = data.get("avg_pm25", "N/A")
        stations = data.get("stations", [])
        lines = [f"Based on station observations, **{city}** has an average PM2.5 of {avg} µg/m³.\n"]
        for s in stations:
            lines.append(f"- {s['station_name']}: {s['pm25']} µg/m³")
        return "\n".join(lines)

    if tool_name == "aq_explain_drivers":
        target = data.get("target", "Unknown")
        drivers = data.get("drivers", [])
        prefix = "Based on estimated driver analysis" if data.get("estimated") else "Based on forecast driver analysis"
        lines = [f"{prefix}, {target}'s air quality is likely driven by:\n"]
        for d in drivers:
            lines.append(f"- **{d['driver']}** (score: {d['score']}): {'; '.join(d.get('evidence', []))}")
        trajectory = data.get("trajectory")
        if trajectory:
            lines.append(
                f"\nTrajectory analysis: air arriving from the {trajectory['upwind_direction']} corridor"
                f" with {trajectory.get('fire_intersections', 0)} fire intersection(s)."
            )
        for lim in data.get("limitations", []):
            lines.append(f"\nNote: {lim}")
        return "\n".join(lines)

    if tool_name == "aq_compare_dates":
        direction = data.get("direction", "unknown")
        delta = data.get("delta_mean_pm25", 0)
        lines = [f"Based on station observations, conditions have {direction} by {delta} µg/m³.\n"]
        movers = data.get("biggest_movers", [])
        for m in movers:
            lines.append(f"- {m['city']}: {m['direction']} by {abs(m['delta'])} µg/m³")
        driver_exp = data.get("driver_explanation")
        if driver_exp:
            primary = driver_exp.get("primary", "unknown")
            lines.append(f"\nPrimary driver of change: {primary}")
            for key, val in driver_exp.items():
                if key != "primary" and "score" in key.lower():
                    lines.append(f"- {key}: {val}")
        return "\n".join(lines)

    if tool_name == "aq_incident_summary":
        incidents = data.get("incidents", [])
        lines = [f"Based on watchlist alerts and station observations, there are {data.get('total_incidents', len(incidents))} active incidents:\n"]
        for inc in incidents:
            lines.append(f"- **{inc['city']}** ({inc['station_name']}): {inc['type']} — {inc['severity']} ({inc['pm25']} µg/m³)")
        return "\n".join(lines)

    if tool_name == "aq_forecast_audit":
        metrics = data.get("metrics", {})
        lines = ["Based on forecast verification:\n"]
        lines.append(f"- MAE: {metrics.get('mae', 'N/A')} µg/m³")
        lines.append(f"- RMSE: {metrics.get('rmse', 'N/A')} µg/m³")
        lines.append(f"- Bias: {metrics.get('bias', 'N/A')} µg/m³")
        lines.append(f"- R²: {metrics.get('r_squared', 'N/A')}")
        lines.append(f"- F1@150: {metrics.get('f1_at_150', 'N/A')}")
        return "\n".join(lines)

    if tool_name == "aq_station_focus":
        if data.get("error") == "not_found":
            query = data.get("query", "that station")
            return (
                f"I couldn't find a station matching '{query}'. "
                "I don't have data for this station. It's not available in our network."
            )
        name = data.get("station_name", "Unknown")
        city = data.get("city", "")
        pm25 = data.get("current_pm25", "N/A")
        risk = data.get("risk_band", "unknown")
        lines = [f"Based on current observations, **{name}** ({city}) is reading {pm25} µg/m³ — rated **{risk}**.\n"]
        fc = data.get("forecast", {})
        for h, vals in fc.items():
            lines.append(f"- {h}: {vals['pm25_forecast']} µg/m³ ({vals['risk_band']})")
        return "\n".join(lines)

    if tool_name == "aq_station_history":
        hist = data.get("history", {})
        name = hist.get("station_name", "Unknown")
        trend = hist.get("trend", "stable")
        avg = hist.get("avg_pm25", "N/A")
        lines = [f"Based on station observations, **{name}** shows a {trend} trend with avg {avg} µg/m³.\n"]
        neighbours = data.get("neighbours", [])
        for n in neighbours:
            lines.append(f"- Nearby: {n['station_name']} at {n['pm25']} µg/m³ ({n['distance_km']} km)")
        return "\n".join(lines)

    if tool_name == "aq_data_coverage":
        entity = data.get("entity", "Unknown")
        earliest = data.get("earliest_reading", "")
        total = data.get("total_stations", 0)
        days = data.get("coverage_days", 0)
        year = earliest[:4] if earliest else "unknown"
        lines = [f"Based on the observations database, **{entity}** has {total} stations with data going back to {year} ({days} days of coverage, earliest reading: {earliest})."]
        return "\n".join(lines)

    if tool_name == "aq_satellite_image":
        status = data.get("status", "ok")
        if status == "no_suitable_scene":
            reason = data.get("reason", "No suitable scene found.")
            return f"I couldn't find a suitable Sentinel-2 scene. {reason}"
        mode = data.get("mode", "latest")
        if mode == "before_after":
            before = data.get("before", {})
            after = data.get("after", {})
            lines = ["Based on the Copernicus CDSE catalog, here are the before and after Sentinel-2 scenes:\n"]
            if before:
                lines.append(f"- **Before:** {before['acquisition_date']} (cloud cover: {before.get('cloud_cover', 'N/A')}%)")
                if before.get("preview_url"):
                    lines.append(f"  Preview: {before['preview_url']}")
            if after:
                lines.append(f"- **After:** {after['acquisition_date']} (cloud cover: {after.get('cloud_cover', 'N/A')}%)")
                if after.get("preview_url"):
                    lines.append(f"  Preview: {after['preview_url']}")
            return "\n".join(lines)
        scene = data.get("scene", {})
        lines = [f"Based on the Copernicus CDSE catalog, the {mode} Sentinel-2 L2A scene is:\n"]
        lines.append(f"- **Date:** {scene.get('acquisition_date', 'N/A')}")
        lines.append(f"- **Cloud cover:** {scene.get('cloud_cover', 'N/A')}%")
        if scene.get("preview_url"):
            lines.append(f"- **Preview:** {scene['preview_url']}")
        return "\n".join(lines)

    if tool_name == "aq_nearest_assets":
        anchor = data.get("anchor", {})
        radius = data.get("radius_m", 5000)
        assets = data.get("assets", [])
        status = data.get("status", "ok")
        if status == "no_results" or not assets:
            notes = data.get("notes", [])
            note_text = notes[0] if notes else "No assets found within the search radius."
            return f"I couldn't find any matching assets within {radius}m. {note_text}"
        counts = data.get("counts_by_type", {})
        lines = [f"Based on OpenStreetMap data, I found {len(assets)} assets within {radius}m of ({anchor.get('lat')}, {anchor.get('lon')}):\n"]
        for a in assets:
            admin = a.get("admin", {})
            district = admin.get("district", "")
            lines.append(f"- **{a['name']}** ({a['asset_type']}) — {a['distance_m']}m away, {district}")
        if counts:
            parts = [f"{v} {k}(s)" for k, v in counts.items()]
            lines.append(f"\nTotal: {', '.join(parts)}")
        return "\n".join(lines)

    return json.dumps(data, indent=2)


def update_fake_session(session: FakeSession, tool_name: str | None, mock_key: str) -> None:
    """Simulate _update_session() for Level A tests.

    Updates the FakeSession based on what the real tool would have done,
    using mock output data to derive the new state.
    """
    if tool_name is None:
        return  # No state change for text-only responses

    output = MOCK_OUTPUTS.get(mock_key, {})
    data = output.get("data", {})

    session.last_tool = tool_name

    if tool_name == "aq_hotspots_daily":
        session.focus_type = "national"
        hotspots = data.get("hotspots", [])
        session.last_entities = [h["name"] for h in hotspots[:5] if h.get("name")]

    elif tool_name == "aq_city_detail":
        session.focus_type = "city"
        city = data.get("city")
        if city:
            session.focused_city = city
            session.last_entities = [city]

    elif tool_name == "aq_explain_drivers":
        session.focus_type = "city"
        target = data.get("target")
        if target:
            session.focused_city = target
            session.last_entities = [target]

    elif tool_name == "aq_compare_dates":
        d1 = data.get("date1")
        if d1:
            session.comparison_date = d1
        movers = data.get("biggest_movers", [])
        session.last_entities = [m["city"] for m in movers if m.get("city")][:5]

    elif tool_name == "aq_incident_summary":
        incidents = data.get("incidents", [])
        session.last_entities = list(dict.fromkeys(
            i["city"] for i in incidents if i.get("city")
        ))[:5]

    elif tool_name == "aq_station_focus":
        if data.get("error") == "not_found":
            pass  # Station not found — don't update focus
        else:
            session.focus_type = "station"
            session.focused_station_id = data.get("station_id")
            session.focused_city = data.get("city")
            name = data.get("station_name")
            if name:
                session.last_entities = [name]

    elif tool_name == "aq_station_history":
        pass  # no state change — uses existing focus

    elif tool_name == "aq_data_coverage":
        entity = data.get("entity")
        session.focus_type = "city" if entity else "national"
        if entity:
            session.focused_city = entity
            session.last_entities = [entity]

    elif tool_name == "aq_forecast_audit":
        pass  # no focus change

    elif tool_name == "aq_nearest_assets":
        pass  # no focus change — spatial context, not entity focus

    elif tool_name == "aq_satellite_image":
        pass  # no focus change — imagery context


@pytest.fixture
def fake_session():
    """Return a fresh FakeSession."""
    return FakeSession()


@pytest.fixture
def mock_outputs():
    """Return the full mock outputs dict."""
    return MOCK_OUTPUTS
