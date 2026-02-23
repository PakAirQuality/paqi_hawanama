"""
Task execution endpoints for triggering data ingestion and discovery jobs.
These endpoints expose the worker tasks as HTTP APIs for external scheduling systems.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from typing import Dict, Any, Optional
from app.core.security import verify_twitter_endpoint_access, verify_tasks_token

logger = logging.getLogger(__name__)
router = APIRouter()

# Setup worker compatibility layer BEFORE importing worker tasks
try:
    from app.worker_compat import *  # This sets up the import aliases
    logger.info("Worker compatibility layer loaded")
except Exception as e:
    logger.error("Failed to load worker compatibility layer: %s", e)

# Worker tasks will be imported lazily inside each endpoint to avoid import-time crashes


@router.post("/tasks/discover")
async def run_station_discovery(
    request: Request,
    country: Optional[str] = Query(None, description="Single country to discover (default: all)"),
    _: bool = Depends(verify_tasks_token)
):
    """
    Trigger station discovery task.
    Discovers all available stations and updates station/city manifests.
    Pass ?country=Pakistan to limit to a single country, or omit for all South Asian countries.
    """
    try:
        logger.info("Starting station discovery via API endpoint (country=%s)", country or "all")
        from app.tasks.station_discovery import StationDiscoveryTask  # lazy import
        discovery_task = StationDiscoveryTask()
        summary = await discovery_task.discover_all_stations_comprehensive(country=country)
        logger.info("Station discovery completed successfully: %s", summary)
        return {
            "status": "success",
            "message": "Station discovery completed",
            "summary": summary
        }
    except Exception as e:
        error_msg = str(e) if str(e) else "Unknown error - no exception message"
        logger.error("Station discovery failed: %s", error_msg)
        import traceback
        logger.error("Station discovery traceback: %s", traceback.format_exc())
        
        raise HTTPException(
            status_code=500,
            detail=f"Station discovery failed: {error_msg}"
        )


@router.post("/tasks/ingest-stations")
async def run_station_ingestion(
    request: Request,
    _: bool = Depends(verify_tasks_token)
):
    """
    Trigger station data ingestion task.
    Fetches current readings from individual stations using the station manifest.
    """
    try:
        logger.info("Starting station ingestion via API endpoint")
        from app.tasks.data_ingestion import DataIngestionTask  # lazy import
        station_ingestion_task = DataIngestionTask()
        summary = await station_ingestion_task.fetch_station_readings()
        logger.info("Station ingestion completed successfully: %s", summary)
        return {
            "status": "success", 
            "message": "Station ingestion completed",
            "summary": summary
        }
    except Exception as e:
        error_msg = str(e) if str(e) else "Unknown error - no exception message"
        logger.error("Station ingestion failed: %s", error_msg)
        import traceback
        logger.error("Station ingestion traceback: %s", traceback.format_exc())
        
        raise HTTPException(
            status_code=500,
            detail=f"Station ingestion failed: {error_msg}"
        )


@router.post("/tasks/ingest-cities")
async def run_city_ingestion(
    request: Request,
    country: Optional[str] = Query(None, description="Single country to ingest (default: all IQAIR_COUNTRIES)"),
    _: bool = Depends(verify_tasks_token)
):
    """
    Trigger city data ingestion task.
    Fetches current readings from cities using the city manifest.
    Pass ?country=Pakistan to limit to a single country, or omit for all South Asian countries.
    """
    try:
        logger.info("Starting city ingestion via API endpoint (country=%s)", country or "all")
        from app.tasks.city_ingest import CityIngestionTask  # lazy import
        city_ingestion_task = CityIngestionTask()
        summary = await city_ingestion_task.fetch_city_readings_hourly(country=country)
        logger.info("City ingestion completed successfully: %s", summary)
        return {
            "status": "success",
            "message": "City ingestion completed", 
            "summary": summary
        }
    except Exception as e:
        error_msg = str(e) if str(e) else "Unknown error - no exception message"
        logger.error("City ingestion failed: %s", error_msg)
        import traceback
        logger.error("City ingestion traceback: %s", traceback.format_exc())
        
        raise HTTPException(
            status_code=500,
            detail=f"City ingestion failed: {error_msg}"
        )


@router.post("/tasks/full-pipeline")
async def run_full_pipeline(
    request: Request,
    _: bool = Depends(verify_tasks_token)
):
    """
    Run the complete ingestion pipeline:
    1. Station discovery (refresh manifests)
    2. Station ingestion
    3. City ingestion
    """
    try:
        logger.info("Starting full pipeline via API endpoint")
        
        # Import tasks lazily
        from app.tasks.station_discovery import StationDiscoveryTask
        from app.tasks.data_ingestion import DataIngestionTask
        from app.tasks.city_ingest import CityIngestionTask
        
        discovery_task = StationDiscoveryTask()
        station_ingestion_task = DataIngestionTask()
        city_ingestion_task = CityIngestionTask()
        
        # Step 1: Discovery
        logger.info("Pipeline step 1/3: Station discovery")
        discovery_summary = await discovery_task.discover_all_stations_comprehensive()
        
        # Step 2: Station ingestion
        logger.info("Pipeline step 2/3: Station ingestion")
        station_summary = await station_ingestion_task.fetch_station_readings()
        
        # Step 3: City ingestion (all configured countries)
        logger.info("Pipeline step 3/3: City ingestion")
        city_summary = await city_ingestion_task.fetch_city_readings_hourly(country=None)
        
        logger.info("Full pipeline completed successfully")
        return {
            "status": "success",
            "message": "Full pipeline completed",
            "summary": {
                "discovery": discovery_summary,
                "station_ingestion": station_summary,
                "city_ingestion": city_summary
            }
        }
    except Exception as e:
        error_msg = str(e) if str(e) else "Unknown error - no exception message"
        logger.error("Full pipeline failed: %s", error_msg)
        import traceback
        logger.error("Full pipeline traceback: %s", traceback.format_exc())
        
        raise HTTPException(
            status_code=500,
            detail=f"Full pipeline failed: {error_msg}"
        )


@router.post("/tasks/twitter-lahore-pm25")
async def run_twitter_lahore_pm25(
    request: Request,
    _: bool = Depends(verify_twitter_endpoint_access)
):
    """
    Trigger Twitter post for Lahore top 10 PM2.5 stations.
    Posts current air quality data to Twitter.
    """
    try:
        logger.info("Starting Twitter automation for Lahore PM2.5 via API endpoint")
        from app.services.twitter_automation import TwitterAutomationService  # lazy import
        
        twitter_service = TwitterAutomationService()
        result = await twitter_service.post_lahore_pm25_update(dry_run=False)
        
        if result["status"] == "success":
            logger.info("Twitter automation completed successfully: %s", result)
            return {
                "status": "success",
                "message": "Twitter post completed",
                "details": result
            }
        else:
            logger.warning("Twitter automation completed with status %s: %s", result["status"], result)
            return {
                "status": result["status"],
                "message": result["message"],
                "details": result
            }
            
    except Exception as e:
        error_msg = str(e) if str(e) else "Unknown error - no exception message"
        logger.error("Twitter automation failed: %s", error_msg)
        import traceback
        logger.error("Twitter automation traceback: %s", traceback.format_exc())
        
        raise HTTPException(
            status_code=500,
            detail=f"Twitter automation failed: {error_msg}"
        )


@router.get("/tasks/status")
async def get_task_status(
    request: Request,
    _: bool = Depends(verify_tasks_token)
):
    """
    Get status information about available tasks and recent runs.
    """
    try:
        # Check if manifests exist
        from pathlib import Path
        worker_root = Path(__file__).resolve().parents[3] / "worker"
        
        station_manifest_dir = worker_root / "artifacts" / "station_manifests"
        city_manifest_dir = worker_root / "artifacts" / "city_manifests"
        
        station_manifest_exists = (
            (station_manifest_dir / "latest.parquet").exists() or 
            (station_manifest_dir / "latest.jsonl").exists()
        )
        city_manifest_exists = (
            (city_manifest_dir / "latest.parquet").exists() or
            (city_manifest_dir / "latest.jsonl").exists()
        )
        
        return {
            "status": "healthy",
            "available_endpoints": [
                "POST /tasks/discover",
                "POST /tasks/ingest-stations", 
                "POST /tasks/ingest-cities",
                "POST /tasks/full-pipeline",
                "POST /tasks/twitter-lahore-pm25",
                "GET /tasks/status"
            ],
            "manifest_status": {
                "station_manifest_exists": station_manifest_exists,
                "city_manifest_exists": city_manifest_exists
            }
        }
    except Exception as e:
        logger.error("Failed to get task status: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task status: {str(e)}"
        )