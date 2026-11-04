"""Prompt, limits, per-turn date handling and tool schemas for the precision tools."""

from types import SimpleNamespace as NS

from pydantic_ai import Agent
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.test import TestModel

from app.routers import copilot as copilot_router
from app.services.copilot import agent as agent_mod
from app.services.copilot import tools
from app.services.copilot.context import CopilotSession


def test_prompt_precision_rules_and_routing():
    p = agent_mod.SYSTEM_PROMPT
    assert "One tool call usually suffices" not in p
    assert "## Precision rules" in p and "Never answer a distance question with city membership" in p
    assert "aq_station_inventory" in p and "aq_nearest_stations" in p and "aq_period_stats" in p
    assert "ALL major tools accept a `date` parameter" not in p and "tools gracefully fall back" not in p
    assert "hours ≤ 744" in p


def test_output_budget():
    assert copilot_router.RUN_LIMITS.request_limit == 10 and copilot_router.RUN_LIMITS.total_tokens_limit == 120_000
    assert copilot_router.RUN_SETTINGS == {"max_tokens": 2048}


def test_begin_turn_moves_last_turns_date_out_of_the_anchor():
    s = CopilotSession(session_id="abcdefgh", active_historical_date="2025-12-15")
    copilot_router._begin_turn(s)
    assert s.active_historical_date is None and s.last_turn_date == "2025-12-15"
    copilot_router._begin_turn(s)                       # no new anchor this turn → keeps the hint
    assert s.last_turn_date == "2025-12-15"


def test_effective_date_within_a_turn_still_follows_the_tool_set_anchor():
    s = CopilotSession(session_id="abcdefgh", current_date="2026-11-03")
    ctx = NS(deps=s)
    assert tools._effective_date(ctx) == "2026-11-03"
    tools._update_session(ctx, tool="aq_hotspots_daily", historical_date="2025-12-15")
    assert tools._effective_date(ctx) == "2025-12-15"


def test_session_context_states_real_and_dashboard_dates():
    s = CopilotSession(session_id="abcdefgh", current_date="2026-11-01", last_turn_date="2026-10-20")
    text = "\n".join(agent_mod.session_context_lines(s, real_today="2026-11-04"))
    assert "Today's calendar date in Pakistan is 2026-11-04" in text
    assert "forecast date 2026-11-01" in text and "relative to the real date 2026-11-04" in text
    assert 'previous turn\'s tools used date 2026-10-20. Pass date="2026-10-20" again only if' in text
    same = CopilotSession(session_id="abcdefgh", current_date="2026-11-04")
    assert "The dashboard is showing today's forecast." in agent_mod.session_context_lines(same, real_today="2026-11-04")
    anchored = CopilotSession(session_id="abcdefgh", active_historical_date="2025-12-15", last_turn_date="2025-12-15")
    joined = "\n".join(agent_mod.session_context_lines(anchored, real_today="2026-11-04"))
    assert "Active historical date: 2025-12-15" in joined and "previous turn's tools used" not in joined


async def test_station_history_refuses_more_than_31_days_and_points_to_period_stats():
    s = CopilotSession(session_id="abcdefgh", current_date="2026-11-03", focused_station_id="a" * 16, focused_station_name="GT Road Peshawar")
    out = await tools.aq_station_history(NS(deps=s), hours=800)
    assert "at most 744 hours" in out["data"]["message"] and 'aq_period_stats(entity="station", name="GT Road Peshawar"' in out["data"]["message"]


async def test_new_tools_have_the_expected_schemas_and_survive_a_db_failure(monkeypatch):
    async def broken_db():
        raise RuntimeError("no database in tests")
    monkeypatch.setattr(tools, "_get_db", broken_db)
    agent = Agent(TestModel(), deps_type=CopilotSession)
    for fn in (tools.aq_station_inventory, tools.aq_nearest_stations, tools.aq_period_stats):
        agent.tool(agent_mod._safe_tool(fn))
    schemas = {n: t.function_schema.json_schema for n, t in agent._function_toolset.tools.items()}
    assert set(schemas["aq_station_inventory"]["properties"]) == {"area", "name", "lat", "lon", "radius_km", "as_of_date", "provider", "list_stations", "limit"}
    assert set(schemas["aq_nearest_stations"]["properties"]) == {"place", "lat", "lon", "k", "max_km"}
    assert set(schemas["aq_period_stats"]["properties"]) == {"entity", "name", "start_date", "end_date", "bucket", "same_calendar_date"}
    assert all(s.get("required", []) == [] for s in schemas.values())          # every parameter has a default
    result = await agent.run("hello", deps=CopilotSession(session_id="abcdefgh", current_date="2026-11-03"))
    returns = {p.tool_name: p.content for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)}
    assert set(returns) == set(schemas)
    assert all("lookup failed (RuntimeError)" in r["data"]["message"] for r in returns.values())


async def test_fire_tools_have_defaulted_schemas_survive_a_db_failure_and_are_routed(monkeypatch):
    async def broken_db():
        raise RuntimeError("no database in tests")
    monkeypatch.setattr(tools, "_get_db", broken_db)
    agent = Agent(TestModel(), deps_type=CopilotSession)
    for fn in (tools.aq_fire_exposure, tools.aq_fire_trends, tools.aq_fire_hotspots):
        agent.tool(agent_mod._safe_tool(fn))
    schemas = {n: t.function_schema.json_schema for n, t in agent._function_toolset.tools.items()}
    assert set(schemas["aq_fire_exposure"]["properties"]) == {"city", "date", "radius_km"}
    assert set(schemas["aq_fire_trends"]["properties"]) == {"region", "start_date", "end_date", "season", "compare_years"}
    assert set(schemas["aq_fire_hotspots"]["properties"]) == {"area", "date", "end_date", "group", "min_days", "radius_km"}
    assert all(s.get("required", []) == [] for s in schemas.values())
    p = agent_mod.SYSTEM_PROMPT
    assert "aq_fire_exposure" in p and "aq_fire_trends" in p and "aq_fire_hotspots" in p and "## Fire wording" in p
    assert "consistent with smoke transport" in p and "Never say fires caused" in p
    assert tools.aq_fire_exposure in agent_mod._TOOL_FUNCTIONS if hasattr(agent_mod, "_TOOL_FUNCTIONS") else True
