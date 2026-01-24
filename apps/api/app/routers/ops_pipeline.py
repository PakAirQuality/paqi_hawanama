"""
Ops Pipeline API endpoints for managing ML estimation pipelines.

Provides:
- Pipeline summary (model pointer, predictions pointer, latest run report)
- Run history listing and details
- Cloud Run job triggering (daily pipeline, retrain)
- Job execution status monitoring
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.security import verify_tasks_token

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_gcs():
    """Lazy-load GCS client; raise 501 if not installed."""
    try:
        from google.cloud import storage
        return storage
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail="GCS operations require 'google-cloud-storage' installed."
        ) from e


def _require_auth():
    """Lazy-load Google auth; raise 501 if not installed."""
    try:
        from google.auth import default
        from google.auth.transport.requests import AuthorizedSession
        return default, AuthorizedSession
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail="Cloud Run operations require 'google-auth' installed."
        ) from e


def _gcs_client():
    """Get GCS client instance."""
    storage = _require_gcs()
    return storage.Client()


def _gcs_read_json(bucket_name: str, blob_path: str) -> Dict[str, Any]:
    """Read and parse JSON from GCS."""
    try:
        client = _gcs_client()
        blob = client.bucket(bucket_name).blob(blob_path)
        if not blob.exists(client):
            raise HTTPException(
                status_code=404,
                detail=f"Object not found: gs://{bucket_name}/{blob_path}"
            )
        raw = blob.download_as_text()
        return json.loads(raw)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GCS read failed: gs://{bucket_name}/{blob_path}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"GCS read failed: {blob_path}: {str(e)}"
        )


def _gcs_list_run_dates(bucket_name: str, limit: int = 30) -> List[str]:
    """
    List run date prefixes like runs/date=YYYY-MM-DD/ and return latest N dates.
    Uses delimiter to get "folders".
    """
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        # List with delimiter to get prefixes (folders)
        blobs_iter = bucket.list_blobs(prefix="runs/date=", delimiter="/")

        # Iterate to populate prefixes
        for _ in blobs_iter:
            pass

        prefixes = list(blobs_iter.prefixes)  # e.g. runs/date=2025-10-25/

        dates = []
        for p in prefixes:
            # p: runs/date=YYYY-MM-DD/
            try:
                d = p.split("runs/date=")[1].split("/")[0]
                dates.append(d)
            except Exception:
                continue

        dates.sort()
        return dates[-limit:]
    except Exception as e:
        logger.error(f"Failed to list run dates from gs://{bucket_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list run dates: {str(e)}"
        )


def _cloudrun_session():
    """Get authorized session for Cloud Run API calls."""
    default_creds, AuthorizedSession = _require_auth()
    creds, _ = default_creds(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(creds)


def _cloudrun_job_name(job: str) -> str:
    """Build full Cloud Run job resource name."""
    if not settings.OPS_GCP_PROJECT:
        raise HTTPException(
            status_code=500,
            detail="OPS_GCP_PROJECT environment variable not set"
        )
    return f"projects/{settings.OPS_GCP_PROJECT}/locations/{settings.OPS_RUN_REGION}/jobs/{job}"


def _get_derived_bucket() -> str:
    """Get the derived bucket name, stripping gs:// prefix if present."""
    bucket = settings.OPS_DERIVED_BUCKET
    if not bucket:
        raise HTTPException(
            status_code=500,
            detail="OPS_DERIVED_BUCKET environment variable not set"
        )
    return bucket.replace("gs://", "").strip("/")


# =============================================================================
# READ-ONLY ENDPOINTS (GCS -> UI)
# =============================================================================

