"""Grader: correct abstention / refusal when data doesn't support claims."""

from __future__ import annotations

from .base import GradeResult

HEDGE_PHRASES = [
    "not available",
    "cannot determine",
    "i don't have",
    "i do not have",
    "no data",
    "unable to",
    "don't have access",
    "do not have access",
    "no tool",
    "cannot provide",
    "not supported",
    "outside my capabilities",
    "i can't",
    "i cannot",
    "not possible",
    "beyond what",
    "couldn't find",
    "could not find",
    "not found",
    "don't have the",
    "do not have the",
    "no way to",
    "not equipped",
]


def grade_abstention(
    agent_text: str,
    tool_calls: list[dict],
    must_refuse: bool,
    forbidden_claims: list[str] | None = None,
) -> GradeResult:
    """Check that the model hedges/refuses when appropriate.

    Args:
        agent_text: The full text response from the agent.
        tool_calls: List of tool calls made (for future use).
        must_refuse: If True, text must contain hedging/refusal language.
        forbidden_claims: Case-insensitive substrings that must NOT appear in text.
    """
    text_lower = agent_text.lower()
    failures: list[str] = []

    if must_refuse:
        has_hedge = any(phrase in text_lower for phrase in HEDGE_PHRASES)
        if not has_hedge:
            failures.append(
                f"expected refusal/hedge language but found none "
                f"(checked {len(HEDGE_PHRASES)} phrases)"
            )

    if forbidden_claims:
        for claim in forbidden_claims:
            if claim.lower() in text_lower:
                failures.append(f"forbidden claim found: '{claim}'")

    passed = len(failures) == 0
    return GradeResult(
        grader="abstention",
        passed=passed,
        detail="; ".join(failures) if failures else "abstention correct",
        expected={"must_refuse": must_refuse, "forbidden_claims": forbidden_claims},
    )
