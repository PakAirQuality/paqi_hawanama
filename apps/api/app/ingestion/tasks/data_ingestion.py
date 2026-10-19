import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

from app.services.ingestion.iqair_service import (
    IQAirClient,
    IQAirError,
    StationNotFound,
    FeatureNotAvailable,
    RateLimited,
    Unauthorized,
    BadRequest,
)
from app.ingestion.db import DatabaseService, AsyncSessionLocal
from app.ingestion.extract import ExtractStats, normalize_envelope
from app.ingestion.manifests import ManifestRef, sync_latest_from_gcs
from app.ingestion.raw_archive import RawPayloadArchiver
from app.ingestion.reconcile import ReconcilePolicy, ReconcileResult
from app.ingestion.leases import LeaseManager, holder_id, lease_key_for
from app.ingestion.quota import PostgresQuota, QuotaUnavailable
from app.ingestion.runs import EntityFailure, RunAborted, RunOutcome, RunRecorder, new_run_id
from app.core.config import settings as _default_settings
from app.core.south_asia import get_state_aliases as _get_state_aliases, get_iqair_countries

logger = logging.getLogger(__name__)

# Optional pandas (for Parquet manifest)
try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    pd = None
    _HAVE_PANDAS = False

# Aliases to fix label mismatches between /stations and /station endpoints.
# Uses shared South Asia config for per-country aliases.
def _state_aliases(state: Optional[str], country: Optional[str] = None) -> List[str]:
    if not state:
        return []
    if country:
        return _get_state_aliases(country, state)
    # Fallback: no country context, just return [state]
    return [state]


# DB fallback inventory. Every column here exists in db_schema/initial_schema.sql
# (stations: station_id, source_station_id, name, lat, lon, active, provider_id,
# city_id, state_id, country_id; providers: id, code; cities: id, name, state_id;
# states: id, name, country_id; countries: id, name). Stations may lack a
# state_id/city_id, so the geo hierarchy is LEFT JOINed both directly and via
# the city. tests/ingestion/test_fallback_sql_schema.py checks this against the DDL.
STATION_FALLBACK_SQL = """
    SELECT
        st.station_id                               AS station_id,
        st.source_station_id                        AS source_station_id,
        st.name                                     AS iqair_station_name,
        st.lat                                      AS lat,
        st.lon                                      AS lon,
        st.active                                   AS active,
        COALESCE(co_direct.name, co_via_state.name) AS country,
        COALESCE(s_direct.name, s_via_city.name)    AS state,
        c.name                                      AS city,
        p.code                                      AS provider_code
    FROM stations st
    JOIN providers p                 ON p.id = st.provider_id
    LEFT JOIN cities c               ON c.id = st.city_id
    LEFT JOIN states s_direct        ON s_direct.id = st.state_id
    LEFT JOIN states s_via_city      ON s_via_city.id = c.state_id
    LEFT JOIN countries co_direct    ON co_direct.id = st.country_id
    LEFT JOIN countries co_via_state ON co_via_state.id = COALESCE(s_direct.country_id, s_via_city.country_id)
    WHERE st.active = true
      AND p.code = :provider_code
    ORDER BY country, st.name
"""


