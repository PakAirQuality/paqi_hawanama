"""
Health endpoints.

  GET /health/            liveness: process is up (no database dependency)
  GET /health/ready       readiness: database answers SELECT 1
  GET /health/freshness   data freshness per readings.source, last run per task;
                          503 when any configured source is older than its threshold
  GET /health/db, /health/metrics   detailed statistics (unchanged semantics)

The old single endpoint only reported `degraded` when the database query itself
failed; a database that answered but had received no readings for a day was
still "ok".
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psutil
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_database
from app.ingestion.provenance import describe as describe_provenance
from app.utils.timefmt import iso_z

logger = logging.getLogger(__name__)
router = APIRouter()


_iso = iso_z   # RFC 3339 with a Z suffix (shared helper)


def _thresholds() -> Dict[str, int]:
    try:
        raw = json.loads(settings.FRESHNESS_MAX_AGE_MIN or "{}")
        out = {str(k): int(v) for k, v in raw.items()}
    except Exception as exc:
        logger.warning("FRESHNESS_MAX_AGE_MIN is not valid JSON (%s); using default 360", exc)
        out = {}
    out.setdefault("default", 360)
    return out


@router.get("/")
async def health_check() -> Dict[str, Any]:
    """Liveness. Deliberately has no database dependency."""
    health_data: Dict[str, Any] = {
        "status": "ok",
        "service": "hawanama-api",
        "version": "1.0.0",
        "timestamp": _iso(datetime.now(timezone.utc)),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "provenance": describe_provenance(),
    }
    try:
        health_data["system"] = {
            # interval=None returns immediately (interval=1 slept a full second per probe)
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        }
    except Exception:
        pass
    return health_data


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_database)):
    """Readiness: the database answers."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "timestamp": _iso(datetime.now(timezone.utc))}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "error": str(exc)[:300],
                                                      "timestamp": _iso(datetime.now(timezone.utc))})


FRESHNESS_SQL = text("""
    SELECT source,
           scope_type::text AS scope_type,
           MAX(ts_utc)      AS latest_ts,
           MAX(ingested_at) AS latest_ingested_at,
           COUNT(DISTINCT scope_key) FILTER (WHERE ts_utc >= now() - interval '24 hours') AS active_24h
    FROM readings
    WHERE ts_utc >= now() - interval '7 days'
    GROUP BY source, scope_type
""")

LAST_RUNS_SQL = text("""
    SELECT DISTINCT ON (task)
           task, run_id, status, started_at, finished_at, error_class,
           expected_count, failed_count, rows_written, latest_observation_ts
    FROM ops.ingest_runs
    ORDER BY task, started_at DESC
""")

# Sources whose freshness comes from ops.ingest_runs rather than readings (task name per source).
RUN_BACKED_SOURCES = {"fires": "ingest-fires"}
LAST_GOOD_RUN_SQL = text("""
    SELECT task, run_id, status, finished_at, latest_observation_ts, rows_written
    FROM ops.ingest_runs
    WHERE task = :task AND status IN ('success', 'partial')
    ORDER BY started_at DESC
    LIMIT 1
""")
# Feeds that are listed for information only while they have no threshold (e.g. the BAM push
# feed while SFL is not sending): shown, never degraded, until a threshold is configured again.
INFORMATIONAL_SOURCES = ("bam",)


