#!/usr/bin/env python3
"""
Main Scheduler (three-core flows only)
- StationDiscoveryTask: writes station + city manifests
- DataIngestionTask: reads STATION manifest and ingests station readings
- CityIngestionTask: reads CITY manifest and ingests city readings
"""

import asyncio
import logging
import os
import signal
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore

from tasks.station_discovery import StationDiscoveryTask
from tasks.data_ingestion import DataIngestionTask
from tasks.city_ingest import CityIngestionTask

# -------- logging --------
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _manifest_exists(dir_path: str) -> bool:
    p = Path(dir_path)
    return (p / "latest.parquet").exists() or (p / "latest.jsonl").exists()


class AirQualityScheduler:
    """Orchestrates the 3 core jobs with a manifest guard."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            executors={"default": AsyncIOExecutor()},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
            timezone="UTC",
        )

        # Task handlers
        self.discovery = StationDiscoveryTask()
        self.station_ingest = DataIngestionTask()
        self.city_ingest = CityIngestionTask()

        # Manifest locations (must match tasks)
        self.station_manifest_dir = os.getenv("STATION_MANIFEST_DIR", "artifacts/station_manifests")
        self.city_manifest_dir = os.getenv("CITY_MANIFEST_DIR", "artifacts/city_manifests")

        # If missing manifests at boot, auto-run discovery once
        self.auto_discover_on_boot = os.getenv("AUTO_DISCOVER_ON_BOOT", "true").lower() in {"1", "true", "yes"}

        self._shutdown_event = asyncio.Event()

    # -------------------- jobs --------------------

    async def job_discover(self):
        logger.info("🚦 Station discovery: start")
        summary = await self.discovery.discover_all_stations_comprehensive()
        logger.info("✅ Station discovery: done | %s", summary)
        return summary

    async def job_ingest_station(self):
        await self._ensure_manifests(need_station=True, need_city=False)
        logger.info("🚦 Station ingestion: start")
        summary = await self.station_ingest.fetch_station_readings()
        logger.info("✅ Station ingestion: done | %s", summary)
        return summary

    async def job_ingest_city(self):
        await self._ensure_manifests(need_station=False, need_city=True)
        logger.info("🚦 City ingestion: start")
        summary = await self.city_ingest.fetch_city_readings_hourly()
        logger.info("✅ City ingestion: done | %s", summary)
        return summary

    # -------------------- manifest guard --------------------

    async def _ensure_manifests(self, need_station: bool, need_city: bool):
        missing_station = need_station and not _manifest_exists(self.station_manifest_dir)
        missing_city = need_city and not _manifest_exists(self.city_manifest_dir)

        if (missing_station or missing_city) and self.auto_discover_on_boot:
            which = "station/city" if (missing_station and missing_city) else ("station" if missing_station else "city")
            logger.info("🛡️ Manifest guard: missing %s manifest(s) → running discovery once.", which)
            await self.job_discover()
        elif missing_station or missing_city:
            which = "station/city" if (missing_station and missing_city) else ("station" if missing_station else "city")
            logger.warning(
                "🛡️ Manifest guard: %s manifest missing and AUTO_DISCOVER_ON_BOOT=false. "
                "Downstream ingestion may skip due to empty manifest.",
                which,
            )

    # -------------------- scheduler lifecycle --------------------

    def setup_jobs(self):
        """Only the three core flows."""
        # Discovery twice daily: 02:00 and 14:00 UTC  
        self.scheduler.add_job(
            self.job_discover,
            CronTrigger(hour=2, minute=0),
            id="discover_stations_2am",
            name="Station Discovery 2:00 AM UTC",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.job_discover,
            CronTrigger(hour=14, minute=0),
            id="discover_stations_2pm", 
            name="Station Discovery 2:00 PM UTC",
            replace_existing=True,
        )
        # Station readings hourly at :15
        self.scheduler.add_job(
            self.job_ingest_station,
            CronTrigger(minute=15),
            id="fetch_station_readings_hourly",
            name="Station Readings Hourly",
            replace_existing=True,
        )
        # City readings hourly at :07 (offset)
        self.scheduler.add_job(
            self.job_ingest_city,
            CronTrigger(minute=7),
            id="fetch_city_readings_hourly",
            name="City Readings Hourly",
            replace_existing=True,
        )
        logger.info("Jobs configured: discovery 02:00 & 14:00 UTC, station :15 each hour, city :07 each hour.")

    async def start(self):
        logger.info("Starting APScheduler (core 3 flows)...")

        # Graceful shutdown hooks
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

        # Ensure manifests on boot (single guard covering both)
        await self._ensure_manifests(need_station=True, need_city=True)

        self.setup_jobs()
        self.scheduler.start()

        for job in self.scheduler.get_jobs():
            logger.info("  - %s (ID=%s) next run: %s", job.name, job.id, job.next_run_time)

        try:
            await self._shutdown_event.wait()
        finally:
            await self.stop()

    async def stop(self):
        logger.info("Shutting down scheduler...")
        self.scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped.")

    def _signal_handler(self, signum, frame):
        logger.info("Signal %s received → shutting down...", signum)
        asyncio.create_task(self._async_shutdown())

    async def _async_shutdown(self):
        self._shutdown_event.set()

    # --------- convenience manual runners ---------
    async def run_station_discovery(self):
        return await self.job_discover()

    async def run_station_ingestion(self):
        return await self.job_ingest_station()

    async def run_city_ingestion(self):
        return await self.job_ingest_city()


async def main():
    app = AirQualityScheduler()
    await app.start()


if __name__ == "__main__":
    asyncio.run(main())
