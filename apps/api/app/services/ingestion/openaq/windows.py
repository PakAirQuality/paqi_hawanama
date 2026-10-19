"""
Checkpoint arithmetic. A checkpoint is the END of the last window whose pages
were all durably written — never the max observed timestamp — so late and
revised data inside OPENAQ_OVERLAP_HOURS is re-read on every run, and a
page-2 failure leaves completed_through untouched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple


def next_window(completed_through: Optional[datetime], now: datetime, *, overlap_h: int, window_h: int,
                initial_backfill_h: int) -> Tuple[datetime, datetime]:
    """[from, to] for the next ingest of a stream."""
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if completed_through is None:
        # Nothing completed yet: there is nothing to re-read, so take the whole initial
        # backfill in one window (72 hourly rows is a single page).
        return now - timedelta(hours=initial_backfill_h), now
    cursor = completed_through
    if cursor.tzinfo is None:
        cursor = cursor.replace(tzinfo=timezone.utc)
    cursor = min(cursor, now)
    frm = cursor - timedelta(hours=overlap_h)
    to = min(now, cursor + timedelta(hours=window_h))
    if to <= frm:
        to = now
    return frm, to


def reconcile_windows(completed_through: Optional[datetime], *, lookback_days: int, overlap_h: int,
                      chunk_days: int = 7) -> List[Tuple[datetime, datetime]]:
    """Older windows [completed_through − lookback, completed_through − overlap], chunked; [] when nothing completed."""
    if completed_through is None or lookback_days <= 0:
        return []
    end = completed_through - timedelta(hours=overlap_h)
    start = completed_through - timedelta(days=lookback_days)
    if end <= start:
        return []
    out = []
    cur = start
    step = timedelta(days=max(1, chunk_days))
    while cur < end:
        nxt = min(cur + step, end)
        out.append((cur, nxt))
        cur = nxt
    return out
