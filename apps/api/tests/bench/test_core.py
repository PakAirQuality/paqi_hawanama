"""Level A tests: parametrized from core_cases.json.

Fast, no LLM — uses scripted responses to verify grader logic and fixture wiring.
"""

from __future__ import annotations

import os
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

# Analytics functions that tools import lazily
_ANALYTICS_TARGETS = [
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
]


def _start_live_patches(mock_output: dict) -> list:
    """Patch DB session + all analytics functions for Level B tests.

    Returns list of started patches (caller must stop them).
    """
    mock_db = AsyncMock()
    mock_db.close = AsyncMock()

    patches = [
        patch("app.services.copilot.tools._get_db", new=AsyncMock(return_value=mock_db)),
        # _resolve_latest_date is imported at module level by tools.py
        patch("app.services.copilot.tools._resolve_latest_date", return_value="2026-03-06"),
    ]

    for target in _ANALYTICS_TARGETS:
        try:
            patches.append(patch(target, new=AsyncMock(return_value=mock_output)))
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
    mock_output = MOCK_OUTPUTS.get(mock_key, {"data": {}})

    patches = _start_live_patches(mock_output)

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
    assert len(GRADER_THRESHOLDS) == 9
