"""
City-Level Hourly Ingestion (manifest-driven, city endpoint)
Consumes the *derived city manifest* produced by station_discovery.py.

- Primary source: artifacts/city_manifests/latest.(parquet|jsonl)
- Automatic fallback: derive unique (country,state,city[,lat,lon]) from
  artifacts/station_manifests/latest.(parquet|jsonl) if city manifest missing.
- Optional fallback: query DB for cities if ALLOW_DB_CITY_FALLBACK=true.
- Strictly uses the IQAir /v2/city endpoint (with optional state-alias retries).
- Optional fallback to /v2/nearest_city when enabled and coords exist.
- Global rate limiter (default 90/min) + bounded concurrency (default 6).
- Writes a per-run ingest report (metrics + failures).
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from app.services.ingestion.iqair_service import IQAirClient, Unauthorized
from app.ingestion.db import DatabaseService, AsyncSessionLocal
from app.ingestion.extract import ExtractStats, normalize_envelope
from app.ingestion.manifests import ManifestRef, sync_latest_from_gcs
from app.ingestion.raw_archive import RawPayloadArchiver
from app.ingestion.reconcile import ReconcilePolicy, ReconcileResult
from app.ingestion.leases import LeaseManager, holder_id, lease_key_for
from app.ingestion.quota import PostgresQuota, QuotaUnavailable
from app.ingestion.runs import EntityFailure, RunAborted, RunOutcome, RunRecorder, new_run_id
from app.core.config import settings as _default_settings
from app.core.south_asia import get_state_aliases as _get_state_aliases_sa, get_iqair_countries

logger = logging.getLogger(__name__)

# Optional pandas (for Parquet manifest)
try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    pd = None
    _HAVE_PANDAS = False

# ---- aliasing to deal with label mismatches between /cities and /city endpoints ----
# Uses shared South Asia config for per-country aliases.
def _state_aliases(state: Optional[str], country: Optional[str] = None) -> List[str]:
    if not state:
        return []
    if country:
        return _get_state_aliases_sa(country, state)
    return [state]

def _scope_key(country: str, state: str, city: str) -> str:
    return f"{country.lower()}|{state.lower()}|{city.lower()}"

# DB fallback inventory. cities has no latitude/longitude columns (only a
# centroid geography), and country_id is NOT NULL on cities so it joins
# directly. Verified against db_schema/initial_schema.sql by
# tests/ingestion/test_fallback_sql_schema.py.
CITY_FALLBACK_SQL = """
    SELECT
        co.name                         AS country,
        s.name                          AS state,
        c.name                          AS city,
        ST_Y(c.centroid::geometry)      AS lat,
        ST_X(c.centroid::geometry)      AS lon
    FROM cities c
    JOIN states s     ON s.id = c.state_id
    JOIN countries co ON co.id = c.country_id
    WHERE c.active = true
      AND LOWER(co.name) = LOWER(:country)
    ORDER BY c.name
