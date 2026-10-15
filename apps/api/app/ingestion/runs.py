"""
Run accounting for ingestion tasks.

Before this module every task returned {"status": "success"} regardless of what
happened (all stations failing, a missing manifest, zero rows written), the HTTP
endpoints always answered 200, and Cloud Scheduler therefore never retried a
broken run. A RunOutcome now carries the real counts, is classified into
success / partial / failed / skipped, and is persisted to ops.ingest_runs (plus
the local metrics.json / failures.jsonl report) by RunRecorder.

Persistence is best-effort by default: if the ops tables are absent the recorder
logs once and the run continues. Quota (quota.py) is the one place that must not
degrade silently; that is handled there.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.ingestion.provenance import GIT_SHA, PROVENANCE

logger = logging.getLogger(__name__)

_UNDEFINED_TABLE = "42P01"


class RunStatus(str, Enum):
    running = "running"
    success = "success"
    partial = "partial"
    failed = "failed"
    skipped = "skipped"


@dataclass
class RunCounts:
    expected: int = 0        # inventory targeted after filters (manifest/DB rows)
    attempted: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0         # not attempted because the run aborted (e.g. provider auth failure)
    rows_fetched: int = 0    # rows parsed from provider responses, before dedupe
    rows_written: int = 0    # rows inserted/updated in readings
    rows_unchanged: int = 0  # rows dropped as already present / no-op


@dataclass
class EntityFailure:
    entity_type: str
    entity_key: str
    error_class: str
    error_message: str
    attempts: int = 1
    details: Optional[Dict[str, Any]] = None


@dataclass
class RunOutcome:
    run_id: str
    task: str
    provider_code: str
    scope: str = "all"
    trigger: str = "http"
    status: RunStatus = RunStatus.running
    counts: RunCounts = field(default_factory=RunCounts)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    manifest_source: Optional[str] = None
    manifest_generation: Optional[str] = None
    manifest_rows: Optional[int] = None
    latest_observation_ts: Optional[datetime] = None
    observation_lag_s: Optional[int] = None
    lease_key: Optional[str] = None
    lease_fence: Optional[int] = None
    report_dir: Optional[str] = None
    partial_reason: Optional[str] = None   # degrade an otherwise-successful run to partial (e.g. skipped states)
    details: Dict[str, Any] = field(default_factory=dict)

    # ---- helpers -------------------------------------------------------

    def fail(self, error_class: str, message: str = "") -> "RunOutcome":
        self.status = RunStatus.failed
        self.error_class = error_class
        self.error_message = (message or "")[:1000]
        return self

    def skip(self, reason: str, message: str = "") -> "RunOutcome":
        self.status = RunStatus.skipped
        self.error_class = reason
        self.error_message = (message or "")[:1000]
        return self

    def finish(self, fatal_error: Optional[str] = None, message: str = "") -> "RunOutcome":
        """Set finished_at and classify, unless already skipped/failed explicitly."""
        self.finished_at = datetime.now(timezone.utc)
        if self.status in (RunStatus.skipped, RunStatus.failed):
            return self
        if fatal_error:
            return self.fail(fatal_error, message)
        self.status = classify(self.counts, fatal_error=None)
        if self.status is RunStatus.success and self.partial_reason:
            self.status = RunStatus.partial
            self.error_class = self.partial_reason
        if self.status is RunStatus.failed and not self.error_class:
            self.error_class = "empty_inventory" if self.counts.expected == 0 else "all_entities_failed"
        if self.latest_observation_ts and self.finished_at:
            self.observation_lag_s = int((self.finished_at - self.latest_observation_ts).total_seconds())
        return self

    @property
    def duration_ms(self) -> Optional[int]:
        if not self.finished_at:
            return None
        return int((self.finished_at - self.started_at).total_seconds() * 1000)

    def http_status(self) -> int:
        """HTTP status for the task endpoints. Cloud Scheduler retries only non-2xx."""
        return {
            RunStatus.success: 200,
            RunStatus.skipped: 200,
            RunStatus.partial: 207,
            RunStatus.failed: 500,
            RunStatus.running: 200,
        }[self.status]

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe summary. Legacy keys from the old summaries are kept inside details."""
        return {
            "run_id": self.run_id,
            "task": self.task,
            "provider_code": self.provider_code,
            "scope": self.scope,
            "trigger": self.trigger,
            "status": self.status.value,
            "counts": asdict(self.counts),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "duration_ms": self.duration_ms,
            "error_class": self.error_class,
            "error_message": self.error_message,
            "manifest": {
                "source": self.manifest_source,
                "generation": self.manifest_generation,
                "rows": self.manifest_rows,
            },
            "latest_observation_ts": _iso(self.latest_observation_ts),
            "observation_lag_s": self.observation_lag_s,
            "lease": {"key": self.lease_key, "fence": self.lease_fence},
            "report_dir": self.report_dir,
            "git_sha": GIT_SHA,
            "provenance": PROVENANCE,
            "details": _json_safe(self.details),
        }


