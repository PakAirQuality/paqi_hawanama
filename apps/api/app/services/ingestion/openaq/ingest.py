"""
OpenAQ measurement ingestion (hourly) and older-window reconciliation (daily).

Per stream: compute the window from the checkpoint, fetch every page into
memory (bounded), archive each page, normalize, then commit readings + the
checkpoint in ONE transaction. A failure on page 2 therefore writes nothing and
leaves completed_through untouched. Budget exhaustion ends the run cleanly as
`partial` with the next window time; a 401/403 fails the run and stops all
further requests; other adapters are unaffected either way.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings as _default_settings
from app.ingestion.db import AsyncSessionLocal
from app.ingestion.leases import LeaseManager, holder_id, lease_key_for
from app.ingestion.quota import PostgresQuota, QuotaUnavailable
from app.ingestion.raw_archive import RawPayloadArchiver
from app.ingestion.runs import EntityFailure, RunOutcome, RunRecorder, new_run_id
from app.services.ingestion.openaq.client import (BudgetExhausted, OpenAQAuthError, OpenAQClient, OpenAQError,
                                                  PaginationAnomaly)
from app.services.ingestion.openaq.discovery import validate_openaq_settings
from app.services.ingestion.openaq.models import parse_measurements_page
from app.services.ingestion.openaq.normalize import PARSER_VERSION, is_hourly, normalize_measurement
from app.services.ingestion.openaq.repository import PostgresOpenAQRepository, Stream
from app.services.ingestion.openaq.windows import next_window, reconcile_windows

logger = logging.getLogger(__name__)


class OpenAQIngestTask:
    def __init__(self, *, settings=None, client: Optional[OpenAQClient] = None, repo=None, archiver=None,
                 recorder_factory=None, leases=None, quota=None, now=None):
        self.settings = s = settings or _default_settings
        self._quota = quota if quota is not None else PostgresQuota(AsyncSessionLocal, required=bool(s.OPS_TABLES_REQUIRED))
        self.client = client or OpenAQClient(settings=s, quota=self._quota)
        self.repo = repo or PostgresOpenAQRepository(AsyncSessionLocal)
        self.archiver = archiver or RawPayloadArchiver(s)
        self._recorder_factory = recorder_factory or (lambda: RunRecorder(AsyncSessionLocal, Path(s.INGEST_OUT_DIR), required=False))
        self._leases = leases or LeaseManager(AsyncSessionLocal, required=True)
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def run(self, *, mode: str = "ingest", trigger: str = "http") -> RunOutcome:
        assert mode in ("ingest", "reconcile")
        s = self.settings
        task = "openaq-ingest" if mode == "ingest" else "openaq-reconcile"
        run_id = new_run_id(task)
        recorder = self._recorder_factory()
        outcome = RunOutcome(run_id=run_id, task=task, provider_code="openaq", scope=s.OPENAQ_COUNTRY_ISO, trigger=trigger)
        await recorder.start(outcome)
        lease = None
        try:
            if not s.OPENAQ_ENABLED:
                outcome.skip("disabled", "OPENAQ_ENABLED is false")
                return outcome
            problem = validate_openaq_settings(s)
            if problem:
                outcome.fail("config_invalid", problem)
                return outcome
            lease = await self._leases.acquire(lease_key_for(task, "openaq", s.OPENAQ_COUNTRY_ISO), holder_id(run_id),
                                               int(s.INGEST_LEASE_TTL_S))
            if lease is None:
                outcome.skip("lease_held", f"another {task} run holds the lease")
                return outcome
            outcome.lease_key, outcome.lease_fence = lease.lease_key, lease.fence
            quota = getattr(self.client, "quota", None)
            if quota is not None:
                await quota.healthcheck()
            await self._run(outcome, recorder, run_id, mode)
        except QuotaUnavailable as exc:
            outcome.fail("quota_unavailable", str(exc))
        except Exception as exc:
            logger.exception("OpenAQ %s run %s crashed", task, run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.details["requests_made"] = getattr(self.client, "requests_made", None)
            outcome.finish()
            await recorder.finish(outcome)
            await self._leases.release(lease)
        logger.info("OpenAQ %s %s %s: %s", task, run_id, outcome.status.value, outcome.counts)
        return outcome

    async def _run(self, outcome: RunOutcome, recorder: RunRecorder, run_id: str, mode: str) -> None:
        s = self.settings
        c = outcome.counts
        streams = await self.repo.list_streams("active", int(s.OPENAQ_MAX_REQUESTS_PER_RUN))
        c.expected = len(streams)
        if not streams:
            outcome.fail("no_streams", "no active OpenAQ streams (run discovery first)")
            return
        now = self._now()
        latest_ts: Optional[datetime] = None
        deferred = 0
        notes: Dict[str, int] = {}
        for stream in streams:
            if mode == "ingest":
                windows = [next_window(stream.completed_through, now, overlap_h=int(stream.overlap_hours or s.OPENAQ_OVERLAP_HOURS),
                                       window_h=int(s.OPENAQ_WINDOW_HOURS), initial_backfill_h=int(s.OPENAQ_INITIAL_BACKFILL_HOURS))]
            else:
                windows = reconcile_windows(stream.completed_through, lookback_days=int(s.OPENAQ_RECONCILE_LOOKBACK_DAYS),
                                            overlap_h=int(stream.overlap_hours or s.OPENAQ_OVERLAP_HOURS))
                if not windows:
                    c.skipped += 1
                    continue
            c.attempted += 1
            try:
                for frm, to in windows:
                    res = await self._ingest_window(stream, frm, to, run_id, now, mode, notes)
                    if res is None:          # deferred (sub-hourly)
                        deferred += 1
                        break
                    rows_written, rows_unchanged, rows_count, mx = res
                    c.rows_fetched += rows_count
                    c.rows_written += rows_written
                    c.rows_unchanged += rows_unchanged
                    if mx and (latest_ts is None or mx > latest_ts):
                        latest_ts = mx
                else:
                    c.completed += 1
            except BudgetExhausted as exc:
                # Stop cleanly: everything committed so far stays; the next run resumes from the checkpoints.
                c.attempted -= 1
                c.skipped += 1
                outcome.partial_reason = "budget"
                outcome.details["budget_stop"] = {"reason": str(exc), "retry_in_s": exc.retry_in_s,
                                                  "streams_remaining": len(streams) - c.completed - c.failed}
                logger.warning("OpenAQ budget stop after %d streams: %s", c.attempted + c.failed, exc)
                break
            except OpenAQAuthError as exc:
                c.failed += 1
                recorder.add_failure(EntityFailure("stream", stream.stream_key, "OpenAQAuthError", str(exc)))
                outcome.fail("provider_auth", "OpenAQ rejected the credential; no further requests this run")
                break
            except (PaginationAnomaly, OpenAQError) as exc:
                c.failed += 1
                await self.repo.mark_stream_failed(stream.stream_key, f"{type(exc).__name__}: {exc}", run_id)
                recorder.add_failure(EntityFailure("stream", stream.stream_key, type(exc).__name__, str(exc)[:300]))
            except Exception as exc:
                c.failed += 1
                await self.repo.mark_stream_failed(stream.stream_key, f"{type(exc).__name__}: {exc}", run_id)
                recorder.add_failure(EntityFailure("stream", stream.stream_key, type(exc).__name__, str(exc)[:300]))
        outcome.latest_observation_ts = latest_ts
        outcome.details.update({"streams_deferred_subhourly": deferred, "normalize_notes": notes, "mode": mode})
        if c.expected and c.attempted == 0 and c.failed == 0 and outcome.partial_reason != "budget":
            # Everything was deferred/skipped without doing anything useful.
            c.attempted = c.expected

    async def _ingest_window(self, stream: Stream, frm: datetime, to: datetime, run_id: str, now: datetime, mode: str,
                             notes: Dict[str, int]):
        """Fetch all pages for [frm, to], normalize, commit atomically. Returns None when the stream is deferred."""
        s = self.settings
        refs = []
        rows: List[Dict[str, Any]] = []
        page_count = 0
        interval_observed = None
        async for pr in self.client.measurements_pages(int(stream.native_sensor_id), frm, to, limit=int(s.OPENAQ_PAGE_LIMIT),
                                                       max_pages=int(s.OPENAQ_MAX_PAGES_PER_STREAM)):
            page_count += 1
            ref = await self.archiver.archive(provider="openaq", stream="measurements", native_id=stream.native_sensor_id,
                                              payload=pr.payload, request_meta={"endpoint": f"sensors/{stream.native_sensor_id}/measurements",
                                                                                "page": pr.page, "from": frm.isoformat(), "to": to.isoformat()},
                                              fetched_at=pr.fetched_at, http_status=pr.http_status, run_id=run_id,
                                              parser_version=PARSER_VERSION, window_from=frm, window_to=to)
            refs.append(ref)
            page = parse_measurements_page(pr.payload)
            if page_count == 1 and page.results:
                first = page.results[0]
                interval_observed = first.period.interval if first.period else None
                if not is_hourly(first):
                    await self.repo.set_stream_status(stream.stream_key, "deferred_subhourly", interval_observed=interval_observed, run_id=run_id)
                    logger.info("Stream %s is %s, not hourly: deferred (the /hours product is a separate follow-up)",
                                stream.stream_key, interval_observed)
                    return None
            for m in page.results:
                row, reason = normalize_measurement(m, station_id=stream.station_id, stream_key=stream.stream_key,
                                                    parameter=stream.parameter, prov_base={**ref.prov(), "run": run_id}, now=now)
                if row is None:
                    notes[reason] = notes.get(reason, 0) + 1
                    continue
                rows.append(row)
        result = await self.repo.commit_window(
            stream, rows, refs, completed_through=to if mode == "ingest" else None, run_id=run_id, page_count=page_count,
            interval_observed=interval_observed, reconciled_through=to if mode == "reconcile" else None)
        mx = max((r["ts_utc"] for r in rows), default=None)
        return result.rows_written, result.rows_unchanged, len(rows), mx
