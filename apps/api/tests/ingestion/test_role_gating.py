"""Each Cloud Run role mounts only what it should."""

import importlib

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _routes(monkeypatch, **env):
    for k in ("BAM_ROLE", "INGEST_ROLE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.main as m
    m = importlib.reload(m)
    return {r.path for r in m.app.routes if hasattr(r, "path")}


def test_bam_role_mounts_only_bam_and_health(monkeypatch):
    paths = _routes(monkeypatch, BAM_ROLE="true")
    assert any(p.startswith("/api/v1/bam") for p in paths)
    assert any(p.startswith("/api/v1/health") for p in paths)
    assert not any(p.startswith(("/api/v1/public", "/api/v1/dashboard", "/api/v1/openaq", "/api/v1/tasks",
                                 "/api/v1/ops", "/api/v1/internal", "/api/v1/stations")) for p in paths)


def test_default_role_mounts_public_but_not_tasks_or_bam(monkeypatch):
    paths = _routes(monkeypatch)
    assert any(p.startswith("/api/v1/dashboard") for p in paths)
    assert any(p.startswith("/api/v1/public") for p in paths)
    assert "/api/v1/stations" in paths
    assert not any(p.startswith("/api/v1/tasks") for p in paths)
    assert not any(p.startswith("/api/v1/bam") for p in paths)


def test_ingest_role_mounts_tasks(monkeypatch):
    paths = _routes(monkeypatch, INGEST_ROLE="true")
    assert "/api/v1/tasks/ingest-stations" in paths and "/api/v1/tasks/status" in paths
    assert not any(p.startswith("/api/v1/bam") for p in paths)


async def test_twitter_dependency_rejects_without_type_error(monkeypatch):
    from app.core import security
    monkeypatch.setattr(security.settings, "TASKS_API_SECRET", "s3cret")
    monkeypatch.delenv("INGEST_ROLE", raising=False)
    scope = {"type": "http", "method": "POST", "path": "/x", "headers": [], "query_string": b"", "client": ("1.2.3.4", 1)}
    req = Request(scope)
    with pytest.raises(HTTPException) as ei:
        await security.verify_twitter_endpoint_access(req, None)
    assert ei.value.status_code == 401
