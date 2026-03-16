"""Grader: is entity ordering preserved in agent text?"""

from __future__ import annotations

from .base import GradeResult


def grade_ranking(
    agent_text: str,
    expected_order: list[str] | None,
) -> GradeResult:
    """Check that entities appear in the expected order in agent text.

    Args:
        agent_text: The full text response from the agent.
        expected_order: List of entity names that should appear in this order.
    """
    if not expected_order:
        return GradeResult(grader="ranking", passed=True, detail="no ranking check")

    text_lower = agent_text.lower()
    positions: list[tuple[str, int]] = []

    for entity in expected_order:
        pos = text_lower.find(entity.lower())
        if pos == -1:
            return GradeResult(
                grader="ranking",
                passed=False,
                detail=f"'{entity}' not found in text",
                expected=expected_order,
                actual=None,
            )
        positions.append((entity, pos))

    # Check monotonic ordering
    for i in range(len(positions) - 1):
        if positions[i][1] >= positions[i + 1][1]:
            actual_order = [name for name, _ in sorted(positions, key=lambda x: x[1])]
            return GradeResult(
                grader="ranking",
                passed=False,
                detail=f"'{positions[i][0]}' appears after '{positions[i+1][0]}'",
                expected=expected_order,
                actual=actual_order,
            )

    return GradeResult(
        grader="ranking",
        passed=True,
        detail=f"order correct: {[n for n, _ in positions]}",
        expected=expected_order,
        actual=[n for n, _ in positions],
    )