def classify(counts: RunCounts, *, fatal_error: Optional[str]) -> RunStatus:
    """
    fatal_error            -> failed
    expected == 0          -> failed  (an unexpectedly empty inventory is a failure, not a success)
    failed == 0            -> success
    failed  < attempted    -> partial
    otherwise              -> failed
    """
    if fatal_error:
        return RunStatus.failed
    if counts.expected == 0:
        return RunStatus.failed
    if counts.failed == 0:
        return RunStatus.success
    if counts.failed < counts.attempted:
        return RunStatus.partial
    return RunStatus.failed


def worst_status(*outcomes: RunOutcome) -> RunStatus:
    order = [RunStatus.failed, RunStatus.partial, RunStatus.running, RunStatus.skipped, RunStatus.success]
    present = {o.status for o in outcomes}
    for s in order:
        if s in present:
            return s
    return RunStatus.success


def new_run_id(task: str) -> str:
    """A fresh id per invocation (the old tasks minted one per object and reused it)."""
    return f"{task}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def host_id() -> str:
    rev = os.getenv("K_REVISION") or socket.gethostname()
    return f"{rev}:{os.getpid()}"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return _iso(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _is_undefined_table(exc: BaseException) -> bool:
    """True for 'relation does not exist' from asyncpg/SQLAlchemy, however it is wrapped."""
    seen = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, "sqlstate", None) == _UNDEFINED_TABLE or getattr(cur, "pgcode", None) == _UNDEFINED_TABLE:
            return True
        if "does not exist" in str(cur) and ("relation" in str(cur) or "schema" in str(cur)):
            return True
        cur = getattr(cur, "orig", None) or cur.__cause__ or cur.__context__
    return False