class DataIngestionTask:
    """Manifest-driven data ingestion (station endpoint) with backfill from history.pollution."""

    def __init__(self, *, settings=None, iqair_client=None, db_service=None, recorder_factory=None, leases=None,
                 archiver=None):
        # Everything is injectable so tests can run without a network or a database.
        self.settings = s = settings or _default_settings
        self.iqair_client = iqair_client or IQAirClient(
            settings=s, quota=PostgresQuota(AsyncSessionLocal, required=bool(s.OPS_TABLES_REQUIRED)))
        self.db_service = db_service or DatabaseService()
        # A fresh recorder per run (it buffers per-entity failures).
        self._recorder_factory = recorder_factory or (
            lambda: RunRecorder(AsyncSessionLocal, Path(s.INGEST_OUT_DIR), required=False)
        )
        self._leases = leases or LeaseManager(AsyncSessionLocal, required=True)
        self._archiver = archiver or RawPayloadArchiver(s)
        self._stats = ExtractStats()
        # Set per run: run id, report dir, abort signal (provider auth failure stops new fetches).
        self._run_id: Optional[str] = None
        self._out_dir: Optional[Path] = None
        self._abort: Optional[asyncio.Event] = None
        self._manifest_source: Optional[str] = None
        self._manifest_read_error: Optional[str] = None   # set when a manifest exists but cannot be parsed
        self._manifest_ref: Optional[ManifestRef] = None

        # Concurrency and rate limiting
        self._concurrency = int(s.INGEST_CONCURRENCY)
        self._sema = asyncio.Semaphore(self._concurrency)
        self._rate = int(s.IQAIR_MAX_CALLS_PER_MIN)

        # Fallback toggles
        self._allow_city_fallback   = bool(s.ALLOW_CITY_FALLBACK)
        self._allow_state_alias     = bool(s.ALLOW_STATE_ALIAS)
        self._db_station_fallback   = bool(s.ALLOW_DB_STATION_FALLBACK)

        # Filters — supports multi-country ingestion via IQAIR_COUNTRIES
        self._countries      = get_iqair_countries(s.IQAIR_COUNTRIES)
        self._provider_code  = s.STATION_PROVIDER_CODE

        # Backfill window (hours)
        self._backfill_hours = int(s.IQAIR_BACKFILL_HOURS)

        # Manifest config (written by station_discovery.py)
        self._manifest_dir = Path(s.STATION_MANIFEST_DIR)

    # --------------------------- manifest loading ---------------------------

    def _resolve_latest_manifest_path(self) -> Optional[Path]:
        # GCS is the source of truth across container instances; download only
        # when the object generation changed since the last sync.
        self._manifest_dir.mkdir(parents=True, exist_ok=True)
        ref = sync_latest_from_gcs(self._manifest_dir, "manifests/station_manifests", "parquet")
        self._manifest_ref = ref
        self._manifest_source = ref.source if ref else None
        return ref.path if ref else None

    def _read_parquet(self, path: Path) -> List[Dict[str, Any]]:
        if not _HAVE_PANDAS:
            logger.error("pandas is required to read parquet manifest: %s", path)
            return []
        try:
            df = pd.read_parquet(path)
            return df.to_dict("records")
        except Exception as e:
            # An unreadable manifest must not degrade into the DB fallback (which lists one
            # provider only): the run fails as manifest_unreadable instead (see _run).
            self._manifest_read_error = f"{type(e).__name__}: {e}"
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

    async def _list_stations_from_db(self) -> List[Dict[str, Any]]:
        """
        Optional DB fallback: list active provider stations for the target countries.
        Expected output keys align with the station manifest written by discovery.
        """
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            rs = await session.execute(text(STATION_FALLBACK_SQL), {"provider_code": self._provider_code})
            out: List[Dict[str, Any]] = []
            for row in rs.fetchall():
                m = dict(row._mapping)
                m["latitude"] = m.get("lat")
                m["longitude"] = m.get("lon")
                out.append(m)
            return out

    def _load_manifest(self) -> List[Dict[str, Any]]:
        """
        Load stations from discovery manifest; optionally fallback to DB if allowed.
        """
        p = self._resolve_latest_manifest_path()
        if p:
            logger.info("Using station manifest: %s", p)
            rows = self._read_parquet(p) if p.suffix == ".parquet" else self._read_jsonl(p)
        else:
            logger.error("No station manifest found in %s", self._manifest_dir)
            rows = []

        # Optional: DB fallback (caller handles async DB query)
        if (not rows) and self._db_station_fallback:
            logger.info("Station manifest empty; caller will attempt DB fallback for provider=%s, countries=%s",
                        self._provider_code, self._countries)

        # Normalize a few common field variants for safety
        for r in rows:
            if "iqair_station_name" not in r and "name" in r:
                r["iqair_station_name"] = r["name"]
            if "lat" not in r and "latitude" in r:
                r["lat"] = r["latitude"]
            if "lon" not in r and "longitude" in r:
                r["lon"] = r["longitude"]
        return rows

    def _build_scope_key(self, s: Dict[str, Any], scope_type: str) -> str:
        # Use hex station_id for stations, keep existing logic for cities
        if scope_type == "station":
            # Prefer hex station_id from manifest
            if s.get("station_id"):
                return s["station_id"]
            # Fallback: generate hex station_id using database service
            country = (s.get("country") or "").strip()
            state = (s.get("state") or "").strip()
            city = (s.get("city") or "").strip()
            name = (s.get("iqair_station_name") or s.get("name") or "").strip()
            lat = float(s.get("lat", 0))
            lon = float(s.get("lon", 0))
            
            return self.db_service.generate_station_id(country, state, city, name, lat, lon)
        else:  # city - keep existing pipe-separated format for compatibility
            parts = [
                (s.get("country") or "").strip().lower(),
                (s.get("state") or "").strip().lower(),
                (s.get("city") or "").strip().lower(),
            ]
            return "|".join([p for p in parts if p])

    # ----------------------------- public API --------------------------------

    async def fetch_station_readings(self, *, trigger: str = "http") -> RunOutcome:
        """
        Station-only ingestion (optionally city-fallback). Reads stations from manifest,
        or from DB if ALLOW_DB_STATION_FALLBACK=true and no manifest is present.
        Backfills using history.pollution within IQAIR_BACKFILL_HOURS.

        Returns a RunOutcome whose status is success / partial / failed; it never
        raises for operational failures (the caller maps status to HTTP/exit code).
        """
        s = self.settings
        run_id = new_run_id("ingest-stations")
        self._run_id = run_id
        self._out_dir = Path(s.INGEST_OUT_DIR) / run_id
        self._abort = asyncio.Event()
        self._manifest_source = None
        self._stats.reset()
        recorder = self._recorder_factory()
        outcome = RunOutcome(
            run_id=run_id, task="ingest-stations", provider_code=self._provider_code,
            scope=",".join(self._countries) if self._countries else "all", trigger=trigger,
        )
        outcome.details["config"] = {
            "rate_limit_per_min": self._rate, "concurrency": self._concurrency,
            "allow_city_fallback": self._allow_city_fallback, "allow_state_alias": self._allow_state_alias,
            "db_station_fallback": self._db_station_fallback, "countries": self._countries,
            "provider_code": self._provider_code, "backfill_hours": self._backfill_hours,
        }
        logger.info(
            "Starting station ingestion run %s (manifest mode). concurrency=%d, rate<=%d/min, "
            "fallback=%s, alias=%s, db_station_fallback=%s",
            run_id, self._concurrency, self._rate, self._allow_city_fallback, self._allow_state_alias,
            self._db_station_fallback,
        )
        await recorder.start(outcome)
        lease = None
        try:
            lease = await self._leases.acquire(lease_key_for("ingest-stations", self._provider_code, outcome.scope),
                                               holder_id(run_id), int(s.INGEST_LEASE_TTL_S))
            if lease is None:
                # Another instance (or a scheduler retry of a live run) holds it: a visible no-op, not a duplicate.
                outcome.skip("lease_held", "another ingest-stations run holds the lease")
            else:
                outcome.lease_key, outcome.lease_fence = lease.lease_key, lease.fence
                await self._run(outcome, recorder)
        except Exception as exc:
            logger.exception("Station ingestion run %s crashed", run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await recorder.finish(outcome)
            await self._leases.release(lease)
        c = outcome.counts
        logger.info("Ingestion run %s %s. expected=%d attempted=%d completed=%d failed=%d skipped=%d "
                    "rows_fetched=%d rows_written=%d rows_unchanged=%d (out: %s)",
                    run_id, outcome.status.value, c.expected, c.attempted, c.completed, c.failed, c.skipped,
                    c.rows_fetched, c.rows_written, c.rows_unchanged, outcome.report_dir)
        return outcome

    async def _run(self, outcome: RunOutcome, recorder: RunRecorder) -> None:
        c = outcome.counts
        quota = getattr(self.iqair_client, "quota", None)
        if quota is not None:
            try:
                await quota.healthcheck()
            except QuotaUnavailable as exc:
                # Never run unmetered against a shared credential.
                outcome.fail("quota_unavailable", str(exc))
                return
        rows = self._load_manifest()
        outcome.manifest_source = self._manifest_source
        if self._manifest_read_error:
            outcome.fail("manifest_unreadable",
                         f"manifest {self._manifest_ref.path if self._manifest_ref else ''} could not be parsed: "
                         f"{self._manifest_read_error} (no DB fallback: it would silently drop other providers)")
            return
        if self._manifest_ref is not None:
            outcome.manifest_generation = self._manifest_ref.generation
        if (not rows) and self._db_station_fallback:
            rows = await self._list_stations_from_db()
            outcome.manifest_source = "db"
        outcome.manifest_rows = len(rows)

        # Filter to active <countries,provider> and dedupe (station_name, city, state, country)
        country_set = {x.lower() for x in self._countries}
        seen = set()
        stations: List[Dict[str, Any]] = []
        for r in rows:
            if r.get("provider_code") != self._provider_code:
                continue
            if (r.get("country") or "").lower() not in country_set:
                continue
            if r.get("active") is False:
                continue
            tup = (r.get("iqair_station_name") or r.get("name"), r.get("city"), r.get("state"), r.get("country"))
            if None in tup:
                continue
            if tup in seen:
                continue
            seen.add(tup)
            stations.append(r)

        c.expected = len(stations)
        if not stations:
            # An empty inventory is a failure, not a success with zero work.
            outcome.fail("empty_inventory",
                         f"no stations after filters (manifest rows={len(rows)}, source={outcome.manifest_source})")
            return

        logger.info("Will request station endpoint for %d stations.", len(stations))
        results = await asyncio.gather(*[self._fetch_one(st) for st in stations], return_exceptions=True)

        buf: List[Dict[str, Any]] = []
        for i, res in enumerate(results):
            st = stations[i]
            meta = {
                "source_station_id": st.get("source_station_id"),
                "station": st.get("iqair_station_name") or st.get("name"),
                "city": st.get("city"), "state": st.get("state"), "country": st.get("country", ""),
            }
            key = st.get("station_id") or st.get("source_station_id") or f"{meta['country']}|{meta['state']}|{meta['city']}|{meta['station']}"
            if isinstance(res, RunAborted):
                c.skipped += 1
                continue
            c.attempted += 1
            if isinstance(res, BaseException):
                c.failed += 1
                recorder.add_failure(EntityFailure("station", key, type(res).__name__, str(res)[:500], details=meta))
            elif isinstance(res, list):
                if res:
                    buf.extend(res)
                    c.rows_fetched += len(res)
                    c.completed += 1
                else:
                    c.failed += 1
                    recorder.add_failure(EntityFailure("station", key, "no_points_in_response", "", details=meta))
            else:
                c.failed += 1
                recorder.add_failure(EntityFailure("station", key, "unexpected_result_type", type(res).__name__, details=meta))

        # Write whatever was fetched, even if the run is about to be marked failed.
        if buf:
            wr = await self._write_rows(buf, outcome.run_id)
            c.rows_written, c.rows_unchanged = wr.rows_written, wr.rows_unchanged
            outcome.details["reconcile"] = {
                "inserted": wr.rows_inserted, "updated": wr.rows_updated, "unchanged": wr.rows_unchanged,
                "withdrawn_fields": wr.rows_withdrawn_fields, "revisions": wr.revisions_recorded,
                "revisions_failed": wr.revisions_failed,
            }
            outcome.latest_observation_ts = max(r["ts_utc"] for r in buf)
            logger.info("Reconciled %d rows: %d inserted, %d updated, %d unchanged, %d revisions.",
                        wr.rows_in, wr.rows_inserted, wr.rows_updated, wr.rows_unchanged, wr.revisions_recorded)

        outcome.details["extraction"] = self._stats.to_dict()
        if self._abort is not None and self._abort.is_set():
            outcome.fail("provider_auth", "IQAir rejected the credential (401/403); remaining stations were skipped")

    # --------------------------- fetch + write helpers -----------------------

    async def _fetch_one(self, s: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Single station fetch using /v2/station. Optional state-alias retry and city fallback.
        Returns a LIST of upsert rows (history + current) or raises.
        """
        if self._abort is not None and self._abort.is_set():
            raise RunAborted("run aborted before fetch")
        async with self._sema:
            if self._abort is not None and self._abort.is_set():
                raise RunAborted("run aborted before fetch")
            station_name = s.get("iqair_station_name") or s.get("name")
            city = s.get("city")
            state = s.get("state")
            country = s.get("country") or ""

            # Try: exact state first, then aliases (if allowed)
            states_to_try = [state] if state else []
            if self._allow_state_alias:
                for a in _state_aliases(state, country)[1:]:
                    states_to_try.append(a)

            last_exc: Optional[Exception] = None

            for idx, state_try in enumerate(states_to_try or [state]):
                try:
                    env = await self.iqair_client.fetch_station(
                        station=station_name, city=city, state=state_try, country=country
                    )
                    parsed = self.iqair_client.parse_station_data(env.data)
                    # History data is already included in the station response
                    scope_type = "station"
                    scope_key = self._build_scope_key(s, scope_type)
                    return await normalize_envelope(
                        env, parsed, scope_type=scope_type, scope_key=scope_key, provider=self._provider_code,
                        native_id=s.get("source_station_id") or scope_key, stream="station",
                        archiver=self._archiver, session_factory=AsyncSessionLocal, run_id=self._run_id,
                        backfill_hours=self._backfill_hours, stats=self._stats,
                    )
                except StationNotFound as e:
                    last_exc = e
                    logger.info(
                        "Station not found: '%s' in %s, %s (try %d/%d).",
                        station_name, city, state_try, idx + 1, len(states_to_try or [state])
                    )
                except FeatureNotAvailable as e:
                    last_exc = e
                    logger.info("Feature not available for station '%s' (%s).", station_name, e)
                    break
                except RateLimited as e:
                    logger.warning("Rate limited while fetching station '%s': %s", station_name, e)
                    raise
                except Unauthorized as e:
                    # The credential is bad for every station: stop launching new fetches.
                    logger.error("Unauthorized for '%s', %s, %s: %s — aborting run", station_name, city, state_try, e)
                    if self._abort is not None:
                        self._abort.set()
                    raise
                except BadRequest as e:
                    logger.error("BadRequest for '%s', %s, %s: %s", station_name, city, state_try, e)
                    raise
                except IQAirError as e:
                    last_exc = e
                    logger.warning("IQAir error for '%s', %s, %s: %s", station_name, city, state_try, e)
                except Exception as e:
                    last_exc = e
                    logger.warning("Unexpected error for '%s', %s, %s: %s", station_name, city, state_try, e)

            # If we reach here, station lookups (incl. aliases) failed.
            # Optional: city fallback
            if self._allow_city_fallback:
                try:
                    env = await self.iqair_client.fetch_city(city=city, state=state, country=country)
                    parsed = self.iqair_client.parse_city_data(env.data)
                    scope_type = "city"
                    scope_key = self._build_scope_key(s, scope_type)
                    return await normalize_envelope(
                        env, parsed, scope_type=scope_type, scope_key=scope_key, provider=self._provider_code,
                        native_id=scope_key, stream="city",
                        archiver=self._archiver, session_factory=AsyncSessionLocal, run_id=self._run_id,
                        backfill_hours=self._backfill_hours, stats=self._stats,
                    )
                except Exception as e2:
                    logger.warning("City fallback failed for '%s' (%s, %s): %s", station_name, city, state, e2)
                    raise (last_exc or e2)

            if last_exc:
                raise last_exc
            raise StationNotFound(f"Unable to resolve station '{station_name}' in {city}, {state}")

    async def _write_rows(self, rows: List[Dict[str, Any]], run_id: Optional[str]) -> ReconcileResult:
        """Field-aware reconcile + commit (replaces dedupe → drop-existing → overwrite upsert)."""
        try:
            async with AsyncSessionLocal() as sess:
                result = await self.db_service.reconcile_and_upsert_readings(
                    sess, rows, ReconcilePolicy(source=self._provider_code, run_id=run_id))
                await sess.commit()
                return result
        except Exception as e:
            logger.error("Readings write failed: %s", e)
            raise

# small runner to match run_task.py expectations
async def station_ingestion():
    return await DataIngestionTask().fetch_station_readings()

if __name__ == "__main__":
    # Allow direct execution for ad-hoc runs
    asyncio.run(station_ingestion())
