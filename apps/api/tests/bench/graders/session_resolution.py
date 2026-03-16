"""Grader: did follow-up turn resolve 'it'/'there' to the focused entity?"""

from __future__ import annotations

from .base import GradeResult


def grade_session_resolution(
    tool_calls: list[dict],
    expect_tool: str,
    resolved_key: str,
    resolved_value: str,
) -> GradeResult:
    """Check that a follow-up tool call resolved a coreference correctly.

    Args:
        tool_calls: List of {"tool_name": str, "args": dict}.
        expect_tool: Which tool should have been called.
        resolved_key: The arg key that should contain the resolved entity
                      (e.g. "city_or_station", "city_name").
        resolved_value: The expected resolved value (case-insensitive).
    """
    matching = [tc for tc in tool_calls if tc["tool_name"] == expect_tool]
    if not matching:
        return GradeResult(
            grader="session_resolution",
            passed=False,
            detail=f"tool {expect_tool} was not called",
            expected=resolved_value,
            actual=None,
        )

    actual = matching[0]["args"].get(resolved_key)
    if actual is None:
        return GradeResult(
            grader="session_resolution",
            passed=False,
            detail=f"arg '{resolved_key}' not found in tool call",
            expected=resolved_value,
            actual=matching[0]["args"],
        )

    passed = str(actual).lower() == resolved_value.lower()
    return GradeResult(
        grader="session_resolution",
        passed=passed,
        detail=f"{resolved_key}={actual!r}",
        expected=resolved_value,
        actual=actual,
    )
