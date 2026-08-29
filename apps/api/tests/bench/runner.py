"""Bench runner — loads JSON cases, replays turns through the agent, applies graders."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .graders import (
    GradeResult,
    grade_tool_choice,
    grade_tool_args,
    grade_numeric_accuracy,
    grade_ranking,
    grade_provenance,
    grade_session_resolution,
    grade_tool_call_count,
    grade_session_state,
    grade_abstention,
    grade_spatial,
)
from .fixtures.tool_outputs import MOCK_OUTPUTS

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_cases(path: Path | str) -> list[dict]:
    """Load benchmark cases from a JSON file."""
    p = Path(path)
    if not p.is_absolute():
        p = FIXTURES_DIR / p
    data = json.loads(p.read_text())
    return data.get("cases", [])


@dataclass
class TurnResult:
    """Result of a single conversation turn."""

    turn_index: int
    user_message: str
    agent_text: str
    tool_calls: list[dict]  # [{"tool_name": str, "args": dict}]
    grades: list[GradeResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.grades)


@dataclass
class CaseResult:
    """Result of running a full benchmark case."""

    case_id: str
    category: str
    tier: str
    description: str
    turns: list[TurnResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.turns)

    @property
    def all_grades(self) -> list[GradeResult]:
        return [g for t in self.turns for g in t.grades]


def grade_turn(
    turn_spec: dict,
    agent_text: str,
    tool_calls: list[dict],
    turn_index: int,
    session: object | None = None,
) -> TurnResult:
    """Apply all relevant graders to a single turn.

    Args:
        turn_spec: Turn definition from the case JSON.
        agent_text: Full text response from the agent.
        tool_calls: Extracted tool calls from agent messages.
        turn_index: 0-based turn index.
        session: Optional session object for session_state grading.
    """
    tr = TurnResult(
        turn_index=turn_index,
        user_message=turn_spec.get("user_message", ""),
        agent_text=agent_text,
        tool_calls=tool_calls,
    )

    expect_tool = turn_spec.get("expect_tool")
    expect_args = turn_spec.get("expect_args")
    expect_args_absent = turn_spec.get("expect_args_absent")
    assertions = turn_spec.get("assertions", {})

    # Tool choice
    if expect_tool:
        tr.grades.append(grade_tool_choice(tool_calls, expect_tool))

    # Tool args
    if expect_tool and (expect_args or expect_args_absent):
        tr.grades.append(
            grade_tool_args(tool_calls, expect_tool, expect_args, expect_args_absent)
        )

    # Tool call count
    max_calls = turn_spec.get("max_tool_calls")
    if max_calls is not None:
        tr.grades.append(grade_tool_call_count(tool_calls, max_calls))

    # Numeric accuracy
    numeric_checks = assertions.get("numeric_checks")
    if numeric_checks:
        tr.grades.append(grade_numeric_accuracy(agent_text, numeric_checks))

    # Ranking
    ranking_check = assertions.get("ranking_check")
    if ranking_check:
        tr.grades.append(grade_ranking(agent_text, ranking_check.get("expected_order")))

    # Provenance
    prov = assertions.get("provenance_check")
    if prov:
        tr.grades.append(
            grade_provenance(agent_text, prov.get("must_say"), prov.get("must_not_say"))
        )

    # Text must contain / must not contain (simple substring checks)
    must_contain = assertions.get("text_must_contain", [])
    must_not_contain = assertions.get("text_must_not_contain", [])
    if must_contain or must_not_contain:
        tr.grades.append(
            grade_provenance(agent_text, must_contain, must_not_contain)
        )

    # Abstention
    abstention = assertions.get("abstention_check")
    if abstention:
        tr.grades.append(
            grade_abstention(
                agent_text,
                tool_calls,
                must_refuse=abstention.get("must_refuse", False),
                forbidden_claims=abstention.get("forbidden_claims"),
            )
        )

    # Spatial checks (validate mock output properties)
    spatial = assertions.get("spatial_checks")
    if spatial:
        mock_key = turn_spec.get("mock_output_key", "")
        mock_output = MOCK_OUTPUTS.get(mock_key, {"data": {}})
        tr.grades.append(
            grade_spatial(
                mock_output,
                max_distance_m=spatial.get("max_distance_m"),
                min_assets=spatial.get("min_assets"),
                allowed_types=spatial.get("allowed_types"),
                distances_monotonic=spatial.get("distances_monotonic", False),
            )
        )

    # Session resolution
    sess_res = turn_spec.get("session_resolution")
    if sess_res and expect_tool:
        tr.grades.append(
            grade_session_resolution(
                tool_calls,
                expect_tool,
                sess_res["resolved_key"],
                sess_res["resolved_value"],
            )
        )

    # Session state checks (post-turn)
    if session is not None:
        exp_ft = turn_spec.get("expected_focus_type_after_turn")
        exp_ent = turn_spec.get("expected_entities_after_turn")
        if exp_ft is not None or exp_ent is not None:
            tr.grades.append(grade_session_state(session, exp_ft, exp_ent))

    return tr


def _is_model_response(msg: Any) -> bool:
    """Check if a message is a model response (not a request/system/user)."""
    # PydanticAI messages: ModelResponse.kind == "response"
    kind = getattr(msg, "kind", None)
    if kind == "response":
        return True
    # Our FakeModelResponse
    role = getattr(msg, "role", None)
    if role == "model-response":
        return True
    return False


def extract_tool_calls_from_messages(messages: list[Any]) -> list[dict]:
    """Extract tool calls from model response messages only.

    Skips system prompts, user messages, and tool-result messages.
    Works with both real PydanticAI messages and our scripted format.
    """
    tool_calls = []
    for msg in messages:
        if not _is_model_response(msg):
            continue
        if hasattr(msg, "parts"):
            for part in msg.parts:
                if hasattr(part, "tool_name"):
                    args = part.args if hasattr(part, "args") else {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    tool_calls.append({
                        "tool_name": part.tool_name,
                        "args": args if isinstance(args, dict) else {},
                    })
        # Dict format (from scripted/mock results)
        elif isinstance(msg, dict) and msg.get("tool_name"):
            tool_calls.append(msg)
    return tool_calls


def extract_text_from_messages(messages: list[Any]) -> str:
    """Extract text content from model response messages only.

    Skips system prompts, user messages, and tool-result messages
    to avoid grading the system prompt or user input as agent output.
    """
    texts = []
    for msg in messages:
        if not _is_model_response(msg):
            continue
        if hasattr(msg, "parts"):
            for part in msg.parts:
                if hasattr(part, "content") and isinstance(part.content, str):
                    texts.append(part.content)
        elif isinstance(msg, dict) and "content" in msg:
            texts.append(msg["content"])
    return "\n".join(texts)
