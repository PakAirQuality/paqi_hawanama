"""Daily spend guard for the public copilot.

Counters live in ``ops.copilot_usage`` (migration 004) so every Cloud Run instance sees
the same numbers. ``reserve()`` atomically increments the request counters for the
caller's IP scope and the global scope and raises 429 when either is at its limit;
``record_tokens()`` adds the model's reported usage afterwards.

Fail closed: if the table is missing or the database is unreachable the copilot is
unavailable (503) rather than unmetered.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine

logger = logging.getLogger(__name__)

_RESERVE_SQL = text(
    """
    INSERT INTO ops.copilot_usage (day, scope, requests)
    VALUES (:day, :scope, 1)
    ON CONFLICT (day, scope) DO UPDATE
       SET requests = ops.copilot_usage.requests + 1,
           updated_at = now()
    RETURNING requests, prompt_tokens + completion_tokens AS tokens
    """
)

_RELEASE_SQL = text(
    """
    UPDATE ops.copilot_usage
       SET requests = GREATEST(requests - 1, 0), updated_at = now()
     WHERE day = :day AND scope = :scope
    """
)

_TOKENS_SQL = text(
    """
    UPDATE ops.copilot_usage
       SET prompt_tokens = prompt_tokens + :p,
           completion_tokens = completion_tokens + :c,
           updated_at = now()
     WHERE day = :day AND scope = :scope
    """
)


def _today() -> datetime.date:
    return datetime.now(timezone.utc).date()


async def reserve(ip: str) -> None:
    """Count one request for ``ip`` and globally; 429 if a limit is reached."""
    day = _today()
    scopes = [("global", settings.COPILOT_GLOBAL_DAILY_REQUESTS, settings.COPILOT_GLOBAL_DAILY_TOKENS),
              (f"ip:{ip}", settings.COPILOT_IP_DAILY_LIMIT, None)]
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                for scope, req_limit, tok_limit in scopes:
                    row = (await session.execute(_RESERVE_SQL, {"day": day, "scope": scope})).one()
                    over = (req_limit and row.requests > req_limit) or (tok_limit and row.tokens >= tok_limit)
                    if over:
                        # Undo this reservation; the transaction commits the decrement.
                        await session.execute(_RELEASE_SQL, {"day": day, "scope": scope})
                        if scope == "global":
                            await session.commit()
                        raise HTTPException(
                            status_code=429,
                            detail=(
                                "The assistant has reached its daily limit; please try again tomorrow."
                                if scope == "global"
                                else "You have reached today's limit for the assistant; please try again tomorrow."
                            ),
                            headers={"Retry-After": "3600"},
                        )
    except HTTPException:
        raise
    except Exception as exc:  # table missing, DB down, ...
        logger.error("copilot budget unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="The assistant is temporarily unavailable.")


async def record_tokens(ip: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Add the model's reported token usage to both scopes (best effort)."""
    day = _today()
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                for scope in ("global", f"ip:{ip}"):
                    await session.execute(
                        _TOKENS_SQL,
                        {"day": day, "scope": scope, "p": int(prompt_tokens or 0), "c": int(completion_tokens or 0)},
                    )
    except Exception as exc:
        logger.warning("copilot token accounting failed: %s", type(exc).__name__)


def usage_tokens(usage) -> tuple[int, int]:
    """Extract (prompt, completion) token counts from a pydantic-ai usage object."""
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "input_tokens", None)
    if prompt is None:
        prompt = getattr(usage, "request_tokens", 0)
    completion = getattr(usage, "output_tokens", None)
    if completion is None:
        completion = getattr(usage, "response_tokens", 0)
    return int(prompt or 0), int(completion or 0)
