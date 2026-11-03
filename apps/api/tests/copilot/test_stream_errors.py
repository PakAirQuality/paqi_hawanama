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
