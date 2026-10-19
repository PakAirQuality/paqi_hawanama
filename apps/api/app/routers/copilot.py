"""Copilot SSE endpoints for the analyst desk AI chat.

Public (no shared secret). Abuse controls, in order:
1. per-IP burst limit (router dependency, in-process);
2. daily request/token budget per IP and global, in ``ops.copilot_usage``
   (``app.services.copilot.budget``), checked before any model call;
3. pydantic-ai ``UsageLimits`` and ``max_tokens`` on every run;
4. bounded session store with per-session locks (``app.services.copilot.context``).
"""

import json
import logging
import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from pydantic_ai.usage import UsageLimits

from app.core.config import settings
from app.core.ratelimit import client_ip, make_rate_limit
from app.services.copilot import budget
from app.services.copilot.agent import get_agent, BRIEFING_PROMPT, MODEL_FALLBACK_CHAIN
from app.services.copilot.context import get_or_create_session

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(make_rate_limit(settings.COPILOT_RATE_LIMIT_PER_MINUTE, "copilot"))])

ACTION_RE = re.compile(r"\{\{ACTION:(\{.*?\})\}\}")
# Model sometimes leaks isolated } from tool JSON envelopes — strip them
# Matches: (a) lines that are just "}", (b) inline "}" after sentence punctuation
STRAY_BRACE_RE = re.compile(r"^\s*\}\s*$|(?<=[.!?])\s*\}", re.MULTILINE)
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")

# One chat turn may need a few tool round-trips; cap requests and total tokens per turn.
RUN_LIMITS = UsageLimits(request_limit=8, total_tokens_limit=60_000)
RUN_SETTINGS = {"max_tokens": 1024}


def _is_rate_limit_error(exc: Exception) -> bool:
    """True for a Gemini quota/429 error (used to fall back to the next model)."""
    exc_str = str(exc).lower()
    return "429" in exc_str or "resource_exhausted" in exc_str or "rate limit" in exc_str or "rate-limit" in exc_str


class SelectionLocation(BaseModel):
    type: str = Field(default="national", max_length=20)      # national | city | station
    id: str = Field(default="", max_length=80)
    name: str = Field(default="", max_length=120)


class SelectionContext(BaseModel):
    """What the user is looking at, so the answer describes the same selection."""
    model: str = Field(default="backbone", max_length=32)     # backbone | support_aware
    pollutant: str = Field(default="pm25", max_length=16)
    units: str = Field(default="µg/m³", max_length=16)
    tz: str = Field(default="Asia/Karachi", max_length=40)
    location: SelectionLocation = Field(default_factory=SelectionLocation)
    layers: list[str] = Field(default_factory=list, max_length=12)


class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=80)
    message: str = Field(default="", max_length=settings.COPILOT_MAX_MESSAGE_CHARS)
    date: str = Field(default="", max_length=10)
    context: SelectionContext | None = None

    @field_validator("session_id")
    @classmethod
    def _session_id_shape(cls, v: str) -> str:
        if not SESSION_ID_RE.match(v):
            raise ValueError("session_id must be 8-80 URL-safe characters")
        return v

    @field_validator("date")
    @classmethod
    def _date_shape(cls, v: str) -> str:
        if v:
            date.fromisoformat(v)  # raises ValueError on anything but YYYY-MM-DD
        return v


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _apply_context(session, ctx: SelectionContext | None) -> None:
    """Copy the client's selection into the session so the prompt can state it."""
    if ctx is None:
        return
    session.model = ctx.model if ctx.model in ("backbone", "support_aware") else "backbone"
    session.pollutant = ctx.pollutant
    session.tz = ctx.tz
    session.active_layers = [l for l in ctx.layers if l][:12]
    loc = ctx.location
    if loc and loc.type == "city" and loc.name:
        session.focus_type = "city"
        session.focused_city = loc.name
    elif loc and loc.type == "station" and loc.id:
        session.focus_type = "station"
        session.focused_station_id = loc.id
        if loc.name:
            session.focused_city = session.focused_city or None
            session.focused_station_name = loc.name
    elif loc and loc.type == "national":
        session.focus_type = "national"


