"""Public-surface hardening: client IP derivation, in-process rate limiter,
copilot request validation and the bounded session store."""

import asyncio
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.ratelimit import SlidingWindowLimiter, client_ip, make_rate_limit
from app.routers.copilot import ChatRequest
from app.services.copilot import context


def _request(headers: dict | None = None, client=("10.0.0.9", 1234)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": "GET", "path": "/", "headers": raw, "client": client, "query_string": b""}
    return Request(scope)


def test_client_ip_uses_rightmost_forwarded_hop():
    req = _request({"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_socket_peer():
    assert client_ip(_request()) == "10.0.0.9"


def test_sliding_window_limiter_blocks_over_limit():
    lim = SlidingWindowLimiter(limit=3, window_s=60)
    assert all(lim.check("k") for _ in range(3))
    assert lim.check("k") is False
    assert lim.check("other") is True


def test_sliding_window_limiter_sweeps_idle_keys():
    lim = SlidingWindowLimiter(limit=1, window_s=0.01)
    lim.check("a")
    time.sleep(0.02)
    lim._calls_since_sweep = 999
    lim.check("b")  # triggers a sweep
    assert "a" not in lim._log


@pytest.mark.asyncio
async def test_rate_limit_dependency_returns_429():
    dep = make_rate_limit(2, "t")
    req = _request({"X-Forwarded-For": "9.9.9.9"})
    await dep(req)
    await dep(req)
    with pytest.raises(HTTPException) as ei:
        await dep(req)
    assert ei.value.status_code == 429
    assert ei.value.headers["Retry-After"] == "60"


def test_chat_request_rejects_bad_session_id_and_date():
    with pytest.raises(ValueError):
        ChatRequest(session_id="short", message="hi")
    with pytest.raises(ValueError):
        ChatRequest(session_id="tracker-2026-10-16", message="hi", date="16/10/2026")
    ok = ChatRequest(session_id="tracker-2026-10-16-3f2a9c1d", message="hi", date="2026-10-16")
    assert ok.date == "2026-10-16"


def test_chat_request_caps_message_length():
    with pytest.raises(ValueError):
        ChatRequest(session_id="abcdefgh", message="x" * 5000)


def test_session_store_is_bounded_and_trims_history():
    context._sessions.clear()
    try:
        for i in range(context.MAX_SESSIONS + 5):
            context.get_or_create_session(f"sess-{i:05d}")
        assert context.session_count() == context.MAX_SESSIONS
        assert "sess-00000" not in context._sessions  # oldest evicted first
        s = context.get_or_create_session("sess-trim")
        s.set_history(list(range(100)))
        assert len(s.message_history) == context.MAX_HISTORY
        assert isinstance(s.lock, asyncio.Lock)
    finally:
        context._sessions.clear()


def test_session_expires_after_max_age_even_when_active():
    context._sessions.clear()
    try:
        s = context.get_or_create_session("sess-old")
        s.created_at = time.time() - context.SESSION_MAX_AGE - 1
        s.last_active = time.time()
        again = context.get_or_create_session("sess-old")
        assert again is not s
    finally:
        context._sessions.clear()


def test_settings_strip_trailing_newline_from_secrets(monkeypatch):
    """Secret Manager values created with `echo` end in a newline; headers cannot carry one."""
    from app.core.config import Settings

    monkeypatch.setenv("TASKS_API_SECRET", "abc123\n")
    monkeypatch.setenv("FIRMS_MAP_KEY", "  key  ")
    s = Settings(POSTGRES_SERVER="x", POSTGRES_USER="x", POSTGRES_PASSWORD="x", POSTGRES_DB="x", POSTGRES_PORT=1)
    assert s.TASKS_API_SECRET == "abc123"
    assert s.FIRMS_MAP_KEY == "key"
