"""The ICIMOD task endpoint exists under INGEST_ROLE, maps outcomes like the others, and needs the tasks token."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import security
from app.core.security import verify_tasks_token
from app.ingestion.runs import RunOutcome, RunStatus
from app.routers import tasks as tasks_router


def _app(auth: bool = True):
    app = FastAPI()
    app.include_router(tasks_router.router, prefix="/api/v1")
    if auth:
        app.dependency_overrides[verify_tasks_token] = lambda: True
    return app


async def test_icimod_endpoint_maps_outcomes_and_passes_dry_run(monkeypatch):
    from app.services.ingestion.icimod import ingest
    seen = {}

    async def fake_run(self, *, dry_run=False, trigger="http"):
        seen["dry_run"] = dry_run
        o = RunOutcome(run_id="i", task="icimod-ingest", provider_code="icimod",
                       status=RunStatus.partial if dry_run else RunStatus.success)
        o.finished_at = o.started_at
        return o
    monkeypatch.setattr(ingest.ICIMODIngestTask, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(ingest.ICIMODIngestTask, "run", fake_run)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/v1/tasks/icimod/ingest")
        assert r.status_code == 200 and seen["dry_run"] is False
        r = await c.post("/api/v1/tasks/icimod/ingest", params={"dry_run": "true"})
        assert r.status_code == 207 and seen["dry_run"] is True
        st = await c.get("/api/v1/tasks/status")
        assert "POST /tasks/icimod/ingest?dry_run=true|false" in st.json()["available_endpoints"]


async def test_icimod_endpoint_rejects_missing_token(monkeypatch):
    async def not_scheduler(*a, **k):
        return False
    monkeypatch.setattr(security, "verify_cloud_scheduler_request", not_scheduler)
    monkeypatch.setattr(security.settings, "TASKS_API_SECRET", "s3cret", raising=False)
    async with AsyncClient(transport=ASGITransport(app=_app(auth=False)), base_url="http://t") as c:
        r = await c.post("/api/v1/tasks/icimod/ingest")
        assert r.status_code == 401
