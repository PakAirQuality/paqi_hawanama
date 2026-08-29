"""Multi-turn conversation replay tests.

Level A: scripted responses, verifies session state carries across turns.
Level B (live): real Gemini with mocked analytics.
"""

from __future__ import annotations

import os

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
MULTI_TURN_CASES = [c for c in CORE_CASES if len(c.get("turns", [])) > 1]


def _case_id(case: dict) -> str:
    return case["id"]


@pytest.mark.bench
@pytest.mark.parametrize(
    "case",
    MULTI_TURN_CASES,
    ids=[_case_id(c) for c in MULTI_TURN_CASES],
)
def test_session_multi_turn(case: dict):
    """Replay a multi-turn case, verifying session state propagation."""
    session = FakeSession(
        current_date=case.get("session", {}).get("current_date", "2026-03-06"),
    )

    for i, turn in enumerate(case["turns"]):
        expect_tool = turn.get("expect_tool")
        expect_args = turn.get("expect_args", {})
        mock_key = turn.get("mock_output_key", "")

        # For follow-up turns, inject resolved entity into args if session has it
        if i > 0 and turn.get("session_resolution"):
            res = turn["session_resolution"]
            key = res["resolved_key"]
            val = res["resolved_value"]
            expect_args = {**expect_args, key: val}

        messages = build_scripted_response(
            tool_name=expect_tool,
            tool_args=expect_args,
            mock_output_key=mock_key,
        )

        tool_calls = extract_tool_calls_from_messages(messages)
        agent_text = extract_text_from_messages(messages)

        # Update session state BEFORE grading (so session_state grader sees current state)
        update_fake_session(session, expect_tool, mock_key)

        # Grade with session
        result = grade_turn(turn, agent_text, tool_calls, turn_index=i, session=session)

        failures = [g for g in result.grades if not g.passed]
        if failures:
            details = "\n".join(
                f"  [{g.grader}] {g.detail}"
                for g in failures
            )
            pytest.fail(f"Case {case['id']} turn {i} failed:\n{details}")


# ---------------------------------------------------------------------------
# Level B: Live multi-turn with real Gemini
# ---------------------------------------------------------------------------

BENCH_MODEL = os.getenv("BENCH_MODEL", "gemini-2.5-flash")

_skip_no_key = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)


@pytest.mark.bench
@pytest.mark.live
@_skip_no_key
@pytest.mark.parametrize(
    "case",
    MULTI_TURN_CASES,
    ids=[_case_id(c) for c in MULTI_TURN_CASES],
)
async def test_session_multi_turn_live(case: dict):
    """Replay multi-turn case with real Gemini, mocked analytics."""
    from app.services.copilot.context import CopilotSession
    import app.services.copilot.agent as agent_mod

    # Fresh agent per test, with optional model override for quota management
    agent_mod._copilot_agent = None
    agent = agent_mod.get_agent(model_name=BENCH_MODEL)

    session = CopilotSession(
        session_id=f"bench-live-{case['id']}",
        current_date=case.get("session", {}).get("current_date", "2026-03-06"),
    )

    message_history = []
    for i, turn in enumerate(case["turns"]):
        result = await agent.run(
            turn["user_message"],
            deps=session,
            message_history=message_history,
        )

        all_msgs = result.all_messages()
        message_history = all_msgs
        tool_calls = extract_tool_calls_from_messages(all_msgs)
        agent_text = extract_text_from_messages(all_msgs)

        # Real session is updated by tool functions
        tr = grade_turn(turn, agent_text, tool_calls, turn_index=i, session=session)
        failures = [g for g in tr.grades if not g.passed]
        if failures:
            details = "\n".join(f"  [{g.grader}] {g.detail}" for g in failures)
            pytest.fail(
                f"[LIVE] Case {case['id']} turn {i} failed:\n{details}\n\nAgent text:\n{agent_text[:500]}"
            )
