"""Dashboard preview channels (hawanama-2--<channel>.web.app) pass CORS like the live site; others do not."""

import re

from app.main import PREVIEW_ORIGIN_REGEX


def test_preview_origin_regex_matches_only_the_dashboard_site_previews():
    ok = re.compile(PREVIEW_ORIGIN_REGEX).fullmatch
    assert ok("https://hawanama-2--ci-preview-9zu6q57j.web.app")
    assert ok("https://hawanama-2--pr-12-abc.web.app")
    assert not ok("https://hawanama-2.web.app.evil.example")
    assert not ok("http://hawanama-2--ci-preview-9zu6q57j.web.app")
    assert not ok("https://other--ci-preview.web.app")
