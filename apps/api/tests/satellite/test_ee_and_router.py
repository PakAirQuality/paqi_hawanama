"""satellite_ee against a recording stand-in for the ``ee`` package, and the task endpoint."""

from datetime import date

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.security import verify_tasks_token
from app.services import satellite_ee as se


# ── a tiny ee ─────────────────────────────────────────────────────────────────

class Node:
    """Every ee call returns a Node that records what was asked of it."""

    def __init__(self, log, kind, *args, **kw):
        self.log, self.kind, self.args, self.kw = log, kind, args, kw
        log.append((kind, args, kw))

    def __getattr__(self, name):
        def call(*a, **k):
            return Node(self.log, f"{self.kind}.{name}", *a, **k)
        return call

    def getInfo(self):
        if self.kind.endswith("size"):
            return 3
        if self.kind == "Number":
            return self.args[0]
        return {"features": [{"properties": {"region": "lahore", "no2_mean": 2e-4, "no2_count": 80, "co_mean": 0.03, "co_count": 80,
                                              "aod550_mean": 0.5, "aod550_count": 300, "aod470_mean": 0.6, "aod470_count": 300, "count": 100}}]}


class FakeEEModule:
    def __init__(self):
        self.log = []
        self.initialized = None
        for n in ("ImageCollection", "Image", "Feature", "FeatureCollection", "Geometry", "Filter", "Reducer", "Number", "Date"):
            setattr(self, n, self._factory(n))
        self.Image.cat = lambda bands: Node(self.log, "Image.cat", bands)
        self.Image.constant = lambda v: Node(self.log, "Image.constant", v)
        self.Reducer.mean = lambda: Node(self.log, "Reducer.mean")
        self.Reducer.count = lambda: Node(self.log, "Reducer.count")
        self.Filter.eq = lambda k, v: Node(self.log, "Filter.eq", k, v)

    def _factory(self, name):
        log = self.log

        class F:
            def __new__(cls, *a, **k):
                return Node(log, name, *a, **k)
        F.__name__ = name
        return F

    def Initialize(self, **kw):
        self.initialized = kw


def _client(monkeypatch):
    mod = FakeEEModule()
    monkeypatch.setattr("google.auth.default", lambda scopes=None: (object(), "hawanama-2"), raising=False)
    import google.auth
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: ("creds", "p"))
    from shapely.geometry import box
    return se.EEClient("hawanama-2", ee_module=mod, regions={"lahore": box(74.0, 31.0, 75.0, 32.0)}), mod


def test_init_uses_adc_the_project_and_the_high_volume_endpoint(monkeypatch):
    c, mod = _client(monkeypatch)
    assert c.ping() == 1
    assert mod.initialized["project"] == "hawanama-2" and mod.initialized["opt_url"] == se.HIGH_VOLUME_URL
    assert mod.initialized["credentials"] == "creds"
    c.init()                                                       # idempotent
    assert sum(1 for k, *_ in mod.log if k == "Number") == 1


def test_tropomi_day_builds_the_offl_collections_with_zero_masks_and_reduces_per_region(monkeypatch):
    c, mod = _client(monkeypatch)
    rows = c.day_regions("tropomi", date(2026, 11, 1), products=["no2", "co"])
    kinds = [k for k, *_ in mod.log]
    colls = [a[0] for k, a, _ in mod.log if k == "ImageCollection"]
    assert "COPERNICUS/S5P/OFFL/L3_NO2" in colls and "COPERNICUS/S5P/OFFL/L3_CO" in colls
    assert any(k == "ImageCollection.filterDate" and a == ("2026-11-01", "2026-11-02") for k, a, _ in mod.log)
    assert any(k.endswith(".select") and a == ("tropospheric_NO2_column_number_density",) for k, a, _ in mod.log)
    assert any(k.endswith(".updateMask") for k in kinds)              # exact zeros are gaps for NO2 and CO
    assert any(k.endswith(".reduceRegions") and kw.get("tileScale") == se.TILE_SCALE for k, _, kw in mod.log)
    assert any(k == "Reducer.mean.combine" and kw.get("sharedInputs") for k, _, kw in mod.log)
    assert {(r["product"], r["region"], r["platform"]) for r in rows} == {("no2", "lahore", None), ("co", "lahore", None)}
    no2 = next(r for r in rows if r["product"] == "no2")
    assert no2["value"] == 2e-4 and no2["n_valid"] == 80


