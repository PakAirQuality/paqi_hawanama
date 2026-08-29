"""Base types for benchmark grading."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GradeResult:
    """Result of a single grader evaluation."""

    grader: str
    passed: bool
    detail: str = ""
    expected: Any = None
    actual: Any = None
    extras: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.passed