def _clean(text: str) -> str:
    return STRAY_BRACE_RE.sub("", ACTION_RE.sub("", text))


async def _stream_with_fallback(run_one, ip: str, label: str):
    """Try the model chain in order, falling back only on quota errors."""
    for i, model_name in enumerate(MODEL_FALLBACK_CHAIN):
        try:
            agent = get_agent() if i == 0 else get_agent(model_name=model_name)
            async for event in run_one(agent):
                yield event
            break
        except Exception as e:
            if _is_rate_limit_error(e) and i < len(MODEL_FALLBACK_CHAIN) - 1:
                logger.warning("%s: model %s rate-limited, falling back to %s", label, model_name, MODEL_FALLBACK_CHAIN[i + 1])
                continue
            logger.error("%s error (%s)", label, type(e).__name__, exc_info=True)
            yield _sse_event({"type": "error", "content": "An internal error occurred."})
            break
    yield _sse_event({"type": "done"})


@router.post("/copilot/chat")
async def copilot_chat(req: ChatRequest, request: Request):
    """Stream a copilot response to a user message via SSE."""
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="message is required")
    ip = client_ip(request)
    await budget.reserve(ip)
    session = get_or_create_session(req.session_id, req.date)
    _apply_context(session, req.context)

    async def _run_with_agent(agent):
        async with session.lock:
            async with agent.run_stream(
                req.message,
                deps=session,
                message_history=session.message_history,
                usage_limits=RUN_LIMITS,
                model_settings=RUN_SETTINGS,
            ) as result:
                buffer = ""
                async for chunk in result.stream_text(delta=True):
                    buffer += chunk
                    for match in ACTION_RE.finditer(buffer):
                        try:
                            yield _sse_event({"type": "action", "action": json.loads(match.group(1))})
                        except json.JSONDecodeError:
                            pass
                    clean = _clean(buffer)
                    if clean.strip():
                        yield _sse_event({"type": "text", "content": clean})
                    buffer = ""
                if buffer:
                    clean = _clean(buffer)
                    if clean.strip():
                        yield _sse_event({"type": "text", "content": clean})
                    for match in ACTION_RE.finditer(buffer):
                        try:
                            yield _sse_event({"type": "action", "action": json.loads(match.group(1))})
                        except json.JSONDecodeError:
                            pass
                session.set_history(result.all_messages())
                p, c = budget.usage_tokens(result.usage())
            await budget.record_tokens(ip, p, c)

    return StreamingResponse(_stream_with_fallback(_run_with_agent, ip, "copilot chat"), media_type="text/event-stream")


@router.post("/copilot/briefing")
async def copilot_briefing(req: ChatRequest, request: Request):
    """Generate an opening briefing for a new copilot session via SSE."""
    ip = client_ip(request)
    await budget.reserve(ip)
    session = get_or_create_session(req.session_id, req.date)
    _apply_context(session, req.context)

    async def _run_briefing_with_agent(agent):
        async with session.lock:
            async with agent.run_stream(
                BRIEFING_PROMPT,
                deps=session,
                message_history=[],
                usage_limits=RUN_LIMITS,
                model_settings=RUN_SETTINGS,
            ) as result:
                buffer = ""
                last_sent = 0
                async for chunk in result.stream_text(delta=True):
                    buffer += chunk
                    clean = _clean(buffer)
                    new_text = clean[last_sent:]
                    if new_text.strip():
                        yield _sse_event({"type": "text", "content": new_text})
                    last_sent = len(clean)
                final = _clean(buffer)[last_sent:]
                if final.strip():
                    yield _sse_event({"type": "text", "content": final})
                session.set_history(result.all_messages())
                p, c = budget.usage_tokens(result.usage())
            await budget.record_tokens(ip, p, c)

    return StreamingResponse(_stream_with_fallback(_run_briefing_with_agent, ip, "copilot briefing"), media_type="text/event-stream")
