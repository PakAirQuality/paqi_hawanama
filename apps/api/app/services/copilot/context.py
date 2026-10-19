"""In-memory session store for copilot conversations.

The copilot is public, so the store is bounded and sessions are short-lived:

* at most ``MAX_SESSIONS`` live sessions (least recently used evicted first);
* a session expires ``SESSION_IDLE_TTL`` after its last use and ``SESSION_MAX_AGE``
  after creation, whichever comes first;
* the model history kept per session is trimmed to the last ``MAX_HISTORY`` messages;
* each session carries an ``asyncio.Lock`` so two concurrent requests on the same id
  cannot interleave their history writes.

Session ids are chosen by the client but must be unguessable (validated in the
router: 8-80 URL-safe chars); the store never links ids to each other.
"""

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pydantic_ai.messages import ModelMessage

SESSION_IDLE_TTL = 900      # 15 minutes without a request
SESSION_MAX_AGE = 3600      # 1 hour from creation, however active
MAX_SESSIONS = 2000
MAX_HISTORY = 30            # model messages kept per session


@dataclass
class CopilotSession:
    session_id: str
    current_date: str = ""
    focused_city: Optional[str] = None
    message_history: List[ModelMessage] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
    # ── Session context ──
    focus_type: str = "national"
    focused_station_id: Optional[str] = None  # hex station_id, set by aq_station_focus
    comparison_date: Optional[str] = None
    last_tool: Optional[str] = None
    last_entities: List[str] = field(default_factory=list)
    # ── Coverage query tracking (for deterministic follow-up upgrades) ──
    last_coverage_query: Optional[Dict] = None  # {entity, geography, detail_level}
    # ── Historical date anchor (set when user focuses on a past date) ──
    active_historical_date: Optional[str] = None  # YYYY-MM-DD
    # ── Shared selection sent by the client (what the map/cards currently show) ──
    model: str = "backbone"                       # backbone | support_aware
    pollutant: str = "pm25"
    tz: str = "Asia/Karachi"
    focused_station_name: Optional[str] = None
    active_layers: List[str] = field(default_factory=list)

    def set_history(self, messages: List[ModelMessage]) -> None:
        """Replace the history, keeping only the most recent messages."""
        self.message_history = list(messages)[-MAX_HISTORY:]


_sessions: "OrderedDict[str, CopilotSession]" = OrderedDict()


def _expired(sess: CopilotSession, now: float) -> bool:
    return now - sess.last_active > SESSION_IDLE_TTL or now - sess.created_at > SESSION_MAX_AGE


def get_or_create_session(session_id: str, current_date: str = "") -> CopilotSession:
    """Return the live session for ``session_id`` or create a fresh one."""
    now = time.time()
    _cleanup_expired(now)
    sess = _sessions.get(session_id)
    if sess is not None and not _expired(sess, now):
        sess.last_active = now
        _sessions.move_to_end(session_id)
        if current_date:
            sess.current_date = current_date
        return sess
    sess = CopilotSession(session_id=session_id, current_date=current_date)
    _sessions[session_id] = sess
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return sess


def _cleanup_expired(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    expired = [k for k, v in _sessions.items() if _expired(v, now)]
    for k in expired:
        del _sessions[k]


def session_count() -> int:
    return len(_sessions)
