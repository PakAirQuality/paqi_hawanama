"""In-memory session store for copilot conversations."""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pydantic_ai.messages import ModelMessage

SESSION_TTL = 3600  # 1 hour


@dataclass
class CopilotSession:
    session_id: str
    current_date: str = ""
    focused_city: Optional[str] = None
    message_history: List[ModelMessage] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    # ── Session context ──
    focus_type: str = "national"
    focused_station_id: Optional[str] = None  # hex station_id, set by aq_station_focus
    comparison_date: Optional[str] = None
    last_tool: Optional[str] = None
    last_entities: List[str] = field(default_factory=list)
    # ── Coverage query tracking (for deterministic follow-up upgrades) ──
    last_coverage_query: Optional[Dict] = None  # {entity, geography, detail_level}


_sessions: Dict[str, CopilotSession] = {}


def get_or_create_session(session_id: str, current_date: str = "") -> CopilotSession:
    """Return existing session or create a new one."""
    _cleanup_expired()
    if session_id in _sessions:
        sess = _sessions[session_id]
        sess.last_active = time.time()
        if current_date:
            sess.current_date = current_date
        return sess
    sess = CopilotSession(session_id=session_id, current_date=current_date)
    _sessions[session_id] = sess
    return sess


def _cleanup_expired() -> None:
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v.last_active > SESSION_TTL]
    for k in expired:
        del _sessions[k]
