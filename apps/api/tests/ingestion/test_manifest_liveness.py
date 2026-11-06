"""
The union manifest ages stations IQAir stopped listing (dormant → daily poll,
inactive → not polled) and never ages anybody for our own failure to read a state.
"""

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.ingestion import manifests as m


@pytest.fixture(autouse=True)
def _no_gcs(monkeypatch):
    monkeypatch.setattr(settings, "MANIFEST_GCS_BUCKET", None)


def _row(name, city="Lahore", state="Punjab", country="Pakistan", **kw):
    r = {"provider_code": "airvisual", "source_station_id": f"iqair_{country}_{state}_{city}_{name}".lower(),
         "country": country, "state": state, "city": city, "iqair_station_name": name, "lat": 31.5, "lon": 74.3,
         "active": True}
    r.update(kw)
    return r


def _finalize(tmp_path, discovered, *, cities_listed=None, states_fetched=None, dormant_after=2, inactive_after=4):
    run_dir = tmp_path / "run"; run_dir.mkdir(exist_ok=True)
    return {r["source_station_id"]: r for r in m.finalize_union_manifest(
        tmp_path, run_dir, "jsonl", discovered, cities_listed=cities_listed, states_fetched=states_fetched,
        dormant_after=dormant_after, inactive_after=inactive_after)}


PK_PB = ("pakistan", "punjab")


def test_listed_station_is_live_and_resets_miss_count(tmp_path):
    rows = _finalize(tmp_path, [_row("A")], states_fetched={PK_PB})
    a = rows["iqair_pakistan_punjab_lahore_a"]
    assert (a["miss_count"], a["dormant"], a["active"]) == (0, False, True)
    # age it, then rediscover: counters reset, first_seen survives
    for _ in range(3):
        rows = _finalize(tmp_path, [_row("B")], states_fetched={PK_PB})
    assert rows["iqair_pakistan_punjab_lahore_a"]["miss_count"] == 3
    rows = _finalize(tmp_path, [_row("A")], states_fetched={PK_PB})
    a = rows["iqair_pakistan_punjab_lahore_a"]
    assert (a["miss_count"], a["dormant"], a["active"]) == (0, False, True)
    assert a["first_seen_at_utc"] <= a["last_seen_at_utc"]


def test_ages_when_city_listed_without_the_station(tmp_path):
    _finalize(tmp_path, [_row("A"), _row("B")], states_fetched={PK_PB})
    rows = _finalize(tmp_path, [_row("B")], states_fetched={PK_PB}, cities_listed={"pakistan|punjab|lahore"})
    assert rows["iqair_pakistan_punjab_lahore_a"]["miss_count"] == 1
    assert rows["iqair_pakistan_punjab_lahore_b"]["miss_count"] == 0


def test_ages_when_city_vanished_but_state_was_fetched(tmp_path):
    _finalize(tmp_path, [_row("A", city="Kasur"), _row("B")], states_fetched={PK_PB})
    # Kasur is no longer listed by /cities for Punjab; Punjab itself was read fine.
    rows = _finalize(tmp_path, [_row("B")], states_fetched={PK_PB}, cities_listed={"pakistan|punjab|lahore"})
    assert rows["iqair_pakistan_punjab_kasur_a"]["miss_count"] == 1


def test_no_ageing_when_state_could_not_be_read(tmp_path):
    _finalize(tmp_path, [_row("A"), _row("S", state="Sindh", city="Karachi")], states_fetched={PK_PB, ("pakistan", "sindh")})
    # This run only Punjab answered; Sindh failed (alias exhausted / exception): Karachi must not age.
    rows = _finalize(tmp_path, [_row("A")], states_fetched={PK_PB}, cities_listed={"pakistan|punjab|lahore"})
    assert rows["iqair_pakistan_sindh_karachi_s"]["miss_count"] == 0
    assert rows["iqair_pakistan_sindh_karachi_s"]["active"] is True


def test_dormant_then_inactive_thresholds_and_never_deleted(tmp_path):
    _finalize(tmp_path, [_row("A")], states_fetched={PK_PB})
    seen = []
    for _ in range(5):
        rows = _finalize(tmp_path, [_row("B")], states_fetched={PK_PB}, dormant_after=2, inactive_after=4)
        a = rows["iqair_pakistan_punjab_lahore_a"]
        seen.append((a["miss_count"], a["dormant"], a["active"]))
    assert seen == [(1, False, True), (2, True, True), (3, True, True), (4, True, False), (5, True, False)]
    latest = [json.loads(l) for l in (tmp_path / "latest.jsonl").read_text().splitlines() if l.strip()]
    assert {r["source_station_id"] for r in latest} == {"iqair_pakistan_punjab_lahore_a", "iqair_pakistan_punjab_lahore_b"}


def test_legacy_caller_without_states_fetched_keeps_old_rule(tmp_path):
    _finalize(tmp_path, [_row("A"), _row("B")])
    # old contract: only a city for which stations were fetched this run ages its absent stations
    rows = {r["source_station_id"]: r for r in m.finalize_union_manifest(
        tmp_path, tmp_path / "run", "jsonl", [_row("B")], cities_successfully_fetched={"pakistan|punjab|lahore"})}
    assert rows["iqair_pakistan_punjab_lahore_a"]["miss_count"] == 1
    rows = {r["source_station_id"]: r for r in m.finalize_union_manifest(
        tmp_path, tmp_path / "run", "jsonl", [], cities_successfully_fetched=set())}
    assert rows["iqair_pakistan_punjab_lahore_a"]["miss_count"] == 1   # nothing fetched: nothing ages


def test_thresholds_default_to_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MANIFEST_DORMANT_AFTER_MISSES", 1)
    monkeypatch.setattr(settings, "MANIFEST_INACTIVE_AFTER_MISSES", 2)
    _finalize(tmp_path, [_row("A")], states_fetched={PK_PB}, dormant_after=None, inactive_after=None)
    rows = _finalize(tmp_path, [], states_fetched={PK_PB}, dormant_after=None, inactive_after=None)
    assert rows["iqair_pakistan_punjab_lahore_a"]["dormant"] is True and rows["iqair_pakistan_punjab_lahore_a"]["active"] is True
    rows = _finalize(tmp_path, [], states_fetched={PK_PB}, dormant_after=None, inactive_after=None)
    assert rows["iqair_pakistan_punjab_lahore_a"]["active"] is False


def test_bool_helpers_tolerate_parquet_shapes():
    assert m._as_bool(None, True) is True and m._as_bool(float("nan"), False) is False
    assert m._as_bool("false", True) is False and m._as_bool("True", False) is True
    assert m._as_int(float("nan")) == 0 and m._as_int("3") == 3 and m._as_int(None, 7) == 7
