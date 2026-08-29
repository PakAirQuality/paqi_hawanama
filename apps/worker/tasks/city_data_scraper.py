#!/usr/bin/env python3
"""
Raw City API Response Scraper for Hawanama Air Quality Data

This script fetches raw API responses from the IQAir city endpoint and saves them 
in both JSON and CSV formats with arrival timestamps. No database operations or data 
transformations are performed - only raw data collection.

The scraper runs at :35 minutes after every hour (e.g., 10:35, 11:35, 12:35, etc.)

Output files per cycle:
- {cycle-id}.json: Complete API responses as JSON array
- {cycle-id}.csv: Flattened data with key fields extracted
- {cycle-id}_stats.json: Cycle statistics and metadata

Usage:
    python city_data_scraper.py [--hours N] [--output-dir DIR]
    
    --hours: Number of hours to run (default: 24)
    --output-dir: Directory to save raw data files (default: ./city_raw_api_data)
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


class CityDataScraper:
    """
    Raw city API data scraper that collects unprocessed city endpoint responses.
    Saves data as JSON and CSV with arrival timestamps for later analysis.
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
        
        # Manifest directory (use city manifests instead of station manifests)
        worker_dir = Path(__file__).parent.parent
        default_manifest_dir = worker_dir / "artifacts/city_manifests"
        self._manifest_dir = Path(os.getenv("CITY_MANIFEST_DIR", str(default_manifest_dir)))
        
        # Output directory for raw city data
        if output_dir:
            self._output_dir = Path(output_dir)
        else:
            # Place raw data in dedicated city directory
            self._output_dir = Path(__file__).parent / "city_raw_api_data"
        
        self._output_dir.mkdir(parents=True, exist_ok=True)
        
        # Current scraping session metadata
        self._session_start = datetime.now(timezone.utc)
        self._session_id = f"city-scrape-{self._session_start.strftime('%Y%m%d-%H%M%S')}"
        
        logger.info(f"City raw data scraper initialized. Session: {self._session_id}")
        logger.info(f"Output directory: {self._output_dir}")
        logger.info(f"Concurrency: {self._concurrency}, Rate limit: {self._rate}/min")

    def _resolve_latest_manifest_path(self) -> Optional[Path]:
        """Find the latest city manifest file (Parquet or JSONL)."""
        p_parq = self._manifest_dir / "latest.parquet"
        p_json = self._manifest_dir / "latest.jsonl"
        if p_parq.exists():
            return p_parq
        if p_json.exists():
            return p_json
        return None

    def _read_parquet(self, path: Path) -> List[Dict[str, Any]]:
        """Read city manifest from Parquet file."""
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
        """Read city manifest from JSONL file."""
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
        """Load cities from the latest manifest file."""
        manifest_path = self._resolve_latest_manifest_path()
        if not manifest_path:
            logger.error("No city manifest found in %s", self._manifest_dir)
            return []
        
        logger.info("Loading city manifest: %s", manifest_path)
        
        if manifest_path.suffix == ".parquet":
            rows = self._read_parquet(manifest_path)
        else:
            rows = self._read_jsonl(manifest_path)
        
        # Filter and deduplicate cities
        seen = set()
        cities: List[Dict[str, Any]] = []
        
        for r in rows:
            # Filter by country (city manifests don't have provider_code)
            if r.get("country") != self._country:
                continue
            
            # Create unique key for deduplication
            city_name = r.get("city")
            state = r.get("state")
            country = r.get("country")
            
            tup = (city_name, state, country)
            if None in tup or tup in seen:
                continue
            
            seen.add(tup)
            cities.append(r)
        
        logger.info("Loaded %d cities from manifest", len(cities))
        return cities

    async def _fetch_raw_city_data(self, city: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Fetch raw API response for a single city.
        Returns the complete API response with arrival timestamp.
        """
        async with self._sema:
            city_name = city.get("city")
            state = city.get("state")
            country = city.get("country", self._country)
            
            arrival_time = datetime.now(timezone.utc)
            
            try:
                await self._limiter.wait()
                
                # Get the raw city API response (not parsed)
                raw_response = await self.iqair_client.get_city_data(
                    city=city_name, 
                    state=state, 
                    country=country
                )
                
                # Package the response with metadata
                return {
                    "arrival_timestamp_utc": arrival_time.isoformat(),
                    "session_id": self._session_id,
                    "city_metadata": {
                        "city_name": city_name,
                        "state": state,
                        "country": country,
                        "latitude": city.get("lat") or city.get("latitude"),
                        "longitude": city.get("lon") or city.get("longitude"),
                    },
                    "api_response": raw_response
                }
                
            except StationNotFound as e:
                logger.debug("City not found: %s in %s", city_name, state)
                return None
            except FeatureNotAvailable as e:
                logger.debug("Feature not available for city: %s", city_name)
                return None
            except (RateLimited, Unauthorized, BadRequest) as e:
                logger.error("API error for city %s: %s", city_name, e)
                raise  # Re-raise to stop the scraping
            except Exception as e:
                logger.warning("Unexpected error for city %s: %s", city_name, e)
                return None

    def _write_csv_output(self, results: List[Dict[str, Any]], csv_file: Path):
        """Write the city API responses to CSV format."""
        import csv
        
        if not results:
            return
        
        # Flatten the nested structure for CSV
        csv_rows = []
        for result in results:
            city_meta = result.get("city_metadata", {})
            api_response = result.get("api_response", {})
            
            # Extract current pollution data
            current = api_response.get("current", {})
            pollution = current.get("pollution", {})
            weather = current.get("weather", {})
            
            row = {
                "arrival_timestamp_utc": result.get("arrival_timestamp_utc"),
                "session_id": result.get("session_id"),
                "city_name": city_meta.get("city_name"),
                "state": city_meta.get("state"),
                "country": city_meta.get("country"),
                "latitude": city_meta.get("latitude"),
                "longitude": city_meta.get("longitude"),
                
                # Pollution data
                "pollution_timestamp": pollution.get("ts"),
                "aqi_us": pollution.get("aqius"),
                "aqi_cn": pollution.get("aqicn"),
                "main_pollutant_us": pollution.get("mainus"),
                "main_pollutant_cn": pollution.get("maincn"),
                
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
        Perform one complete scraping cycle of all cities.
        Returns statistics about the cycle.
        """
        cycle_start = datetime.now(timezone.utc)
        cycle_id = f"city-cycle-{cycle_start.strftime('%Y%m%d-%H%M%S')}"
        
        logger.info("Starting city scraping cycle: %s", cycle_id)
        
        # Load cities from manifest
        cities = self._load_city_manifest()
        if not cities:
            logger.warning("No cities found to scrape")
            return {
                "cycle_id": cycle_id,
                "cycle_start": cycle_start.isoformat(),
                "cities_attempted": 0,
                "responses_collected": 0,
                "errors": 0
            }
        
        # Create output files for this cycle
        json_output_file = self._output_dir / f"{cycle_id}.json"
        csv_output_file = self._output_dir / f"{cycle_id}.csv"
        
        # Fetch data for all cities
        tasks = [self._fetch_raw_city_data(city) for city in cities]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect successful results
        responses_collected = 0
        errors = 0
        successful_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors += 1
                # Log the error but don't write to file
                logger.error("Error in cycle %s for city %d: %s", 
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
            "cities_attempted": len(cities),
            "responses_collected": responses_collected,
            "errors": errors,
            "json_output_file": str(json_output_file),
            "csv_output_file": str(csv_output_file)
        }
        
        logger.info("City cycle %s complete: %d responses collected, %d errors, %.1f seconds", 
                   cycle_id, responses_collected, errors, duration)
        
        # Write cycle statistics
        stats_file = self._output_dir / f"{cycle_id}_stats.json"
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        
        return stats

    async def _wait_until_next_hour(self):
        """Wait until the next :35 minute mark of the hour."""
        now = datetime.now(timezone.utc)
        
        # Calculate next :35 minute
        if now.minute < 35:
            # If it's before :35, wait until :35 of current hour
            next_run = now.replace(minute=35, second=0, microsecond=0)
        else:
            # If it's after :35, wait until :35 of next hour
            next_hour = (now.hour + 1) % 24
            next_run = now.replace(hour=next_hour, minute=35, second=0, microsecond=0)
            
            # Handle day rollover
            if next_hour == 0:
                next_run = next_run.replace(day=now.day + 1)
        
        wait_seconds = (next_run - now).total_seconds()
        
        if wait_seconds > 0:
            logger.info("Waiting %.1f seconds until next city run at %s UTC", 
                       wait_seconds, next_run.strftime("%H:%M:%S"))
            await asyncio.sleep(wait_seconds)

    async def run_for_duration(self, hours: int = 24):
        """
        Run the city scraper for the specified duration, collecting data at :35 after each hour.
        
        Args:
            hours: Number of hours to run (default: 24)
        """
        logger.info("Starting city raw data scraper for %d hours, collecting at :35 after every hour", 
                   hours)
        
        start_time = datetime.now(timezone.utc)
        end_time = start_time.replace(hour=(start_time.hour + hours) % 24)
        
        # If end_time is on the next day, add a day
        if hours >= 24 or end_time <= start_time:
            end_time = end_time.replace(day=end_time.day + (hours // 24))
            if hours % 24 > 0:
                end_time = end_time.replace(hour=end_time.hour + (hours % 24))
        
        logger.info("City scraper will run from %s to %s UTC", 
                   start_time.isoformat(), end_time.isoformat())
        
        cycle_count = 0
        total_responses = 0
        total_errors = 0
        
        try:
            while datetime.now(timezone.utc) < end_time:
                # Wait until the next :27 minute mark
                await self._wait_until_next_hour()
                
                # Check if we're still within the duration
                if datetime.now(timezone.utc) >= end_time:
                    logger.info("End time reached, stopping city scraper")
                    break
                
                cycle_stats = await self.scrape_cycle()
                cycle_count += 1
                total_responses += cycle_stats["responses_collected"]
                total_errors += cycle_stats["errors"]
        
        except KeyboardInterrupt:
            logger.info("City scraper interrupted by user")
        except Exception as e:
            logger.error("City scraper failed with error: %s", e)
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
                "schedule": "hourly_at_35_minutes",
                "output_directory": str(self._output_dir)
            }
            
            summary_file = self._output_dir / f"{self._session_id}_summary.json"
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(session_summary, f, indent=2)
            
            logger.info("City scraper session complete. Summary written to: %s", summary_file)
            logger.info("City session stats: %d cycles, %d responses, %d errors, %.2f hours", 
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
    """Main entry point for the city raw data scraper."""
    parser = argparse.ArgumentParser(description="Raw City API Response Scraper for Hawanama - Runs at :35 after every hour")
    parser.add_argument("--hours", type=int, default=24, 
                       help="Number of hours to run (default: 24)")
    parser.add_argument("--output-dir", type=str, default=None,
                       help="Output directory for raw city data files")
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.hours <= 0:
        parser.error("Hours must be positive")
    
    scraper = CityDataScraper(output_dir=args.output_dir)
    await scraper.run_for_duration(hours=args.hours)


if __name__ == "__main__":
    asyncio.run(main())