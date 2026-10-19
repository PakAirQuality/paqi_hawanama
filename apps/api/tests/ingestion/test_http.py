"""Shared HTTP helpers: redaction and rate-limit header parsing."""

import logging
from datetime import datetime, timedelta, timezone

from app.ingestion import http as h


def test_redact_url_masks_credential_query_params():
    assert h.redact_url("https://api.airvisual.com/v2/station?city=Lahore&key=sk-abc123&state=Punjab") == \
        "https://api.airvisual.com/v2/station?city=Lahore&key=***&state=Punjab"
    assert h.redact_url("https://x/?API_KEY=zzz") == "https://x/?API_KEY=***"
    assert h.redact_url("https://x/?token=t1&apikey=a2") == "https://x/?token=***&apikey=***"
    assert h.redact_url("https://x/?city=Lahore") == "https://x/?city=Lahore"


def test_registered_secret_values_are_redacted_everywhere(caplog):
    h.configure_logging("INFO", secrets=("sk-test-SECRET-9f2a",))
    logger = logging.getLogger("some.module")
    with caplog.at_level(logging.INFO):
        logger.info("calling %s with %s", "https://x/?key=sk-test-SECRET-9f2a", "sk-test-SECRET-9f2a")
    assert "sk-test-SECRET-9f2a" not in caplog.text
    assert "key=***" in caplog.text


def test_parse_retry_after_delta_seconds():
    assert h.parse_retry_after({"retry-after": "7"}) == 7.0


def test_parse_retry_after_http_date():
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    date = (now + timedelta(seconds=90)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert abs(h.parse_retry_after({"Retry-After": date}, now=now) - 90.0) < 1


def test_parse_ratelimit_reset_epoch_vs_delta():
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    epoch = str(int(now.timestamp()) + 42)
    assert abs(h.parse_retry_after({"x-ratelimit-reset": epoch}, now=now) - 42.0) < 1
    assert h.parse_retry_after({"x-ratelimit-reset": "60"}, now=now) == 60.0


def test_parse_retry_after_missing_or_garbage():
    assert h.parse_retry_after({}) is None
    assert h.parse_retry_after({"retry-after": "soon"}) is None


def test_parse_retry_after_is_clamped():
    assert h.parse_retry_after({"retry-after": "999999"}) == 3600.0
