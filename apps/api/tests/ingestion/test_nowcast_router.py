"""Nowcast read routes serve the published latest.json; station lookup by id, member id or sensor id."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.routers import nowcast

SAMPLE = {
    "init_time": "2026-11-04T09:00:00+00:00", "generated_at": "2026-11-04T09:21:00+00:00",
    "model_tag": "v1", "leads": [3, 6, 12, 24], "n_stations": 2,
    "data_quality": {"task": "nowcast", "n_forecastable": 1, "forecastable_fraction": 0.5,
                     "basis_counts": {"model": 1, "neighbours": 1}, "source_ifs": True,
                     "met_run": "2026-11-04T00:00:00+00:00", "newest_obs_utc": "2026-11-04T08:00:00+00:00",
                     "duration_s": 4.5},
    "stations": [
        {"sensor_id": 3210805276, "station_id": "445be36a99f5083c", "member_station_ids": ["445be36a99f5083c", "old-id "],
         "station_name": "Korangi Sector 15", "city": "Karachi", "latitude": 24.83, "longitude": 67.10,
         "basis": "model", "forecastable": True, "last_obs": 67.0, "obs_age_h": 1.0, "n_valid_24h": 20,
         "leads": [{"lead_hours": 3, "valid_time": "2026-11-04T12:00:00+00:00", "pm25": 70.1, "q75": 80.0, "q90": 90.0}]},
        {"sensor_id": 4198982304, "station_id": None, "member_station_ids": [],
         "station_name": "DHA Phase 5", "city": "Lahore", "latitude": 31.47, "longitude": 74.41,
         "basis": "neighbours", "forecastable": False, "last_obs": None, "obs_age_h": None, "n_valid_24h": 0,
         "leads": [{"lead_hours": 3, "valid_time": "2026-11-04T12:00:00+00:00", "pm25": 120.0, "q75": 150.0, "q90": 170.0}]},
    ],
}


def _app():
    app = FastAPI()
    app.include_router(nowcast.router, prefix="/api/v1/nowcast")
    return app


async def _get(path):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        return await c.get(path)


@pytest.fixture(autouse=True)
def _reset_cache():
    nowcast._cache.update({"at": 0.0, "data": None})
    yield
    nowcast._cache.update({"at": 0.0, "data": None})


async def test_latest_serves_the_published_file_and_caches_it():
    with patch.object(nowcast, "_gcs_read_json", return_value=SAMPLE) as read:
        r = await _get("/api/v1/nowcast/latest")
        assert r.status_code == 200 and r.json()["n_stations"] == 2 and r.json()["leads"] == [3, 6, 12, 24]
        r2 = await _get("/api/v1/nowcast/latest?city=lahore")
        assert r2.status_code == 200 and [s["city"] for s in r2.json()["stations"]] == ["Lahore"] and r2.json()["n_stations"] == 1
        assert read.call_count == 1  # second call served from the 60 s cache


async def test_latest_404_before_the_first_cycle():
    with patch.object(nowcast, "_gcs_read_json", side_effect=HTTPException(status_code=404, detail="x")):
        r = await _get("/api/v1/nowcast/latest")
    assert r.status_code == 404 and "No nowcast" in r.json()["detail"]


async def test_station_lookup_by_id_member_or_sensor():
    with patch.object(nowcast, "_gcs_read_json", return_value=SAMPLE):
        by_id = await _get("/api/v1/nowcast/station/445be36a99f5083c")
        by_member = await _get("/api/v1/nowcast/station/old-id")
        by_sensor = await _get("/api/v1/nowcast/station/4198982304")
        missing = await _get("/api/v1/nowcast/station/nope")
    assert by_id.status_code == 200 and by_id.json()["station"]["station_name"] == "Korangi Sector 15"
    assert by_id.json()["init_time"] == SAMPLE["init_time"] and by_id.json()["leads"] == [3, 6, 12, 24]
    assert by_member.status_code == 200 and by_member.json()["station"]["sensor_id"] == 3210805276
    assert by_sensor.status_code == 200 and by_sensor.json()["station"]["basis"] == "neighbours"
    assert missing.status_code == 404


async def test_runs_lists_cycles_newest_first():
    class _Blob:
        def __init__(self, name): self.name = name

    class _Bucket:
        def list_blobs(self, prefix): return [_Blob("nowcast/nowcast_20261104T06Z.json"), _Blob("nowcast/nowcast_20261104T09Z.json"),
                                              _Blob("nowcast/nowcast_20261104T09Z.parquet"), _Blob("nowcast/latest.json")]

    class _Client:
        def bucket(self, name): return _Bucket()

    with patch.object(nowcast, "_gcs_client", return_value=_Client()), patch.object(nowcast, "_gcs_read_json", return_value=SAMPLE):
        r = await _get("/api/v1/nowcast/runs?limit=1")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 1 and runs[0]["blob"] == "nowcast/nowcast_20261104T09Z.json" and runs[0]["init_time"].startswith("2026-11-04T09:00:00")
    assert runs[0]["n_forecastable"] == 1 and runs[0]["basis_counts"] == {"model": 1, "neighbours": 1}
