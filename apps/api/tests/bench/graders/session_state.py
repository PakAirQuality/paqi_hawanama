"""Grader: did the turn leave session state in the expected shape?"""

from __future__ import annotations

from .base import GradeResult


def grade_session_state(
    session: object,
    expected_focus_type: str | None = None,
    expected_entities: list[str] | None = None,
) -> GradeResult:
    """Check session state after a turn completes.

    Args:
        session: FakeSession or CopilotSession with .focus_type, .last_entities, etc.
        expected_focus_type: Expected focus_type (e.g. "city", "station", "national").
        expected_entities: List of entity names that should be in last_entities.
    """
    failures: list[str] = []

    if expected_focus_type is not None:
        actual_ft = getattr(session, "focus_type", None)
        if actual_ft != expected_focus_type:
            failures.append(f"focus_type: expected={expected_focus_type!r}, got={actual_ft!r}")

    if expected_entities is not None:
        actual_ent = getattr(session, "last_entities", []) or []
        # Check that all expected entities appear (order-independent, case-insensitive)
        actual_lower = {e.lower() for e in actual_ent}
        for ent in expected_entities:
            if ent.lower() not in actual_lower:
                failures.append(f"entity '{ent}' not in last_entities={actual_ent}")

    passed = len(failures) == 0
    return GradeResult(
        grader="session_state",
        passed=passed,
        detail="; ".join(failures) if failures else "session state correct",
        expected={"focus_type": expected_focus_type, "entities": expected_entities},
        actual={
            "focus_type": getattr(session, "focus_type", None),
            "last_entities": getattr(session, "last_entities", []),
        },
    )
