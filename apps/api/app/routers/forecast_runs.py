"""
Forecast run status: the daily-forecast Cloud Run job reports each run here
(POST /api/v1/forecast-runs/status, bearer TASKS_API_SECRET). The report is
stored as an ops.ingest_runs row (task "daily-forecast") so /health/freshness
judges forecast freshness like any other run-backed source, and the last
runs can be listed for the dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_database
from app.core.security import verify_tasks_token

logger = logging.getLogger(__name__)
router = APIRouter()

FORECAST_TASK = "daily-forecast"
NOWCAST_TASK = "nowcast"
# The nowcast job (every 3 h) reports through the same route with data_quality.task == "nowcast"
_TASKS = {"nowcast": NOWCAST_TASK, "daily-forecast": FORECAST_TASK, "daily_forecast": FORECAST_TASK}
_STATUS_MAP = {"success": "success", "degraded": "partial", "failed": "failed"}


class ForecastRunStatus(BaseModel):
    init_date: str
    status: str = Field(..., description="success | degraded | failed")
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    duration_s: float = 0.0
    n_stations: int = 0
    horizons: List[int] = Field(default_factory=list)
    error: Optional[str] = None
    shadow_summary: Optional[Dict[str, Any]] = None
    drift_alerts: Optional[List[str]] = None


@router.post("/status", summary="Record a daily-forecast run (called by the forecast job)")
async def post_forecast_run_status(
    body: ForecastRunStatus,
    request: Request,
    _: bool = Depends(verify_tasks_token),
) -> Dict[str, Any]:
    from app.ingestion.db import AsyncSessionLocal
    from app.ingestion.runs import RunOutcome, RunRecorder, RunStatus, new_run_id, trigger_from_headers

    status = _STATUS_MAP.get(body.status, "failed")
    task = _task_for(body.data_quality)
    now = datetime.now(timezone.utc)
    outcome = RunOutcome(
        run_id=new_run_id(task),
        task=task,
        provider_code="forecast",
        scope="pakistan",
        trigger=trigger_from_headers(request.headers),
        started_at=now - timedelta(seconds=max(float(body.duration_s or 0.0), 0.0)),
    )
    outcome.counts.expected = outcome.counts.attempted = int(body.n_stations or 0)
    outcome.counts.completed = int(body.n_stations or 0) if status != "failed" else 0
    outcome.counts.rows_written = int(body.n_stations or 0) * max(len(body.horizons), 1) if status != "failed" else 0
    outcome.details = {
        "init_date": body.init_date,
        "init_time": (body.data_quality or {}).get("init_time"),
        "task": task,
        "reported_status": body.status,
        "data_quality": body.data_quality,
        "horizons": body.horizons,
        "n_stations": body.n_stations,
        "duration_s": body.duration_s,
        "drift_alerts": body.drift_alerts,
        "shadow_summary": body.shadow_summary,
    }
    lake_max = (body.data_quality or {}).get("obs_lake_max_date")
    if isinstance(lake_max, str):
        try:
            outcome.latest_observation_ts = datetime.fromisoformat(lake_max).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    recorder = RunRecorder(AsyncSessionLocal, Path(settings.INGEST_OUT_DIR), required=False)
    await recorder.start(outcome)
    if status == "failed":
        outcome.fail("forecast_failed", body.error or "forecast job reported failure")
    elif status == "partial":
        outcome.status = RunStatus.partial
        outcome.error_class = "degraded"
        outcome.error_message = _degraded_reason(body.data_quality, task)
    else:
        outcome.status = RunStatus.success
    outcome.finished_at = now
    await recorder.finish(outcome)

    logger.info("%s run recorded: init=%s status=%s stations=%s run_id=%s",
                task, body.init_date, status, body.n_stations, outcome.run_id)
    return {"ok": True, "run_id": outcome.run_id, "status": status, "task": task}


def _task_for(dq: Optional[Dict[str, Any]]) -> str:
    """ops.ingest_runs task for a report: data_quality.task selects the nowcast, default daily."""
    name = str((dq or {}).get("task") or "").strip().lower()
    return _TASKS.get(name, FORECAST_TASK)


def _degraded_reason(dq: Dict[str, Any], task: str = FORECAST_TASK) -> str:
    parts = []
    if task == NOWCAST_TASK:
        if dq.get("source_ifs") is False:
            parts.append("ifs missing")
        f = dq.get("forecastable_fraction")
        if isinstance(f, (int, float)) and f < 0.3:
            parts.append(f"forecastable fraction {f:.2f}")
        return "; ".join(parts) or "degraded"
    for k in ("ifs", "cams", "geos_cf"):
        if dq.get(k) is False:
            parts.append(f"{k} missing")
    f = dq.get("obs_fresh_fraction")
    if isinstance(f, (int, float)) and f < 0.5:
        parts.append(f"obs fresh fraction {f:.2f}")
    return "; ".join(parts) or "degraded"


@router.get("/latest", summary="Most recent forecast runs (daily-forecast, or task=nowcast)")
async def get_latest_forecast_runs(
    limit: int = Query(7, ge=1, le=60),
    task: str = Query(FORECAST_TASK, description="daily-forecast | nowcast"),
    db: AsyncSession = Depends(get_database),
) -> Dict[str, Any]:
    task = _TASKS.get(task.strip().lower(), FORECAST_TASK)
    sql = text("""
        SELECT run_id, status, started_at, finished_at, error_class, error_message,
               expected_count, details
        FROM ops.ingest_runs
        WHERE task = :task
        ORDER BY started_at DESC
        LIMIT :limit
    """)
    try:
        rows = (await db.execute(sql, {"task": task, "limit": limit})).fetchall()
    except Exception as exc:  # ops schema missing
        return {"runs": [], "task": task, "error": str(exc)[:200]}
    runs = []
    for r in rows:
        m = dict(r._mapping)
        d = m.get("details") or {}
        runs.append({
            "run_id": m["run_id"], "status": m["status"],
            "started_at": m["started_at"].isoformat() if m.get("started_at") else None,
            "finished_at": m["finished_at"].isoformat() if m.get("finished_at") else None,
            "init_date": d.get("init_date"), "init_time": d.get("init_time"), "n_stations": m.get("expected_count"),
            "error_class": m.get("error_class"), "error_message": m.get("error_message"),
            "data_quality": d.get("data_quality"),
        })
    return {"runs": runs, "task": task}
