"""Station daily loader and the copilot hotspots built on it: the chat's "worst cities"
must rank the same station daily means, the same way, as the daily brief."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.ops_pipeline import _build_brief_context
from app.services import analytics
from app.services.station_daily import load_station_daily

STATIONS = [
    {"station_id": "a1", "name": "Eminabad", "city": "Eminabad", "lat": 32.04, "lon": 74.25, "pm25": 232.8, "valid_hours": 22},
    {"station_id": "b1", "name": "PHA Office", "city": "Faisalabad", "lat": 31.42, "lon": 73.08, "pm25": 204.7, "valid_hours": 24},
    {"station_id": "b2", "name": "University Town", "city": "Faisalabad", "lat": 31.40, "lon": 73.10, "pm25": 31.2, "valid_hours": 8},
    {"station_id": "c1", "name": "IAS Grw", "city": "Gujranwala", "lat": 32.16, "lon": 74.19, "pm25": 172.0, "valid_hours": 18},
    {"station_id": "d1", "name": "Delhi Anand Vihar", "city": "Delhi", "lat": 28.65, "lon": 77.31, "pm25": 300.0, "valid_hours": 24},
]


def _bucket(json_payload=None, parquet_names=()):
    bucket = MagicMock()
    blob = MagicMock()
    blob.exists.return_value = json_payload is not None
    blob.download_as_text.return_value = json.dumps(json_payload or {})
    bucket.blob.return_value = blob
    bucket.list_blobs.return_value = [MagicMock(name=n) for n in parquet_names]
    for m, n in zip(bucket.list_blobs.return_value, parquet_names):
        m.name = n
    return bucket


def _load(bucket, *args, **kwargs):
    with patch("google.cloud.storage.Client") as client:
        client.return_value.bucket.return_value = bucket
        return load_station_daily(*args, **kwargs)


def _in_pakistan(lat, lon):
    return lon < 77  # Delhi is outside


def test_loader_json_path_filters_country_and_min_hours():
    payload = {"date": "2026-10-18", "stations": STATIONS}
    with patch("app.services.station_daily.point_in_pakistan", side_effect=_in_pakistan):
        data = _load(_bucket(payload), "2026-10-18", country="Pakistan", min_hours=10)
    names = [s["name"] for s in data["stations"]]
    assert "Delhi Anand Vihar" not in names          # outside Pakistan
    assert "University Town" not in names            # 8 valid hours < 10
    assert data["count"] == len(names) == 3


def test_loader_returns_none_when_day_not_aggregated():
    assert _load(_bucket(None), "2026-10-20") is None


def _brief_worst_cities(stations):
    ctx = _build_brief_context(stations, None, None, None)
    return [line.split(":")[0].lstrip("- ") for line in ctx["worst_cities"].splitlines()]


async def test_city_hotspots_match_the_daily_brief_ranking():
    pk = [s for s in STATIONS if s["city"] != "Delhi"]
    with patch.object(analytics, "_station_daily_safe", AsyncMock(return_value=pk)), \
         patch.object(analytics, "_load_forecast_safe", return_value={}):
        out = await analytics.get_hotspots_daily(MagicMock(), "2026-10-18", "city", "avg_pm25", 5, "Pakistan")

    hotspots = out["data"]["hotspots"]
    assert [h["name"] for h in hotspots] == _brief_worst_cities(pk)
    assert hotspots[0] == {"name": "Eminabad", "n_stations": 1, "avg_pm25": 232.8, "max_pm25": 232.8, "worst_band": hotspots[0]["worst_band"]}
    faisalabad = next(h for h in hotspots if h["name"] == "Faisalabad")
    assert faisalabad["avg_pm25"] == round((204.7 + 31.2) / 2, 1) and faisalabad["max_pm25"] == 204.7
    assert out["data"]["national_summary"]["n_stations"] == 4
    assert "daily mean" in out["basis"]["description"]


async def test_hotspots_fall_back_to_live_readings_when_day_not_aggregated():
    live = {"national_summary": {"n_stations": 0}, "hotspots": []}
    with patch.object(analytics, "_station_daily_safe", AsyncMock(return_value=None)), \
         patch.object(analytics, "_hotspots_live", AsyncMock(return_value=live)) as live_path, \
         patch.object(analytics, "_load_forecast_safe", return_value={}):
        out = await analytics.get_hotspots_daily(MagicMock(), "2026-10-20", "city", "avg_pm25", 5, "Pakistan")
    live_path.assert_awaited_once()
    assert out["basis"]["observation_window"] == "latest_reading"