def test_aai_is_not_zero_masked_and_maiac_reduces_both_platforms_under_the_strict_qa(monkeypatch):
    c, mod = _client(monkeypatch)
    c.day_regions("tropomi", date(2026, 11, 1), products=["aai"])
    assert not any(k.endswith(".updateMask") for k, *_ in mod.log)
    mod.log.clear()
    rows = c.day_regions("maiac", date(2026, 11, 1))
    assert [a for k, a, _ in mod.log if k == "ImageCollection"][0] == ("MODIS/061/MCD19A2_GRANULES",)
    assert [a for k, a, _ in mod.log if k == "Filter.eq"] == [("SATELLITE", "T"), ("SATELLITE", "A")]
    # the strict QA is applied per granule inside the mapped function: run it on a stand-in granule
    map_calls = [a for k, a, _ in mod.log if k.endswith(".map")]
    assert map_calls and callable(map_calls[0][0])
    map_calls[0][0](Node(mod.log, "granule"))
    assert any(k.endswith(".multiply") and a == (0.001,) for k, a, _ in mod.log)
    assert any(k.endswith(".bitwiseAnd") and a == (0b111,) for k, a, _ in mod.log)        # cloud bits
    assert any(k.endswith(".rightShift") and a == (8,) for k, a, _ in mod.log)            # QA-for-AOD bits
    assert any(k.endswith(".select") and a == (["Optical_Depth_055", "Optical_Depth_047"], ["aod550", "aod470"]) for k, a, _ in mod.log)
    assert {(r["product"], r["platform"]) for r in rows} == {("aod550", "terra"), ("aod550", "aqua"), ("aod470", "terra"), ("aod470", "aqua")}
    assert c.n_possible("tropomi", date(2026, 11, 1)) == {"lahore": 100}


def test_unpublished_days_give_no_rows(monkeypatch):
    c, mod = _client(monkeypatch)
    orig = Node.getInfo
    Node.getInfo = lambda self: 0 if self.kind.endswith("size") else orig(self)
    try:
        assert c.day_regions("tropomi", date(2026, 11, 5)) == []
        assert c.day_regions("maiac", date(2026, 11, 5)) == []
    finally:
        Node.getInfo = orig


# ── the endpoint ──────────────────────────────────────────────────────────────

class _Outcome:
    def __init__(self, kw):
        from app.ingestion.runs import RunStatus
        self.kw = kw
        self.status = RunStatus.success
        self.run_id = "r1"

    def http_status(self):
        return 200

    def to_dict(self):
        return {"status": "success", "kw": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in self.kw.items()}}


@pytest.fixture
def client(monkeypatch):
    from app.routers import tasks as tasks_router
    app = FastAPI()
    app.include_router(tasks_router.router, prefix="/api/v1")
    app.dependency_overrides[verify_tasks_token] = lambda: True
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_the_endpoint_is_off_unless_enabled_validates_its_inputs_and_runs_the_task(client, monkeypatch):
    async with client as c:
        r = await c.post("/api/v1/tasks/satellite/refresh")
        assert r.status_code == 503
        monkeypatch.setattr(settings, "SATELLITE_ENABLED", True)
        r = await c.post("/api/v1/tasks/satellite/refresh?since=2026-13-01")
        assert r.status_code == 422
        r = await c.post("/api/v1/tasks/satellite/refresh?kind=modis")
        assert r.status_code == 422

        calls = []

        class FakeTask:
            async def run(self, **kw):
                calls.append(kw)
                return _Outcome(kw)
        import app.services.satellite_series as mod
        monkeypatch.setattr(mod, "SatelliteSeriesTask", FakeTask)
        r = await c.post("/api/v1/tasks/satellite/refresh?kind=maiac&days=12&since=2026-10-01&dry_run=true")
        assert r.status_code == 200, r.text
        assert calls[0]["kind"] == "maiac" and calls[0]["days"] == 12 and calls[0]["since"] == date(2026, 10, 1) and calls[0]["dry_run"] is True
        assert "Satellite series planned" in r.json()["message"]
        r = await c.get("/api/v1/tasks/status")
        assert any("tasks/satellite/refresh" in e for e in r.json()["available_endpoints"])
