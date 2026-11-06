"""The SSE stream tells the user why a turn stopped: too much data vs an internal error."""

import json

from pydantic_ai.exceptions import UsageLimitExceeded

from app.routers import copilot


def _events(chunks):
    out = []
    for c in chunks:
        for line in c.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


async def _collect(monkeypatch, exc):
    monkeypatch.setattr(copilot, "get_agent", lambda *a, **k: object())

    async def run_one(agent):
        yield copilot._sse_event({"type": "text", "content": "partial"})
        raise exc

    return _events([c async for c in copilot._stream_with_fallback(run_one, "203.0.113.9", "copilot chat")])


async def test_usage_limit_gets_a_narrowing_message(monkeypatch, caplog):
    events = await _collect(monkeypatch, UsageLimitExceeded("Exceeded the total_tokens_limit of 120000"))
    assert events[-2:] == [{"type": "error", "content": copilot.TOO_MUCH_DATA_MSG}, {"type": "done"}]
    assert "Traceback" not in caplog.text


async def test_other_errors_keep_the_generic_message(monkeypatch):
    events = await _collect(monkeypatch, RuntimeError("boom"))
    assert events[-2:] == [{"type": "error", "content": "An internal error occurred."}, {"type": "done"}]


def test_per_turn_token_cap_is_well_under_the_daily_budget():
    from app.core.config import settings
    assert copilot.RUN_LIMITS.total_tokens_limit == 120_000
    assert copilot.RUN_LIMITS.total_tokens_limit * 10 <= settings.COPILOT_GLOBAL_DAILY_TOKENS


def test_trajectory_action_comes_from_this_turns_tool_return():
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolReturnPart, UserPromptPart
    doc = {"date": "2026-11-06", "data": {"status": "kinematic", "engine": "kinematic_ecmwf_ifs025", "direction": "backward", "hours": 72,
                                          "origin": {"lat": 31.5204, "lon": 74.3587, "label": "Lahore"}, "at_utc": "2026-11-05T23:00:00", "place": "Lahore"}}
    msgs = [ModelRequest(parts=[UserPromptPart(content="where did the air come from")]),
            ModelResponse(parts=[TextPart(content="calling")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="aq_fire_trends", content={"data": {}}, tool_call_id="1"),
                                ToolReturnPart(tool_name="aq_trajectory", content=doc, tool_call_id="2")]),
            ModelResponse(parts=[TextPart(content="answer")])]
    assert copilot.trajectory_action(msgs) == {"type": "show_trajectory", "lat": 31.5204, "lon": 74.3587, "at": "2026-11-05T23:00:00",
                                               "direction": "backward", "hours": 72, "label": "Lahore", "engine": "kinematic_ecmwf_ifs025"}
    # an unavailable run, or a run without coordinates, gives no action
    bad = {"data": {"status": "unavailable", "message": "too old"}}
    assert copilot.trajectory_action([ModelRequest(parts=[ToolReturnPart(tool_name="aq_trajectory", content=bad, tool_call_id="3")])]) is None
    assert copilot.trajectory_action([]) is None and copilot.trajectory_action(None) is None


async def test_a_retired_model_falls_back_to_the_next_one(monkeypatch, caplog):
    """gemini-3.1-pro-preview vanished from API v1 on 2026-11-06 and every answer died; a 404 must try the next model."""
    from pydantic_ai.exceptions import ModelHTTPError
    seen = []
    monkeypatch.setattr(copilot, "get_agent", lambda *a, **k: k.get("model_name", copilot.MODEL_FALLBACK_CHAIN[0]))

    async def run_one(agent):
        seen.append(agent)
        if agent == copilot.MODEL_FALLBACK_CHAIN[0]:
            raise ModelHTTPError(status_code=404, model_name=agent, body={"error": {"code": 404, "message": "models/x is not found for API version v1"}})
        yield copilot._sse_event({"type": "text", "content": "answer from " + agent})

    events = _events([c async for c in copilot._stream_with_fallback(run_one, "203.0.113.9", "copilot chat")])
    assert seen == copilot.MODEL_FALLBACK_CHAIN[:2]
    assert events == [{"type": "text", "content": "answer from " + copilot.MODEL_FALLBACK_CHAIN[1]}, {"type": "done"}]
    assert "unavailable, falling back to" in caplog.text and "Traceback" not in caplog.text
    assert copilot._is_model_unavailable(RuntimeError("status_code: 404, model_name: x")) and not copilot._is_model_unavailable(RuntimeError("boom"))


def test_gemini_client_is_pinned_to_v1beta():
    """The preview models exist only on v1beta; a google-genai upgrade must not move the copilot to v1."""
    from app.services.copilot import agent as agent_mod
    client = agent_mod._genai_client("not-a-real-key")
    assert agent_mod.GEMINI_API_VERSION == "v1beta" and client._api_client._http_options.api_version == "v1beta"
