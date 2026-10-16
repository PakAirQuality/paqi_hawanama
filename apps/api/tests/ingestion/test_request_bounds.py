"""Request bounds, export destinations, bounded blob cache and scheduler token gating."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.filecache import BlobMissing, BoundedBlobCache
from app.routers.exports_publish import _check_target
from app.routers.internal_stations import _bounded_window
from app.routers.ops_pipeline import _check_model, _check_pred_date


def test_bounded_window_defaults_and_limits():
    f, t = _bounded_window(None, None, max_days=400)
    assert t - f == timedelta(days=365)
    now = datetime.now(timezone.utc)
    with pytest.raises(HTTPException) as ei:
        _bounded_window(now, now - timedelta(hours=1), max_days=400)
    assert ei.value.status_code == 400
    with pytest.raises(HTTPException) as ei:
        _bounded_window(now - timedelta(days=401), now, max_days=400)
    assert ei.value.status_code == 400
    f2, t2 = _bounded_window(datetime(2026, 1, 1), datetime(2026, 1, 10), max_days=31)
    assert f2.tzinfo is not None and t2.tzinfo is not None


def test_export_target_allow_list(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXPORT_GCS_ALLOWED", "paqi-raw-hawanama-data, other-bucket/raw")
    _check_target("paqi-raw-hawanama-data", "raw/station_hourly")
    _check_target("other-bucket", "raw/station_daily/date=2026-01-01")
    for bucket, key in [
        ("someone-elses-bucket", "raw/x"),
        ("other-bucket", "models/latest.pkl"),
        ("paqi-raw-hawanama-data", "../escape"),
    ]:
        with pytest.raises(HTTPException) as ei:
            _check_target(bucket, key)
        assert ei.value.status_code == 400


def test_pred_date_and_model_validation():
    assert _check_pred_date("2026-10-16") == "2026-10-16"
    for bad in ["2026-13-40", "yesterday", "2026-10-16/../x", ""]:
        with pytest.raises(HTTPException):
            _check_pred_date(bad)
    assert _check_model("urban/lahore") == "urban/lahore"
    for bad in ["urban/../x", "anything", "urban/Lahore City"]:
        with pytest.raises(HTTPException):
            _check_model(bad)


def test_bounded_blob_cache_evicts_and_remembers_missing():
    cache = BoundedBlobCache("t", max_files=2, max_absent=2)
    made = []

    def downloader(name):
        def _dl():
            fd, path = tempfile.mkstemp(prefix=name)
            os.close(fd)
            made.append(path)
            return path
        return _dl

    p1 = cache.get_or_download("a", downloader("a"))
    p2 = cache.get_or_download("b", downloader("b"))
    assert cache.get_or_download("a", downloader("a2")) == p1  # cached, no second download
    cache.get_or_download("c", downloader("c"))                # evicts b (least recently used)
    assert not os.path.exists(p2) and os.path.exists(p1)
    assert cache.stats()["files"] == 2

    def missing():
        raise BlobMissing("x")

    with pytest.raises(HTTPException) as ei:
        cache.get_or_download("gone", missing)
    assert ei.value.status_code == 404
    calls = {"n": 0}

    def missing_counted():
        calls["n"] += 1
        raise BlobMissing("x")

    with pytest.raises(HTTPException):
        cache.get_or_download("gone", missing_counted)
    assert calls["n"] == 0  # served from the negative cache
    for p in made:
        if os.path.exists(p):
            os.unlink(p)


@pytest.mark.asyncio
async def test_scheduler_bypass_requires_verified_id_token(monkeypatch):
    from starlette.requests import Request
    from app.core import security

    monkeypatch.setenv("INGEST_ROLE", "true")

    def req(auth: str) -> Request:
        scope = {"type": "http", "method": "POST", "path": "/", "query_string": b"",
                 "headers": [(b"authorization", auth.encode()), (b"x-cloudscheduler", b"true"),
                             (b"user-agent", b"Google-Cloud-Scheduler")]}
        return Request(scope)

    # Scheduler-looking headers plus an arbitrary bearer are no longer enough.
    assert await security.verify_cloud_scheduler_request(req("Bearer not-a-jwt")) is False
    # A well-formed but unverifiable JWT is rejected too.
    monkeypatch.setattr(security, "_verify_google_id_token", lambda token, aud: None)
    assert await security.verify_cloud_scheduler_request(req("Bearer a.b.c")) is False
    # A verified token for the wrong principal is rejected.
    monkeypatch.setattr(security, "_verify_google_id_token",
                        lambda token, aud: {"email": "someone@example.com", "email_verified": True})
    assert await security.verify_cloud_scheduler_request(req("Bearer a.b.c")) is False
    # The scheduler service account passes.
    from app.core.config import settings
    monkeypatch.setattr(security, "_verify_google_id_token",
                        lambda token, aud: {"email": settings.SCHEDULER_SERVICE_ACCOUNT, "email_verified": True})
    assert await security.verify_cloud_scheduler_request(req("Bearer a.b.c")) is True
