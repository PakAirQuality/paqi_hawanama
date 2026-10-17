"""Report request validation: explicit windows in Pakistan time, bounded stations and parameters."""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.routers.reports import MAX_STATIONS, parse_parameters, parse_station_ids, parse_window


def test_window_naive_values_are_pakistan_time():
    s, e = parse_window("2026-10-01T00:00", "2026-10-02T00:00")
    assert s.isoformat() == "2026-09-30T19:00:00+00:00"
    assert e - s == timedelta(days=1)


def test_window_rejects_inverted_oversized_and_future():
    for start, end in [("2026-10-02T00:00", "2026-10-01T00:00"), ("2026-08-01T00:00", "2026-09-15T00:00"), ("2026-10-01", "2099-01-01")]:
        with pytest.raises(HTTPException) as ei:
            parse_window(start, end)
        assert ei.value.status_code == 400
    with pytest.raises(HTTPException):
        parse_window(None, "2026-10-01T00:00")
    with pytest.raises(HTTPException):
        parse_window("yesterday", "2026-10-01T00:00")


def test_parameters_and_station_ids():
    assert parse_parameters(None) == ["pm25"]
    assert parse_parameters("PM25, pm10,pm25") == ["pm25", "pm10"]
    with pytest.raises(HTTPException):
        parse_parameters("pm25,lead")
    ids = parse_station_ids("10904b39b73ecb27, 3E67AF27279C2BBE")
    assert ids == ["10904b39b73ecb27", "3e67af27279c2bbe"]
    with pytest.raises(HTTPException):
        parse_station_ids("12")
    with pytest.raises(HTTPException):
        parse_station_ids(",".join(f"{i:016x}" for i in range(MAX_STATIONS + 1)))
