"""
IQAir client transport behaviour, exercised against respx mocks (no network).
"""

import logging

import httpx
import pytest
import respx

from app.ingestion.http import configure_logging
from app.services.ingestion.iqair_service import (IQAirClient, IQAirError, RateLimited, StationNotFound,
                                                  TransientError, Unauthorized)
from tests.ingestion.fakes import make_settings

BASE = "https://api.airvisual.com/v2"
OK = {"status": "success", "data": [{"country": "Pakistan"}]}


class SleepSpy:
    def __init__(self):
        self.calls = []

    async def __call__(self, secs):
        self.calls.append(secs)


class FakeQuota:
    """Counts reservations; optionally denies the first N (raising) or records waits."""

    def __init__(self, deny_first: int = 0):
        self.reservations = 0
        self.deny_first = deny_first

    async def reserve_or_wait(self, alias, *, limit_per_min, max_wait_s):
        self.reservations += 1
        if self.deny_first > 0:
            self.deny_first -= 1
            raise RateLimited("shared_quota_exhausted", retry_after_s=1)


def _client(tmp_path, **kw):
    s = make_settings(tmp_path, IQAIR_RETRY_MAX_ATTEMPTS=4, IQAIR_RETRY_MAX_WAIT_S=0.01)
    sleep = SleepSpy()
    quota = kw.pop("quota", FakeQuota())
    c = IQAirClient(settings=s, quota=quota, retry_sleep=sleep, **kw)
    return c, sleep, quota


@respx.mock
async def test_requests_use_https_and_key_param(tmp_path):
    route = respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(200, json=OK))
    c, _, quota = _client(tmp_path)
    data = await c.get_countries()
    assert data == OK["data"]
    req = route.calls.last.request
    assert req.url.scheme == "https" and req.url.params["key"] == "sk-test-SECRET-9f2a"
    assert quota.reservations == 1


@respx.mock
async def test_503_then_200_is_retried_and_each_attempt_reserved(tmp_path):
    route = respx.get(f"{BASE}/countries").mock(side_effect=[httpx.Response(503, text="boom-body"), httpx.Response(200, json=OK)])
    c, sleep, quota = _client(tmp_path)
    assert await c.get_countries() == OK["data"]
    assert route.call_count == 2 and quota.reservations == 2 and len(sleep.calls) == 1


@respx.mock
async def test_5xx_body_is_never_logged(tmp_path, caplog):
    respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(500, text="SECRET-BODY-CONTENT"))
    c, _, _ = _client(tmp_path)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TransientError):
            await c.get_countries()
    assert "SECRET-BODY-CONTENT" not in caplog.text


@pytest.mark.parametrize("code", [401, 403])
@respx.mock
async def test_auth_failure_is_persistent_and_not_retried(tmp_path, code):
    route = respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(code, json={"status": "fail"}))
    c, sleep, quota = _client(tmp_path)
    with pytest.raises(Unauthorized):
        await c.get_countries()
    assert route.call_count == 1 and quota.reservations == 1 and sleep.calls == []


@respx.mock
async def test_429_waits_at_least_retry_after(tmp_path):
    route = respx.get(f"{BASE}/countries").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json=OK)])
    c, sleep, _ = _client(tmp_path)
    assert await c.get_countries() == OK["data"]
    assert route.call_count == 2
    assert len(sleep.calls) == 1 and sleep.calls[0] >= 7


@respx.mock
async def test_network_errors_retried_then_transient(tmp_path):
    route = respx.get(f"{BASE}/countries").mock(side_effect=httpx.ConnectError("refused"))
    c, sleep, quota = _client(tmp_path)
    with pytest.raises(TransientError):
        await c.get_countries()
    assert route.call_count == 4 and quota.reservations == 4 and len(sleep.calls) == 3


@respx.mock
async def test_shared_quota_denial_is_retried_then_succeeds(tmp_path):
    route = respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(200, json=OK))
    c, sleep, quota = _client(tmp_path, quota=FakeQuota(deny_first=2))
    assert await c.get_countries() == OK["data"]
    assert route.call_count == 1 and quota.reservations == 3 and len(sleep.calls) == 2


@respx.mock
async def test_shared_quota_exhausted_raises_rate_limited(tmp_path):
    respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(200, json=OK))
    c, _, quota = _client(tmp_path, quota=FakeQuota(deny_first=99))
    with pytest.raises(RateLimited):
        await c.get_countries()
    assert quota.reservations == 4  # bounded by IQAIR_RETRY_MAX_ATTEMPTS


@respx.mock
async def test_api_fail_messages_map_to_typed_errors(tmp_path):
    respx.get(f"{BASE}/station").mock(return_value=httpx.Response(200, json={"status": "fail", "data": {"message": "station_not_found"}}))
    c, _, _ = _client(tmp_path)
    with pytest.raises(StationNotFound):
        await c.get_station_data(station="X", city="Lahore", state="Punjab", country="Pakistan")


@respx.mock
async def test_invalid_json_is_not_retried(tmp_path):
    route = respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(200, text="<html>"))
    c, _, _ = _client(tmp_path)
    with pytest.raises(IQAirError):
        await c.get_countries()
    assert route.call_count == 1


@respx.mock
async def test_key_never_appears_in_logs_even_with_verbose_httpx(tmp_path, caplog):
    configure_logging("DEBUG", secrets=("sk-test-SECRET-9f2a",))
    respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(200, json=OK))
    c, _, _ = _client(tmp_path)
    httpx_logger = logging.getLogger("httpx")
    old = httpx_logger.level
    httpx_logger.setLevel(logging.DEBUG)   # simulate someone turning request logging back on
    try:
        with caplog.at_level(logging.DEBUG):
            await c.get_countries()
            logging.getLogger("x").info("manual %s", f"{BASE}/countries?key=sk-test-SECRET-9f2a")
    finally:
        httpx_logger.setLevel(old)
    assert "sk-test-SECRET-9f2a" not in caplog.text
    assert "key=***" in caplog.text


def test_no_arg_constructor_still_works_for_read_path_services(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "IQAIR_API_KEY", "sk-test")
    from app.ingestion.quota import PostgresQuota
    c = IQAirClient()
    assert isinstance(c.quota, PostgresQuota) and c.quota._required is False
    assert c.base_url.startswith("https://")
    assert IQAirClient(quota=None).quota is None
