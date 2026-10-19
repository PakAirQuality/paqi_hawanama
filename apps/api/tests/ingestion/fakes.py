"""Shared fakes for ingestion tests: no network, no database."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.ingestion.runs import RunRecorder


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        POSTGRES_SERVER="x", POSTGRES_USER="x", POSTGRES_PASSWORD="x", POSTGRES_DB="x", POSTGRES_PORT=5432,
        IQAIR_API_KEY="sk-test-SECRET-9f2a",
        INGEST_OUT_DIR=str(tmp_path / "runs"),
        STATION_MANIFEST_DIR=str(tmp_path / "station_manifests"),
        CITY_MANIFEST_DIR=str(tmp_path / "city_manifests"),
        STATION_MANIFEST_FORMAT="jsonl",
        IQAIR_COUNTRIES="Pakistan",
        INGEST_CONCURRENCY=1,            # deterministic ordering for abort tests
        IQAIR_MAX_CALLS_PER_MIN=100000,  # no pacing delays in tests
        MANIFEST_GCS_BUCKET=None,
    )
    base.update(overrides)
    return Settings(**base)


def write_station_manifest(settings: Settings, rows: List[Dict[str, Any]]) -> Path:
    d = Path(settings.STATION_MANIFEST_DIR); d.mkdir(parents=True, exist_ok=True)
    p = d / "latest.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def write_city_manifest(settings: Settings, rows: List[Dict[str, Any]]) -> Path:
    d = Path(settings.CITY_MANIFEST_DIR); d.mkdir(parents=True, exist_ok=True)
    p = d / "latest.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def station_row(i: int, **kw) -> Dict[str, Any]:
    r = {
        "provider_code": "airvisual", "station_id": f"st{i:014d}", "source_station_id": f"iqair_pakistan_punjab_lahore_s{i}",
        "country": "Pakistan", "state": "Punjab", "city": "Lahore", "iqair_station_name": f"Station {i}",
        "lat": 31.5 + i / 1000, "lon": 74.3 + i / 1000, "active": True,
    }
    r.update(kw)
    return r


def city_row(i: int, **kw) -> Dict[str, Any]:
    r = {"country": "Pakistan", "state": "Punjab", "city": f"City{i}", "lat": 31.0 + i, "lon": 74.0 + i,
         "active": True, "scope_key": f"pakistan|punjab|city{i}"}
    r.update(kw)
    return r


def iqair_payload(ts: Optional[datetime] = None, pm25: float = 12.0, aqi: int = 50) -> Dict[str, Any]:
    ts = ts or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    iso = ts.isoformat().replace("+00:00", "Z")
    return {
        "current": {
            "pollution": {"ts": iso, "aqius": aqi, "aqicn": aqi, "mainus": "p2", "maincn": "p2", "p2": {"conc": pm25}},
            "weather": {"ts": iso, "tp": 30, "pr": 1005, "hu": 40, "ws": 1.2, "wd": 90, "ic": "01d"},
        },
        "history": {"pollution": [], "weather": []},
        "raw_response": {},
    }


class FakeIQAirClient:
    """
    `script` maps a station/city name (or '*') to either a payload dict or an
    exception instance to raise. Records every call.
    """

    def __init__(self, script: Dict[str, Any]):
        self.script = script
        self.calls: List[Dict[str, Any]] = []
        self.quota = None

    def _envelope(self, endpoint, data, params):
        from app.services.ingestion.iqair_service import FetchEnvelope
        return FetchEnvelope(data=data, http_status=200, fetched_at=datetime.now(timezone.utc), endpoint=endpoint,
                             params_redacted=params, elapsed_ms=1)

    async def fetch_station(self, station=None, city=None, state=None, country=None):
        data = await self.get_station_data(station=station, city=city, state=state, country=country)
        return self._envelope("station", data, {"station": station, "city": city, "state": state, "country": country})

    async def fetch_city(self, city=None, state=None, country=None):
        data = await self.get_city_data(city=city, state=state, country=country)
        return self._envelope("city", data, {"city": city, "state": state, "country": country})

    async def fetch_nearest_city(self, lat=None, lon=None):
        data = await self.get_nearest_city_data(lat=lat, lon=lon)
        return self._envelope("nearest_city", data, {"lat": lat, "lon": lon})

    def _lookup(self, key: str):
        res = self.script.get(key, self.script.get("*"))
        if isinstance(res, BaseException):
            raise res
        return res

    async def get_station_data(self, station=None, city=None, state=None, country=None):
        self.calls.append({"kind": "station", "station": station, "city": city, "state": state, "country": country})
        return self._lookup(station)

    async def get_city_data(self, city=None, state=None, country=None):
        self.calls.append({"kind": "city", "city": city, "state": state, "country": country})
        return self._lookup(city)

    async def get_nearest_city_data(self, lat=None, lon=None):
        self.calls.append({"kind": "nearest", "lat": lat, "lon": lon})
        return self._lookup("nearest")

    # discovery
    async def get_states(self, country):
        self.calls.append({"kind": "states", "country": country})
        return self._lookup(f"states:{country}")

    async def get_cities(self, country, state):
        self.calls.append({"kind": "cities", "country": country, "state": state})
        return self._lookup(f"cities:{country}:{state}")

    async def get_stations(self, city, state, country):
        self.calls.append({"kind": "stations", "city": city, "state": state, "country": country})
        return self._lookup(f"stations:{country}:{state}:{city}")

    def parse_station_data(self, raw):
        return raw

    def parse_city_data(self, raw):
        return raw


class FakeDatabaseService:
    def __init__(self):
        self.written: List[Dict[str, Any]] = []
        self.stations: List[Dict[str, Any]] = []

    def generate_station_id(self, country, state, city, name, lat, lon):
        import hashlib
        return hashlib.sha1(f"{country}|{state}|{city}|{name}|{lat:.6f}|{lon:.6f}".encode()).hexdigest()[:16]

    unchanged_all = False   # tests flip this to simulate an exact replay

    async def reconcile_and_upsert_readings(self, session, rows, policy):
        from app.ingestion.reconcile import ReconcileResult, dedupe_rows
        deduped = dedupe_rows(rows)
        self.policies = getattr(self, "policies", []) + [policy]
        if self.unchanged_all:
            return ReconcileResult(rows_in=len(rows), rows_unchanged=len(deduped))
        self.written.extend(deduped)
        return ReconcileResult(rows_in=len(rows), rows_inserted=len(deduped))

    async def upsert_country(self, session, data): return 1
    async def upsert_state(self, session, data): return 2
    async def upsert_city(self, session, data): return 3
    async def resolve_country_id(self, session, name, iso2=None): return 1
    async def get_or_create_provider(self, session, code, display_name=None): return 7

    async def upsert_station(self, session, info):
        self.stations.append(info)
        return {"station_id": self.generate_station_id(info["country"], info["state"], info["city"], info["name"], info["lat"], info["lon"]),
                "created": True, "updated": False}


class FakeSession:
    """Minimal async session: records executed statements, never talks to a DB."""

    def __init__(self, fail_with: Optional[BaseException] = None):
        self.executed: List[Any] = []
        self.fail_with = fail_with
        self.committed = 0

    async def execute(self, sql, params=None):
        if self.fail_with:
            raise self.fail_with
        self.executed.append((str(sql), params))
        return None

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        pass

    def begin_nested(self):
        # savepoint stand-in: the same object works as an async context manager
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSessionFactory:
    def __init__(self, fail_with: Optional[BaseException] = None):
        self.fail_with = fail_with
        self.sessions: List[FakeSession] = []

    def __call__(self):
        s = FakeSession(self.fail_with)
        self.sessions.append(s)
        return s


class CapturingRecorder(RunRecorder):
    """Local-report-only recorder that keeps the finished outcome for assertions."""

    def __init__(self, out_dir: Path):
        super().__init__(None, out_dir, required=False)
        self.finished = None
        self.started = None

    async def start(self, outcome):
        self.started = outcome
        await super().start(outcome)

    async def finish(self, outcome):
        await super().finish(outcome)
        self.finished = outcome


class FakeLeases:
    """Grants unless deny=True; records acquire/release calls."""

    def __init__(self, deny: bool = False):
        self.deny = deny
        self.acquired: List[Any] = []
        self.released: List[Any] = []

    async def acquire(self, lease_key, holder, ttl_s):
        from app.ingestion.leases import Lease
        from datetime import timedelta
        self.acquired.append((lease_key, holder, ttl_s))
        if self.deny:
            return None
        return Lease(lease_key, holder, 42, datetime.now(timezone.utc) + timedelta(seconds=ttl_s))

    async def release(self, lease):
        self.released.append(lease)
