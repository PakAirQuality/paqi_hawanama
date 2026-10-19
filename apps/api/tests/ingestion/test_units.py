"""Units are recorded only where the provider documents them."""

from app.ingestion.units import UGM3, apply_units, units_for


def test_airvisual_pm_units_only():
    assert units_for("airvisual", "pm25") == UGM3 and units_for("airvisual", "pm10") == UGM3
    assert units_for("airvisual", "o3") is None and units_for("airvisual", "co") is None


def test_unknown_provider_has_no_units():
    assert units_for("punjab", "pm25") is None and units_for("nobody", "pm25") is None


def test_apply_units_only_where_value_present():
    row = apply_units({"pm25": 10.0, "pm10": None, "o3": 5.0}, "airvisual")
    assert row["units_pm25"] == UGM3 and row["units_pm10"] is None and row["units_o3"] is None
    assert all(f"units_{p}" in row for p in ("pm25", "pm10", "o3", "no2", "so2", "co"))
