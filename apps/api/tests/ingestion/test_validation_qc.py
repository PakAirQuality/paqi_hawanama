"""Quarantine invalid values, reject impossible timestamps, never downgrade curated QC."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.ingestion.validation import (QC_INVALID, QC_OK, QC_RAW, QC_SUSPECT, merge_qc, validate_reading)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(hours=48)


def _row(**kw):
    base = {"scope_type": "station", "scope_key": "s1", "ts_utc": NOW - timedelta(hours=1), "pm25": 12.0,
            "temp_c": 30.0, "humidity": 40.0}
    base.update(kw)
    return base


def test_clean_row_is_raw_not_ok():
    out = validate_reading(_row(), now=NOW, cutoff=CUTOFF)
    assert out.ok and out.flags == [] and out.row["qc_state"] == QC_RAW and out.row["qc_flags"] == []
    assert out.row["_present"] == {"pm25", "temp_c", "humidity"}


@pytest.mark.parametrize("field,value,reason", [
    ("pm25", -3.0, "negative"), ("pm25", float("nan"), "nonfinite"), ("pm10", float("inf"), "nonfinite"),
    ("pm25", 2500.0, "above_max"), ("humidity", 140.0, "above_max"), ("temp_c", -90.0, "below_min"),
    ("wind_dir_deg", 400, "above_max"), ("aqi_us", -1, "negative"), ("co", "abc", "nonfinite"),
])
def test_bad_values_are_quarantined(field, value, reason):
    out = validate_reading(_row(**{field: value}), now=NOW, cutoff=CUTOFF)
    assert out.ok
    assert out.flags == [f"v:{field}:{reason}"]
    assert out.row[field] is None
    assert field in out.quarantined and (out.quarantined[field] != out.quarantined[field]  # NaN
                                         or out.quarantined[field] == value)
    # only a flag on a primary field (pm25 / aqi_us) invalidates the row; others just quarantine the field
    expected_state = QC_INVALID if field in ("pm25", "aqi_us") else QC_RAW
    assert out.row["qc_state"] == expected_state and field not in out.row["_present"]


def test_negative_temperature_is_fine():
    out = validate_reading(_row(temp_c=-5.0), now=NOW, cutoff=CUTOFF)
    assert out.flags == [] and out.row["temp_c"] == -5.0


def test_original_row_is_not_mutated():
    row = _row(pm25=-1.0)
    validate_reading(row, now=NOW, cutoff=CUTOFF)
    assert row["pm25"] == -1.0 and "qc_state" not in row


@pytest.mark.parametrize("ts,reason", [
    (None, "ts_missing"),
    (NOW + timedelta(hours=2), "ts_future"),
    (NOW - timedelta(hours=72), "ts_before_cutoff"),
])
def test_impossible_timestamps_are_rejected(ts, reason):
    out = validate_reading(_row(ts_utc=ts), now=NOW, cutoff=CUTOFF)
    assert out.rejected == reason and not out.ok


def test_future_tolerance_and_naive_timestamps():
    assert validate_reading(_row(ts_utc=NOW + timedelta(minutes=30)), now=NOW).ok
    out = validate_reading(_row(ts_utc=(NOW - timedelta(hours=1)).replace(tzinfo=None)), now=NOW)
    assert out.ok and out.row["ts_utc"].tzinfo is not None


# ---------------------------------------------------------------- merge_qc

def test_curated_state_is_never_downgraded():
    assert merge_qc(QC_OK, ["high_rh"], ["v:pm25:negative"], set()) == (QC_OK, ["high_rh", "v:pm25:negative"])
    assert merge_qc(QC_SUSPECT, [], [], {"pm25"}) == (QC_SUSPECT, [])


def test_incoming_flags_make_invalid_only_for_primary_fields():
    assert merge_qc(QC_RAW, [], ["v:pm25:negative"], set()) == (QC_INVALID, ["v:pm25:negative"])
    assert merge_qc(None, None, ["v:aqi_us:negative"], {"pm25"}) == (QC_INVALID, ["v:aqi_us:negative"])
    # a secondary-field flag is recorded but keeps the row visible ('raw')
    assert merge_qc(None, None, ["v:pm10:above_max"], {"pm25"}) == (QC_RAW, ["v:pm10:above_max"])
    assert merge_qc(QC_RAW, ["v:co:above_max"], ["v:pressure_hpa:above_max"], {"pm25", "co"}) == (QC_RAW, ["v:pressure_hpa:above_max"])


def test_co_has_no_upper_bound_until_units_are_attested():
    out = validate_reading(_row(co=9606), now=NOW, cutoff=CUTOFF)
    assert out.flags == [] and out.row["co"] == 9606 and out.row["qc_state"] == QC_RAW


def test_invalid_heals_when_corrected_replay_supplies_valid_values():
    assert merge_qc(QC_INVALID, ["v:pm25:negative"], [], {"pm25"}) == (QC_RAW, [])
    # only the primary flag corrected → row heals to 'raw'; the secondary flag stays on record
    assert merge_qc(QC_INVALID, ["v:pm25:negative", "v:pm10:above_max"], [], {"pm25"}) == (QC_RAW, ["v:pm10:above_max"])
    assert merge_qc(QC_INVALID, ["v:pm25:negative", "v:aqi_us:negative"], [], {"pm25"}) == (QC_INVALID, ["v:aqi_us:negative"])
    # rows the 2026-10-15 run flagged on CO only heal as soon as CO is supplied again
    assert merge_qc(QC_INVALID, ["v:co:above_max"], [], {"pm25", "co"}) == (QC_RAW, [])
    # incoming does not mention the flagged field → unchanged
    assert merge_qc(QC_INVALID, ["v:pm25:negative"], [], {"temp_c"}) == (QC_INVALID, ["v:pm25:negative"])


def test_invalid_from_non_validation_source_is_left_alone():
    assert merge_qc(QC_INVALID, ["pm25_sentinel"], [], {"pm25"}) == (QC_INVALID, ["pm25_sentinel"])


def test_plain_rows_stay_raw():
    assert merge_qc(QC_RAW, [], [], {"pm25"}) == (QC_RAW, [])
    assert merge_qc(None, None, [], set()) == (QC_RAW, [])
