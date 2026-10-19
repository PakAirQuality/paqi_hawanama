"""POST /fires/ingest is recorded as a run and its HTTP status follows the run."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.security import verify_tasks_token
from app.ingestion.runs import RunRecorder
from app.routers import analyst_desk
from app.services import fires

RAW = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
31.5,74.3,330.1,0.4,0.4,2026-10-16,2045,N20,VIIRS,n,2.0NRT,290.1,12.34,N
"""
KEY_OK = '{ "transaction_limit" : 5000, "current_transactions": 1, "transaction_interval" : "10 minutes" }'


class _Resp:
    def __init__(self, status_code, text):
        self.status_code, self.text = status_code, text


class _Http:
    def __init__(self, by_source, key_status=KEY_OK):
        self.by_source, self.key_status = by_source, key_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        if "mapkey_status" in url:
            return _Resp(200, self.key_status)
        for src, resp in self.by_source.items():
            if f"/{src}/" in url:
                return resp
        return _Resp(404, "")


class _Blob:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def upload_from_string(self, data, content_type=None):
        self.store[self.path] = data


class _Bucket:
    def __init__(self):
        self.store = {}

    def blob(self, path):
        return _Blob(self.store, path)


class _Client:
    def __init__(self):
        self.b = _Bucket()

    def bucket(self, name):
        return self.b


class _RecordingRecorder(RunRecorder):
    """No DB: keeps the finished outcome so the test can inspect it."""
    last = None

    async def finish(self, outcome):
        await super().finish(outcome)
        _RecordingRecorder.last = outcome


@pytest.fixture
def app(monkeypatch, tmp_path):
    a = FastAPI()
    a.include_router(analyst_desk.router, prefix="/api/v1/ops/analyst-desk")
    a.dependency_overrides[verify_tasks_token] = lambda: True
    monkeypatch.setattr(settings, "FIRMS_MAP_KEY", "k")
    monkeypatch.setattr(analyst_desk, "_gcs_client", lambda: _Client())
    monkeypatch.setattr(analyst_desk, "_fire_recorder", lambda: _RecordingRecorder(None, tmp_path))

    async def instant(_s):
        return None
    monkeypatch.setattr(fires, "_sleep", instant)
    return a


def _use_http(monkeypatch, http):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: http)


async def _post(app, path, headers=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(path, headers=headers or {})


@pytest.mark.asyncio
async def test_success_is_200_and_recorded(app, monkeypatch):
    _use_http(monkeypatch, _Http({s: _Resp(200, RAW) for s in ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT")}))
    r = await _post(app, "/api/v1/ops/analyst-desk/fires/ingest?window_days=3&date=2026-10-17",
                    headers={"user-agent": "Google-Cloud-Scheduler"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success" and body["run_id"].startswith("ingest-fires")
    out = _RecordingRecorder.last
    assert out.task == "ingest-fires" and out.provider_code == "firms" and out.trigger == "scheduler"
    assert out.counts.expected == 3 and out.counts.completed == 3 and out.counts.rows_fetched == 3
    assert out.latest_observation_ts == datetime(2026, 10, 16, 20, 45, tzinfo=timezone.utc)
    assert out.details["key"]["status"] == "ok" and out.details["config"]["window_days"] == 3


@pytest.mark.asyncio
async def test_one_failed_satellite_is_207_partial(app, monkeypatch):
    _use_http(monkeypatch, _Http({"VIIRS_NOAA20_NRT": _Resp(200, RAW), "VIIRS_NOAA21_NRT": _Resp(500, ""),
                                  "VIIRS_SNPP_NRT": _Resp(200, RAW)}))
    r = await _post(app, "/api/v1/ops/analyst-desk/fires/ingest?date=2026-10-17")
    assert r.status_code == 207 and r.json()["status"] == "partial"
    out = _RecordingRecorder.last
    failed = [x["source"] for x in out.details["sources"] if x["status"] != "ok"]
    assert out.counts.failed == 1 and failed == ["VIIRS_NOAA21_NRT"]


@pytest.mark.asyncio
async def test_invalid_key_is_500_failed_invalid_key(app, monkeypatch):
    _use_http(monkeypatch, _Http({"VIIRS_NOAA20_NRT": _Resp(200, RAW)}, key_status="MAP_KEY is invalid"))
    r = await _post(app, "/api/v1/ops/analyst-desk/fires/ingest?date=2026-10-17")
    assert r.status_code == 500
    body = r.json()
    assert body["status"] == "failed" and body["summary"]["error_class"] == "invalid_key"
    assert "k" != body["summary"]["error_message"] and "secret version" in body["summary"]["error_message"]


@pytest.mark.asyncio
async def test_every_satellite_down_is_500_all_sources_failed(app, monkeypatch):
    _use_http(monkeypatch, _Http({s: _Resp(503, "") for s in ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT")}))
    r = await _post(app, "/api/v1/ops/analyst-desk/fires/ingest?date=2026-10-17")
    assert r.status_code == 500 and r.json()["summary"]["error_class"] == "all_sources_failed"


@pytest.mark.asyncio
async def test_missing_key_is_500_missing_key(app, monkeypatch):
    monkeypatch.setattr(settings, "FIRMS_MAP_KEY", None)
    r = await _post(app, "/api/v1/ops/analyst-desk/fires/ingest?date=2026-10-17")
    assert r.status_code == 500 and r.json()["summary"]["error_class"] == "missing_key"


def test_backfill_route_is_gone():
    assert not any(getattr(r, "path", "").endswith("/fires/backfill") for r in analyst_desk.router.routes)
