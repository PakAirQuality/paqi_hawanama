"""
OpenAQ discovery: Pakistan locations → shadow stations + pm25 stream checkpoints.

Shadow containment is three things together: stations.active = false,
metadata_json.ingest_mode = 'shadow', and city_id/state_id left NULL (the
resolved geography goes to metadata_json.geo_resolution for the cutover to
promote). Locations whose provider/owner is us are origin='hawanama_loop' and
never fetched; mobile locations are excluded. Alias candidates are written
with evidence only. dry_run makes the requests and returns the inventory
report but writes nothing except the run record.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.core.config import settings as _default_settings
from app.ingestion.db import AsyncSessionLocal
from app.ingestion.identity import now_iso
from app.ingestion.leases import LeaseManager, holder_id, lease_key_for
from app.ingestion.quota import PostgresQuota, QuotaUnavailable
from app.ingestion.raw_archive import RawPayloadArchiver
from app.ingestion.runs import EntityFailure, RunOutcome, RunRecorder, new_run_id
from app.services.ingestion.openaq.client import OpenAQAuthError, OpenAQClient, PaginationAnomaly, BudgetExhausted
from app.services.ingestion.openaq.identity import compute_alias_candidates, is_self_loop
from app.services.ingestion.openaq.models import Location, Page, parse_locations_page
from app.services.ingestion.openaq.repository import (InMemoryOpenAQRepository, PostgresOpenAQRepository, StationUpsert,
                                                     StreamSeed, stream_key_for)

logger = logging.getLogger(__name__)

PARSER_VERSION = "openaq_locations_v1"


def validate_openaq_settings(s) -> Optional[str]:
    """Return a problem description or None. Checked at task start, never at import."""
    if not s.OPENAQ_API_KEY:
        return "OPENAQ_API_KEY is not set"
    if int(s.OPENAQ_RATE_PER_MIN) > 60 or int(s.OPENAQ_RATE_PER_HOUR) > 2000:
        return "OPENAQ_RATE_PER_MIN/HOUR exceed the documented 60/min and 2000/hour"
    if int(s.OPENAQ_MAX_REQUESTS_PER_RUN) > int(s.OPENAQ_RATE_PER_HOUR):
        return "OPENAQ_MAX_REQUESTS_PER_RUN exceeds OPENAQ_RATE_PER_HOUR"
    return None


def parameters_from(s) -> List[str]:
    return [p.strip().lower() for p in (s.OPENAQ_PARAMETERS or "pm25").split(",") if p.strip()]


def self_names_from(s) -> List[str]:
    return [p.strip() for p in (s.OPENAQ_SELF_PROVIDER_NAMES or "").split(",") if p.strip()]


class OpenAQDiscoveryTask:
    def __init__(self, *, settings=None, client: Optional[OpenAQClient] = None, repo=None, archiver=None,
                 recorder_factory=None, leases=None, quota=None):
        self.settings = s = settings or _default_settings
        self._quota = quota if quota is not None else PostgresQuota(AsyncSessionLocal, required=bool(s.OPS_TABLES_REQUIRED))
        self.client = client or OpenAQClient(settings=s, quota=self._quota)
        self.repo = repo or PostgresOpenAQRepository(AsyncSessionLocal)
        self.archiver = archiver or RawPayloadArchiver(s)
        self._recorder_factory = recorder_factory or (lambda: RunRecorder(AsyncSessionLocal, Path(s.INGEST_OUT_DIR), required=False))
        self._leases = leases or LeaseManager(AsyncSessionLocal, required=True)

    async def run(self, *, dry_run: bool = False, trigger: str = "http") -> RunOutcome:
        s = self.settings
        run_id = new_run_id("openaq-discover")
        recorder = self._recorder_factory()
        outcome = RunOutcome(run_id=run_id, task="openaq-discover", provider_code="openaq", scope=s.OPENAQ_COUNTRY_ISO,
                             trigger=trigger)
        outcome.details["dry_run"] = dry_run
        await recorder.start(outcome)
        lease = None
        try:
            if not s.OPENAQ_ENABLED and not dry_run:
                outcome.skip("disabled", "OPENAQ_ENABLED is false (dry_run=true still allowed)")
                return outcome
            problem = validate_openaq_settings(s)
            if problem:
                outcome.fail("config_invalid", problem)
                return outcome
            lease = await self._leases.acquire(lease_key_for("openaq-discover", "openaq", s.OPENAQ_COUNTRY_ISO),
                                               holder_id(run_id), int(s.INGEST_LEASE_TTL_S))
            if lease is None:
                outcome.skip("lease_held", "another openaq-discover run holds the lease")
                return outcome
            outcome.lease_key, outcome.lease_fence = lease.lease_key, lease.fence
            quota = getattr(self.client, "quota", None)
            if quota is not None:
                await quota.healthcheck()
            await self._discover(outcome, recorder, run_id, dry_run)
        except QuotaUnavailable as exc:
            outcome.fail("quota_unavailable", str(exc))
        except OpenAQAuthError as exc:
            outcome.fail("provider_auth", str(exc))
        except BudgetExhausted as exc:
            outcome.fail("budget_exhausted", str(exc))
        except PaginationAnomaly as exc:
            outcome.fail("pagination_anomaly", str(exc))
        except Exception as exc:
            logger.exception("OpenAQ discovery run %s crashed", run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await recorder.finish(outcome)
            await self._leases.release(lease)
        logger.info("OpenAQ discovery %s %s: %s", run_id, outcome.status.value, outcome.counts)
        return outcome

    async def _discover(self, outcome: RunOutcome, recorder: RunRecorder, run_id: str, dry_run: bool) -> None:
        s = self.settings
        c = outcome.counts
        params = parameters_from(s)
        self_names = self_names_from(s)
        provider_id = None if dry_run else await self.repo.ensure_provider()
        country_id = None if dry_run else await self.repo.resolve_country_id(s.OPENAQ_COUNTRY_ISO, "Pakistan")

        locations: List[Location] = []
        pages = 0
        async for pr in self.client.locations_pages(s.OPENAQ_COUNTRY_ISO, limit=int(s.OPENAQ_PAGE_LIMIT),
                                                    max_pages=int(s.OPENAQ_MAX_PAGES_PER_STREAM) * 5):
            pages += 1
            ref = await self.archiver.archive(provider="openaq", stream="locations", native_id=s.OPENAQ_COUNTRY_ISO,
                                              payload=pr.payload, request_meta={"endpoint": "locations", "page": pr.page},
                                              fetched_at=pr.fetched_at, http_status=pr.http_status, run_id=run_id,
                                              parser_version=PARSER_VERSION)
            if not dry_run:
                await self.archiver.record(AsyncSessionLocal, ref)
            page: Page[Location] = parse_locations_page(pr.payload)
            locations.extend(page.results)
        c.expected = len(locations)
        if not locations:
            outcome.fail("no_locations", f"/v3/locations?iso={s.OPENAQ_COUNTRY_ISO} returned no locations")
            return

        stats = {"by_provider": Counter(), "by_owner": Counter(), "monitor": Counter(), "sensors_by_parameter": Counter(),
                 "streams": 0, "loop_excluded": 0, "mobile_excluded": 0, "geo_resolved": 0, "alias_candidates": 0,
                 "licenses": Counter()}
        seen_keys: Set[str] = set()
        ts = now_iso()
        for loc in locations:
            c.attempted += 1
            key = str(loc.id)
            try:
                stats["by_provider"][(loc.provider.name if loc.provider else None) or "?"] += 1
                stats["by_owner"][(loc.owner.name if loc.owner else None) or "?"] += 1
                stats["monitor"]["reference_reported" if loc.is_monitor else "low_cost_reported"] += 1
                for sn in loc.sensors:
                    stats["sensors_by_parameter"][sn.parameter.name] += 1
                for lic in loc.licenses or []:
                    stats["licenses"][lic.name or "?"] += 1

                lat = loc.coordinates.latitude if loc.coordinates else None
                lon = loc.coordinates.longitude if loc.coordinates else None
                if lat is None or lon is None:
                    raise ValueError("location without coordinates")
                loop = is_self_loop(loc, self_names)
                origin = "hawanama_loop" if loop else "external"
                if loop:
                    stats["loop_excluded"] += 1
                if loc.is_mobile:
                    stats["mobile_excluded"] += 1

                geo = await self.repo.resolve_geo(lat, lon)
                if geo.get("method") != "none":
                    stats["geo_resolved"] += 1
                nearby = [] if loop else await self.repo.candidate_stations_near(lat, lon, float(s.OPENAQ_ALIAS_DISTANCE_M))
                candidates = compute_alias_candidates(loc, nearby, evaluated_at=ts)
                stats["alias_candidates"] += len(candidates)

                snapshot = {
                    "location_id": loc.id, "name": loc.name, "locality": loc.locality, "timezone": loc.timezone,
                    "lat": lat, "lon": lon,
                    "country": loc.country.model_dump() if loc.country else None,
                    "provider": loc.provider.model_dump() if loc.provider else None,
                    "owner": loc.owner.model_dump() if loc.owner else None,
                    "instruments": [i.model_dump() for i in loc.instruments],
                    "sensors": [{"id": sn.id, "name": sn.name, "parameter": sn.parameter.name, "units": sn.parameter.units}
                                for sn in loc.sensors],
                    "is_mobile": loc.is_mobile, "is_monitor": loc.is_monitor,
                    "datetime_first": loc.datetime_first.utc.isoformat() if loc.datetime_first else None,
                    "datetime_last": loc.datetime_last.utc.isoformat() if loc.datetime_last else None,
                    "licenses": [lic.model_dump(mode="json") for lic in (loc.licenses or [])],
                    "bounds": loc.bounds,
                }
                monitor_type = "reference_reported_by_openaq" if loc.is_monitor else "low_cost_reported_by_openaq"
                if not dry_run:
                    sid = await self.repo.upsert_shadow_station(
                        StationUpsert(loc.id, loc.name or f"OpenAQ location {loc.id}", float(lat), float(lon), country_id,
                                      loc.timezone, monitor_type,
                                      {"openaq": snapshot, "origin": origin, "geo_resolution": geo}, candidates),
                        provider_id, run_id)
                    for parameter in params:
                        for sn in loc.sensors_for(parameter):
                            status = "excluded_loop" if loop else ("excluded_mobile" if loc.is_mobile else "active")
                            key_s = stream_key_for(sn.id, parameter)
                            await self.repo.seed_stream(StreamSeed(key_s, sid, str(loc.id), str(sn.id), parameter,
                                                                   sn.parameter.units, status))
                            seen_keys.add(key_s)
                            if status == "active":
                                stats["streams"] += 1
                else:
                    if not loop and not loc.is_mobile:
                        stats["streams"] += sum(len(loc.sensors_for(p)) for p in params)
                c.completed += 1
            except Exception as exc:
                c.failed += 1
                recorder.add_failure(EntityFailure("location", key, type(exc).__name__, str(exc)[:300]))

        retired = 0
        if not dry_run:
            retired = await self.repo.mark_unseen_streams(seen_keys, int(s.OPENAQ_RETIRE_AFTER_MISSED_RUNS))
        c.rows_fetched = len(locations)
        c.rows_written = 0 if dry_run else c.completed
        per_hour = stats["streams"]
        outcome.details.update({
            "pages": pages, "locations": len(locations),
            "by_provider": dict(stats["by_provider"].most_common(25)), "by_owner": dict(stats["by_owner"].most_common(25)),
            "monitor": dict(stats["monitor"]), "sensors_by_parameter": dict(stats["sensors_by_parameter"]),
            "licenses": dict(stats["licenses"]), "active_streams": stats["streams"],
            "loop_excluded": stats["loop_excluded"], "mobile_excluded": stats["mobile_excluded"],
            "geo_resolved": stats["geo_resolved"], "alias_candidates": stats["alias_candidates"],
            "streams_marked_unseen": retired,
            "budget": {"estimated_requests_per_hour": per_hour, "rate_per_hour_target": int(s.OPENAQ_RATE_PER_HOUR),
                       "max_requests_per_run": int(s.OPENAQ_MAX_REQUESTS_PER_RUN),
                       "fits": per_hour <= int(s.OPENAQ_MAX_REQUESTS_PER_RUN)},
            "requests_made": self.client.requests_made,
        })
        if c.failed and c.completed:
            outcome.partial_reason = "entities_skipped"
