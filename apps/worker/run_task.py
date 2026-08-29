#!/usr/bin/env python3
"""
Task Runner Script
Allows manual execution of individual scheduler tasks for testing and debugging
"""

import asyncio
import sys
import logging
from main_scheduler import AirQualityScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_task(task_name: str):
    """Run a specific task by name"""
    scheduler = AirQualityScheduler()
    
    task_map = {
        'discovery': scheduler.run_station_discovery,
        'station_discovery': scheduler.run_station_discovery,
        'station-discovery': scheduler.run_station_discovery,
        'station_ingestion': scheduler.run_station_ingestion,
        'station-ingestion': scheduler.run_station_ingestion,
        'city_ingestion': scheduler.run_city_ingestion,
        'city-ingestion': scheduler.run_city_ingestion
    }
    
    if task_name.lower() not in task_map:
        logger.error(f"Unknown task: {task_name}")
        logger.info(f"Available tasks: {', '.join(task_map.keys())}")
        return False
    
    try:
        logger.info(f"Running task: {task_name}")
        result = await task_map[task_name.lower()]()
        logger.info(f"Task completed successfully: {result}")
        return True
    except Exception as exc:
        logger.error(f"Task failed: {exc}")
        return False

def print_usage():
    """Print usage instructions"""
    print("Usage: python run_task.py <task_name>")
    print("")
    print("Available tasks:")
    print("  discovery, station-discovery  - Discover monitoring stations")
    print("  fetch, data-fetch            - Fetch readings from stations")  
    print("  city-ingest, city-ingestion  - Fetch city-level readings with history & forecasts")
    print("  health, health-check         - Monitor data pipeline health")
    print("  qc, quality-control         - Run quality control validation")
    print("  cleanup, maintenance         - Clean up old data")
    print("")
    print("Examples:")
    print("  python run_task.py discovery")
    print("  python run_task.py city-ingest")
    print("  python run_task.py health")
    print("  python run_task.py qc")

async def main():
    """Main entry point"""
    if len(sys.argv) != 2:
        print_usage()
        sys.exit(1)
    
    task_name = sys.argv[1]
    
    if task_name in ['-h', '--help', 'help']:
        print_usage()
        sys.exit(0)
    
    success = await run_task(task_name)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())