@router.get("/freshness")
async def freshness(db: AsyncSession = Depends(get_database)):
    """
    Observation age per readings.source/scope_type against FRESHNESS_MAX_AGE_MIN
    (JSON: {"airvisual": 180, ..., "default": 360}). Sources named in the
    thresholds but absent from the last 7 days are reported degraded too.
    Returns 503 when degraded so uptime checks can alert on stale data.
    """
    now = datetime.now(timezone.utc)
    thresholds = _thresholds()
    try:
        rows = (await db.execute(FRESHNESS_SQL)).fetchall()
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "degraded", "error": f"readings query failed: {str(exc)[:300]}",
                                                      "timestamp": _iso(now)})

    sources: List[Dict[str, Any]] = []
    seen = set()
    for r in rows:
        m = dict(r._mapping)
        source = m["source"] or "unknown"
        seen.add(source)
        latest = m["latest_ts"]
        if latest is not None and latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age_min = int((now - latest).total_seconds() // 60) if latest else None
        informational = source in INFORMATIONAL_SOURCES and source not in thresholds
        limit = None if informational else thresholds.get(source, thresholds["default"])
        sources.append({
            "source": source, "scope_type": m["scope_type"],
            "latest_ts": _iso(latest), "latest_ingested_at": _iso(m["latest_ingested_at"]),
            "active_24h": int(m["active_24h"] or 0),
            "age_min": age_min, "threshold_min": limit,
            "status": "no_threshold" if informational else ("ok" if (age_min is not None and age_min <= limit) else "degraded"),
        })
    for source, limit in thresholds.items():
        if source != "default" and source not in seen and source not in RUN_BACKED_SOURCES:
            sources.append({"source": source, "scope_type": None, "latest_ts": None, "latest_ingested_at": None,
                            "active_24h": 0, "age_min": None, "threshold_min": limit, "status": "degraded"})
    for source in INFORMATIONAL_SOURCES:
        if source not in seen and source not in thresholds:
            sources.append({"source": source, "scope_type": None, "latest_ts": None, "latest_ingested_at": None,
                            "active_24h": 0, "age_min": None, "threshold_min": None, "status": "no_threshold"})

    runs: List[Dict[str, Any]] = []
    runs_error: Optional[str] = None
    try:
        for r in (await db.execute(LAST_RUNS_SQL)).fetchall():
            m = dict(r._mapping)
            started = m["started_at"]
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            stale_running = (m["status"] == "running" and started is not None and
                             (now - started).total_seconds() > int(settings.INGEST_LEASE_TTL_S))
            runs.append({
                "task": m["task"], "run_id": m["run_id"],
                "status": "stale_running" if stale_running else m["status"],
                "started_at": _iso(started), "finished_at": _iso(m["finished_at"]),
                "error_class": m["error_class"], "expected": m["expected_count"], "failed": m["failed_count"],
                "rows_written": m["rows_written"], "latest_observation_ts": _iso(m["latest_observation_ts"]),
            })
    except Exception as exc:
        # ops.ingest_runs may not exist yet (migration 001 not applied); not a freshness failure.
        runs_error = str(exc)[:200]

    # Run-backed sources (fires): degraded when the last run failed, when no run has ever
    # succeeded, or when the last success is older than the threshold.
    for source, task in RUN_BACKED_SOURCES.items():
        if source not in thresholds:
            continue
        limit = thresholds[source]
        last = next((r for r in runs if r["task"] == task), None)
        good = None
        if runs_error is None:
            try:
                row = (await db.execute(LAST_GOOD_RUN_SQL, {"task": task})).fetchone()
                good = dict(row._mapping) if row else None
            except Exception as exc:
                runs_error = str(exc)[:200]
        finished = good["finished_at"] if good else None
        if finished is not None and finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        age_min = int((now - finished).total_seconds() // 60) if finished else None
        last_failed = bool(last and last["status"] in ("failed", "stale_running"))
        status = "ok" if (age_min is not None and age_min <= limit and not last_failed) else "degraded"
        latest_obs = good["latest_observation_ts"] if good else None
        if latest_obs is not None and latest_obs.tzinfo is None:
            latest_obs = latest_obs.replace(tzinfo=timezone.utc)
        sources.append({
            "source": source, "scope_type": "run", "task": task,
            "latest_ts": _iso(latest_obs), "latest_ingested_at": _iso(finished),
            "active_24h": int(good["rows_written"] or 0) if good else 0,
            "age_min": age_min, "threshold_min": limit, "status": status,
            "last_run_status": last["status"] if last else None,
            "last_run_error": last["error_class"] if last else None,
        })

    degraded = any(s["status"] == "degraded" for s in sources)
    body = {
        "status": "degraded" if degraded else "ok",
        "timestamp": _iso(now),
        "sources": sources,
        "runs": runs,
        "runs_error": runs_error,
        "thresholds_min": thresholds,
    }
    return JSONResponse(status_code=503 if degraded else 200, content=body)


@router.get("/db")
async def health_check_db(db: AsyncSession = Depends(get_database)):
    """Detailed database health check"""
    try:
        await db.execute(text("SELECT 1"))
        stats_query = text("""
            SELECT
                (SELECT COUNT(*) FROM stations) as total_stations,
                (SELECT COUNT(*) FROM readings WHERE ts_utc >= NOW() - INTERVAL '1 hour') as readings_last_hour,
                (SELECT COUNT(*) FROM readings WHERE ts_utc >= NOW() - INTERVAL '24 hours') as readings_last_24h,
                (SELECT MAX(ts_utc) FROM readings) as latest_reading,
                (SELECT pg_size_pretty(pg_database_size(current_database()))) as database_size
        """)
        result = await db.execute(stats_query)
        stats = dict(result.fetchone()._mapping)
        return {
            "status": "ok",
            "database": "connected",
            "statistics": {
                "total_stations": stats["total_stations"],
                "readings_last_hour": stats["readings_last_hour"],
                "readings_last_24h": stats["readings_last_24h"],
                "latest_reading": _iso(stats["latest_reading"]),
                "database_size": stats["database_size"],
            },
        }
    except Exception as e:
        return {"status": "error", "database": str(e)}


@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_database)) -> Dict[str, Any]:
    """Get detailed API metrics"""
    try:
        metrics_query = text("""
            SELECT
                (SELECT COUNT(*) FROM stations) as total_stations,
                COUNT(DISTINCT CASE WHEN r.ts_utc >= NOW() - INTERVAL '1 hour' THEN r.scope_key END) as active_stations_1h,
                COUNT(DISTINCT CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN r.scope_key END) as active_stations_24h,
                COUNT(CASE WHEN r.ts_utc >= NOW() - INTERVAL '1 hour' THEN 1 END) as readings_1h,
                COUNT(CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN 1 END) as readings_24h,
                AVG(CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN r.pm25 END) as avg_pm25_24h,
                AVG(CASE WHEN r.ts_utc >= NOW() - INTERVAL '24 hours' THEN r.aqi_us END) as avg_aqi_24h,
                MAX(r.ts_utc) as latest_reading
            FROM readings r
            WHERE r.scope_type = 'station'
        """)
        result = await db.execute(metrics_query)
        metrics = dict(result.fetchone()._mapping)
        return {
            "timestamp": _iso(datetime.now(timezone.utc)),
            "stations": {
                "total": metrics["total_stations"],
                "active_1h": metrics["active_stations_1h"],
                "active_24h": metrics["active_stations_24h"],
            },
            "readings": {"last_1h": metrics["readings_1h"], "last_24h": metrics["readings_24h"]},
            "air_quality": {
                "avg_pm25_24h": float(metrics["avg_pm25_24h"]) if metrics["avg_pm25_24h"] else None,
                "avg_aqi_24h": float(metrics["avg_aqi_24h"]) if metrics["avg_aqi_24h"] else None,
            },
            "data_freshness": {"latest_reading": _iso(metrics["latest_reading"])},
        }
    except Exception as e:
        return {"error": str(e), "timestamp": _iso(datetime.now(timezone.utc))}
