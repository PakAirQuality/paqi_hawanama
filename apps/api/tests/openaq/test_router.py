"""The OpenAQ task endpoints exist under INGEST_ROLE and map outcomes like the others."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.security import verify_tasks_token
from app.ingestion.runs import RunOutcome, RunStatus
from app.routers import tasks as tasks_router


def _app():
    app = FastAPI()
    app.include_router(tasks_router.router, prefix="/api/v1")
    app.dependency_overrides[verify_tasks_token] = lambda: True
    return app


async def test_openaq_endpoints(monkeypatch):
    from app.services.ingestion.openaq import discovery, ingest
    seen = {}

    async def fake_disc(self, *, dry_run=False, trigger="http"):
        seen["dry_run"] = dry_run
        o = RunOutcome(run_id="d", task="openaq-discover", provider_code="openaq", status=RunStatus.success)
        o.finished_at = o.started_at
        return o

    async def fake_ing(self, *, mode="ingest", trigger="http"):
        seen["mode"] = mode
        o = RunOutcome(run_id="i", task="openaq-ingest", provider_code="openaq", status=RunStatus.partial)
        o.finished_at = o.started_at
        return o
    monkeypatch.setattr(discovery.OpenAQDiscoveryTask, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(discovery.OpenAQDiscoveryTask, "run", fake_disc)
    monkeypatch.setattr(ingest.OpenAQIngestTask, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(ingest.OpenAQIngestTask, "run", fake_ing)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/api/v1/tasks/openaq/discover", params={"dry_run": "true"})
        assert r.status_code == 200 and seen["dry_run"] is True
        r = await c.post("/api/v1/tasks/openaq/ingest")
        assert r.status_code == 207 and seen["mode"] == "ingest"
        r = await c.post("/api/v1/tasks/openaq/reconcile")
        assert r.status_code == 207 and seen["mode"] == "reconcile"
        st = await c.get("/api/v1/tasks/status")
        assert "POST /tasks/openaq/ingest" in st.json()["available_endpoints"]
