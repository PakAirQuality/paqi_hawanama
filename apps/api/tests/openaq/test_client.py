"""OpenAQ client: budget reservation, rate-limit handling, auth failure, pagination guard (respx)."""

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.ingestion.quota import LocalQuota, QuotaExhausted
from app.services.ingestion.openaq.client import (BudgetExhausted, OpenAQAuthError, OpenAQClient, OpenAQTransient,
                                                  PaginationAnomaly)
from tests.ingestion.fakes import make_settings
from tests.openaq.fixtures import BASE, location, page


class SleepSpy:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


class CountingQuota(LocalQuota):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.reservations = 0
        self.hour_limits = []

    async def reserve(self, alias, *, limit_per_min, limit_per_hour=None):
        self.reservations += 1
        self.hour_limits.append(limit_per_hour)
        return await super().reserve(alias, limit_per_min=limit_per_min, limit_per_hour=limit_per_hour)


def _client(tmp_path, **kw):
    s = make_settings(tmp_path, OPENAQ_BASE_URL=BASE, OPENAQ_API_KEY="oq-SECRET-key-123456", OPENAQ_ENABLED=True,
                      OPENAQ_RATE_PER_MIN=45, OPENAQ_RATE_PER_HOUR=1500)
    quota = kw.pop("quota", CountingQuota())
    sleep = SleepSpy()
    return OpenAQClient(settings=s, quota=quota, retry_sleep=sleep, **kw), quota, sleep


@respx.mock
async def test_key_in_header_and_every_attempt_reserved(tmp_path):
    route = respx.get(f"{BASE}/locations").mock(side_effect=[httpx.Response(503), httpx.Response(200, json=page([location(1)]))])
    c, quota, sleep = _client(tmp_path)
    payload, rate, status, fetched_at = await c.get("locations", {"iso": "PK"})
    assert route.call_count == 2 and quota.reservations == 2 and c.requests_made == 2
    req = route.calls.last.request
    assert req.headers["X-API-Key"] == "oq-SECRET-key-123456" and "key" not in str(req.url)
    assert quota.hour_limits == [1500, 1500] and len(sleep.calls) == 1 and fetched_at.tzinfo is not None


@respx.mock
async def test_auth_failure_is_persistent(tmp_path):
    route = respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(401))
    c, quota, _ = _client(tmp_path)
    with pytest.raises(OpenAQAuthError):
        await c.get("locations")
    assert route.call_count == 1


@respx.mock
async def test_429_honours_reset_seconds_and_epoch(tmp_path):
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    route = respx.get(f"{BASE}/locations").mock(side_effect=[
        httpx.Response(429, headers={"x-ratelimit-reset": "7"}),
        httpx.Response(429, headers={"x-ratelimit-reset": str(now_epoch + 5)}),
        httpx.Response(200, json=page([])),
    ])
    c, _, sleep = _client(tmp_path)
    await c.get("locations")
    assert route.call_count == 3 and len(sleep.calls) == 2
    assert sleep.calls[0] >= 7 and 3 <= sleep.calls[1] <= 8


@respx.mock
async def test_remaining_zero_sets_cooldown(tmp_path):
    respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(200, json=page([]), headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "30"}))
    c, _, sleep = _client(tmp_path)
    await c.get("locations")
    assert c.cooldown_until is not None
    await c.get("locations")                       # second call waits out the cooldown
    assert sleep.calls and 25 <= sleep.calls[0] <= 30


@respx.mock
async def test_per_run_cap_and_shared_budget_raise_budget_exhausted(tmp_path):
    respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(200, json=page([])))
    c, _, _ = _client(tmp_path, max_requests=2)
    await c.get("locations"); await c.get("locations")
    with pytest.raises(BudgetExhausted):
        await c.get("locations")

    class Dead(LocalQuota):
        async def reserve_or_wait(self, *a, **k):
            raise QuotaExhausted("spent", retry_in_s=42, decision=None)
    c2, _, _ = _client(tmp_path, quota=Dead())
    with pytest.raises(BudgetExhausted) as ei:
        await c2.get("locations")
    assert ei.value.retry_in_s == 42


@respx.mock
async def test_paginate_stops_on_integer_found_and_short_page(tmp_path):
    respx.get(f"{BASE}/locations", params={"page": "1"}).mock(return_value=httpx.Response(200, json=page([location(1), location(2)], page_no=1, limit=2, found=3)))
    respx.get(f"{BASE}/locations", params={"page": "2"}).mock(return_value=httpx.Response(200, json=page([location(3)], page_no=2, limit=2, found=3)))
    c, quota, _ = _client(tmp_path)
    pages = [p async for p in c.locations_pages("PK", limit=2, max_pages=10)]
    assert [p.page for p in pages] == [1, 2] and quota.reservations == 2
    assert [r["id"] for p in pages for r in p.results] == [1, 2, 3]


@respx.mock
async def test_paginate_ignores_string_found_and_stops_on_short_page(tmp_path):
    respx.get(f"{BASE}/locations", params={"page": "1"}).mock(return_value=httpx.Response(200, json=page([location(1), location(2)], limit=2, found=">1000")))
    respx.get(f"{BASE}/locations", params={"page": "2"}).mock(return_value=httpx.Response(200, json=page([location(3)], limit=2, found=">1000")))
    c, _, _ = _client(tmp_path)
    pages = [p async for p in c.locations_pages("PK", limit=2, max_pages=10)]
    assert len(pages) == 2 and pages[0].found is None


@respx.mock
async def test_paginate_detects_repeated_page_and_page_cap(tmp_path):
    respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(200, json=page([location(1), location(2)], limit=2, found=">1000")))
    c, _, _ = _client(tmp_path)
    with pytest.raises(PaginationAnomaly, match="repeated_page"):
        [p async for p in c.locations_pages("PK", limit=2, max_pages=10)]
    c2, _, _ = _client(tmp_path)
    respx.get(f"{BASE}/locations").mock(side_effect=lambda req: httpx.Response(200, json=page([location(int(req.url.params["page"])), location(int(req.url.params["page"]) + 100)], limit=2, found=">1000")))
    with pytest.raises(PaginationAnomaly, match="page_cap"):
        [p async for p in c2.locations_pages("PK", limit=2, max_pages=3)]


@respx.mock
async def test_measurements_pages_params(tmp_path):
    route = respx.get(f"{BASE}/sensors/77/measurements").mock(return_value=httpx.Response(200, json=page([])))
    c, _, _ = _client(tmp_path)
    frm, to = datetime(2026, 10, 14, tzinfo=timezone.utc), datetime(2026, 10, 15, tzinfo=timezone.utc)
    [p async for p in c.measurements_pages(77, frm, to, limit=1000, max_pages=6)]
    q = route.calls.last.request.url.params
    assert q["datetime_from"] == "2026-10-14T00:00:00Z" and q["datetime_to"] == "2026-10-15T00:00:00Z"
    assert q["limit"] == "1000" and q["page"] == "1"


@respx.mock
async def test_key_never_logged(tmp_path, caplog):
    import logging
    from app.ingestion.http import configure_logging
    configure_logging("DEBUG", secrets=("oq-SECRET-key-123456",))
    respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(401))
    c, _, _ = _client(tmp_path)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(OpenAQAuthError):
            await c.get("locations")
        logging.getLogger("x").info("header %s", {"X-API-Key": "oq-SECRET-key-123456"})
    assert "oq-SECRET-key-123456" not in caplog.text
