"""Pure normalisation: the live GeoJSON shape → readings rows with the label policy recorded per row."""

from datetime import timedelta

from app.services.ingestion.icimod.normalize import (PARSER_VERSION, TS_POLICY, Feature, normalize_feature,
                                                     parse_feature_collection, parse_stations, station_id_for_icimod)
from tests.icimod.fixtures import DAY, collection, feature, hourly, label, station

NOW = DAY + timedelta(hours=18)
PROV = {"sha": "abc", "pv": "x", "fa": "2026-11-03T17:50:00Z", "archived": True, "run": "r1"}


def test_station_id_is_deterministic_char16():
    a, b = station_id_for_icimod(26), station_id_for_icimod("26")
    assert a == b and len(a) == 16 and a.startswith("ic_") and a != station_id_for_icimod(27)


def test_parse_stations_filters_state_and_counts_bad_rows():
    rows = [station(1, "A"), station(2, "B", state="Khyber Pakhtunkhwa"), station(3, "", ), {"id": "x"},
            {**station(4, "D"), "latitude": None}, "junk"]
    out, notes = parse_stations(rows, state="Punjab")
    assert [s.name for s in out] == ["A"]
    assert notes == {"station_outside_state": 1, "station_missing_name": 1, "station_missing_id": 1,
                     "station_missing_coordinates": 1, "station_not_an_object": 1}
    assert parse_stations({"not": "a list"}) == ([], {"catalogue_not_a_list": 1})


def test_rows_are_keyed_on_the_floored_hour_and_keep_the_label():
    feats = parse_feature_collection(collection(feature("Egerton Road", hourly(0, 3, base=346.569, step=-10))))
    assert len(feats) == 1 and feats[0].lat == 31.56 and feats[0].lon == 74.33
    rows, notes = normalize_feature(feats[0], station_id="ic_x", prov_base=PROV, now=NOW)
    assert len(rows) == 3 and notes == {}
    r0 = rows[0]
    assert r0["ts_utc"] == DAY and r0["pm25"] == 346.569 and r0["source"] == "icimod" and r0["scope_key"] == "ic_x"
    assert r0["units_pm25"] is None                                   # not attested by the feed
    p = r0["raw"]["prov"]
    assert p["label"] == label(0) and p["tsp"] == TS_POLICY and p["pv"] == PARSER_VERSION and p["native_name"] == "Egerton Road"
    assert p["sha"] == "abc" and p["run"] == "r1"
    assert r0["qc_state"] == "raw" and r0["qc_flags"] == []


def test_silent_station_gives_no_rows_and_a_note():
    f = Feature(name="GT Road", value=None, hourly_data={})
    rows, notes = normalize_feature(f, station_id="ic_y", prov_base=PROV, now=NOW)
    assert rows == [] and notes == {"no_hourly_data": 1}


def test_null_and_unparsable_and_future_values_are_counted_not_raised():
    data = {label(1): None, "not-a-date": 5.0, label(30): 7.0, label(2): "12.5"}
    rows, notes = normalize_feature(Feature(name="X", value=None, hourly_data=data), station_id="ic_z", prov_base=PROV, now=NOW)
    assert [r["pm25"] for r in rows] == [12.5]
    assert notes["value_missing"] == 1 and notes["label_unparsable"] == 1 and notes["ts_future"] == 1


def test_extreme_value_is_quarantined_with_the_reason_in_prov():
    rows, notes = normalize_feature(Feature(name="X", value=None, hourly_data={label(3): 5000.0}), station_id="ic_q",
                                    prov_base=PROV, now=NOW)
    assert len(rows) == 1 and notes["quarantined"] == 1
    assert rows[0]["pm25"] is None and "pm25" in rows[0]["raw"]["prov"]["q"]


def test_feature_collection_tolerates_junk():
    assert parse_feature_collection({"features": [None, {"properties": {}}, {"properties": {"name": "A"}}]})[0].hourly_data == {}
    assert parse_feature_collection([]) == [] and parse_feature_collection({"type": "FeatureCollection"}) == []