"""


class CityIngestionTask:
    """Manifest-driven city-level ingestion (IQAir /v2/city)."""

    def __init__(self, *, settings=None, iqair_client=None, db_service=None, recorder_factory=None, leases=None,
                 archiver=None):
        # Everything is injectable so tests can run without a network or a database.
        self.settings = s = settings or _default_settings
        self.iqair_client = iqair_client or IQAirClient(
            settings=s, quota=PostgresQuota(AsyncSessionLocal, required=bool(s.OPS_TABLES_REQUIRED)))
        self.db_service = db_service or DatabaseService()
        self._recorder_factory = recorder_factory or (
            lambda: RunRecorder(AsyncSessionLocal, Path(s.INGEST_OUT_DIR), required=False)
        )
        self._leases = leases or LeaseManager(AsyncSessionLocal, required=True)
        self._archiver = archiver or RawPayloadArchiver(s)
        self._stats = ExtractStats()
        self._run_id: Optional[str] = None
        self._out_dir: Optional[Path] = None
        self._abort: Optional[asyncio.Event] = None
        self._manifest_source: Optional[str] = None
        self._manifest_ref: Optional[ManifestRef] = None

        # Concurrency and rate limiting
        self._concurrency = int(s.INGEST_CONCURRENCY)
        self._sema = asyncio.Semaphore(self._concurrency)
        self._rate = int(s.IQAIR_MAX_CALLS_PER_MIN)

        # Toggles
        self._allow_state_alias      = bool(s.ALLOW_STATE_ALIAS)
        self._allow_nearest_fallback = bool(s.ALLOW_NEAREST_FALLBACK)
        self._db_city_fallback       = bool(s.ALLOW_DB_CITY_FALLBACK)
        self._manifest_read_error: Optional[str] = None

        # Manifest locations (produced by station_discovery.py)
        self._city_manifest_dir    = Path(s.CITY_MANIFEST_DIR)
        self._station_manifest_dir = Path(s.STATION_MANIFEST_DIR)

    # --------------------------- manifest loading ---------------------------

    def _prefer_existing(self, base: Path, gcs_prefix: str = "") -> Optional[Path]:
        """Latest manifest path, synced from GCS when the bucket has a newer generation."""
        base.mkdir(parents=True, exist_ok=True)
        ref = sync_latest_from_gcs(base, gcs_prefix, "parquet") if gcs_prefix else None
        if ref is None:
            for p in (base / "latest.parquet", base / "latest.jsonl"):
                if p.exists():
                    ref = ManifestRef(p, "local")
                    break
        self._manifest_ref = ref
        self._manifest_source = ref.source if ref else None
        return ref.path if ref else None

    def _resolve_latest_city_manifest_path(self) -> Optional[Path]:
        return self._prefer_existing(self._city_manifest_dir, gcs_prefix="manifests/city_manifests")

    def _resolve_latest_station_manifest_path(self) -> Optional[Path]:
        return self._prefer_existing(self._station_manifest_dir, gcs_prefix="manifests/station_manifests")

    def _read_parquet(self, path: Path) -> List[Dict[str, Any]]:
        if not _HAVE_PANDAS:
            logger.error("pandas is required to read parquet manifest: %s", path)
            return []
        try:
            df = pd.read_parquet(path)
            return df.to_dict("records")
        except Exception as e:
            self._manifest_read_error = f"{type(e).__name__}: {e}"   # _run fails as manifest_unreadable
            logger.error("Failed reading parquet %s: %s", path, e)
            return []

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception as e:
                        logger.warning("Skipping malformed JSONL line in %s: %s", path, e)
        except FileNotFoundError:
            logger.error("JSONL manifest not found: %s", path)
        return rows

    def _load_city_manifest(self) -> List[Dict[str, Any]]:
        """
        Try city manifest first (preferred). If missing, derive from station manifest:
        group by (country,state,city), compute simple centroid of lat/lon, build rows compatible
        with station_discovery's derived city manifest keys.
        """
        p = self._resolve_latest_city_manifest_path()
        if p:
            logger.info("Using city manifest: %s", p)
            rows = self._read_parquet(p) if p.suffix == ".parquet" else self._read_jsonl(p)
            return rows

        # Fallback: derive from station manifest
        ps = self._resolve_latest_station_manifest_path()
        if not ps:
            logger.error("No city manifest at %s and no station manifest at %s", self._city_manifest_dir, self._station_manifest_dir)
            return []

        logger.info("Deriving city list from station manifest: %s", ps)
        self._manifest_source = "derived"
        srows = self._read_parquet(ps) if ps.suffix == ".parquet" else self._read_jsonl(ps)
        if not srows:
            logger.error("Station manifest is empty or unreadable: %s", ps)
            return []

        groups = defaultdict(list)  # (country,state,city) -> [(lat,lon), ...]
        for r in srows:
            if r.get("active") is False:
                continue
            country, state, city = r.get("country"), r.get("state"), r.get("city")
            if not (country and state and city):
                continue
            lat = r.get("lat") if r.get("lat") is not None else r.get("latitude")
            lon = r.get("lon") if r.get("lon") is not None else r.get("longitude")
            try:
                lat_f = float(lat) if lat is not None else None
                lon_f = float(lon) if lon is not None else None
            except Exception:
                lat_f, lon_f = None, None
            groups[(country, state, city)].append((lat_f, lon_f))

        out: List[Dict[str, Any]] = []
        for (country, state, city), coords in groups.items():
            lats = [la for la, _ in coords if la is not None]
            lons = [lo for _, lo in coords if lo is not None]
            lat = sum(lats) / len(lats) if lats else None
            lon = sum(lons) / len(lons) if lons else None
            out.append({
                "run_id": "derived-from-stations",
                "country": country,
                "state": state,
                "city": city,
                "lat": lat,
                "lon": lon,
                "active": True,
                "scope_key": _scope_key(country, state, city),
                "last_seen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })

        logger.info("Derived %d unique cities from station manifest.", len(out))
        return out

    async def _list_cities_from_db(self, country: str) -> List[Dict[str, Any]]:
        """
        Optional DB fallback if both manifests are missing/empty and ALLOW_DB_CITY_FALLBACK=true.
        Returns dicts with keys: country, state, city, lat, lon, active (assume True), scope_key
        """
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            rs = await session.execute(text(CITY_FALLBACK_SQL), {"country": country})
            out: List[Dict[str, Any]] = []
            for row in rs.fetchall():
                m = dict(row._mapping)
                m["active"] = True
                m["scope_key"] = _scope_key(m["country"], m["state"], m["city"])
                out.append(m)
            return out

    # ----------------------------- public API --------------------------------

    async def fetch_city_readings_hourly(self, country: Optional[str] = None, *, trigger: str = "http") -> RunOutcome:
        """
        Hourly city ingestion job – reads cities from manifest (or derives from station manifest / DB),
        fetches /v2/city for each, normalizes, and bulk upserts readings.

        If country is None, ingests all countries from IQAIR_COUNTRIES config.
        Returns a RunOutcome (success / partial / failed); never raises for operational failures.
        """
        s = self.settings
        target_countries = [country] if country else get_iqair_countries(s.IQAIR_COUNTRIES)
        run_id = new_run_id("ingest-cities")
        self._run_id = run_id
        self._out_dir = Path(s.INGEST_OUT_DIR) / run_id
        self._abort = asyncio.Event()
        self._manifest_source = None
        self._stats.reset()
        recorder = self._recorder_factory()
        outcome = RunOutcome(
            run_id=run_id, task="ingest-cities", provider_code="airvisual",
            scope=country or ",".join(target_countries), trigger=trigger,
        )
        outcome.details["config"] = {
            "rate_limit_per_min": self._rate, "concurrency": self._concurrency,
            "allow_state_alias": self._allow_state_alias, "allow_nearest_fallback": self._allow_nearest_fallback,
            "db_city_fallback": self._db_city_fallback, "countries": target_countries,
        }
        logger.info(
            "Starting city ingestion run %s (manifest mode). countries=%s, concurrency=%d, rate<=%d/min, "
            "alias=%s, nearest_fallback=%s, db_city_fallback=%s",
            run_id, target_countries, self._concurrency, self._rate, self._allow_state_alias,
            self._allow_nearest_fallback, self._db_city_fallback,
        )
        await recorder.start(outcome)
        lease = None
        try:
            lease = await self._leases.acquire(lease_key_for("ingest-cities", "airvisual", outcome.scope),
                                               holder_id(run_id), int(s.INGEST_LEASE_TTL_S))
            if lease is None:
                outcome.skip("lease_held", "another ingest-cities run holds the lease")
            else:
                outcome.lease_key, outcome.lease_fence = lease.lease_key, lease.fence
                await self._run(outcome, recorder, target_countries)
        except Exception as exc:
            logger.exception("City ingestion run %s crashed", run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await recorder.finish(outcome)
            await self._leases.release(lease)
        c = outcome.counts
        logger.info("City ingestion run %s %s. expected=%d attempted=%d completed=%d failed=%d skipped=%d "
                    "rows_fetched=%d rows_written=%d rows_unchanged=%d (out: %s)",
                    run_id, outcome.status.value, c.expected, c.attempted, c.completed, c.failed, c.skipped,
                    c.rows_fetched, c.rows_written, c.rows_unchanged, outcome.report_dir)
        return outcome

    async def _run(self, outcome: RunOutcome, recorder: RunRecorder, target_countries: List[str]) -> None:
        c = outcome.counts
        quota = getattr(self.iqair_client, "quota", None)
        if quota is not None:
            try:
                await quota.healthcheck()
            except QuotaUnavailable as exc:
                # Never run unmetered against a shared credential.
                outcome.fail("quota_unavailable", str(exc))
                return
        country_set = {x.lower() for x in target_countries}

        rows = self._load_city_manifest()
        outcome.manifest_source = self._manifest_source
        if self._manifest_read_error:
            outcome.fail("manifest_unreadable", f"manifest could not be parsed: {self._manifest_read_error}")
            return
        if self._manifest_ref is not None and self._manifest_source in ("gcs", "local"):
            outcome.manifest_generation = self._manifest_ref.generation
        if not rows and self._db_city_fallback:
            logger.info("City manifest empty → using DB fallback for countries=%s", target_countries)
            for tc in target_countries:
                rows.extend(await self._list_cities_from_db(tc))
            outcome.manifest_source = "db"
        outcome.manifest_rows = len(rows)

        # Filter to target countries + active, dedupe (city,state,country)
        seen = set()
        cities: List[Dict[str, Any]] = []
        for r in rows:
            if (r.get("country") or "").lower() not in country_set:
                continue
            if r.get("active") is False:
                continue
            tup = (r.get("city"), r.get("state"), r.get("country"))
            if None in tup:
                continue
            if tup in seen:
                continue
            seen.add(tup)
            r["scope_key"] = r.get("scope_key") or _scope_key(r["country"], r["state"], r["city"])
            cities.append(r)

        c.expected = len(cities)
        if not cities:
            outcome.fail("empty_inventory",
                         f"no cities after filters (manifest rows={len(rows)}, source={outcome.manifest_source})")
            return

        logger.info("Will request city endpoint for %d cities.", len(cities))
        results = await asyncio.gather(*[self._fetch_one_city(ct) for ct in cities], return_exceptions=True)

        buf: List[Dict[str, Any]] = []
        for i, res in enumerate(results):
            ct = cities[i]
            meta = {"scope_key": ct["scope_key"], "city": ct["city"], "state": ct["state"], "country": ct["country"]}
            if isinstance(res, RunAborted):
                c.skipped += 1
                continue
            c.attempted += 1
            if isinstance(res, BaseException):
                c.failed += 1
                recorder.add_failure(EntityFailure("city", ct["scope_key"], type(res).__name__, str(res)[:500], details=meta))
            elif res:
                c.completed += 1
                if isinstance(res, list):
                    buf.extend(res)
                    c.rows_fetched += len(res)
                else:
                    buf.append(res)
                    c.rows_fetched += 1
            else:
                c.failed += 1
                recorder.add_failure(EntityFailure("city", ct["scope_key"], "empty_result", "", details=meta))

        if buf:
            wr = await self._write_rows(buf, outcome.run_id)
            c.rows_written, c.rows_unchanged = wr.rows_written, wr.rows_unchanged
            outcome.details["reconcile"] = {
                "inserted": wr.rows_inserted, "updated": wr.rows_updated, "unchanged": wr.rows_unchanged,
                "withdrawn_fields": wr.rows_withdrawn_fields, "revisions": wr.revisions_recorded,
                "revisions_failed": wr.revisions_failed,
            }
            outcome.latest_observation_ts = max(r["ts_utc"] for r in buf)
            logger.info("Reconciled %d city rows: %d inserted, %d updated, %d unchanged.",
                        wr.rows_in, wr.rows_inserted, wr.rows_updated, wr.rows_unchanged)

        outcome.details["extraction"] = self._stats.to_dict()
        if self._abort is not None and self._abort.is_set():
            outcome.fail("provider_auth", "IQAir rejected the credential (401/403); remaining cities were skipped")

    # --------------------------- helpers -------------------------------------

    async def _fetch_one_city(self, row: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch one city via /v2/city with optional state-alias retries.
        If enabled and lat/lon present, fallback to /v2/nearest_city.
        """
        if self._abort is not None and self._abort.is_set():
            raise RunAborted("run aborted before fetch")
        async with self._sema:
            if self._abort is not None and self._abort.is_set():
                raise RunAborted("run aborted before fetch")
            city = row.get("city")
            state = row.get("state")
            country = row.get("country") or ""
            scope_key = row["scope_key"]

            states_to_try = [state] if state else []
            if self._allow_state_alias:
                for a in _state_aliases(state, country)[1:]:
                    states_to_try.append(a)

            last_exc: Optional[Exception] = None

            # Try exact + alias states
            for idx, state_try in enumerate(states_to_try or [state]):
                try:
                    env = await self.iqair_client.fetch_city(city=city, state=state_try, country=country)
                    parsed = self.iqair_client.parse_city_data(env.data)
                    return await self._normalize(env, parsed, scope_key)
                except Unauthorized as e:
                    # The credential is bad for every city: stop launching new fetches.
                    logger.error("Unauthorized for %s (%s, %s): %s — aborting run", city, state_try, country, e)
                    if self._abort is not None:
                        self._abort.set()
                    raise
                except Exception as e:
                    last_exc = e
                    emsg = str(e).lower()
                    if "not_found" in emsg or "city_not_found" in emsg:
                        logger.info(
                            "City not found: '%s, %s, %s' (try %d/%d).",
                            city, state_try, country, idx + 1, len(states_to_try or [state])
                        )
                        continue
                    logger.warning("City API error for %s (%s, %s): %s", city, state_try, country, e)
                    # Continue trying aliases unless it's clearly unrecoverable.

            # Optional nearest_city fallback
            if self._allow_nearest_fallback:
                lat = row.get("lat") or row.get("latitude")
                lon = row.get("lon") or row.get("longitude")
                if lat is not None and lon is not None:
                    try:
                        env = await self.iqair_client.fetch_nearest_city(lat=float(lat), lon=float(lon))
                        parsed = self.iqair_client.parse_city_data(env.data)
                        logger.info("Used nearest_city fallback for %s (%.4f, %.4f)", scope_key, lat, lon)
                        return await self._normalize(env, parsed, scope_key)
                    except Exception as e2:
                        logger.warning("Nearest-city fallback failed for %s: %s", scope_key, e2)
                        if last_exc:
                            raise last_exc
                        raise e2

            if last_exc:
                raise last_exc
            return None

    async def _normalize(self, env, parsed: Dict[str, Any], scope_key: str) -> List[Dict[str, Any]]:
        """Archive the response, extract rows under iqair_city_v1, validate; qc_state is never 'OK' here."""
        return await normalize_envelope(
            env, parsed, scope_type="city", scope_key=scope_key, provider="airvisual",
            native_id=scope_key, stream="city",
            archiver=self._archiver, session_factory=AsyncSessionLocal, run_id=self._run_id,
            backfill_hours=int(self.settings.IQAIR_BACKFILL_HOURS), stats=self._stats,
        )

    async def _write_rows(self, rows: List[Dict[str, Any]], run_id: Optional[str]) -> ReconcileResult:
        """Field-aware reconcile + commit (replaces dedupe → drop-existing → overwrite upsert)."""
        try:
            async with AsyncSessionLocal() as sess:
                result = await self.db_service.reconcile_and_upsert_readings(
                    sess, rows, ReconcilePolicy(source="airvisual", run_id=run_id))
                await sess.commit()
                return result
        except Exception as e:
            logger.error("Readings write failed: %s", e)
            raise
