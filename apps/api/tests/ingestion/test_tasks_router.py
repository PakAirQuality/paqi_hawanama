"""The task endpoints answer with the run's real status code."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.security import verify_tasks_token
from app.ingestion.runs import RunCounts, RunOutcome, RunStatus
from app.routers import tasks as tasks_router


def _app():
    app = FastAPI()
    app.include_router(tasks_router.router, prefix="/api/v1")
    app.dependency_overrides[verify_tasks_token] = lambda: True
    return app


def _outcome(status, **kw):
    o = RunOutcome(run_id="run-x", task="ingest-stations", provider_code="airvisual", status=status,
                   counts=RunCounts(expected=3, attempted=3, completed=2, failed=1), **kw)
    o.finished_at = o.started_at
    return o


@pytest.mark.parametrize("status,code", [
    (RunStatus.success, 200), (RunStatus.partial, 207), (RunStatus.failed, 500), (RunStatus.skipped, 200),
])
async def test_station_ingest_status_codes(monkeypatch, status, code):
    captured = {}

    async def fake_run(self, *, trigger="http"):
        captured["trigger"] = trigger
        return _outcome(status)
    monkeypatch.setattr(tasks_router.DataIngestionTask, "fetch_station_readings", fake_run)
    monkeypatch.setattr(tasks_router.DataIngestionTask, "__init__", lambda self, **kw: None)

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/v1/tasks/ingest-stations", headers={"X-CloudScheduler": "true"})
    assert r.status_code == code
    body = r.json()
    assert body["status"] == status.value and body["run_id"] == "run-x"
    assert body["summary"]["counts"]["failed"] == 1
    assert body["provenance"]["provenance"].startswith("hawanama.ingestion")
    assert captured["trigger"] == "scheduler"


async def test_trigger_defaults_to_http(monkeypatch):
    captured = {}

    async def fake_run(self, country=None, *, trigger="http"):
        captured["trigger"] = trigger
        return _outcome(RunStatus.success)
    monkeypatch.setattr(tasks_router.CityIngestionTask, "fetch_city_readings_hourly", fake_run)
    monkeypatch.setattr(tasks_router.CityIngestionTask, "__init__", lambda self, **kw: None)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/v1/tasks/ingest-cities")
    assert r.status_code == 200 and captured["trigger"] == "http"


async def test_full_pipeline_reports_worst_status(monkeypatch):
    async def disc(self, country=None, *, trigger="http"):
        return _outcome(RunStatus.success)

    async def st(self, *, trigger="http"):
        return _outcome(RunStatus.failed)

    async def ci(self, country=None, *, trigger="http"):
        return _outcome(RunStatus.partial)
    for cls, name, fn in [(tasks_router.StationDiscoveryTask, "discover_all_stations_comprehensive", disc),
                          (tasks_router.DataIngestionTask, "fetch_station_readings", st),
                          (tasks_router.CityIngestionTask, "fetch_city_readings_hourly", ci)]:
        monkeypatch.setattr(cls, name, fn)
        monkeypatch.setattr(cls, "__init__", lambda self, **kw: None)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/v1/tasks/full-pipeline")
    assert r.status_code == 500 and r.json()["status"] == "failed"
    assert set(r.json()["summary"]) == {"discovery", "station_ingestion", "city_ingestion"}
