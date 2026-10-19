"""
Task execution endpoints for triggering data ingestion and discovery jobs.
These endpoints expose the worker tasks as HTTP APIs for external scheduling systems.
"""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from app.core.config import settings
from app.core.security import verify_twitter_endpoint_access, verify_tasks_token
from app.ingestion.provenance import describe as describe_provenance
from app.ingestion.runs import RunOutcome, outcome_response, trigger_from_headers, worst_status
from app.ingestion.tasks import StationDiscoveryTask, DataIngestionTask, CityIngestionTask

logger = logging.getLogger(__name__)
router = APIRouter()


def _trigger(request: Request) -> str:
    return trigger_from_headers(request.headers)


def _outcome_response(outcome: RunOutcome, message: str) -> JSONResponse:
    return outcome_response(outcome, message)


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
        discovery_task = StationDiscoveryTask()
        outcome = await discovery_task.discover_all_stations_comprehensive(country=country, trigger=_trigger(request))
        logger.info("Station discovery finished with status=%s run_id=%s", outcome.status.value, outcome.run_id)
        return _outcome_response(outcome, "Station discovery completed")
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
        station_ingestion_task = DataIngestionTask()
        outcome = await station_ingestion_task.fetch_station_readings(trigger=_trigger(request))
        logger.info("Station ingestion finished with status=%s run_id=%s", outcome.status.value, outcome.run_id)
        return _outcome_response(outcome, "Station ingestion completed")
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
        city_ingestion_task = CityIngestionTask()
        outcome = await city_ingestion_task.fetch_city_readings_hourly(country=country, trigger=_trigger(request))
        logger.info("City ingestion finished with status=%s run_id=%s", outcome.status.value, outcome.run_id)
        return _outcome_response(outcome, "City ingestion completed")
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
        
        discovery_task = StationDiscoveryTask()
        station_ingestion_task = DataIngestionTask()
        city_ingestion_task = CityIngestionTask()
        
        trigger = _trigger(request)
        # Step 1: Discovery
        logger.info("Pipeline step 1/3: Station discovery")
        discovery = await discovery_task.discover_all_stations_comprehensive(trigger=trigger)
        
        # Step 2: Station ingestion
        logger.info("Pipeline step 2/3: Station ingestion")
        stations = await station_ingestion_task.fetch_station_readings(trigger=trigger)
        
        # Step 3: City ingestion (all configured countries)
        logger.info("Pipeline step 3/3: City ingestion")
        cities = await city_ingestion_task.fetch_city_readings_hourly(country=None, trigger=trigger)

        status = worst_status(discovery, stations, cities)
        logger.info("Full pipeline finished with status=%s", status.value)
        # Reuse the HTTP mapping of whichever step was worst.
        worst = next(o for o in (discovery, stations, cities) if o.status is status)
        return JSONResponse(
            status_code=worst.http_status(),
            content={
                "status": status.value,
                "message": "Full pipeline completed",
                "summary": {
                    "discovery": discovery.to_dict(),
                    "station_ingestion": stations.to_dict(),
                    "city_ingestion": cities.to_dict(),
                },
                "provenance": describe_provenance(),
            },
        )
    except Exception as e:
        error_msg = str(e) if str(e) else "Unknown error - no exception message"
        logger.error("Full pipeline failed: %s", error_msg)
        import traceback
        logger.error("Full pipeline traceback: %s", traceback.format_exc())
        
        raise HTTPException(
            status_code=500,
            detail=f"Full pipeline failed: {error_msg}"
        )


# ---------------------------------------------------------------------------
# OpenAQ v3 (independent source, shadow mode; gated by OPENAQ_ENABLED)
# ---------------------------------------------------------------------------

@router.post("/tasks/openaq/discover")
async def run_openaq_discovery(
    request: Request,
    dry_run: bool = Query(False, description="Make the requests and report the inventory, but write nothing"),
    _: bool = Depends(verify_tasks_token)
):
    """Discover Pakistan locations on OpenAQ → shadow stations + pm25 stream checkpoints."""
    from app.services.ingestion.openaq.discovery import OpenAQDiscoveryTask
    try:
        outcome = await OpenAQDiscoveryTask().run(dry_run=dry_run, trigger=_trigger(request))
        return _outcome_response(outcome, "OpenAQ discovery completed")
    except Exception as e:
        logger.error("OpenAQ discovery failed: %s", e)
        raise HTTPException(status_code=500, detail=f"OpenAQ discovery failed: {e}")


@router.post("/tasks/openaq/ingest")
async def run_openaq_ingest(request: Request, _: bool = Depends(verify_tasks_token)):
    """Hourly: fetch the next window per active stream and reconcile into readings (source='openaq')."""
    from app.services.ingestion.openaq.ingest import OpenAQIngestTask
    try:
        outcome = await OpenAQIngestTask().run(mode="ingest", trigger=_trigger(request))
        return _outcome_response(outcome, "OpenAQ ingestion completed")
    except Exception as e:
        logger.error("OpenAQ ingestion failed: %s", e)
        raise HTTPException(status_code=500, detail=f"OpenAQ ingestion failed: {e}")


@router.post("/tasks/openaq/reconcile")
async def run_openaq_reconcile(request: Request, _: bool = Depends(verify_tasks_token)):
    """Daily: re-read older windows (late/revised data) without moving the completed-window checkpoint."""
    from app.services.ingestion.openaq.ingest import OpenAQIngestTask
    try:
        outcome = await OpenAQIngestTask().run(mode="reconcile", trigger=_trigger(request))
        return _outcome_response(outcome, "OpenAQ reconciliation completed")
    except Exception as e:
        logger.error("OpenAQ reconciliation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"OpenAQ reconciliation failed: {e}")


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
        # Manifest locations must match what the tasks use (relative to the
        # process working directory, /app in the image), not a worker checkout.
        station_manifest_dir = Path(settings.STATION_MANIFEST_DIR)
        city_manifest_dir = Path(settings.CITY_MANIFEST_DIR)
        
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
                "POST /tasks/openaq/discover?dry_run=true|false",
                "POST /tasks/openaq/ingest",
                "POST /tasks/openaq/reconcile",
                "POST /tasks/twitter-lahore-pm25",
                "GET /tasks/status"
            ],
            "manifest_status": {
                "station_manifest_exists": station_manifest_exists,
                "city_manifest_exists": city_manifest_exists
            },
            "provenance": describe_provenance(),
        }
    except Exception as e:
        logger.error("Failed to get task status: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task status: {str(e)}"
        )