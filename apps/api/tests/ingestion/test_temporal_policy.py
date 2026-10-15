"""
Versioned temporal policy: today's +1h shift is preserved exactly, original
timestamps are recorded, and the overlap entry no longer loses data.
"""

from datetime import datetime, timezone

import pytest

from app.ingestion.temporal import (PARSER_VERSION, TEMPORAL_POLICIES, TemporalPolicy, extract_iqair_rows,
                                    parse_ts, norm_hour)

T08 = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
T09 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
T10 = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
T11 = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)


def _z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _audit_fixture():
    """current 10:00 has AQI but no PM2.5; history 09:00 pm25=11; history 08:00 pm25=22."""
    return {
        "current": {"pollution": {"ts": _z(T10), "aqius": 60, "mainus": "p2"},
                    "weather": {"ts": _z(T10), "tp": 31}},
        "history": {
            "pollution": [{"ts": _z(T09), "aqius": 55, "p2": {"conc": 11}},
                          {"ts": _z(T08), "aqius": 70, "p2": {"conc": 22}}],
            "weather": [{"ts": _z(T09), "tp": 30}, {"ts": _z(T08), "tp": 29}],
        },
    }


def _by_ts(rows):
    return {r["ts_utc"]: r for r in rows}


def test_station_v1_keeps_shift_and_fills_current_from_overlap():
    res = extract_iqair_rows(_audit_fixture(), scope_type="station", scope_key="s1",
                             policy=TEMPORAL_POLICIES["iqair_station_v1"])
    rows = _by_ts(res.rows)
    assert set(rows) == {T08, T09, T10}
    r10, r09, r08 = rows[T10], rows[T09], rows[T08]
    # 10:00 keeps current's AQI and gains the overlap entry's PM2.5 (was lost before)
    assert r10["aqi_us"] == 60 and r10["pm25"] == 11 and r10["raw"]["prov"]["from"] == {"pm25": "history"}
    assert r10["raw"]["prov"]["src_ts"]["p"] == _z(T10) and r10["raw"]["prov"]["src_ts"]["p_overlap"] == _z(T09)
    # 08:00 pollution shifted to 09:00 with its original timestamp recorded
    assert r09["pm25"] == 22 and r09["aqi_us"] == 70
    assert r09["raw"]["prov"]["src_ts"]["p"] == _z(T08) and r09["raw"]["prov"]["shift_h"]["p"] == 1
    # station weather history is NOT shifted: 08:00 weather stays at 08:00, 09:00 at 09:00
    assert r08["temp_c"] == 29 and r09["temp_c"] == 30 and r10["temp_c"] == 31
    assert r08["raw"]["prov"]["shift_h"].get("w") == 0 and r08["pm25"] is None
    for r in res.rows:
        assert r["raw"]["prov"]["tsp"] == "iqair_station_v1" and r["raw"]["prov"]["pv"] == PARSER_VERSION
        assert r["source"] == "airvisual"


def test_city_v1_shifts_weather_with_pollution_and_keeps_unpaired_weather():
    fx = _audit_fixture()
    fx["history"]["weather"].append({"ts": _z(datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)), "tp": 20})
    res = extract_iqair_rows(fx, scope_type="city", scope_key="pakistan|punjab|lahore",
                             policy=TEMPORAL_POLICIES["iqair_city_v1"])
    rows = _by_ts(res.rows)
    # 08:00 weather moves to 09:00 alongside the 08:00 pollution; 09:00 weather is the overlap → fills 10:00 (already has tp)
    assert rows[T09]["temp_c"] == 29 and rows[T09]["pm25"] == 22
    assert rows[T10]["temp_c"] == 31          # current wins over the overlap fill
    # unpaired 05:00 weather is retained (at 06:00 under the +1h city policy)
    assert rows[datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)]["temp_c"] == 20
    assert rows[T09]["scope_type"] == "city"


def test_legacy_skip_mode_reproduces_the_loss():
    legacy = TemporalPolicy("legacy", history_pollution_shift_hours=1, overlap_mode="skip")
    rows = _by_ts(extract_iqair_rows(_audit_fixture(), scope_type="station", scope_key="s", policy=legacy).rows)
    assert rows[T10]["pm25"] is None          # exactly the audit's reproduced loss of pm25=11


def test_current_wins_over_overlap_on_conflict():
    fx = _audit_fixture()
    fx["current"]["pollution"]["p2"] = {"conc": 99}
    rows = _by_ts(extract_iqair_rows(fx, scope_type="station", scope_key="s", policy=TEMPORAL_POLICIES["iqair_station_v1"]).rows)
    assert rows[T10]["pm25"] == 99 and "from" not in rows[T10]["raw"]["prov"]


def test_no_current_ts_means_no_row_and_a_note():
    fx = {"current": {"pollution": {"aqius": 60}, "weather": {"tp": 1}}, "history": {"pollution": [], "weather": []}}
    res = extract_iqair_rows(fx, scope_type="station", scope_key="s", policy=TEMPORAL_POLICIES["iqair_station_v1"])
    assert res.rows == [] and "no_current_pollution_ts" in res.notes and "no_current_weather_ts" in res.notes


def test_history_entry_equal_to_current_hour_lands_in_the_future_hour():
    # Pre-existing oddity under the lag assumption; recorded, not changed. The probe script measures its frequency.
    fx = {"current": {"pollution": {"ts": _z(T10), "aqius": 1}},
          "history": {"pollution": [{"ts": _z(T10), "aqius": 2, "p2": {"conc": 5}}], "weather": []}}
    rows = _by_ts(extract_iqair_rows(fx, scope_type="station", scope_key="s", policy=TEMPORAL_POLICIES["iqair_station_v1"]).rows)
    assert rows[T11]["pm25"] == 5 and rows[T11]["raw"]["prov"]["src_ts"]["p"] == _z(T10)


def test_units_and_pollutant_codes():
    fx = {"current": {"pollution": {"ts": _z(T10), "mainus": "p2", "maincn": "p1", "p2": {"conc": 3.5}, "o3": {"conc": 7}}}}
    r = extract_iqair_rows(fx, scope_type="station", scope_key="s", policy=TEMPORAL_POLICIES["iqair_station_v1"]).rows[0]
    assert r["main_us"] == "pm25" and r["main_cn"] == "pm10"
    assert r["units_pm25"] == "µg/m³" and r["units_o3"] is None and r["units_pm10"] is None


def test_prov_base_is_merged():
    fx = {"current": {"pollution": {"ts": _z(T10), "aqius": 1}}}
    r = extract_iqair_rows(fx, scope_type="station", scope_key="s", policy=TEMPORAL_POLICIES["iqair_station_v1"],
                           prov_base={"sha": "abc", "run": "run-1"}).rows[0]
    assert r["raw"]["prov"]["sha"] == "abc" and r["raw"]["prov"]["run"] == "run-1"


def test_parse_ts_variants():
    assert parse_ts("2026-10-15T09:00:00.000Z") == T09
    assert parse_ts("2026-10-15T14:00:00+05:00") == T09
    assert parse_ts("garbage") is None and parse_ts(None) is None
    assert norm_hour(datetime(2026, 10, 15, 9, 59, 59, tzinfo=timezone.utc)) == T09


def test_policy_registry_is_frozen():
    with pytest.raises(Exception):
        TEMPORAL_POLICIES["iqair_station_v1"].history_pollution_shift_hours = 0
