"""Grader: did the agent stay within the tool-call budget?"""

from __future__ import annotations

from .base import GradeResult


def grade_tool_call_count(
    tool_calls: list[dict],
    max_tool_calls: int | None,
) -> GradeResult:
    """Check that the number of tool calls does not exceed the budget.

    Args:
        tool_calls: List of {"tool_name": str, "args": dict}.
        max_tool_calls: Maximum allowed tool calls, or None to skip.
    """
    if max_tool_calls is None:
        return GradeResult(grader="tool_call_count", passed=True, detail="no limit set")

    actual = len(tool_calls)
    passed = actual <= max_tool_calls
    return GradeResult(
        grader="tool_call_count",
        passed=passed,
        detail=f"{actual} calls (max {max_tool_calls})",
        expected=max_tool_calls,
        actual=actual,
    )
