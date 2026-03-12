"""Copilot SSE endpoints for the analyst desk AI chat."""

import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import verify_tasks_token
from app.services.copilot.agent import get_agent, BRIEFING_PROMPT
from app.services.copilot.context import get_or_create_session

logger = logging.getLogger(__name__)
router = APIRouter()

ACTION_RE = re.compile(r"\{\{ACTION:(\{.*?\})\}\}")
# Model sometimes leaks isolated } from tool JSON envelopes — strip them
# Matches: (a) lines that are just "}", (b) inline "}" after sentence punctuation
STRAY_BRACE_RE = re.compile(r"^\s*\}\s*$|(?<=[.!?])\s*\}", re.MULTILINE)


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

    async def event_stream():
        try:
            async with get_agent().run_stream(
                req.message,
                deps=session,
                message_history=session.message_history,
            ) as result:
                buffer = ""
                async for chunk in result.stream_text(delta=True):
                    # Check for action tags in accumulated buffer
                    buffer += chunk

                    # Extract and emit action events
                    for match in ACTION_RE.finditer(buffer):
                        try:
                            action = json.loads(match.group(1))
                            yield _sse_event({"type": "action", "action": action})
                        except json.JSONDecodeError:
                            pass

                    # Emit text without action tags or stray braces
                    clean = ACTION_RE.sub("", buffer)
                    clean = STRAY_BRACE_RE.sub("", clean)
                    if clean.strip():
                        yield _sse_event({"type": "text", "content": clean})
                    buffer = ""

                # Flush any remaining buffer
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

                # Save message history for follow-ups
                session.message_history = result.all_messages()

        except Exception as e:
            logger.error(f"Copilot stream error: {e}", exc_info=True)
            yield _sse_event({"type": "error", "content": "An internal error occurred."})

        yield _sse_event({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/copilot/briefing")
async def copilot_briefing(req: ChatRequest, _auth=Depends(verify_tasks_token)):
    """Generate an opening briefing for a new copilot session via SSE."""

    session = get_or_create_session(req.session_id, req.date)

    async def event_stream():
        try:
            async with get_agent().run_stream(
                BRIEFING_PROMPT,
                deps=session,
                message_history=[],
            ) as result:
                async for chunk in result.stream_text(delta=True):
                    clean = ACTION_RE.sub("", chunk)
                    clean = STRAY_BRACE_RE.sub("", clean)
                    if clean.strip():
                        yield _sse_event({"type": "text", "content": clean})

                session.message_history = result.all_messages()

        except Exception as e:
            logger.error(f"Copilot briefing error: {e}", exc_info=True)
            yield _sse_event({"type": "error", "content": "An internal error occurred."})

        yield _sse_event({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
