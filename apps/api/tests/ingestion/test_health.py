"""Liveness has no DB dependency; readiness and freshness report real state; timestamps are RFC 3339 Z."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import get_database
from app.routers import health

Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


class _Row:
    def __init__(self, d):
        self._mapping = d


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return [_Row(r) for r in self._rows]

    def fetchone(self):
        return _Row(self._rows[0]) if self._rows else None


class FakeDB:
    """Routes statements by a substring of their SQL to scripted rows or exceptions."""

    def __init__(self, script):
        self.script = script

    async def execute(self, sql, params=None):
        s = str(sql)
        for key, val in self.script.items():
            if key in s:
                if isinstance(val, Exception):
                    raise val
                return _Result(val)
        raise AssertionError(f"unexpected SQL: {s[:80]}")


def _app(db):
    app = FastAPI()
    app.include_router(health.router, prefix="/api/v1/health")

    async def override():
        yield db
    app.dependency_overrides[get_database] = override
    return app


async def _get(app, path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


def test_iso_never_emits_plus0000z():
    aware = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)
    naive = datetime(2026, 10, 15, 12, 30)
    assert health._iso(aware) == "2026-10-15T12:30:00Z"
    assert health._iso(naive) == "2026-10-15T12:30:00Z"
    assert health._iso(None) is None


async def test_liveness_has_no_db_dependency():
    class Exploding:
        async def execute(self, *a, **k):
            raise RuntimeError("db down")
    r = await _get(_app(Exploding()), "/api/v1/health/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and Z_RE.match(body["timestamp"]) and "provenance" in body


async def test_ready_503_on_db_error():
    r = await _get(_app(FakeDB({"SELECT 1": RuntimeError("no db")})), "/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"


async def test_ready_200():
    r = await _get(_app(FakeDB({"SELECT 1": [{}]})), "/api/v1/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def _freshness_rows(age_min_airvisual):
    now = datetime.now(timezone.utc)
    return [{"source": "airvisual", "scope_type": "station", "latest_ts": now - timedelta(minutes=age_min_airvisual),
             "latest_ingested_at": now, "active_24h": 210}]


async def test_freshness_degraded_over_threshold(monkeypatch):
    monkeypatch.setattr(settings, "FRESHNESS_MAX_AGE_MIN", '{"airvisual": 180, "default": 360}')
    db = FakeDB({"FROM readings": _freshness_rows(240), "ops.ingest_runs": []})
    r = await _get(_app(db), "/api/v1/health/freshness")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    av = next(s for s in body["sources"] if s["source"] == "airvisual")
    assert av["status"] == "degraded" and av["threshold_min"] == 180 and 239 <= av["age_min"] <= 241


async def test_freshness_ok_under_threshold_and_missing_source_is_degraded(monkeypatch):
    monkeypatch.setattr(settings, "FRESHNESS_MAX_AGE_MIN", '{"airvisual": 180, "default": 360}')
    db = FakeDB({"FROM readings": _freshness_rows(30), "ops.ingest_runs": []})
    r = await _get(_app(db), "/api/v1/health/freshness")
    assert r.status_code == 200 and r.json()["status"] == "ok"

    monkeypatch.setattr(settings, "FRESHNESS_MAX_AGE_MIN", '{"airvisual": 180, "punjab": 180, "default": 360}')
    r = await _get(_app(db), "/api/v1/health/freshness")
    assert r.status_code == 503
    assert next(s for s in r.json()["sources"] if s["source"] == "punjab")["age_min"] is None


async def test_freshness_reports_last_runs_and_stale_running(monkeypatch):
    monkeypatch.setattr(settings, "FRESHNESS_MAX_AGE_MIN", '{"default": 360}')
    monkeypatch.setattr(settings, "INGEST_LEASE_TTL_S", 3300)
    now = datetime.now(timezone.utc)
    runs = [
        {"task": "ingest-stations", "run_id": "r1", "status": "running", "started_at": now - timedelta(hours=2),
         "finished_at": None, "error_class": None, "expected_count": 3, "failed_count": 0, "rows_written": 0,
         "latest_observation_ts": None},
        {"task": "ingest-cities", "run_id": "r2", "status": "partial", "started_at": now - timedelta(minutes=5),
         "finished_at": now, "error_class": None, "expected_count": 10, "failed_count": 2, "rows_written": 80,
         "latest_observation_ts": now - timedelta(minutes=70)},
    ]
    db = FakeDB({"FROM readings": _freshness_rows(10), "ops.ingest_runs": runs})
    r = await _get(_app(db), "/api/v1/health/freshness")
    body = r.json()
    assert r.status_code == 200
    by_task = {x["task"]: x for x in body["runs"]}
    assert by_task["ingest-stations"]["status"] == "stale_running"
    assert by_task["ingest-cities"]["status"] == "partial"
    for ts in (body["timestamp"], by_task["ingest-cities"]["finished_at"], body["sources"][0]["latest_ts"]):
        assert Z_RE.match(ts) and "+00:00" not in ts


async def test_freshness_tolerates_missing_ops_table(monkeypatch):
    monkeypatch.setattr(settings, "FRESHNESS_MAX_AGE_MIN", '{"default": 360}')
    db = FakeDB({"FROM readings": _freshness_rows(10), "ops.ingest_runs": RuntimeError('relation "ops.ingest_runs" does not exist')})
    r = await _get(_app(db), "/api/v1/health/freshness")
    assert r.status_code == 200 and r.json()["runs"] == [] and "does not exist" in r.json()["runs_error"]


async def test_metrics_and_db_timestamps_are_z():
    now = datetime.now(timezone.utc)
    db = FakeDB({"SELECT 1": [{}],
                 "pg_database_size": [{"total_stations": 1, "readings_last_hour": 2, "readings_last_24h": 3,
                                       "latest_reading": now, "database_size": "1 MB"}],
                 "active_stations_1h": [{"total_stations": 1, "active_stations_1h": 1, "active_stations_24h": 1,
                                         "readings_1h": 1, "readings_24h": 1, "avg_pm25_24h": 10.0, "avg_aqi_24h": 40.0,
                                         "latest_reading": now}]})
    app = _app(db)
    r1 = await _get(app, "/api/v1/health/db")
    r2 = await _get(app, "/api/v1/health/metrics")
    assert Z_RE.match(r1.json()["statistics"]["latest_reading"])
    assert Z_RE.match(r2.json()["data_freshness"]["latest_reading"]) and Z_RE.match(r2.json()["timestamp"])
