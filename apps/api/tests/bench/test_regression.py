"""Level A tests: parametrized from regression_cases.json.

Same mechanics as test_core.py but loaded from the growing regression file.
Cases are added via langfuse_sync.py or manually.
"""

from __future__ import annotations

import pytest

from .conftest import FakeSession, build_scripted_response, update_fake_session
from .runner import (
    extract_text_from_messages,
    extract_tool_calls_from_messages,
    grade_turn,
    load_cases,
)

REGRESSION_CASES = load_cases("regression_cases.json")
SINGLE_TURN = [c for c in REGRESSION_CASES if len(c.get("turns", [])) == 1]
MULTI_TURN = [c for c in REGRESSION_CASES if len(c.get("turns", [])) > 1]


def _case_id(case: dict) -> str:
    return case["id"]


@pytest.mark.bench
@pytest.mark.parametrize(
    "case",
    SINGLE_TURN,
    ids=[_case_id(c) for c in SINGLE_TURN],
)
def test_regression_single_turn(case: dict):
    """Run a single-turn regression case with scripted responses."""
    turn = case["turns"][0]
    session = FakeSession(
        current_date=case.get("session", {}).get("current_date", "2026-03-06"),
    )

    expect_tool = turn.get("expect_tool", "aq_hotspots_daily")
    expect_args = turn.get("expect_args", {})
    mock_key = turn.get("mock_output_key", "")

    messages = build_scripted_response(
        tool_name=expect_tool,
        tool_args=expect_args,
        mock_output_key=mock_key,
    )

    tool_calls = extract_tool_calls_from_messages(messages)
    agent_text = extract_text_from_messages(messages)

    update_fake_session(session, expect_tool, mock_key)

    result = grade_turn(turn, agent_text, tool_calls, turn_index=0, session=session)

    failures = [g for g in result.grades if not g.passed]
    if failures:
        details = "\n".join(
            f"  [{g.grader}] {g.detail}"
            for g in failures
        )
        pytest.fail(f"Regression case {case['id']} failed:\n{details}")


@pytest.mark.bench
@pytest.mark.parametrize(
    "case",
    MULTI_TURN,
    ids=[_case_id(c) for c in MULTI_TURN],
)
def test_regression_multi_turn(case: dict):
    """Run a multi-turn regression case."""
    session = FakeSession(
        current_date=case.get("session", {}).get("current_date", "2026-03-06"),
    )

    for i, turn in enumerate(case["turns"]):
        expect_tool = turn.get("expect_tool")
        expect_args = turn.get("expect_args", {})
        mock_key = turn.get("mock_output_key", "")

        messages = build_scripted_response(
            tool_name=expect_tool,
            tool_args=expect_args,
            mock_output_key=mock_key,
        )

        tool_calls = extract_tool_calls_from_messages(messages)
        agent_text = extract_text_from_messages(messages)

        update_fake_session(session, expect_tool, mock_key)

        result = grade_turn(turn, agent_text, tool_calls, turn_index=i, session=session)

        failures = [g for g in result.grades if not g.passed]
        if failures:
            details = "\n".join(
                f"  [{g.grader}] {g.detail}"
                for g in failures
            )
            pytest.fail(f"Regression case {case['id']} turn {i} failed:\n{details}")
