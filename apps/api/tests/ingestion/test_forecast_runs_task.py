"""A status report with data_quality.task == "nowcast" is recorded under the nowcast task; the daily job is unchanged."""

from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.security import verify_tasks_token
from app.routers import forecast_runs


class _Recorder:
    """Captures outcomes instead of writing ops.ingest_runs."""
    seen = []

    def __init__(self, *a, **k):
        pass

    async def start(self, outcome):
        pass

    async def finish(self, outcome):
        _Recorder.seen.append(outcome)


def _app():
    app = FastAPI()
    app.include_router(forecast_runs.router, prefix="/api/v1/forecast-runs")

    async def ok():
        return True
    app.dependency_overrides[verify_tasks_token] = ok
    return app


async def _post(body):
    _Recorder.seen.clear()
    with patch("app.ingestion.runs.RunRecorder", _Recorder):
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
            return await c.post("/api/v1/forecast-runs/status", json=body)


async def test_nowcast_report_is_recorded_under_its_own_task():
    r = await _post({"init_date": "2026-11-04", "status": "degraded", "n_stations": 360, "horizons": [3, 6, 12, 24],
                     "duration_s": 42.0,
                     "data_quality": {"task": "nowcast", "init_time": "2026-11-04T09:00:00+00:00",
                                      "source_ifs": False, "forecastable_fraction": 0.9}})
    assert r.status_code == 200, r.text
    assert r.json()["task"] == "nowcast" and r.json()["status"] == "partial"
    out = _Recorder.seen[0]
    assert out.task == "nowcast" and out.run_id.startswith("nowcast")
    assert out.details["init_time"] == "2026-11-04T09:00:00+00:00" and out.details["task"] == "nowcast"
    assert out.error_message == "ifs missing"
    assert out.counts.rows_written == 360 * 4


async def test_daily_report_keeps_the_daily_task():
    r = await _post({"init_date": "2026-11-04", "status": "success", "n_stations": 360, "horizons": [1, 2, 3],
                     "data_quality": {"ifs": True}})
    assert r.status_code == 200 and r.json()["task"] == "daily-forecast"
    assert _Recorder.seen[0].task == "daily-forecast"


def test_task_resolution_defaults_to_daily():
    assert forecast_runs._task_for(None) == "daily-forecast"
    assert forecast_runs._task_for({"task": "NOWCAST "}) == "nowcast"
    assert forecast_runs._task_for({"task": "something-else"}) == "daily-forecast"
