"""Typed contracts, window arithmetic, normalization policy and identity helpers (no network)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.ingestion.openaq import identity as oid
from app.services.ingestion.openaq import windows as w
from app.services.ingestion.openaq.models import (Location, Measurement, parse_locations_page, parse_measurements_page)
from app.services.ingestion.openaq.normalize import PARSER_VERSION, TS_POLICY, normalize_measurement
from tests.openaq.fixtures import T0, hourly_series, location, measurement, page, sensor


def test_locations_page_parses_and_found_may_be_string():
    p = parse_locations_page(page([location(1), location(2, sensors=[sensor(20), sensor(21, "pm10")])], found=">1000"))
    assert p.meta.found == ">1000" and p.meta.found_int() is None
    assert [loc.id for loc in p.results] == [1, 2]
    assert p.results[0].coordinates.latitude == 31.5 and p.results[0].country.code == "PK"
    assert [s.id for s in p.results[1].sensors_for("pm25")] == [20]
    assert p.results[0].licenses[0].name == "CC BY 4.0" and p.results[0].is_monitor is False
    assert parse_locations_page(page([], found=0)).meta.found_int() == 0


def test_measurements_page_parses_period_and_coverage():
    p = parse_measurements_page(page(hourly_series(T0, 2)))
    m = p.results[0]
    assert m.value == 10.0 and m.period.interval == "01:00:00"
    assert m.period.datetime_to.utc == T0 + timedelta(hours=1) and m.coverage.percent_coverage == 100
    assert m.flag_info.has_flags is False


def test_unknown_fields_are_ignored():
    raw = location(5)
    raw["brandNewField"] = {"x": 1}
    assert Location.model_validate(raw).id == 5


# ---------------------------------------------------------------- windows

def test_next_window_initial_and_incremental():
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    frm, to = w.next_window(None, now, overlap_h=72, window_h=24, initial_backfill_h=72)
    assert to == now and frm == now - timedelta(hours=72)      # first window: whole backfill, no overlap
    cp = now - timedelta(hours=30)
    frm, to = w.next_window(cp, now, overlap_h=72, window_h=24, initial_backfill_h=72)
    assert frm == cp - timedelta(hours=72) and to == cp + timedelta(hours=24)
    # checkpoint at/after now: still re-read the overlap, never a future window
    frm, to = w.next_window(now + timedelta(hours=5), now, overlap_h=72, window_h=24, initial_backfill_h=72)
    assert frm == now - timedelta(hours=72) and to == now


def test_reconcile_windows_chunked_and_empty_when_nothing_completed():
    cp = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
    assert w.reconcile_windows(None, lookback_days=14, overlap_h=72) == []
    chunks = w.reconcile_windows(cp, lookback_days=14, overlap_h=72, chunk_days=7)
    assert chunks[0][0] == cp - timedelta(days=14) and chunks[-1][1] == cp - timedelta(hours=72)
    assert len(chunks) == 2 and all(a < b for a, b in chunks)
    assert w.reconcile_windows(cp, lookback_days=2, overlap_h=72) == []


# ---------------------------------------------------------------- normalize

def _m(**kw):
    return Measurement.model_validate(measurement(T0 + timedelta(hours=1), 12.5, **kw))


def test_normalize_uses_period_end_and_records_policy():
    row, reason = normalize_measurement(_m(), station_id="oq_abc", stream_key="sensor:10:pm25", parameter="pm25",
                                        prov_base={"sha": "s", "run": "r"}, now=T0 + timedelta(hours=2))
    assert reason is None
    assert row["ts_utc"] == T0 + timedelta(hours=1) and row["pm25"] == 12.5 and row["units_pm25"] == "µg/m³"
    assert row["source"] == "openaq" and row["qc_state"] == "raw" and row["qc_flags"] == []
    prov = row["raw"]["prov"]
    assert prov["tsp"] == TS_POLICY and prov["pv"] == PARSER_VERSION and prov["sha"] == "s"
    assert prov["period"]["from_utc"].startswith("2026-10-15T00:00:00") and prov["period"]["interval"] == "01:00:00"
    assert "aqi_us" not in row or row.get("aqi_us") is None


def test_normalize_rejects_subhourly_and_missing_period():
    assert normalize_measurement(_m(interval="00:01:00"), station_id="x", stream_key="k", parameter="pm25", prov_base={})[1] == "interval_not_hourly"
    m = _m()
    m.period = None
    assert normalize_measurement(m, station_id="x", stream_key="k", parameter="pm25", prov_base={})[1] == "no_period"


def test_normalize_flags_unexpected_units_and_misaligned_period():
    row, _ = normalize_measurement(_m(units="ppb"), station_id="x", stream_key="k", parameter="pm25", prov_base={}, now=T0 + timedelta(hours=2))
    assert row["qc_state"] == "INVALID" and "units_unexpected" in row["qc_flags"] and row["units_pm25"] == "ppb"
    raw = measurement(T0 + timedelta(hours=1, minutes=30), 5.0)
    row, _ = normalize_measurement(Measurement.model_validate(raw), station_id="x", stream_key="k", parameter="pm25",
                                   prov_base={}, now=T0 + timedelta(hours=3))
    assert "period_misaligned" in row["qc_flags"] and row["ts_utc"] == T0 + timedelta(hours=1)


def test_normalize_quarantines_negative_and_rejects_future():
    row, _ = normalize_measurement(_m().model_copy(update={"value": -4.0}), station_id="x", stream_key="k", parameter="pm25",
                                   prov_base={}, now=T0 + timedelta(hours=2))
    assert row["pm25"] is None and row["qc_state"] == "INVALID" and row["raw"]["prov"]["q"] == {"pm25": -4.0}
    _, reason = normalize_measurement(_m(), station_id="x", stream_key="k", parameter="pm25", prov_base={}, now=T0 - timedelta(days=1))
    assert reason == "ts_future"


# ---------------------------------------------------------------- identity

def test_self_loop_detection_by_provider_or_owner():
    names = ["PAQI", "Pakistan Air Quality Initiative", "Hawanama"]
    assert oid.is_self_loop(Location.model_validate(location(1, provider="PAQI AirVisual")), names)
    assert oid.is_self_loop(Location.model_validate(location(1, owner="hawanama.org")), names)
    assert not oid.is_self_loop(Location.model_validate(location(1, provider="AirGradient", owner="Someone")), names)


def test_alias_candidates_are_evidence_only():
    loc = Location.model_validate(location(1, name="Gulberg Monitor", provider="EPA Punjab"))
    cands = oid.compute_alias_candidates(loc, [
        {"station_id": "pb_x".ljust(16), "provider_code": "punjab", "name": "Gulberg monitor", "distance_m": 42.0},
        {"station_id": "abc".ljust(16), "provider_code": "airvisual", "name": "Totally different", "distance_m": 10.0},
    ], evaluated_at="2026-10-15T00:00:00Z")
    assert [c["station_id"] for c in cands] == ["abc", "pb_x"]          # nearest first
    pb = cands[1]
    assert pb["name_similarity"] > 0.9 and pb["provider_hint_match"] is True and pb["reviewed"] is False
    assert cands[0]["provider_hint_match"] is False and "relation" not in cands[0]