@router.get(
    "/summary",
    summary="Get pipeline summary",
    description="Returns current model pointer, predictions pointer, and latest run report."
)
async def get_pipeline_summary(
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get pipeline summary including:
    - Model pointer (current operational model)
    - Predictions pointer (latest published predictions)
    - Latest run report with health stats
    """
    bucket = _get_derived_bucket()

    # Read model pointer
    model_ptr = None
    try:
        model_ptr = _gcs_read_json(bucket, "models/operational/latest.json")
    except HTTPException as e:
        if e.status_code != 404:
            raise
        logger.warning("Model pointer not found")

    # Read predictions pointer
    preds_ptr = None
    try:
        preds_ptr = _gcs_read_json(bucket, "predictions/latest.json")
    except HTTPException as e:
        if e.status_code != 404:
            raise
        logger.warning("Predictions pointer not found")

    # Get latest run report
    latest_run = None
    dates = _gcs_list_run_dates(bucket, limit=1)
    if dates:
        try:
            latest_run = _gcs_read_json(bucket, f"runs/date={dates[-1]}/run_report.json")
        except HTTPException as e:
            if e.status_code != 404:
                raise
            logger.warning(f"Run report not found for {dates[-1]}")

    return {
        "model_pointer": model_ptr,
        "predictions_pointer": preds_ptr,
        "latest_run_report": latest_run,
        "derived_bucket": bucket,
        "region": settings.OPS_RUN_REGION,
        "gcp_project": settings.OPS_GCP_PROJECT,
        "jobs": {
            "daily": settings.OPS_DAILY_JOB_NAME,
            "retrain": settings.OPS_RETRAIN_JOB_NAME
        },
    }


@router.get(
    "/runs",
    summary="List pipeline runs",
    description="Returns list of run dates available in the derived bucket."
)
async def list_pipeline_runs(
    limit: int = Query(30, ge=1, le=365, description="Maximum number of run dates to return"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """List available pipeline run dates (most recent last)."""
    bucket = _get_derived_bucket()
    dates = _gcs_list_run_dates(bucket, limit=limit)
    return {"dates": dates, "count": len(dates)}


@router.get(
    "/runs/{run_date}",
    summary="Get run report",
    description="Returns the run report for a specific date."
)
async def get_run_report(
    run_date: str,
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get the run report for a specific date.

    Args:
        run_date: Date in YYYY-MM-DD format
    """
    bucket = _get_derived_bucket()
    return _gcs_read_json(bucket, f"runs/date={run_date}/run_report.json")


# =============================================================================
# JOB CONTROL ENDPOINTS (Cloud Run Jobs API)
# =============================================================================

@router.post(
    "/run/{which}",
    summary="Trigger pipeline job",
    description="Triggers a Cloud Run job (daily pipeline or retrain)."
)
async def run_pipeline_job(
    which: str,
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Trigger a Cloud Run pipeline job.

    Args:
        which: Job type - "daily" for daily estimation pipeline, "retrain" for model retraining
    """
    if which not in ("daily", "retrain"):
        raise HTTPException(
            status_code=400,
            detail="which must be 'daily' or 'retrain'"
        )

    job = settings.OPS_DAILY_JOB_NAME if which == "daily" else settings.OPS_RETRAIN_JOB_NAME
    name = _cloudrun_job_name(job)

    # POST https://run.googleapis.com/v2/{name}:run
    url = f"https://run.googleapis.com/v2/{name}:run"

    try:
        sess = _cloudrun_session()
        resp = sess.post(url, json={})

        if resp.status_code >= 400:
            logger.error(f"Cloud Run job trigger failed: {resp.status_code} {resp.text}")
            raise HTTPException(
                status_code=500,
                detail=f"Cloud Run job trigger failed: {resp.text}"
            )

        operation = resp.json()
        logger.info(f"Triggered Cloud Run job: {which} ({job})")

        return {
            "job": which,
            "job_name": name,
            "status": "triggered",
            "operation": operation
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger Cloud Run job {which}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger job: {str(e)}"
        )


@router.get(
    "/executions/{which}",
    summary="Get job executions",
    description="Returns recent executions of a Cloud Run job."
)
async def get_job_executions(
    which: str,
    page_size: int = Query(10, ge=1, le=50, description="Number of executions to return"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get recent executions of a Cloud Run job.

    Args:
        which: Job type - "daily" or "retrain"
        page_size: Number of executions to return (default 10)
    """
    if which not in ("daily", "retrain"):
        raise HTTPException(
            status_code=400,
            detail="which must be 'daily' or 'retrain'"
        )

    job = settings.OPS_DAILY_JOB_NAME if which == "daily" else settings.OPS_RETRAIN_JOB_NAME
    parent = _cloudrun_job_name(job)

    # GET https://run.googleapis.com/v2/{parent}/executions
    url = f"https://run.googleapis.com/v2/{parent}/executions?pageSize={page_size}"

    try:
        sess = _cloudrun_session()
        resp = sess.get(url)

        if resp.status_code >= 400:
            logger.error(f"Cloud Run executions list failed: {resp.status_code} {resp.text}")
            raise HTTPException(
                status_code=500,
                detail=f"Cloud Run executions list failed: {resp.text}"
            )

        return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list executions for {which}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list executions: {str(e)}"
        )


@router.get(
    "/execution/{execution_name:path}",
    summary="Get execution details",
    description="Returns details of a specific Cloud Run job execution."
)
async def get_execution_details(
    execution_name: str,
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get details of a specific Cloud Run job execution.

    Args:
        execution_name: Full execution resource name (projects/.../locations/.../jobs/.../executions/...)
    """
    # GET https://run.googleapis.com/v2/{name}
    url = f"https://run.googleapis.com/v2/{execution_name}"

    try:
        sess = _cloudrun_session()
        resp = sess.get(url)

        if resp.status_code >= 400:
            logger.error(f"Cloud Run execution get failed: {resp.status_code} {resp.text}")
            raise HTTPException(
                status_code=500,
                detail=f"Cloud Run execution get failed: {resp.text}"
            )

        return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution {execution_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get execution: {str(e)}"
        )
