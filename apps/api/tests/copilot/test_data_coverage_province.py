"""Province-level data coverage resolves names through `states`, never a `stations.state` column.

Regression for the 2026-10-28 production failure: "how many monitors in KP" →
`column s.state does not exist` → the whole copilot reply aborted.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from app.services import analytics

PAKISTAN_STATES = [
    NS(id=1, name="Azad Kashmir", code=None),
    NS(id=2, name="Balochistan", code="BA"),
    NS(id=3, name="Gilgit-Baltistan", code=None),
    NS(id=4, name="Islamabad", code="IS"),
    NS(id=5, name="Khyber Pakhtunkhwa", code="KP"),
    NS(id=6, name="Punjab", code="PB"),
    NS(id=7, name="Sindh", code="SD"),
]
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """Dispatches on the SQL text; records every statement and its parameters."""

    def __init__(self, stations_in_state=("st_a", "st_b")):
        self.calls: list[tuple[str, dict]] = []
        self.stations_in_state = list(stations_in_state)

    async def execute(self, q, params=None):
        sql = " ".join(str(q).split())
        self.calls.append((sql, dict(params or {})))
        if "FROM states st" in sql:
            return FakeResult(PAKISTAN_STATES)
        if "FROM stations s WHERE s.state_id" in sql:
            return FakeResult([NS(station_id=s) for s in self.stations_in_state])
        if "COUNT(DISTINCT r.scope_key)" in sql:
            return FakeResult([NS(earliest_ts=T0, latest_ts=T0 + timedelta(days=100), n_obs=4000,
                                  n_with_data=len(self.stations_in_state))])
        if "GROUP BY r.scope_key, s.name" in sql:
            return FakeResult([NS(station_id=s, station_name=s.upper(), earliest_ts=T0,
                                  latest_ts=T0 + timedelta(days=100), n_readings=2000)
                               for s in self.stations_in_state])
        raise AssertionError(f"unexpected SQL: {sql[:120]}")


@pytest.mark.parametrize("typed", ["KP", "kpk", "Khyber Pakhtunkhwa", "khyber pakhtunkhwa", "Khyber Pakhtunkwa", "NWFP"])
async def test_kp_short_forms_and_typos_resolve_to_the_same_state(typed):
    db = FakeDB()
    out = await analytics.get_data_coverage(db, "province", typed)
    data = out["data"]
    assert data["entity"] == "Khyber Pakhtunkhwa" and data["geography"] == "province"
    assert data["n_stations_total"] == 2 and data["n_stations_with_data"] == 2
    station_sql, station_params = next((s, p) for s, p in db.calls if "FROM stations s WHERE" in s)
    assert station_params == {"sid": 5} and "state_id" in station_sql
    assert all("s.state " not in s and "LOWER(s.state)" not in s for s, _ in db.calls), "the old nonexistent column is back"


async def test_states_are_looked_up_for_pakistan_only():
    db = FakeDB()
    await analytics.get_data_coverage(db, "province", "Punjab")
    states_sql, params = next((s, p) for s, p in db.calls if "FROM states st" in s)
    assert "JOIN countries co" in states_sql and params == {"country": "Pakistan"}


@pytest.mark.parametrize("typed, expected", [("ICT", "Islamabad"), ("AJK", "Azad Kashmir"), ("GB", "Gilgit-Baltistan"),
                                             ("Baluchistan", "Balochistan"), ("SD", "Sindh")])
async def test_other_aliases_and_state_codes(typed, expected):
    out = await analytics.get_data_coverage(FakeDB(), "province", typed)
    assert out["data"]["entity"] == expected


async def test_unknown_province_is_a_message_not_an_exception():
    out = await analytics.get_data_coverage(FakeDB(), "province", "Narnia")
    msg = out["data"]["message"]
    assert msg.startswith("Province 'Narnia' not found") and "Khyber Pakhtunkhwa" in msg and "Sindh" in msg


async def test_province_without_active_stations():
    out = await analytics.get_data_coverage(FakeDB(stations_in_state=()), "province", "GB")
    assert out["data"] == {"message": "No active stations found in Gilgit-Baltistan."}