class RunRecorder:
    """
    Persists RunOutcome to ops.ingest_runs / ops.ingest_run_entities and writes the
    local metrics.json + failures.jsonl report.

    session_factory: an async sessionmaker (app.ingestion.db.AsyncSessionLocal) or
    None to disable DB persistence entirely (CLI dry runs, tests).
    required: raise instead of degrading when the ops tables are missing.
    """

    _warned_missing = False

    def __init__(self, session_factory=None, out_dir: Optional[Path] = None, *, required: bool = False):
        self._sf = session_factory
        self._out_dir = Path(out_dir) if out_dir else None
        self._required = required
        self._failures: List[EntityFailure] = []
        self._db_ok = session_factory is not None

    # ---- buffering --------------------------------------------------------

    def add_failure(self, f: EntityFailure) -> None:
        self._failures.append(f)

    @property
    def failures(self) -> List[EntityFailure]:
        return list(self._failures)

    # ---- lifecycle --------------------------------------------------------

    async def start(self, outcome: RunOutcome) -> None:
        outcome.status = RunStatus.running
        if self._out_dir:
            outcome.report_dir = str(self._out_dir / outcome.run_id)
        if not self._db_ok:
            return
        sql = text("""
            INSERT INTO ops.ingest_runs
                (run_id, task, provider_code, scope, trigger, status, started_at, git_sha, provenance, host, details)
            VALUES
                (:run_id, :task, :provider_code, :scope, :trigger, 'running', :started_at, :git_sha, :provenance, :host, CAST(:details AS jsonb))
            ON CONFLICT (run_id) DO NOTHING
        """)
        params = {
            "run_id": outcome.run_id, "task": outcome.task, "provider_code": outcome.provider_code,
            "scope": outcome.scope, "trigger": outcome.trigger, "started_at": outcome.started_at,
            "git_sha": GIT_SHA, "provenance": PROVENANCE, "host": host_id(),
            "details": json.dumps(_json_safe(outcome.details)),
        }
        await self._execute("start", sql, params)

    async def finish(self, outcome: RunOutcome) -> None:
        if outcome.finished_at is None:
            outcome.finish()
        self._write_local_report(outcome)
        if not self._db_ok:
            return
        c = outcome.counts
        sql = text("""
            UPDATE ops.ingest_runs SET
                status = :status, finished_at = :finished_at, duration_ms = :duration_ms,
                expected_count = :expected, attempted_count = :attempted, completed_count = :completed,
                failed_count = :failed, rows_fetched = :rows_fetched, rows_written = :rows_written,
                rows_unchanged = :rows_unchanged, latest_observation_ts = :latest_observation_ts,
                observation_lag_s = :observation_lag_s, manifest_source = :manifest_source,
                manifest_generation = :manifest_generation, manifest_rows = :manifest_rows,
                lease_key = :lease_key, lease_fence = :lease_fence, error_class = :error_class,
                error_message = :error_message, details = CAST(:details AS jsonb)
            WHERE run_id = :run_id
        """)
        params = {
            "run_id": outcome.run_id, "status": outcome.status.value, "finished_at": outcome.finished_at,
            "duration_ms": outcome.duration_ms, "expected": c.expected, "attempted": c.attempted,
            "completed": c.completed, "failed": c.failed, "rows_fetched": c.rows_fetched,
            "rows_written": c.rows_written, "rows_unchanged": c.rows_unchanged,
            "latest_observation_ts": outcome.latest_observation_ts, "observation_lag_s": outcome.observation_lag_s,
            "manifest_source": outcome.manifest_source, "manifest_generation": outcome.manifest_generation,
            "manifest_rows": outcome.manifest_rows, "lease_key": outcome.lease_key, "lease_fence": outcome.lease_fence,
            "error_class": outcome.error_class, "error_message": outcome.error_message,
            "details": json.dumps(_json_safe({**outcome.details, "skipped": c.skipped})),
        }
        ok = await self._execute("finish", sql, params)
        if ok and self._failures:
            ent_sql = text("""
                INSERT INTO ops.ingest_run_entities
                    (run_id, entity_type, entity_key, outcome, error_class, error_message, attempts, details)
                VALUES
                    (:run_id, :entity_type, :entity_key, 'failed', :error_class, :error_message, :attempts, CAST(:details AS jsonb))
                ON CONFLICT (run_id, entity_type, entity_key) DO UPDATE SET
                    error_class = EXCLUDED.error_class, error_message = EXCLUDED.error_message,
                    attempts = EXCLUDED.attempts, details = EXCLUDED.details
            """)
            rows = [{
                "run_id": outcome.run_id, "entity_type": f.entity_type, "entity_key": str(f.entity_key)[:500],
                "error_class": f.error_class[:200], "error_message": (f.error_message or "")[:1000],
                "attempts": f.attempts, "details": json.dumps(_json_safe(f.details or {})),
            } for f in self._failures]
            await self._execute("entities", ent_sql, rows)
        # Best-effort housekeeping for the shared quota table.
        await self._execute("quota_gc", text("DELETE FROM ops.provider_quota WHERE window_start < now() - interval '7 days'"), {})

    # ---- internals --------------------------------------------------------

    async def _execute(self, what: str, sql, params) -> bool:
        if not self._db_ok:
            return False
        try:
            async with self._sf() as sess:
                await sess.execute(sql, params)
                await sess.commit()
            return True
        except Exception as exc:  # never let accounting break a run
            if _is_undefined_table(exc):
                if self._required:
                    raise
                if not RunRecorder._warned_missing:
                    RunRecorder._warned_missing = True
                    logger.warning("ops tables missing (apply db_schema/migrations/001_ops_ingestion.sql); "
                                   "run accounting disabled for this process: %s", exc)
                self._db_ok = False
                return False
            logger.warning("RunRecorder.%s failed (continuing): %s: %s", what, type(exc).__name__, exc)
            return False

    def _write_local_report(self, outcome: RunOutcome) -> None:
        if not self._out_dir:
            return
        try:
            d = self._out_dir / outcome.run_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "metrics.json").write_text(json.dumps(outcome.to_dict(), indent=2, ensure_ascii=False))
            if self._failures:
                with open(d / "failures.jsonl", "w", encoding="utf-8") as f:
                    for fl in self._failures:
                        f.write(json.dumps(_json_safe(asdict(fl)), ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed writing ingest report for %s: %s", outcome.run_id, exc)


class RunAborted(Exception):
    """Raised inside per-entity workers when the run has been aborted (e.g. provider auth failure)."""


# ---- FastAPI glue shared by every task endpoint -----------------------------

def trigger_from_headers(headers) -> str:
    """'scheduler' for Cloud Scheduler calls (header or user agent), else 'http'."""
    ua = headers.get("user-agent", "") or ""
    if headers.get("x-cloudscheduler") or "Google-Cloud-Scheduler" in ua:
        return "scheduler"
    return "http"


def outcome_response(outcome: RunOutcome, message: str):
    """
    JSONResponse whose status code follows the run: success/skipped 200, partial
    207, failed 500 — Cloud Scheduler retries only non-2xx, so total failures
    get retried and live runs (skipped/lease_held) do not.
    """
    from fastapi.responses import JSONResponse
    from app.ingestion.provenance import describe
    return JSONResponse(
        status_code=outcome.http_status(),
        content={"status": outcome.status.value, "message": message, "run_id": outcome.run_id,
                 "summary": outcome.to_dict(), "provenance": describe()},
    )
