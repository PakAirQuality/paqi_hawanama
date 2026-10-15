"""One PM2.5→AQI converter, 2024 breakpoints, EPA truncation, explicit above-500 policy."""

import math

import pytest

from app.services.aqi import category_for, pm25_to_aqi, truncate_1dp
from app.services.ingestion.bam_service import pm25_to_aqi_us, bam_aqi_provenance
from app.utils.normalization import pm25_to_aqi as legacy_pm25_to_aqi


@pytest.mark.parametrize("conc,aqi", [
    (0.0, 0), (9.0, 50), (9.1, 51), (35.4, 100), (35.5, 101), (55.4, 150), (55.5, 151),
    (125.4, 200), (125.5, 201), (225.4, 300), (225.5, 301), (325.4, 500),
])
def test_every_2024_boundary(conc, aqi):
    assert pm25_to_aqi(conc).value == aqi


def test_truncation_not_rounding():
    assert truncate_1dp(9.09) == 9.0 and truncate_1dp(35.49) == 35.4
    assert pm25_to_aqi(9.09).value == 50          # 9.09 → 9.0 → 50, not 9.1 → 51
    assert pm25_to_aqi(35.49).value == 100
    assert pm25_to_aqi(12.0).value == 56          # interior interpolation: 49/26.3*2.9+51


def test_audit_regression_325_4_is_500_everywhere():
    """The old BAM/Punjab table gave 373 for 325.4 µg/m³."""
    assert pm25_to_aqi(325.4).value == 500
    assert pm25_to_aqi_us(325.4) == 500
    assert legacy_pm25_to_aqi(325.4) == 500
    assert pm25_to_aqi(300.0).value == 449        # was 355 with the hybrid table


@pytest.mark.parametrize("policy,value,capped,category", [
    ("extrapolate", 649, False, "Beyond Index"),
    ("cap", 500, True, "Hazardous"),
    ("none", None, False, "Beyond Index"),
])
def test_above_500_policies(policy, value, capped, category):
    r = pm25_to_aqi(400.0, above_500=policy)
    assert (r.value, r.capped, r.category) == (value, capped, category)
    assert r.extrapolated_value == 649


def test_unusable_inputs_give_none_not_zero():
    for bad in (None, float("nan"), float("inf"), -1.0, "x"):
        r = pm25_to_aqi(bad)
        assert r.value is None and r.category == "Unknown"
    # the legacy read-path wrapper keeps its documented quirk
    assert legacy_pm25_to_aqi(-1.0) == 0 and legacy_pm25_to_aqi(None) is None and legacy_pm25_to_aqi(math.nan) is None


def test_categories():
    assert [category_for(x) for x in (0, 50, 51, 100, 101, 150, 151, 200, 201, 300, 301, 500, 501)] == [
        "Good", "Good", "Moderate", "Moderate", "Unhealthy for Sensitive Groups", "Unhealthy for Sensitive Groups",
        "Unhealthy", "Unhealthy", "Very Unhealthy", "Very Unhealthy", "Hazardous", "Hazardous", "Beyond Index"]
    assert category_for(None) == "Unknown"


def test_averaging_basis_is_declared_never_inferred():
    assert pm25_to_aqi(10.0).averaging_basis == "1h_subindex"
    assert pm25_to_aqi(10.0, averaging_basis="24h").averaging_basis == "24h"


def test_bam_stores_capped_and_records_extrapolation():
    assert pm25_to_aqi_us(400.0) == 500
    prov = bam_aqi_provenance(400.0)
    assert prov["capped"] is True and prov["extrapolated"] == 649 and prov["basis"] == "1h_subindex"
    assert prov["scale"] == "us_epa_2024" and prov["conc_trunc"] == 400.0


def test_legacy_wrapper_policies():
    assert legacy_pm25_to_aqi(400.0) == 500
    assert legacy_pm25_to_aqi(400.0, cap_at_500=False) == 649


def test_punjab_subindex_uses_converter():
    from app.routers.punjab_epa import compute_hourly_usaqi_iqair
    overall, main, sub = compute_hourly_usaqi_iqair(325.4, None, None, None, None, None)
    assert sub["PM2.5"] == 500 and overall == 500 and main == "PM2.5"


def test_no_hybrid_table_left_in_repo(api_root):
    import re
    bad = re.compile(r"225\.5,\s*500\.4")
    offenders = [p for p in (api_root / "app").rglob("*.py") if bad.search(p.read_text())]
    assert offenders == []
