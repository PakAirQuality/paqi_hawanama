"""
ICIMOD hourly ingestion (shadow provider; gated by ICIMOD_ENABLED).

One run = station catalogue (2 GETs) → shadow-station upserts with alias
candidates toward nearby non-ICIMOD stations → ONE POST for the current UTC
day of PM2.5 for every catalogued station → normalise → commit readings and
the raw-payload index rows in one transaction. Every payload is archived first.

The run record's `details` carries the pilot metrics (stations_in_catalogue,
stations_with_data, hours_covered, latest_label, latest_label_age_min,
stations_per_hour, …) so 48 hours of ops.ingest_runs answer "how consistently
does the feed update" without any extra tooling.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings as _default_settings
from app.ingestion.db import AsyncSessionLocal
from app.ingestion.identity import now_iso
from app.ingestion.leases import LeaseManager, holder_id, lease_key_for
from app.ingestion.raw_archive import RawPayloadArchiver, RawPayloadRef
from app.ingestion.runs import EntityFailure, RunOutcome, RunRecorder, new_run_id
from app.services.ingestion.icimod.client import ICIMODClient, ICIMODError
from app.services.ingestion.icimod.normalize import (DEFAULT_TZ, PARSER_VERSION, PROVIDER_CODE, TS_POLICY, Station,
                                                     normalize_feature, parse_feature_collection, parse_stations,
                                                     station_id_for_icimod)
from app.services.ingestion.icimod.repository import PostgresICIMODRepository, StationUpsert
from app.services.ingestion.openaq.identity import compute_alias_candidates
from app.services.ingestion.openaq.models import Location, NamedRef

logger = logging.getLogger(__name__)

TASK = "icimod-ingest"
SCOPE = "punjab"
COUNTRY_ISO, COUNTRY_NAME = "PK", "Pakistan"
GROUND_DATA_PROVIDER = "EPCCD Punjab"      # the originating agency, as the portal attributes it


class ICIMODIngestTask:
    def __init__(self, *, settings=None, client: Optional[ICIMODClient] = None, repo=None, archiver=None,
                 recorder_factory=None, leases=None, now=None):
        self.settings = s = settings or _default_settings
        self.client = client or ICIMODClient(settings=s)
        self.repo = repo or PostgresICIMODRepository(AsyncSessionLocal)
        self.archiver = archiver or RawPayloadArchiver(s)
        self._recorder_factory = recorder_factory or (lambda: RunRecorder(AsyncSessionLocal, Path(s.INGEST_OUT_DIR), required=False))
        self._leases = leases or LeaseManager(AsyncSessionLocal, required=True)
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def run(self, *, dry_run: bool = False, trigger: str = "http") -> RunOutcome:
        s = self.settings
        run_id = new_run_id(TASK)
        recorder = self._recorder_factory()
        outcome = RunOutcome(run_id=run_id, task=TASK, provider_code=PROVIDER_CODE, scope=SCOPE, trigger=trigger)
        outcome.details.update({"dry_run": dry_run, "ts_policy": TS_POLICY})
        await recorder.start(outcome)
        lease = None
        try:
            if not s.ICIMOD_ENABLED and not dry_run:
                outcome.skip("disabled", "ICIMOD_ENABLED is false")
                return outcome
            lease = await self._leases.acquire(lease_key_for(TASK, PROVIDER_CODE, SCOPE), holder_id(run_id), int(s.INGEST_LEASE_TTL_S))
            if lease is None:
                outcome.skip("lease_held", f"another {TASK} run holds the lease")
                return outcome
            outcome.lease_key, outcome.lease_fence = lease.lease_key, lease.fence
            await self._run(outcome, recorder, run_id, dry_run)
        except ICIMODError as exc:
            outcome.fail("provider_error", str(exc))
        except Exception as exc:
            logger.exception("ICIMOD %s run %s crashed", TASK, run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.details["requests_made"] = getattr(self.client, "requests_made", None)
            outcome.finish()
            await recorder.finish(outcome)
            await self._leases.release(lease)
        logger.info("ICIMOD %s %s %s: %s", TASK, run_id, outcome.status.value, outcome.counts)
        return outcome

    # ---- steps -----------------------------------------------------------------

    async def _run(self, outcome: RunOutcome, recorder: RunRecorder, run_id: str, dry_run: bool) -> None:
        s = self.settings
        c = outcome.counts
        d = outcome.details
        now = self._now()

        provider_id = country_id = None
        if not dry_run:
            provider_id = await self.repo.ensure_provider()
            country_id = await self.repo.resolve_country_id(COUNTRY_ISO, COUNTRY_NAME)

        # 1. catalogue
        districts_payload, _, _ = await self.client.list_districts()
        districts = [str(x) for x in districts_payload] if isinstance(districts_payload, list) else []
        d["districts"] = len(districts)
        if not districts:
            outcome.fail("catalogue_empty", "ICIMOD returned no districts for the configured state")
            return
        stations_payload, fetched_at, status = await self.client.list_stations(districts)
        ref = await self._archive("stations", SCOPE, stations_payload, fetched_at, status, run_id,
                                  {"endpoint": "pakistan-dashboard/icimod/stations", "districts": len(districts)})
        await self.archiver.record(AsyncSessionLocal, ref)
        stations, cat_notes = parse_stations(stations_payload, state=s.ICIMOD_STATE)
        d["catalogue_notes"] = dict(cat_notes)
        d["stations_in_catalogue"] = len(stations)
        if not stations:
            outcome.fail("catalogue_empty", "ICIMOD station catalogue is empty")
            return
        c.expected = len(stations)

        # 2. shadow stations (+ alias candidates toward our own stations nearby)
        by_name: Dict[str, Station] = {}
        duplicates: List[str] = []
        for st in stations:
            if st.name in by_name:
                duplicates.append(st.name)
            else:
                by_name[st.name] = st
        for name in duplicates:
            by_name.pop(name, None)
        d["duplicate_names"] = sorted(set(duplicates))
        # counts: attempted = stations we tried to register, failed = upsert failures,
        # completed = stations that delivered at least one hourly value this run.
        station_ids: Dict[str, str] = {}
        c.attempted = len(by_name)
        if not dry_run:
            for st in by_name.values():
                try:
                    station_ids[st.name] = await self._upsert_station(st, provider_id, country_id, run_id)
                except Exception as exc:
                    c.failed += 1
                    recorder.add_failure(EntityFailure("station", st.name, type(exc).__name__, str(exc)[:300]))
                    logger.warning("ICIMOD station %s upsert failed: %s", st.name, exc)
        else:
            station_ids = {st.name: station_id_for_icimod(st.id) for st in by_name.values()}

        # 3. one POST for the current UTC day
        names = sorted(station_ids)
        if not names:
            outcome.fail("all_entities_failed", "no station could be upserted")
            return
        payload, fetched_at, status = await self.client.recent_timeseries(names)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        ts_ref = await self._archive("timeseries_recent", f"{SCOPE}-pm25", payload, fetched_at, status, run_id,
                                     {"endpoint": "external-api/charts/timeseries/recent/geojson", "station_count": len(names),
                                      "pollutant": s.ICIMOD_POLLUTANT, "source": s.ICIMOD_SOURCE}, window_from=day_start, window_to=now)
        features = parse_feature_collection(payload)
        if not features:
            outcome.fail("timeseries_empty", "ICIMOD returned no features for the requested stations")
            return

        # 4. normalise
        prov_base = {**ts_ref.prov(), "run": run_id}
        rows: List[Dict[str, Any]] = []
        notes: Counter = Counter()
        unmatched: List[str] = []
        with_data = 0
        per_hour: Counter = Counter()
        labels: List[str] = []
        for f in features:
            sid = station_ids.get(f.name)
            if sid is None:
                unmatched.append(f.name)
                continue
            frows, fnotes = normalize_feature(f, station_id=sid, prov_base=prov_base, now=now)
            notes.update(fnotes)
            if frows:
                with_data += 1
                c.completed += 1
            rows.extend(frows)
            for r in frows:
                per_hour[r["ts_utc"].isoformat()] += 1
                labels.append(r["raw"]["prov"]["label"])
        c.rows_fetched = sum(len(f.hourly_data) for f in features)
        latest_ts = max((r["ts_utc"] for r in rows), default=None)
        latest_label = max(labels, default=None)
        d.update({
            "stations_in_response": len(features), "stations_with_data": with_data,
            "hours_covered": len(per_hour), "stations_per_hour": dict(sorted(per_hour.items())),
            "earliest_label": min(labels, default=None), "latest_label": latest_label,
            "latest_label_age_min": (round((now - latest_ts).total_seconds() / 60.0, 1) if latest_ts else None),
            "normalize_notes": dict(notes), "unmatched_features": sorted(unmatched),
        })
        outcome.latest_observation_ts = latest_ts

        # 5. commit
        if dry_run:
            d["rows_would_write"] = len(rows)
            return
        res = await self.repo.commit_readings(rows, [ts_ref], run_id=run_id)
        c.rows_written += res.rows_written
        c.rows_unchanged += res.rows_unchanged
        d["revisions_recorded"] = res.revisions_recorded

    async def _upsert_station(self, st: Station, provider_id: int, country_id: int, run_id: str) -> str:
        s = self.settings
        nearby = await self.repo.candidate_stations_near(st.lat, st.lon, float(s.ICIMOD_ALIAS_DISTANCE_M))
        loc = Location(id=st.id, name=st.name, provider=NamedRef(name=GROUND_DATA_PROVIDER))
        cands = compute_alias_candidates(loc, nearby, evaluated_at=now_iso())
        snapshot = {"icimod": {"id": st.id, "name": st.name, "district": st.district, "city": st.city, "state": st.state,
                               "lat": st.lat, "lon": st.lon, "ground_data_provider": GROUND_DATA_PROVIDER},
                    "origin": PROVIDER_CODE}
        return await self.repo.upsert_shadow_station(
            StationUpsert(native_id=st.id, name=st.name, lat=st.lat, lon=st.lon, country_id=country_id, timezone=DEFAULT_TZ,
                          metadata=snapshot, alias_candidates=cands), provider_id, run_id)

    async def _archive(self, stream: str, native_id: str, payload: Any, fetched_at: datetime, status: int, run_id: str,
                       request_meta: Dict[str, Any], *, window_from: Optional[datetime] = None,
                       window_to: Optional[datetime] = None) -> RawPayloadRef:
        return await self.archiver.archive(provider=PROVIDER_CODE, stream=stream, native_id=native_id, payload=payload,
                                           request_meta=request_meta, fetched_at=fetched_at, http_status=status, run_id=run_id,
                                           parser_version=PARSER_VERSION, window_from=window_from, window_to=window_to)
