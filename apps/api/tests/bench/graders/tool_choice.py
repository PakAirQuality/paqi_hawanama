"""Grader: did the agent select the correct tool?"""

from __future__ import annotations

from .base import GradeResult


def grade_tool_choice(
    tool_calls: list[dict],
    expect_tool: str | None,
) -> GradeResult:
    """Check whether the expected tool was called.

    Args:
        tool_calls: List of dicts with at least {"tool_name": str, "args": dict}.
        expect_tool: The tool name that should have been called, or None to skip.
    """
    if expect_tool is None:
        return GradeResult(grader="tool_choice", passed=True, detail="no tool expectation")

    called_names = [tc["tool_name"] for tc in tool_calls]
    passed = expect_tool in called_names
    return GradeResult(
        grader="tool_choice",
        passed=passed,
        detail=f"called: {called_names}",
        expected=expect_tool,
        actual=called_names,
    )
