"""Grader: do PM2.5 values in agent text match tool output?"""

from __future__ import annotations

import re

from .base import GradeResult


_NUMBER_RE = re.compile(r"[\d,]+\.?\d*")


def _extract_numbers(text: str) -> list[float]:
    """Pull all numbers from text."""
    nums = []
    for m in _NUMBER_RE.finditer(text):
        try:
            nums.append(float(m.group().replace(",", "")))
        except ValueError:
            pass
    return nums


def grade_numeric_accuracy(
    agent_text: str,
    checks: list[dict],
) -> GradeResult:
    """Verify numeric values in agent text match expected values within tolerance.

    Args:
        agent_text: The full text response from the agent.
        checks: List of {"label": str, "expected": float, "tolerance": float}.
    """
    if not checks:
        return GradeResult(grader="numeric_accuracy", passed=True, detail="no checks")

    numbers_in_text = _extract_numbers(agent_text)
    failures: list[str] = []

    for check in checks:
        expected = check["expected"]
        tolerance = check.get("tolerance", 1.0)
        label = check.get("label", str(expected))

        # Find the closest number in text to the expected value
        if not numbers_in_text:
            failures.append(f"{label}: no numbers found in text")
            continue

        closest = min(numbers_in_text, key=lambda n: abs(n - expected))
        if abs(closest - expected) > tolerance:
            failures.append(
                f"{label}: expected ~{expected} (±{tolerance}), closest in text was {closest}"
            )

    passed = len(failures) == 0
    return GradeResult(
        grader="numeric_accuracy",
        passed=passed,
        detail="; ".join(failures) if failures else f"all {len(checks)} checks passed",
        expected=[c["expected"] for c in checks],
        actual=numbers_in_text[:10],
    )
