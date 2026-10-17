"""One classification for the whole product: US EPA 2024 PM2.5 categories."""

import pytest

from app.services.aqi.pm25 import (
    BANDS, BAND_KEYS, BAND_ORDER, band_for_aqi, band_key, categories_payload, classify, normalize_band,
)


@pytest.mark.parametrize("pm25,expected", [
    (0, "good"), (9.0, "good"), (9.04, "good"), (9.1, "moderate"), (35.4, "moderate"), (35.5, "unhealthy_sensitive"),
    (40, "unhealthy_sensitive"), (55.4, "unhealthy_sensitive"), (55.5, "unhealthy"), (125.4, "unhealthy"),
    (125.5, "very_unhealthy"), (225.4, "very_unhealthy"), (225.5, "hazardous"), (300, "hazardous"), (999, "hazardous"),
])
def test_band_key_follows_epa_2024_breakpoints(pm25, expected):
    assert band_key(pm25) == expected


def test_unusable_inputs_are_unknown():
    for v in (None, -1, float("nan"), "abc"):
        assert band_key(v) == "unknown"
    assert classify(None)["key"] == "unknown"


def test_classify_carries_label_aqi_and_colour():
    c = classify(40)
    assert c["key"] == "unhealthy_sensitive"
    assert c["label"] == "Unhealthy for Sensitive Groups"
    assert 101 <= c["aqi"] <= 150
    assert c["color"].startswith("#") and c["text_color"].startswith("#")


def test_band_for_aqi_matches_band_key():
    for pm in (5, 20, 45, 80, 150, 260):
        assert band_for_aqi(classify(pm)["aqi"]) == band_key(pm)


def test_legacy_keys_normalise():
    assert normalize_band("severe") == "hazardous"
    assert normalize_band("usg") == "unhealthy_sensitive"
    assert normalize_band("Unhealthy") == "unhealthy"
    assert normalize_band("weird") == "unknown"
    assert normalize_band(None) == "unknown"


def test_payload_and_order_are_consistent():
    p = categories_payload()
    assert [b["key"] for b in p["categories"]] == BAND_KEYS
    assert p["scale"] == "us_epa_2024"
    assert BAND_ORDER["hazardous"] > BAND_ORDER["unhealthy"] > BAND_ORDER["good"] > BAND_ORDER["unknown"]
    maxes = [b["pm25_max"] for b in BANDS[:-1]]
    assert maxes == sorted(maxes)
