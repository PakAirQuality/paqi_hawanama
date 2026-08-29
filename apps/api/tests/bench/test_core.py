"""Level A tests: parametrized from core_cases.json.

Fast, no LLM — uses scripted responses to verify grader logic and fixture wiring.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import FakeSession, build_scripted_response, update_fake_session
from .fixtures.tool_outputs import MOCK_OUTPUTS
from .runner import (
    extract_text_from_messages,
    extract_tool_calls_from_messages,
    grade_turn,
    load_cases,
)

CORE_CASES = load_cases("core_cases.json")

# Only single-turn cases for this file (multi-turn in test_session.py)
SINGLE_TURN_CASES = [c for c in CORE_CASES if len(c.get("turns", [])) == 1]


def _case_id(case: dict) -> str:
    return case["id"]


@pytest.mark.bench
@pytest.mark.parametrize("case", SINGLE_TURN_CASES, ids=[_case_id(c) for c in SINGLE_TURN_CASES])
def test_core_single_turn(case: dict):
    """Run a single-turn benchmark case with scripted agent responses."""
    turn = case["turns"][0]
    session = FakeSession(
        current_date=case.get("session", {}).get("current_date", "2026-03-06"),
    )

    expect_tool = turn.get("expect_tool")
    expect_args = turn.get("expect_args", {})
    mock_key = turn.get("mock_output_key", "")

    messages = build_scripted_response(
        tool_name=expect_tool,
        tool_args=expect_args if expect_tool else {},
        mock_output_key=mock_key,
    )

    tool_calls = extract_tool_calls_from_messages(messages)
    agent_text = extract_text_from_messages(messages)

    update_fake_session(session, expect_tool, mock_key)

    result = grade_turn(turn, agent_text, tool_calls, turn_index=0, session=session)

    failures = [g for g in result.grades if not g.passed]
    if failures:
        details = "\n".join(
            f"  [{g.grader}] {g.detail} (expected={g.expected}, actual={g.actual})"
            for g in failures
        )
        pytest.fail(f"Case {case['id']} failed:\n{details}")


# ---------------------------------------------------------------------------
# Level B: Live tests with real Gemini API
# ---------------------------------------------------------------------------

LIVE_CASES = [c for c in CORE_CASES if len(c.get("turns", [])) == 1]

# Model override: BENCH_MODEL env var lets you switch models for quota/cost.
# Default: gemini-2.5-flash (10K RPD). Set BENCH_MODEL=gemini-3.1-pro-preview
# for the production model (250 RPD, most capable).
BENCH_MODEL = os.getenv("BENCH_MODEL", "gemini-2.5-flash")

_skip_no_key = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)

# Map: expected tool name → analytics function(s) that the tool calls.
# Only the analytics function for the expected tool gets the case's mock output.
# All other analytics functions get a safe empty dict so they don't crash.
_TOOL_TO_ANALYTICS = {
    "aq_hotspots_daily": ["app.services.analytics.get_hotspots_daily"],
    "aq_city_detail": ["app.services.analytics.get_city_detail"],
    "aq_compare_dates": ["app.services.analytics.get_compare_dates"],
    "aq_explain_drivers": ["app.services.analytics.get_explain_drivers"],
    "aq_incident_summary": ["app.services.analytics.get_incident_summary"],
    "aq_forecast_audit": ["app.services.analytics.get_forecast_audit"],
    "aq_station_focus": [
        "app.services.analytics._resolve_station",
        "app.services.analytics._load_forecast_safe",
    ],
    "aq_station_history": [
        "app.services.analytics.get_station_history",
        "app.services.analytics.get_station_neighbours",
    ],
    "aq_data_coverage": ["app.services.analytics.get_data_coverage"],
    "aq_nearest_assets": ["app.services.spatial.get_nearest_assets"],
    "aq_satellite_image": ["app.services.spatial.get_sentinel_catalog"],
}

_ALL_ANALYTICS_TARGETS = [
    "app.services.analytics.get_hotspots_daily",
    "app.services.analytics.get_city_detail",
    "app.services.analytics.get_compare_dates",
    "app.services.analytics.get_explain_drivers",
    "app.services.analytics.get_incident_summary",
    "app.services.analytics.get_forecast_audit",
    "app.services.analytics._resolve_station",
    "app.services.analytics.get_station_history",
    "app.services.analytics.get_station_neighbours",
    "app.services.analytics.get_data_coverage",
    "app.services.analytics._load_forecast_safe",
    "app.services.analytics._safe_round",
    "app.services.spatial.get_nearest_assets",
    "app.services.spatial.get_sentinel_catalog",
]


def _build_station_focus_patches(mock_output: dict) -> dict[str, Any]:
    """Build per-function mocks for aq_station_focus.

    _resolve_station expects a flat dict: {station_id, station_name, city_name, lat, lon}
    _load_forecast_safe expects a dict with "forecasts" list
    """
    data = mock_output.get("data", {})
    resolve_result = {
        "station_id": data.get("station_id", "a1b2c3d4e5f60001"),
        "station_name": data.get("station_name", ""),
        "city_name": data.get("city", ""),
        "lat": 31.56,
        "lon": 74.35,
    }
    # Build forecast entries from the tool envelope
    fc = data.get("forecast", {})
    forecast_entries = []
    for horizon, vals in fc.items():
        ld = int(horizon.replace("D+", "")) if "D+" in horizon else 1
        forecast_entries.append({
            "lead_days": ld,
            "station_id": data.get("station_id", ""),
            "station_name": data.get("station_name", ""),
            "pm25_forecast": vals.get("pm25_forecast"),
            "pm25_q90": vals.get("pm25_q90"),
            "risk_band": vals.get("risk_band"),
            "ramp_detected": vals.get("ramp_detected", False),
            "episode_state": data.get("episode_state", "stable"),
            "confidence": data.get("confidence", "medium"),
            "priority": data.get("priority", "monitor"),
        })
    load_forecast_result = {"forecasts": forecast_entries}
    return {
        "app.services.analytics._resolve_station": resolve_result,
        "app.services.analytics._load_forecast_safe": load_forecast_result,
    }


def _start_live_patches(mock_output: dict, expect_tool: str | None = None) -> list:
    """Patch DB session + analytics functions for Level B tests.

    When expect_tool is provided, only the analytics functions for that tool
    receive the case's mock output. All other functions get a safe empty dict.
    This prevents mock data leaking across tool boundaries.

    For aq_station_focus, internal functions get correctly shaped mocks
    (flat station dict for _resolve_station, forecast dict for _load_forecast_safe).

    Returns list of started patches (caller must stop them).
    """
    mock_db = AsyncMock()
    mock_db.close = AsyncMock()

    patches = [
        patch("app.services.copilot.tools._get_db", new=AsyncMock(return_value=mock_db)),
        patch("app.services.copilot.tools._resolve_latest_date", return_value="2026-03-06"),
    ]

    # Determine which analytics targets get the real mock output
    hot_targets = set()
    if expect_tool:
        hot_targets = set(_TOOL_TO_ANALYTICS.get(expect_tool, []))

    # For station_focus, build per-function mocks with correct shapes
    station_focus_overrides: dict[str, Any] = {}
    if expect_tool == "aq_station_focus":
        station_focus_overrides = _build_station_focus_patches(mock_output)

    for target in _ALL_ANALYTICS_TARGETS:
        try:
            if target in station_focus_overrides:
                patches.append(patch(target, new=AsyncMock(
                    return_value=station_focus_overrides[target]
                )))
            elif target in hot_targets:
                patches.append(patch(target, new=AsyncMock(return_value=mock_output)))
            else:
                patches.append(patch(target, new=AsyncMock(return_value={"data": {}})))
        except (ModuleNotFoundError, AttributeError):
            pass

    for p in patches:
        p.start()
    return patches


@pytest.mark.bench
@pytest.mark.live
@_skip_no_key
@pytest.mark.parametrize("case", LIVE_CASES, ids=[_case_id(c) for c in LIVE_CASES])
async def test_core_live(case: dict):
    """Run a single-turn case with real Gemini API (mock analytics only)."""
    from app.services.copilot.context import CopilotSession
    import app.services.copilot.agent as agent_mod

    turn = case["turns"][0]
    mock_key = turn.get("mock_output_key", "")
    expect_tool = turn.get("expect_tool")
    mock_output = MOCK_OUTPUTS.get(mock_key, {"data": {}})

    patches = _start_live_patches(mock_output, expect_tool=expect_tool)

    try:
        # Fresh agent per test, with optional model override for quota management
        agent_mod._copilot_agent = None
        agent = agent_mod.get_agent(model_name=BENCH_MODEL)

        session = CopilotSession(
            session_id=f"bench-live-{case['id']}",
            current_date=case.get("session", {}).get("current_date", "2026-03-06"),
        )

        result = await agent.run(
            turn["user_message"],
            deps=session,
        )

        all_msgs = result.all_messages()
        tool_calls = extract_tool_calls_from_messages(all_msgs)
        agent_text = extract_text_from_messages(all_msgs)

        tr = grade_turn(turn, agent_text, tool_calls, turn_index=0, session=session)
        failures = [g for g in tr.grades if not g.passed]
        if failures:
            details = "\n".join(
                f"  [{g.grader}] {g.detail}"
                for g in failures
            )
            pytest.fail(f"[LIVE] Case {case['id']} failed:\n{details}\n\nAgent text:\n{agent_text[:500]}")
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            pytest.skip(f"httpx event loop teardown: {e}")
        raise
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# Aggregate threshold check
# ---------------------------------------------------------------------------

@pytest.mark.bench
@pytest.mark.live
@_skip_no_key
def test_live_thresholds_placeholder():
    """Confirms the thresholds module loads correctly."""
    from .thresholds import TIER_THRESHOLDS, GRADER_THRESHOLDS
    assert len(TIER_THRESHOLDS) == 4
    assert len(GRADER_THRESHOLDS) == 10
