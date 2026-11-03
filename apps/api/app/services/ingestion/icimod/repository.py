"""
Persistence for the ICIMOD adapter: shadow stations in public.stations and
readings via the field-aware reconcile. PostgresICIMODRepository is the real
one; InMemoryICIMODRepository drives the task tests without a database.

The readings commit is ONE transaction: raw payload index rows → readings.
There are no stream checkpoints: every run re-reads the whole current UTC day.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from sqlalchemy import text

from app.ingestion.identity import as_dict, ensure_identity, now_iso
from app.ingestion.raw_archive import RawPayloadRef, record_in_session
from app.ingestion.reconcile import ReconcilePolicy, ReconcileResult, reconcile_and_upsert_readings
from app.services.ingestion.icimod.normalize import (PROVIDER_CODE, PROVIDER_DISPLAY_NAME, PROVIDER_METADATA, TS_POLICY,
                                                     station_id_for_icimod)

logger = logging.getLogger(__name__)

MONITOR_TYPE = "reference_reported_by_icimod"   # EPCCD regulatory monitors, as relayed by ICIMOD


@dataclass
class StationUpsert:
    native_id: int
    name: str
    lat: float
    lon: float
    country_id: int
    timezone: Optional[str]
    metadata: Dict[str, Any]            # the 'icimod' snapshot (+ origin); identity merged by the repo
    alias_candidates: List[Dict[str, Any]] = field(default_factory=list)


class ICIMODRepository(Protocol):
    async def ensure_provider(self) -> int: ...
    async def resolve_country_id(self, iso2: str, name: str) -> int: ...
    async def upsert_shadow_station(self, st: StationUpsert, provider_id: int, run_id: str) -> str: ...
    async def candidate_stations_near(self, lat: float, lon: float, radius_m: float) -> List[Dict[str, Any]]: ...
    async def commit_readings(self, rows: List[Dict[str, Any]], refs: List[RawPayloadRef], *, run_id: str) -> ReconcileResult: ...


def _merge_station_metadata(existing: Optional[Dict[str, Any]], st: StationUpsert, run_id: str) -> Dict[str, Any]:
    """
    existing ∪ incoming: curated keys and identity.aliases survive; identity.alias_candidates
    is replaced (machine-generated); the 'icimod' snapshot is replaced but keeps first_seen_at
    and a bounded history of name/coordinate changes; ingest_mode is only set when absent.
    """
    out = as_dict(existing)
    ts = now_iso()
    prev = as_dict(out.get("icimod"))
    new = dict(st.metadata.get("icimod") or {})
    new["first_seen_at"] = prev.get("first_seen_at") or ts
    new["last_seen_at"] = ts
    new["catalogue_run_id"] = run_id
    hist = list(prev.get("history") or [])
    if prev and (prev.get("name") != new.get("name") or prev.get("lat") != new.get("lat") or prev.get("lon") != new.get("lon")):
        hist.append({"at": ts, "run_id": run_id, "from": {k: prev.get(k) for k in ("name", "lat", "lon")},
                     "to": {k: new.get(k) for k in ("name", "lat", "lon")}})
    new["history"] = hist[-50:]
    out["icimod"] = new
    out["origin"] = st.metadata.get("origin", out.get("origin", PROVIDER_CODE))
    out.setdefault("ingest_mode", "shadow")
    out = ensure_identity(out, PROVIDER_CODE, str(st.native_id), since=ts, evidence="icimod:/pakistan-dashboard/icimod/stations")
    out["identity"]["alias_candidates"] = st.alias_candidates
    out["identity"].setdefault("hardware", {"instruments": None, "source": "icimod_relayed", "confidence": "unknown"})
    return out


class PostgresICIMODRepository:
    def __init__(self, session_factory):
        self._sf = session_factory

    async def ensure_provider(self) -> int:
        md = {**PROVIDER_METADATA, "ts_policy": TS_POLICY}
        async with self._sf() as s:
            pid = (await s.execute(text("SELECT id FROM providers WHERE code = :c"), {"c": PROVIDER_CODE})).scalar()
            if pid is None:
                pid = (await s.execute(text("""INSERT INTO providers (code, display_name, metadata, active)
                                               VALUES (:c, :d, CAST(:m AS jsonb), true) RETURNING id"""),
                                       {"c": PROVIDER_CODE, "d": PROVIDER_DISPLAY_NAME, "m": json.dumps(md)})).scalar_one()
            else:
                await s.execute(text("""UPDATE providers SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:m AS jsonb)
                                        WHERE id = :id"""), {"m": json.dumps(md), "id": pid})
            await s.commit()
            return int(pid)

    async def resolve_country_id(self, iso2: str, name: str) -> int:
        async with self._sf() as s:
            cid = (await s.execute(text("SELECT id FROM countries WHERE iso2 = :i OR name = :n ORDER BY iso2 = :i DESC LIMIT 1"),
                                   {"i": iso2, "n": name})).scalar()
            if cid is None:
                cid = (await s.execute(text("INSERT INTO countries (name, iso2, active, last_seen_at) VALUES (:n, :i, true, now()) RETURNING id"),
                                       {"n": name, "i": iso2})).scalar_one()
            await s.commit()
            return int(cid)

    async def upsert_shadow_station(self, st: StationUpsert, provider_id: int, run_id: str) -> str:
        station_id = station_id_for_icimod(st.native_id)
        async with self._sf() as s:
            existing = (await s.execute(text("SELECT station_id, metadata_json FROM stations WHERE provider_id = :p AND source_station_id = :sid"),
                                        {"p": provider_id, "sid": str(st.native_id)})).fetchone()
            merged = _merge_station_metadata(existing.metadata_json if existing else None, st, run_id)
            sid = existing.station_id.strip() if existing else station_id
            await s.execute(text("""
                INSERT INTO stations (station_id, country_id, name, lat, lon, provider_id, source_station_id, timezone,
                                      monitor_type, metadata_json, active, last_seen_at, updated_at)
                VALUES (:sid, :co, :name, :lat, :lon, :pid, :src, :tz, :mt, CAST(:md AS jsonb), false, now(), now())
                ON CONFLICT (provider_id, source_station_id) DO UPDATE SET
                    name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon, timezone = EXCLUDED.timezone,
                    monitor_type = EXCLUDED.monitor_type, metadata_json = EXCLUDED.metadata_json,
                    last_seen_at = now(), updated_at = now()
            """), {"sid": sid, "co": st.country_id, "name": st.name, "lat": st.lat, "lon": st.lon, "pid": provider_id,
                   "src": str(st.native_id), "tz": st.timezone, "mt": MONITOR_TYPE, "md": json.dumps(merged)})
            await s.commit()
            return sid

    async def candidate_stations_near(self, lat: float, lon: float, radius_m: float) -> List[Dict[str, Any]]:
        try:
            async with self._sf() as s:
                rows = (await s.execute(text("""
                    SELECT s.station_id, p.code, s.name,
                           ST_Distance(ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography,
                                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d
                    FROM stations s JOIN providers p ON p.id = s.provider_id
                    WHERE p.code <> :me
                      AND ST_DWithin(ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography,
                                     ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)
                    ORDER BY d ASC LIMIT 10
                """), {"lat": lat, "lon": lon, "r": float(radius_m), "me": PROVIDER_CODE})).fetchall()
            return [{"station_id": r[0].strip(), "provider_code": r[1], "name": r[2], "distance_m": float(r[3])} for r in rows]
        except Exception as exc:
            logger.warning("alias candidate lookup unavailable (%s)", type(exc).__name__)
            return []

    async def commit_readings(self, rows, refs, *, run_id: str) -> ReconcileResult:
        async with self._sf() as s:
            for ref in refs:
                try:
                    async with s.begin_nested():
                        await record_in_session(s, ref)
                except Exception as exc:  # index row is best-effort; readings are not
                    logger.warning("raw payload index write failed (%s); continuing", type(exc).__name__)
            result = await reconcile_and_upsert_readings(s, rows, ReconcilePolicy(source=PROVIDER_CODE, run_id=run_id))
            await s.commit()
            return result


class InMemoryICIMODRepository:
    """Dict-backed stand-in with the same contract (tests, dry runs without a DB)."""

    def __init__(self, *, nearby: Optional[List[Dict[str, Any]]] = None, fail_commit: bool = False):
        self.provider_id = 43
        self.country_id = 1
        self.stations: Dict[str, Dict[str, Any]] = {}       # station_id -> row
        self.readings: Dict[tuple, Dict[str, Any]] = {}
        self.refs: List[RawPayloadRef] = []
        self.commits: List[Dict[str, Any]] = []
        self.nearby = nearby or []
        self.fail_commit = fail_commit

    async def ensure_provider(self) -> int:
        return self.provider_id

    async def resolve_country_id(self, iso2, name) -> int:
        return self.country_id

    async def upsert_shadow_station(self, st: StationUpsert, provider_id: int, run_id: str) -> str:
        existing = next((r for r in self.stations.values() if r["source_station_id"] == str(st.native_id)), None)
        sid = existing["station_id"] if existing else station_id_for_icimod(st.native_id)
        merged = _merge_station_metadata(existing["metadata_json"] if existing else None, st, run_id)
        self.stations[sid] = {"station_id": sid, "source_station_id": str(st.native_id), "name": st.name, "lat": st.lat,
                              "lon": st.lon, "active": False, "city_id": None, "state_id": None, "monitor_type": MONITOR_TYPE,
                              "metadata_json": merged, "provider_id": provider_id}
        return sid

    async def candidate_stations_near(self, lat, lon, radius_m):
        return list(self.nearby)

    async def commit_readings(self, rows, refs, *, run_id: str) -> ReconcileResult:
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")
        res = ReconcileResult(rows_in=len(rows))
        for r in rows:
            k = (r["scope_type"], r["scope_key"], r["ts_utc"])
            if k in self.readings:
                if self.readings[k].get("pm25") == r.get("pm25"):
                    res.rows_unchanged += 1
                else:
                    res.rows_updated += 1
                    res.revisions_recorded += 1
                    self.readings[k] = dict(r)
            else:
                self.readings[k] = dict(r)
                res.rows_inserted += 1
        self.refs.extend(refs)
        self.commits.append({"rows": len(rows), "run_id": run_id})
        return res
