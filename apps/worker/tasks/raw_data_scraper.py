#!/usr/bin/env python3
"""
Raw API Response Scraper for Hawanama Air Quality Data

This script fetches raw API responses from the IQAir station endpoint and saves them 
in both JSON and CSV formats with arrival timestamps. No database operations or data 
transformations are performed - only raw data collection.

The scraper runs at :22 minutes after every hour (e.g., 10:22, 11:22, 12:22, etc.)

Output files per cycle:
- {cycle-id}.json: Complete API responses as JSON array
- {cycle-id}.csv: Flattened data with key fields extracted
- {cycle-id}_stats.json: Cycle statistics and metadata

Usage:
    python raw_data_scraper.py [--hours N] [--output-dir DIR]
    
    --hours: Number of hours to run (default: 24)
    --output-dir: Directory to save raw data files (default: ./raw_api_data)
"""

import asyncio
import json
import logging
import os
import sys
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from services.iqair_client import (
    IQAirClient,
    IQAirError,
    StationNotFound,
    FeatureNotAvailable,
    RateLimited,
    Unauthorized,
    BadRequest,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Optional pandas for Parquet manifest reading
try:
    import pandas as pd
    _HAVE_PANDAS = True
except ImportError:
    pd = None
    _HAVE_PANDAS = False


class RawDataScraper:
    """
    Raw API data scraper that collects unprocessed station endpoint responses.
    Saves data as JSONL with arrival timestamps for later analysis.
    """
    
    def __init__(self, output_dir: Optional[str] = None):
        self.iqair_client = IQAirClient()
        
        # Configuration from environment
        self._concurrency = int(os.getenv("RAW_SCRAPER_CONCURRENCY", "6"))
        self._sema = asyncio.Semaphore(self._concurrency)
        self._rate = int(os.getenv("IQAIR_MAX_CALLS_PER_MIN", "90"))
        self._limiter = _AsyncRateLimiter(self._rate)
        
        # Filters
        self._country = os.getenv("INGEST_COUNTRY", "")
        self._provider_code = os.getenv("STATION_PROVIDER_CODE", "airvisual")
        
        # Manifest directory (same as data_ingestion) - make it relative to worker directory
        worker_dir = Path(__file__).parent.parent
        default_manifest_dir = worker_dir / "artifacts/station_manifests"
        self._manifest_dir = Path(os.getenv("STATION_MANIFEST_DIR", str(default_manifest_dir)))
        
        # Output directory for raw data
        if output_dir:
            self._output_dir = Path(output_dir)
        else:
            # Place raw data in same directory as data_ingestion tasks
            self._output_dir = Path(__file__).parent / "raw_api_data"
        
        self._output_dir.mkdir(parents=True, exist_ok=True)
        
        # Current scraping session metadata
        self._session_start = datetime.now(timezone.utc)
        self._session_id = f"raw-scrape-{self._session_start.strftime('%Y%m%d-%H%M%S')}"
        
        logger.info(f"Raw data scraper initialized. Session: {self._session_id}")
        logger.info(f"Output directory: {self._output_dir}")
        logger.info(f"Concurrency: {self._concurrency}, Rate limit: {self._rate}/min")

    def _resolve_latest_manifest_path(self) -> Optional[Path]:
        """Find the latest station manifest file (Parquet or JSONL)."""
        p_parq = self._manifest_dir / "latest.parquet"
        p_json = self._manifest_dir / "latest.jsonl"
        if p_parq.exists():
            return p_parq
        if p_json.exists():
            return p_json
        return None

    def _read_parquet(self, path: Path) -> List[Dict[str, Any]]:
        """Read station manifest from Parquet file."""
        if not _HAVE_PANDAS:
            logger.error("pandas is required to read parquet manifest: %s", path)
            return []
        try:
            df = pd.read_parquet(path)
            return df.to_dict("records")
        except Exception as e:
            logger.error("Failed reading parquet %s: %s", path, e)
            return []

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        """Read station manifest from JSONL file."""
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

    def _load_station_manifest(self) -> List[Dict[str, Any]]:
        """Load stations from the latest manifest file."""
        manifest_path = self._resolve_latest_manifest_path()
        if not manifest_path:
            logger.error("No station manifest found in %s", self._manifest_dir)
            return []
        
        logger.info("Loading station manifest: %s", manifest_path)
        
        if manifest_path.suffix == ".parquet":
            rows = self._read_parquet(manifest_path)
        else:
            rows = self._read_jsonl(manifest_path)
        
        # Filter and deduplicate stations
        seen = set()
        stations: List[Dict[str, Any]] = []
        
        for r in rows:
            # Filter by provider and country
            if r.get("provider_code") != self._provider_code:
                continue
            if r.get("country") != self._country:
                continue
            if r.get("active") is False:
                continue
            
            # Create unique key for deduplication
            station_name = r.get("iqair_station_name") or r.get("name")
            city = r.get("city")
            state = r.get("state")
            country = r.get("country")
            
            tup = (station_name, city, state, country)
            if None in tup or tup in seen:
                continue
            
            seen.add(tup)
            stations.append(r)
        
        logger.info("Loaded %d stations from manifest", len(stations))
        return stations

    async def _fetch_raw_station_data(self, station: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Fetch raw API response for a single station.
        Returns the complete API response with arrival timestamp.
        """
        async with self._sema:
            station_name = station.get("iqair_station_name") or station.get("name")
            city = station.get("city")
            state = station.get("state")
            country = station.get("country", self._country)
            
            arrival_time = datetime.now(timezone.utc)
            
            try:
                await self._limiter.wait()
                
                # Get the raw API response (not parsed)
                raw_response = await self.iqair_client.get_station_data(
                    station=station_name, 
                    city=city, 
                    state=state, 
                    country=country
                )
                
                # Package the response with metadata
                return {
                    "arrival_timestamp_utc": arrival_time.isoformat(),
                    "session_id": self._session_id,
                    "station_metadata": {
                        "station_name": station_name,
                        "city": city,
                        "state": state,
                        "country": country,
                        "source_station_id": station.get("source_station_id"),
                        "latitude": station.get("lat") or station.get("latitude"),
                        "longitude": station.get("lon") or station.get("longitude"),
                    },
                    "api_response": raw_response
                }
                
            except StationNotFound as e:
                logger.debug("Station not found: %s in %s, %s", station_name, city, state)
                return None
            except FeatureNotAvailable as e:
                logger.debug("Feature not available for station: %s", station_name)
                return None
            except (RateLimited, Unauthorized, BadRequest) as e:
                logger.error("API error for station %s: %s", station_name, e)
                raise  # Re-raise to stop the scraping
            except Exception as e:
                logger.warning("Unexpected error for station %s: %s", station_name, e)
                return None

    def _write_csv_output(self, results: List[Dict[str, Any]], csv_file: Path):
        """Write the API responses to CSV format."""
        import csv
        
        if not results:
            return
        
        # Flatten the nested structure for CSV
        csv_rows = []
        for result in results:
            station_meta = result.get("station_metadata", {})
            api_response = result.get("api_response", {})
            
            # Extract current pollution data
            current = api_response.get("current", {})
            pollution = current.get("pollution", {})
            weather = current.get("weather", {})
            
            # Extract PM2.5 and PM10 concentration data
            pm25_data = pollution.get("p2", {})
            pm10_data = pollution.get("p1", {})
            
            row = {
                "arrival_timestamp_utc": result.get("arrival_timestamp_utc"),
                "session_id": result.get("session_id"),
                "station_name": station_meta.get("station_name"),
                "city": station_meta.get("city"),
                "state": station_meta.get("state"),
                "country": station_meta.get("country"),
                "latitude": station_meta.get("latitude"),
                "longitude": station_meta.get("longitude"),
                "source_station_id": station_meta.get("source_station_id"),
                
                # Pollution data
                "pollution_timestamp": pollution.get("ts"),
                "aqi_us": pollution.get("aqius"),
                "aqi_cn": pollution.get("aqicn"),
                "main_pollutant_us": pollution.get("mainus"),
                "main_pollutant_cn": pollution.get("maincn"),
                "pm25_concentration": pm25_data.get("conc") if isinstance(pm25_data, dict) else None,
                "pm25_aqi_us": pm25_data.get("aqius") if isinstance(pm25_data, dict) else None,
                "pm25_aqi_cn": pm25_data.get("aqicn") if isinstance(pm25_data, dict) else None,
                "pm10_concentration": pm10_data.get("conc") if isinstance(pm10_data, dict) else None,
                "pm10_aqi_us": pm10_data.get("aqius") if isinstance(pm10_data, dict) else None,
                "pm10_aqi_cn": pm10_data.get("aqicn") if isinstance(pm10_data, dict) else None,
                
                # Weather data
                "weather_timestamp": weather.get("ts"),
                "temperature_c": weather.get("tp"),
                "pressure_hpa": weather.get("pr"),
                "humidity_percent": weather.get("hu"),
                "wind_speed_ms": weather.get("ws"),
                "wind_direction_deg": weather.get("wd"),
                "weather_icon": weather.get("ic"),
                
                # Full API response as JSON string for reference
                "raw_api_response": json.dumps(api_response, ensure_ascii=False)
            }
            csv_rows.append(row)
        
        # Write to CSV
        if csv_rows:
            fieldnames = csv_rows[0].keys()
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_rows)

    async def scrape_cycle(self) -> Dict[str, Any]:
        """
        Perform one complete scraping cycle of all stations.
        Returns statistics about the cycle.
        """
        cycle_start = datetime.now(timezone.utc)
        cycle_id = f"cycle-{cycle_start.strftime('%Y%m%d-%H%M%S')}"
        
        logger.info("Starting scraping cycle: %s", cycle_id)
        
        # Load stations from manifest
        stations = self._load_station_manifest()
        if not stations:
            logger.warning("No stations found to scrape")
            return {
                "cycle_id": cycle_id,
                "cycle_start": cycle_start.isoformat(),
                "stations_attempted": 0,
                "responses_collected": 0,
                "errors": 0
            }
        
        # Create output files for this cycle
        json_output_file = self._output_dir / f"{cycle_id}.json"
        csv_output_file = self._output_dir / f"{cycle_id}.csv"
        
        # Fetch data for all stations
        tasks = [self._fetch_raw_station_data(station) for station in stations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect successful results
        responses_collected = 0
        errors = 0
        successful_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors += 1
                # Log the error but don't write to file
                logger.error("Error in cycle %s for station %d: %s", 
                           cycle_id, i, result)
            elif result:
                responses_collected += 1
                successful_results.append(result)
        
        # Write results to JSON format
        with open(json_output_file, "w", encoding="utf-8") as f:
            json.dump(successful_results, f, indent=2, ensure_ascii=False)
        
        # Write results to CSV format
        if successful_results:
            self._write_csv_output(successful_results, csv_output_file)
        
        cycle_end = datetime.now(timezone.utc)
        duration = (cycle_end - cycle_start).total_seconds()
        
        stats = {
            "cycle_id": cycle_id,
            "cycle_start": cycle_start.isoformat(),
            "cycle_end": cycle_end.isoformat(),
            "duration_seconds": duration,
            "stations_attempted": len(stations),
            "responses_collected": responses_collected,
            "errors": errors,
            "json_output_file": str(json_output_file),
            "csv_output_file": str(csv_output_file)
        }
        
        logger.info("Cycle %s complete: %d responses collected, %d errors, %.1f seconds", 
                   cycle_id, responses_collected, errors, duration)
        
        # Write cycle statistics
        stats_file = self._output_dir / f"{cycle_id}_stats.json"
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        
        return stats

    async def _wait_until_next_hour(self):
        """Wait until the next :22 minute mark of the hour."""
        now = datetime.now(timezone.utc)
        
        # Calculate next :22 minute
        if now.minute < 22:
            # If it's before :22, wait until :22 of current hour
            next_run = now.replace(minute=22, second=0, microsecond=0)
        else:
            # If it's after :22, wait until :22 of next hour
            next_hour = (now.hour + 1) % 24
            next_run = now.replace(hour=next_hour, minute=22, second=0, microsecond=0)
            
            # Handle day rollover
            if next_hour == 0:
                next_run = next_run.replace(day=now.day + 1)
        
        wait_seconds = (next_run - now).total_seconds()
        
        if wait_seconds > 0:
            logger.info("Waiting %.1f seconds until next run at %s UTC", 
                       wait_seconds, next_run.strftime("%H:%M:%S"))
            await asyncio.sleep(wait_seconds)

    async def run_for_duration(self, hours: int = 24):
        """
        Run the scraper for the specified duration, collecting data at :22 after each hour.
        
        Args:
            hours: Number of hours to run (default: 24)
        """
        logger.info("Starting raw data scraper for %d hours, collecting at :22 after every hour", 
                   hours)
        
        start_time = datetime.now(timezone.utc)
        end_time = start_time.replace(hour=(start_time.hour + hours) % 24)
        
        # If end_time is on the next day, add a day
        if hours >= 24 or end_time <= start_time:
            end_time = end_time.replace(day=end_time.day + (hours // 24))
            if hours % 24 > 0:
                end_time = end_time.replace(hour=end_time.hour + (hours % 24))
        
        logger.info("Scraper will run from %s to %s UTC", 
                   start_time.isoformat(), end_time.isoformat())
        
        cycle_count = 0
        total_responses = 0
        total_errors = 0
        
        try:
            while datetime.now(timezone.utc) < end_time:
                # Wait until the next :01 minute mark
                await self._wait_until_next_hour()
                
                # Check if we're still within the duration
                if datetime.now(timezone.utc) >= end_time:
                    logger.info("End time reached, stopping")
                    break
                
                cycle_stats = await self.scrape_cycle()
                cycle_count += 1
                total_responses += cycle_stats["responses_collected"]
                total_errors += cycle_stats["errors"]
        
        except KeyboardInterrupt:
            logger.info("Scraper interrupted by user")
        except Exception as e:
            logger.error("Scraper failed with error: %s", e)
            raise
        finally:
            # Write final session summary
            session_end = datetime.now(timezone.utc)
            session_duration = (session_end - self._session_start).total_seconds()
            
            session_summary = {
                "session_id": self._session_id,
                "session_start": self._session_start.isoformat(),
                "session_end": session_end.isoformat(),
                "duration_hours": session_duration / 3600,
                "planned_duration_hours": hours,
                "cycles_completed": cycle_count,
                "total_responses_collected": total_responses,
                "total_errors": total_errors,
                "schedule": "hourly_at_22_minutes",
                "output_directory": str(self._output_dir)
            }
            
            summary_file = self._output_dir / f"{self._session_id}_summary.json"
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(session_summary, f, indent=2)
            
            logger.info("Scraper session complete. Summary written to: %s", summary_file)
            logger.info("Session stats: %d cycles, %d responses, %d errors, %.2f hours", 
                       cycle_count, total_responses, total_errors, session_duration / 3600)


class _AsyncRateLimiter:
    """
    Smooth global rate limiter (token spacing). Guarantees average <= rate/min.
    Copied from data_ingestion.py for consistency.
    """
    def __init__(self, per_minute: int):
        per_minute = max(1, per_minute)
        self._interval = 60.0 / float(per_minute)
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self):
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._next <= now:
                self._next = now + self._interval
                return
            delay = self._next - now
            self._next += self._interval
        await asyncio.sleep(delay)


async def main():
    """Main entry point for the raw data scraper."""
    parser = argparse.ArgumentParser(description="Raw API Response Scraper for Hawanama - Runs at :22 after every hour")
    parser.add_argument("--hours", type=int, default=24, 
                       help="Number of hours to run (default: 24)")
    parser.add_argument("--output-dir", type=str, default=None,
                       help="Output directory for raw data files")
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.hours <= 0:
        parser.error("Hours must be positive")
    
    scraper = RawDataScraper(output_dir=args.output_dir)
    await scraper.run_for_duration(hours=args.hours)


if __name__ == "__main__":
    asyncio.run(main())