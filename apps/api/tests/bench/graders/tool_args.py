"""Grader: were the correct arguments passed to the tool?"""

from __future__ import annotations

from .base import GradeResult


def _normalize(value: object) -> object:
    """Lowercase strings for case-insensitive comparison."""
    if isinstance(value, str):
        return value.lower()
    return value


def grade_tool_args(
    tool_calls: list[dict],
    expect_tool: str,
    expect_args: dict | None = None,
    expect_args_absent: list[str] | None = None,
) -> GradeResult:
    """Check partial key match and absence for the target tool's arguments.

    Args:
        tool_calls: List of {"tool_name": str, "args": dict}.
        expect_tool: Which tool call to inspect.
        expect_args: Keys/values that must appear (case-insensitive for strings).
        expect_args_absent: Keys that must NOT appear.
    """
    matching = [tc for tc in tool_calls if tc["tool_name"] == expect_tool]
    if not matching:
        return GradeResult(
            grader="tool_args",
            passed=False,
            detail=f"tool {expect_tool} was not called",
            expected=expect_args,
            actual=None,
        )

    actual_args = matching[0]["args"]
    failures: list[str] = []

    # Partial key match
    if expect_args:
        for key, expected_val in expect_args.items():
            actual_val = actual_args.get(key)
            if _normalize(actual_val) != _normalize(expected_val):
                failures.append(f"{key}: expected={expected_val!r}, got={actual_val!r}")

    # Absence check
    if expect_args_absent:
        for key in expect_args_absent:
            if key in actual_args and actual_args[key] is not None:
                failures.append(f"{key} should be absent but got {actual_args[key]!r}")

    passed = len(failures) == 0
    return GradeResult(
        grader="tool_args",
        passed=passed,
        detail="; ".join(failures) if failures else "all args match",
        expected=expect_args,
        actual=actual_args,
    )
