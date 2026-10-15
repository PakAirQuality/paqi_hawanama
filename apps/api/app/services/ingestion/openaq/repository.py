"""
Persistence for the OpenAQ adapter: shadow stations in public.stations,
streams in ops.stream_checkpoints, readings via the field-aware reconcile.

PostgresOpenAQRepository is the real one; InMemoryOpenAQRepository drives the
task tests without a database. The window commit is ONE transaction: raw
payload index rows → readings → checkpoint. A failure anywhere rolls all of it
back, so completed_through only ever moves after every page is durably written.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Set

from sqlalchemy import text

from app.ingestion.identity import as_dict, ensure_identity, now_iso
from app.ingestion.raw_archive import RawPayloadRef, record_in_session
from app.ingestion.reconcile import ReconcilePolicy, ReconcileResult, reconcile_and_upsert_readings

logger = logging.getLogger(__name__)

PROVIDER_CODE = "openaq"
PROVIDER_DISPLAY_NAME = "OpenAQ"
PROVIDER_METADATA = {"origin": "openaq", "terms_url": "https://docs.openaq.org/about/terms", "attribution": "OpenAQ"}


def station_id_for_location(location_id: int) -> str:
    """Deterministic char(16) id from the OpenAQ location id; renames/moves never change it."""
    return f"oq_{hashlib.sha256(f'openaq:location:{int(location_id)}'.encode()).hexdigest()[:13]}"


def stream_key_for(sensor_id: int, parameter: str) -> str:
    return f"sensor:{int(sensor_id)}:{parameter}"


@dataclass
class StationUpsert:
    location_id: int
    name: str
    lat: float
    lon: float
    country_id: int
    timezone: Optional[str]
    monitor_type: str
    metadata: Dict[str, Any]            # the 'openaq' snapshot + origin + geo_resolution (identity merged by the repo)
    alias_candidates: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class StreamSeed:
    stream_key: str
    station_id: str
    native_location_id: str
    native_sensor_id: str
    parameter: str
    units_reported: Optional[str]
    status: str = "active"


@dataclass
class Stream:
    stream_key: str
    station_id: str
    native_location_id: str
    native_sensor_id: str
    parameter: str
    status: str = "active"
    units_reported: Optional[str] = None
    interval_observed: Optional[str] = None
    completed_through: Optional[datetime] = None
    overlap_hours: int = 72
    reconciled_through: Optional[datetime] = None
    last_reconcile_at: Optional[datetime] = None
    consecutive_failures: int = 0
    missed_runs: int = 0


class OpenAQRepository(Protocol):
    async def ensure_provider(self) -> int: ...
    async def resolve_country_id(self, iso2: str, name: str) -> int: ...
    async def resolve_geo(self, lat: float, lon: float) -> Dict[str, Any]: ...
    async def upsert_shadow_station(self, st: StationUpsert, provider_id: int, run_id: str) -> str: ...
    async def seed_stream(self, seed: StreamSeed) -> None: ...
    async def mark_unseen_streams(self, seen_keys: Set[str], retire_after: int) -> int: ...
    async def list_streams(self, status: str, limit: int) -> List[Stream]: ...
    async def commit_window(self, stream: Stream, rows: List[Dict[str, Any]], refs: List[RawPayloadRef], *,
                            completed_through: Optional[datetime], run_id: str, page_count: int,
                            interval_observed: Optional[str], reconciled_through: Optional[datetime] = None) -> ReconcileResult: ...
    async def mark_stream_failed(self, stream_key: str, error: str, run_id: str) -> None: ...
    async def set_stream_status(self, stream_key: str, status: str, *, interval_observed: Optional[str] = None,
                                run_id: Optional[str] = None) -> None: ...
    async def candidate_stations_near(self, lat: float, lon: float, radius_m: float) -> List[Dict[str, Any]]: ...


def _merge_station_metadata(existing: Optional[Dict[str, Any]], st: StationUpsert, run_id: str) -> Dict[str, Any]:
    """
    existing ∪ incoming with these rules: curated keys and identity.aliases/history
    survive; identity.alias_candidates is replaced (machine-generated); the
    'openaq' snapshot is replaced but keeps first_seen_at and a bounded history of
    name/coordinate changes; ingest_mode is only set when absent (so a cutover to
    'primary' is never reverted by discovery).
    """
    out = as_dict(existing)
    ts = now_iso()
    prev_oq = as_dict(out.get("openaq"))
    new_oq = dict(st.metadata.get("openaq") or {})
    new_oq["first_seen_at"] = prev_oq.get("first_seen_at") or ts
    new_oq["last_seen_at"] = ts
    new_oq["discovery_run_id"] = run_id
    hist = list(prev_oq.get("history") or [])
    if prev_oq and (prev_oq.get("name") != new_oq.get("name") or prev_oq.get("lat") != new_oq.get("lat")
                    or prev_oq.get("lon") != new_oq.get("lon")):
        hist.append({"at": ts, "run_id": run_id, "from": {k: prev_oq.get(k) for k in ("name", "lat", "lon")},
                     "to": {k: new_oq.get(k) for k in ("name", "lat", "lon")}})
    new_oq["history"] = hist[-50:]
    out["openaq"] = new_oq
    out["origin"] = st.metadata.get("origin", out.get("origin", "external"))
    out["geo_resolution"] = st.metadata.get("geo_resolution", out.get("geo_resolution"))
    out.setdefault("ingest_mode", "shadow")
    out = ensure_identity(out, PROVIDER_CODE, str(st.location_id), since=ts, evidence="openaq:/v3/locations")
    out["identity"]["alias_candidates"] = st.alias_candidates
    out["identity"].setdefault("hardware", {"instruments": new_oq.get("instruments"), "source": "openaq_reported",
                                            "confidence": "reported"})
    return out


class PostgresOpenAQRepository:
    def __init__(self, session_factory):
        self._sf = session_factory

    async def ensure_provider(self) -> int:
        async with self._sf() as s:
            pid = (await s.execute(text("SELECT id FROM providers WHERE code = :c"), {"c": PROVIDER_CODE})).scalar()
            if pid is None:
                pid = (await s.execute(text("""INSERT INTO providers (code, display_name, metadata, active)
                                               VALUES (:c, :d, CAST(:m AS jsonb), true) RETURNING id"""),
                                       {"c": PROVIDER_CODE, "d": PROVIDER_DISPLAY_NAME, "m": json.dumps(PROVIDER_METADATA)})).scalar_one()
            else:
                await s.execute(text("""UPDATE providers SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:m AS jsonb)
                                        WHERE id = :id AND COALESCE(metadata->>'origin','') <> 'openaq'"""),
                                {"m": json.dumps(PROVIDER_METADATA), "id": pid})
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

    async def resolve_geo(self, lat: float, lon: float) -> Dict[str, Any]:
        """Nearest existing city within 25 km (PostGIS). Metadata only; stations.city_id stays NULL in shadow."""
        try:
            async with self._sf() as s:
                row = (await s.execute(text("""
                    SELECT c.id, c.name, c.state_id,
                           ST_Distance(c.centroid, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d
                    FROM cities c
                    WHERE c.centroid IS NOT NULL
                      AND ST_DWithin(c.centroid, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 25000)
                    ORDER BY d ASC LIMIT 1
                """), {"lat": lat, "lon": lon})).first()
            if row is None:
                return {"method": "none", "resolved_at": now_iso()}
            return {"method": "nearest_city_centroid_25km", "city_id": int(row[0]), "city_name": row[1],
                    "state_id": int(row[2]) if row[2] is not None else None, "distance_m": round(float(row[3]), 1),
                    "resolved_at": now_iso(), "promoted": False}
        except Exception as exc:
            logger.warning("geo resolution unavailable (%s); leaving unresolved", type(exc).__name__)
            return {"method": "none", "error": type(exc).__name__, "resolved_at": now_iso()}

    async def upsert_shadow_station(self, st: StationUpsert, provider_id: int, run_id: str) -> str:
        station_id = station_id_for_location(st.location_id)
        async with self._sf() as s:
            existing = (await s.execute(text("SELECT station_id, metadata_json FROM stations WHERE provider_id = :p AND source_station_id = :sid"),
                                        {"p": provider_id, "sid": str(st.location_id)})).fetchone()
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
                   "src": str(st.location_id), "tz": st.timezone, "mt": st.monitor_type, "md": json.dumps(merged)})
            await s.commit()
            return sid

    async def seed_stream(self, seed: StreamSeed) -> None:
        async with self._sf() as s:
            await s.execute(text("""
                INSERT INTO ops.stream_checkpoints
                    (provider, stream_key, station_id, native_location_id, native_sensor_id, parameter, units_reported, status)
                VALUES (:p, :k, :st, :loc, :sen, :par, :u, :status)
                ON CONFLICT (provider, stream_key) DO UPDATE SET
                    station_id = EXCLUDED.station_id, units_reported = EXCLUDED.units_reported,
                    status = CASE WHEN ops.stream_checkpoints.status IN ('retired') THEN EXCLUDED.status
                                  ELSE ops.stream_checkpoints.status END,
                    missed_runs = 0, last_seen_at = now(), updated_at = now()
            """), {"p": PROVIDER_CODE, "k": seed.stream_key, "st": seed.station_id, "loc": seed.native_location_id,
                   "sen": seed.native_sensor_id, "par": seed.parameter, "u": seed.units_reported, "status": seed.status})
            await s.commit()

    async def mark_unseen_streams(self, seen_keys: Set[str], retire_after: int) -> int:
        async with self._sf() as s:
            keys = list(seen_keys) or ["__none__"]
            rs = await s.execute(text("""
                UPDATE ops.stream_checkpoints
                   SET missed_runs = missed_runs + 1,
                       status = CASE WHEN missed_runs + 1 >= :n AND status = 'active' THEN 'retired' ELSE status END,
                       updated_at = now()
                 WHERE provider = :p AND stream_key <> ALL(CAST(:keys AS text[])) AND status IN ('active', 'deferred_subhourly')
                 RETURNING stream_key
            """), {"p": PROVIDER_CODE, "keys": keys, "n": int(retire_after)})
            n = len(rs.fetchall())
            await s.commit()
            return n

    async def list_streams(self, status: str, limit: int) -> List[Stream]:
        async with self._sf() as s:
            rows = (await s.execute(text("""
                SELECT stream_key, station_id, native_location_id, native_sensor_id, parameter, status, units_reported,
                       interval_observed, completed_through, overlap_hours, reconciled_through, last_reconcile_at,
                       consecutive_failures, missed_runs
                FROM ops.stream_checkpoints
                WHERE provider = :p AND status = :s
                ORDER BY completed_through NULLS FIRST, last_attempt_at NULLS FIRST
                LIMIT :lim
            """), {"p": PROVIDER_CODE, "s": status, "lim": int(limit)})).fetchall()
        return [Stream(r[0], r[1].strip(), r[2], r[3], r[4], r[5], r[6], r[7], r[8], int(r[9] or 72), r[10], r[11],
                       int(r[12] or 0), int(r[13] or 0)) for r in rows]

    async def commit_window(self, stream: Stream, rows, refs, *, completed_through, run_id, page_count, interval_observed,
                            reconciled_through=None) -> ReconcileResult:
        async with self._sf() as s:
            for ref in refs:
                try:
                    async with s.begin_nested():
                        await record_in_session(s, ref)
                except Exception as exc:  # index row is best-effort; readings and checkpoint are not
                    logger.warning("raw payload index write failed (%s); continuing", type(exc).__name__)
            result = await reconcile_and_upsert_readings(s, rows, ReconcilePolicy(source=PROVIDER_CODE, run_id=run_id))
            await s.execute(text("""
                UPDATE ops.stream_checkpoints
                   SET completed_through = COALESCE(:ct, completed_through),
                       reconciled_through = COALESCE(:rt, reconciled_through),
                       last_reconcile_at = CASE WHEN :rt IS NULL THEN last_reconcile_at ELSE now() END,
                       interval_observed = COALESCE(:iv, interval_observed),
                       last_run_id = :run, last_attempt_at = now(), last_success_at = now(),
                       last_page_count = :pc, last_row_count = :rc, last_error = NULL, consecutive_failures = 0,
                       updated_at = now()
                 WHERE provider = :p AND stream_key = :k
            """), {"ct": completed_through, "rt": reconciled_through, "iv": interval_observed, "run": run_id,
                   "pc": page_count, "rc": len(rows), "p": PROVIDER_CODE, "k": stream.stream_key})
            await s.commit()
            return result

    async def mark_stream_failed(self, stream_key: str, error: str, run_id: str) -> None:
        async with self._sf() as s:
            await s.execute(text("""
                UPDATE ops.stream_checkpoints
                   SET last_attempt_at = now(), last_run_id = :run, last_error = :err,
                       consecutive_failures = consecutive_failures + 1, updated_at = now()
                 WHERE provider = :p AND stream_key = :k
            """), {"run": run_id, "err": error[:500], "p": PROVIDER_CODE, "k": stream_key})
            await s.commit()

    async def set_stream_status(self, stream_key: str, status: str, *, interval_observed=None, run_id=None) -> None:
        async with self._sf() as s:
            await s.execute(text("""
                UPDATE ops.stream_checkpoints
                   SET status = :st, interval_observed = COALESCE(:iv, interval_observed),
                       last_attempt_at = now(), last_run_id = COALESCE(:run, last_run_id), updated_at = now()
                 WHERE provider = :p AND stream_key = :k
            """), {"st": status, "iv": interval_observed, "run": run_id, "p": PROVIDER_CODE, "k": stream_key})
            await s.commit()

    async def candidate_stations_near(self, lat: float, lon: float, radius_m: float) -> List[Dict[str, Any]]:
        try:
            async with self._sf() as s:
                rows = (await s.execute(text("""
                    SELECT s.station_id, p.code, s.name,
                           ST_Distance(ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography,
                                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d
                    FROM stations s JOIN providers p ON p.id = s.provider_id
                    WHERE p.code <> :oq
                      AND ST_DWithin(ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326)::geography,
                                     ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)
                    ORDER BY d ASC LIMIT 10
                """), {"lat": lat, "lon": lon, "r": float(radius_m), "oq": PROVIDER_CODE})).fetchall()
            return [{"station_id": r[0].strip(), "provider_code": r[1], "name": r[2], "distance_m": float(r[3])} for r in rows]
        except Exception as exc:
            logger.warning("alias candidate lookup unavailable (%s)", type(exc).__name__)
            return []


class InMemoryOpenAQRepository:
    """Dict-backed stand-in with the same contract (tests, dry runs without a DB)."""

    def __init__(self, *, nearby: Optional[List[Dict[str, Any]]] = None, fail_commit_for: Optional[Set[str]] = None):
        self.provider_id = 42
        self.country_id = 1
        self.stations: Dict[str, Dict[str, Any]] = {}       # station_id -> row
        self.streams: Dict[str, Stream] = {}
        self.readings: Dict[tuple, Dict[str, Any]] = {}
        self.refs: List[RawPayloadRef] = []
        self.commits: List[Dict[str, Any]] = []
        self.failed: List[tuple] = []
        self.nearby = nearby or []
        self.fail_commit_for = fail_commit_for or set()

    async def ensure_provider(self) -> int:
        return self.provider_id

    async def resolve_country_id(self, iso2, name) -> int:
        return self.country_id

    async def resolve_geo(self, lat, lon):
        return {"method": "none", "resolved_at": now_iso()}

    async def upsert_shadow_station(self, st: StationUpsert, provider_id: int, run_id: str) -> str:
        existing = next((r for r in self.stations.values() if r["source_station_id"] == str(st.location_id)), None)
        sid = existing["station_id"] if existing else station_id_for_location(st.location_id)
        merged = _merge_station_metadata(existing["metadata_json"] if existing else None, st, run_id)
        self.stations[sid] = {"station_id": sid, "source_station_id": str(st.location_id), "name": st.name, "lat": st.lat,
                              "lon": st.lon, "active": False, "city_id": None, "state_id": None, "monitor_type": st.monitor_type,
                              "metadata_json": merged, "provider_id": provider_id}
        return sid

    async def seed_stream(self, seed: StreamSeed) -> None:
        cur = self.streams.get(seed.stream_key)
        if cur is None:
            self.streams[seed.stream_key] = Stream(seed.stream_key, seed.station_id, seed.native_location_id, seed.native_sensor_id,
                                                   seed.parameter, seed.status, seed.units_reported)
        else:
            cur.units_reported = seed.units_reported
            cur.missed_runs = 0
            if cur.status == "retired":
                cur.status = seed.status

    async def mark_unseen_streams(self, seen_keys, retire_after) -> int:
        n = 0
        for k, st in self.streams.items():
            if k not in seen_keys and st.status in ("active", "deferred_subhourly"):
                st.missed_runs += 1
                n += 1
                if st.missed_runs >= retire_after and st.status == "active":
                    st.status = "retired"
        return n

    async def list_streams(self, status, limit) -> List[Stream]:
        out = [s for s in self.streams.values() if s.status == status]
        out.sort(key=lambda s: (s.completed_through is not None, s.completed_through or datetime.min.replace(tzinfo=timezone.utc)))
        return out[:limit]

    async def commit_window(self, stream, rows, refs, *, completed_through, run_id, page_count, interval_observed,
                            reconciled_through=None) -> ReconcileResult:
        if stream.stream_key in self.fail_commit_for:
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
        st = self.streams[stream.stream_key]
        if completed_through is not None:
            st.completed_through = completed_through
        if reconciled_through is not None:
            st.reconciled_through = reconciled_through
        st.interval_observed = interval_observed or st.interval_observed
        st.consecutive_failures = 0
        self.commits.append({"stream": stream.stream_key, "rows": len(rows), "pages": page_count, "run_id": run_id,
                             "completed_through": completed_through})
        return res

    async def mark_stream_failed(self, stream_key, error, run_id) -> None:
        self.streams[stream_key].consecutive_failures += 1
        self.failed.append((stream_key, error))

    async def set_stream_status(self, stream_key, status, *, interval_observed=None, run_id=None) -> None:
        st = self.streams[stream_key]
        st.status = status
        if interval_observed:
            st.interval_observed = interval_observed

    async def candidate_stations_near(self, lat, lon, radius_m):
        return list(self.nearby)
