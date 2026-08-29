"""Copilot SSE endpoints for the analyst desk AI chat."""

import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import verify_tasks_token
from app.services.copilot.agent import get_agent, BRIEFING_PROMPT, MODEL_FALLBACK_CHAIN
from app.services.copilot.context import get_or_create_session

logger = logging.getLogger(__name__)
router = APIRouter()

ACTION_RE = re.compile(r"\{\{ACTION:(\{.*?\})\}\}")
# Model sometimes leaks isolated } from tool JSON envelopes — strip them
# Matches: (a) lines that are just "}", (b) inline "}" after sentence punctuation
STRAY_BRACE_RE = re.compile(r"^\s*\}\s*$|(?<=[.!?])\s*\}", re.MULTILINE)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a 429 rate-limit error from Gemini."""
    exc_str = str(exc).lower()
    return "429" in exc_str or "resource_exhausted" in exc_str or "rate" in exc_str


class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = ""
    date: str = ""


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.post("/copilot/chat")
async def copilot_chat(req: ChatRequest, _auth=Depends(verify_tasks_token)):
    """Stream a copilot response to a user message via SSE."""

    session = get_or_create_session(req.session_id, req.date)

    async def _run_with_agent(agent):
        """Run a single agent stream, yielding SSE events."""
        async with agent.run_stream(
            req.message,
            deps=session,
            message_history=session.message_history,
        ) as result:
            buffer = ""
            async for chunk in result.stream_text(delta=True):
                buffer += chunk

                for match in ACTION_RE.finditer(buffer):
                    try:
                        action = json.loads(match.group(1))
                        yield _sse_event({"type": "action", "action": action})
                    except json.JSONDecodeError:
                        pass

                clean = ACTION_RE.sub("", buffer)
                clean = STRAY_BRACE_RE.sub("", clean)
                if clean.strip():
                    yield _sse_event({"type": "text", "content": clean})
                buffer = ""

            if buffer:
                clean = ACTION_RE.sub("", buffer)
                clean = STRAY_BRACE_RE.sub("", clean)
                if clean.strip():
                    yield _sse_event({"type": "text", "content": clean})
                for match in ACTION_RE.finditer(buffer):
                    try:
                        action = json.loads(match.group(1))
                        yield _sse_event({"type": "action", "action": action})
                    except json.JSONDecodeError:
                        pass

            session.message_history = result.all_messages()

    async def event_stream():
        # Try primary model, fall back on rate limit (429)
        for i, model_name in enumerate(MODEL_FALLBACK_CHAIN):
            try:
                agent = get_agent() if i == 0 else get_agent(model_name=model_name)
                async for event in _run_with_agent(agent):
                    yield event
                break  # success — stop trying fallbacks
            except Exception as e:
                if _is_rate_limit_error(e) and i < len(MODEL_FALLBACK_CHAIN) - 1:
                    next_model = MODEL_FALLBACK_CHAIN[i + 1]
                    logger.warning(
                        "Model %s rate-limited, falling back to %s",
                        model_name, next_model,
                    )
                    continue  # try next model
                logger.error(f"Copilot stream error: {e}", exc_info=True)
                yield _sse_event({"type": "error", "content": "An internal error occurred."})
                break

        yield _sse_event({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/copilot/briefing")
async def copilot_briefing(req: ChatRequest, _auth=Depends(verify_tasks_token)):
    """Generate an opening briefing for a new copilot session via SSE."""

    session = get_or_create_session(req.session_id, req.date)

    async def _run_briefing_with_agent(agent):
        """Run a briefing stream, yielding SSE events."""
        async with agent.run_stream(
            BRIEFING_PROMPT,
            deps=session,
            message_history=[],
        ) as result:
            buffer = ""
            last_sent = 0
            async for chunk in result.stream_text(delta=True):
                buffer += chunk
                clean = ACTION_RE.sub("", buffer)
                clean = STRAY_BRACE_RE.sub("", clean)
                new_text = clean[last_sent:]
                if new_text.strip():
                    yield _sse_event({"type": "text", "content": new_text})
                last_sent = len(clean)

            clean = ACTION_RE.sub("", buffer)
            clean = STRAY_BRACE_RE.sub("", clean)
            final = clean[last_sent:]
            if final.strip():
                yield _sse_event({"type": "text", "content": final})

            session.message_history = result.all_messages()

    async def event_stream():
        for i, model_name in enumerate(MODEL_FALLBACK_CHAIN):
            try:
                agent = get_agent() if i == 0 else get_agent(model_name=model_name)
                async for event in _run_briefing_with_agent(agent):
                    yield event
                break
            except Exception as e:
                if _is_rate_limit_error(e) and i < len(MODEL_FALLBACK_CHAIN) - 1:
                    next_model = MODEL_FALLBACK_CHAIN[i + 1]
                    logger.warning(
                        "Briefing model %s rate-limited, falling back to %s",
                        model_name, next_model,
                    )
                    continue
                logger.error(f"Copilot briefing error: {e}", exc_info=True)
                yield _sse_event({"type": "error", "content": "An internal error occurred."})
                break

        yield _sse_event({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
