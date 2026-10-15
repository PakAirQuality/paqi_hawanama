"""
Process-local request pacing: a concurrency cap plus token spacing so the
average rate stays at or below `per_minute`. This is *not* the shared quota
(that is quota.py, backed by Postgres); it only smooths one process's bursts.
"""

from __future__ import annotations

import asyncio


class LocalPacer:
    def __init__(self, per_minute: int, concurrency: int):
        self._interval = 60.0 / float(max(1, int(per_minute)))
        self._sema = asyncio.Semaphore(max(1, int(concurrency)))
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def __aenter__(self):
        await self._sema.acquire()
        try:
            await self._wait_turn()
        except BaseException:
            self._sema.release()
            raise
        return self

    async def __aexit__(self, *exc):
        self._sema.release()
        return False

    async def _wait_turn(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._next <= now:
                self._next = now + self._interval
                delay = 0.0
            else:
                delay = self._next - now
                self._next += self._interval
        if delay > 0:
            await asyncio.sleep(delay)
