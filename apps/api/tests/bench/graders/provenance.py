"""Grader: correct source attribution (observations vs forecast)?"""

from __future__ import annotations

from .base import GradeResult


def grade_provenance(
    agent_text: str,
    must_say: list[str] | None = None,
    must_not_say: list[str] | None = None,
) -> GradeResult:
    """Check case-insensitive substring presence/absence in agent text.

    Args:
        agent_text: The full text response from the agent.
        must_say: Phrases that must appear (case-insensitive).
        must_not_say: Phrases that must NOT appear (case-insensitive).
    """
    text_lower = agent_text.lower()
    failures: list[str] = []

    if must_say:
        for phrase in must_say:
            if phrase.lower() not in text_lower:
                failures.append(f"missing required phrase: '{phrase}'")

    if must_not_say:
        for phrase in must_not_say:
            if phrase.lower() in text_lower:
                failures.append(f"forbidden phrase found: '{phrase}'")

    passed = len(failures) == 0
    return GradeResult(
        grader="provenance",
        passed=passed,
        detail="; ".join(failures) if failures else "provenance correct",
        expected={"must_say": must_say, "must_not_say": must_not_say},
    )
