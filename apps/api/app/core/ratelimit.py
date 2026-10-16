"""Client identification and best-effort per-instance rate limiting.

Cloud Run terminates TLS at Google's front end and appends the connecting client's
address as the LAST element of X-Forwarded-For; everything before it is whatever the
client sent. So the trustworthy hop is the rightmost one. uvicorn is started with
``--forwarded-allow-ips="*"`` and would otherwise expose the leftmost (spoofable)
entry as ``request.client.host``.

The limiter is a sliding window kept in process memory: Cloud Run instances do not
share it, so a limit of N/min is really N/min per instance. It is a safeguard against
accidental or lazy abuse, not a hard quota; the copilot's spend cap is enforced in the
database instead (app/services/copilot/budget.py).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, Dict

from fastapi import HTTPException, Request

_MAX_TRACKED_KEYS = 50_000


def client_ip(request: Request) -> str:
    """Return the client address Google's front end saw (rightmost X-Forwarded-For hop)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    """Allow at most ``limit`` calls per ``window_s`` seconds per key."""

    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._log: Dict[str, Deque[float]] = {}
        self._calls_since_sweep = 0

    def _sweep(self, now: float) -> None:
        """Drop idle keys so the table cannot grow without bound."""
        self._calls_since_sweep = 0
        stale = [k for k, dq in self._log.items() if not dq or now - dq[-1] > self.window_s]
        for k in stale:
            del self._log[k]
        if len(self._log) > _MAX_TRACKED_KEYS:
            # Pathological churn (rotating spoofed addresses): keep the newest half.
            for k in list(self._log)[: len(self._log) // 2]:
                del self._log[k]

    def check(self, key: str) -> bool:
        """Record a call for ``key``; return False when over the limit."""
        if self.limit <= 0:
            return True
        now = time.monotonic()
        self._calls_since_sweep += 1
        if self._calls_since_sweep >= 1000:
            self._sweep(now)
        dq = self._log.get(key)
        if dq is None:
            dq = self._log[key] = deque()
        while dq and now - dq[0] > self.window_s:
            dq.popleft()
        if len(dq) >= self.limit:
            return False
        dq.append(now)
        return True


def make_rate_limit(limit_per_minute: int, scope: str = "public") -> Callable[[Request], None]:
    """Build a FastAPI dependency enforcing ``limit_per_minute`` per client IP.

    Attach at router level (``include_router(..., dependencies=[Depends(dep)])``) so
    handler signatures stay untouched.
    """
    limiter = SlidingWindowLimiter(limit_per_minute)

    async def _dependency(request: Request) -> None:
        if not limiter.check(f"{scope}:{client_ip(request)}"):
            raise HTTPException(
                status_code=429,
                detail="Too many requests; slow down and retry in a minute.",
                headers={"Retry-After": "60"},
            )

    _dependency.__name__ = f"rate_limit_{scope}"
    return _dependency
