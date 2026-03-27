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
from ._tile_utils import (
    TURBO_CMAP,
    _clip_tile_alpha,
    _load_pakistan_boundary_3857,
    _tile_mercator_bounds,
)

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


def _gcs_list_run_dates(limit: int = 30) -> List[str]:
    """
    List run date prefixes like runs/date=YYYY-MM-DD/ and return latest N dates.
    Uses delimiter to get "folders".
    Reads from OUTPUTS bucket.
    """
    bucket_name = _get_outputs_bucket()
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


def _get_bucket(bucket_setting: str, env_var_name: str) -> str:
    """Get a bucket name, stripping gs:// prefix if present."""
    if not bucket_setting:
        raise HTTPException(
            status_code=500,
            detail=f"{env_var_name} environment variable not set"
        )
    return bucket_setting.replace("gs://", "").strip("/")


def _get_models_bucket() -> str:
    """Get the models bucket name (for model artifacts)."""
    return _get_bucket(settings.OPS_MODELS_BUCKET, "OPS_MODELS_BUCKET")


def _get_outputs_bucket() -> str:
    """Get the outputs bucket name (for predictions and runs)."""
    return _get_bucket(settings.OPS_OUTPUTS_BUCKET, "OPS_OUTPUTS_BUCKET")


def _get_features_bucket() -> str:
    """Get the features bucket name (for COGs and training data)."""
    return _get_bucket(settings.OPS_FEATURES_BUCKET, "OPS_FEATURES_BUCKET")


def _get_derived_bucket() -> str:
    """Get the derived bucket name (for feature stores - legacy/fallback)."""
    return _get_bucket(settings.OPS_DERIVED_BUCKET, "OPS_DERIVED_BUCKET")


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
    models_bucket = _get_models_bucket()
    outputs_bucket = _get_outputs_bucket()

    # Read model pointer (from MODELS bucket, path: operational/latest.json)
    model_ptr = None
    try:
        model_ptr = _gcs_read_json(models_bucket, "operational/latest.json")
    except HTTPException as e:
        if e.status_code != 404:
            raise
        logger.warning("Model pointer not found")

    # Read predictions pointer (from OUTPUTS bucket)
    preds_ptr = None
    try:
        preds_ptr = _gcs_read_json(outputs_bucket, "predictions/latest.json")
    except HTTPException as e:
        if e.status_code != 404:
            raise
        logger.warning("Predictions pointer not found")

    # Get latest run report (from OUTPUTS bucket)
    latest_run = None
    dates = _gcs_list_run_dates(limit=1)
    if dates:
        try:
            latest_run = _gcs_read_json(outputs_bucket, f"runs/date={dates[-1]}/run_report.json")
        except HTTPException as e:
            if e.status_code != 404:
                raise
            logger.warning(f"Run report not found for {dates[-1]}")

    return {
        "model_pointer": model_ptr,
        "predictions_pointer": preds_ptr,
        "latest_run_report": latest_run,
        "models_bucket": models_bucket,
        "outputs_bucket": outputs_bucket,
        "region": settings.OPS_RUN_REGION,
        "gcp_project": settings.OPS_GCP_PROJECT,
        "jobs": {
            "daily": settings.OPS_DAILY_JOB_NAME,
            "retrain": settings.OPS_RETRAIN_JOB_NAME
        },
    }


def _find_model_results_file(waterline: str) -> Optional[str]:
    """
    Find the results JSON file for a given waterline.

    Results files are named like: operational_results_W20250713_20260122_172806.json
    We match by waterline (W{date}) and return the most recent one.
    Reads from MODELS bucket.
    """
    bucket_name = _get_models_bucket()
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        # List all results files (path: operational/results/ in models bucket)
        waterline_compact = waterline.replace("-", "")
        prefix = f"operational/results/operational_results_W{waterline_compact}_"

        blobs = list(bucket.list_blobs(prefix=prefix))
        if not blobs:
            return None

        # Sort by name (timestamp is part of filename) and return the latest
        blobs.sort(key=lambda b: b.name, reverse=True)
        return blobs[0].name
    except Exception as e:
        logger.error(f"Failed to find model results for waterline {waterline}: {e}")
        return None


@router.get(
    "/model-details",
    summary="Get model training details",
    description="Returns model training results including hyperparameters, CV metrics, and feature importance."
)
async def get_model_details(
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get detailed model training results for the current operational model.

    Returns:
    - model_type: Type of model (e.g., "registry_authoritative_lgbm_daily")
    - best_params: Hyperparameters used
    - cv: Cross-validation results with per-fold metrics
    - final_model: Final model metrics on dev/test sets
    - feature_importance: Top features by importance
    """
    models_bucket = _get_models_bucket()

    # First get the model pointer to find the waterline (path: operational/latest.json)
    try:
        model_ptr = _gcs_read_json(models_bucket, "operational/latest.json")
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="No model pointer found")
        raise

    waterline = model_ptr.get("waterline")
    if not waterline:
        raise HTTPException(status_code=404, detail="Model pointer missing waterline")

    # Find the results file (in MODELS bucket)
    results_path = _find_model_results_file(waterline)
    if not results_path:
        raise HTTPException(
            status_code=404,
            detail=f"Model results not found for waterline {waterline}"
        )

    # Read and return the results
    results = _gcs_read_json(models_bucket, results_path)

    # Sanitize NaN/Inf values that can't be JSON serialized
    import math
    def sanitize_value(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    def sanitize_dict(d):
        if d is None:
            return None
        if isinstance(d, dict):
            return {k: sanitize_dict(v) for k, v in d.items()}
        if isinstance(d, list):
            return [sanitize_dict(v) for v in d]
        return sanitize_value(d)

    results = sanitize_dict(results)

    # Handle both operational waterline format and CV training format
    training_mode = results.get("training_mode", "cv")

    if training_mode == "operational_waterline":
        # Operational waterline training results format
        val_metrics = results.get("val_metrics", {})
        return {
            "training_mode": "operational",
            "model_type": "LightGBM (operational waterline)",
            "waterline": waterline,
            "reference_date": results.get("reference_date"),
            "cutoff_days": results.get("cutoff_days"),
            "validation_days": results.get("validation_days"),
            "n_features": results.get("n_features"),
            "train_samples": results.get("train_samples"),
            "val_samples": results.get("val_samples"),
            "train_date_range": results.get("train_date_range"),
            "val_date_range": results.get("val_date_range"),
            "train_years": results.get("train_years"),
            "val_metrics": {
                "rmse": val_metrics.get("rmse"),
                "mae": val_metrics.get("mae"),
                "r2": val_metrics.get("r2"),
                "bias": val_metrics.get("bias"),
                "n_predictions": val_metrics.get("n_predictions"),
                "n_stations": val_metrics.get("n_stations"),
                "skill_vs_station_month": val_metrics.get("skill_vs_station_month"),
                "skill_vs_yesterday": val_metrics.get("skill_vs_yesterday"),
            },
            "val_monthly": results.get("val_monthly"),
            "lgbm_params_used": results.get("lgbm_params_used"),
            "timestamp": results.get("timestamp"),
        }
    else:
        # CV training results format (from production.py)
        return {
            "training_mode": "cv",
            "model_type": results.get("model_type"),
            "waterline": waterline,
            "n_features": results.get("n_features_full"),
            "train_samples": results.get("train_samples"),
            "dev_samples": results.get("dev_samples"),
            "test_samples": results.get("test_samples"),
            "best_params": results.get("best_params_from_tuning"),
            "cv": {
                "folds": results.get("cv", {}).get("folds", {}),
                "summary": results.get("cv", {}).get("summary_val_metrics", {}),
            },
            "final_model": {
                "dev_overall": results.get("final_model", {}).get("dev_overall"),
                "test_overall": results.get("final_model", {}).get("test_overall"),
            },
            "feature_importance_top20": results.get("final_model", {}).get("feature_importance", [])[:20],
            "timestamp": results.get("timestamp"),
        }


def _gcs_list_model_history(limit: int = 30) -> List[str]:
    """
    List model history entries like history/ref_YYYYMMDD.json.
    Returns reference dates (sorted, most recent last).
    Reads from MODELS bucket.
    """
    bucket_name = _get_models_bucket()
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        # Path in models bucket: history/ref_*
        blobs = bucket.list_blobs(prefix="history/ref_")

        dates = []
        for blob in blobs:
            # blob.name: history/ref_20250101.json
            try:
                name = blob.name
                if name.endswith(".json") and "ref_" in name:
                    # Extract date from ref_YYYYMMDD.json
                    date_part = name.split("ref_")[1].split(".json")[0]
                    # Convert YYYYMMDD to YYYY-MM-DD
                    formatted = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
                    dates.append(formatted)
            except Exception:
                continue

        dates.sort()
        return dates[-limit:]
    except Exception as e:
        logger.error(f"Failed to list model history from gs://{bucket_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list model history: {str(e)}"
        )


@router.get(
    "/model-history",
    summary="List model training history",
    description="Returns list of reference dates with model training results."
)
async def list_model_history(
    limit: int = Query(30, ge=1, le=365, description="Maximum number of entries to return"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """List available model training history entries (most recent last)."""
    dates = _gcs_list_model_history(limit=limit)
    return {"reference_dates": dates, "count": len(dates)}


@router.get(
    "/model-history/{reference_date}",
    summary="Get model training details",
    description="Returns model training results for a specific reference date."
)
async def get_model_history_entry(
    reference_date: str,
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get model training results for a specific reference date.

    Args:
        reference_date: Date in YYYY-MM-DD format
    """
    models_bucket = _get_models_bucket()

    # Convert YYYY-MM-DD to YYYYMMDD for the filename
    # Path in models bucket: history/ref_YYYYMMDD.json
    date_compact = reference_date.replace("-", "")
    blob_path = f"history/ref_{date_compact}.json"

    try:
        results = _gcs_read_json(models_bucket, blob_path)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Model history not found for reference date: {reference_date}"
            )
        raise

    # Sanitize NaN/Inf values
    import math
    def sanitize_value(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    def sanitize_dict(d):
        if d is None:
            return None
        if isinstance(d, dict):
            return {k: sanitize_dict(v) for k, v in d.items()}
        if isinstance(d, list):
            return [sanitize_dict(v) for v in d]
        return sanitize_value(d)

    return sanitize_dict(results)


@router.get(
    "/runs",
    summary="List pipeline runs",
    description="Returns list of run dates available in the outputs bucket."
)
async def list_pipeline_runs(
    limit: int = Query(30, ge=1, le=365, description="Maximum number of run dates to return"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """List available pipeline run dates (most recent last)."""
    dates = _gcs_list_run_dates(limit=limit)
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
    outputs_bucket = _get_outputs_bucket()
    return _gcs_read_json(outputs_bucket, f"runs/date={run_date}/run_report.json")


def _gcs_list_prediction_dates(limit: int = 30) -> List[str]:
    """
    List prediction date prefixes like predictions/date=YYYY-MM-DD/.
    Reads from OUTPUTS bucket.
    """
    bucket_name = _get_outputs_bucket()
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        blobs_iter = bucket.list_blobs(prefix="predictions/date=", delimiter="/")

        for _ in blobs_iter:
            pass

        prefixes = list(blobs_iter.prefixes)

        dates = []
        for p in prefixes:
            try:
                d = p.split("predictions/date=")[1].split("/")[0]
                dates.append(d)
            except Exception:
                continue

        dates.sort()
        return dates[-limit:]
    except Exception as e:
        logger.error(f"Failed to list prediction dates from gs://{bucket_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list prediction dates: {str(e)}"
        )


@router.get(
    "/predictions",
    summary="List available predictions",
    description="Returns list of dates with predictions available."
)
async def list_predictions(
    limit: int = Query(30, ge=1, le=365, description="Maximum number of dates to return"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """List available prediction dates (most recent last)."""
    dates = _gcs_list_prediction_dates(limit=limit)
    return {"dates": dates, "count": len(dates)}


@router.get(
    "/predictions/{pred_date}",
    summary="Get prediction data",
    description="Returns prediction data for map visualization."
)
async def get_prediction_data(
    pred_date: str,
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get prediction data for a specific date.

    Returns JSON with grid metadata, statistics, and PM2.5 values
    optimized for frontend map rendering.

    Args:
        pred_date: Date in YYYY-MM-DD format
    """
    outputs_bucket = _get_outputs_bucket()

    # Try JSON format first (new format with grid data)
    try:
        return _gcs_read_json(outputs_bucket, f"predictions/date={pred_date}/pm25_{pred_date}.json")
    except HTTPException as e:
        if e.status_code != 404:
            raise

    # Fallback: check if GeoTIFF exists (older predictions)
    try:
        client = _gcs_client()
        tif_blob = client.bucket(outputs_bucket).blob(f"predictions/date={pred_date}/pm25_{pred_date}.tif")
        if tif_blob.exists(client):
            raise HTTPException(
                status_code=501,
                detail=f"Prediction for {pred_date} exists as GeoTIFF only. JSON format not available. Re-run pipeline to generate JSON."
            )
    except HTTPException:
        raise

    raise HTTPException(
        status_code=404,
        detail=f"Prediction not found for date: {pred_date}"
    )


# =============================================================================
# COG TILE SERVING ENDPOINTS
# =============================================================================

def _require_rio_tiler():
    """Lazy-load rio-tiler; raise 501 if not installed."""
    try:
        from rio_tiler.io import Reader
        from rio_tiler.colormap import cmap
        return Reader, cmap
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail="Tile serving requires 'rio-tiler' installed."
        ) from e


# PM2.5 colorscale range (fixed)
PM25_VMIN = 20.0
PM25_VMAX = 180.0


# =============================================================================
# FEATURE CONFIG & COLORMAPS
# =============================================================================

FEATURE_CONFIG = {
    # MET features (ERA5)
    "t2m": {"stage": "met", "vmin": 270, "vmax": 320, "unit": "K", "colormap": "RdBu_r"},
    "d2m": {"stage": "met", "vmin": 250, "vmax": 310, "unit": "K", "colormap": "RdBu_r"},
    "sp": {"stage": "met", "vmin": 60000, "vmax": 105000, "unit": "Pa", "colormap": "viridis"},
    "u10": {"stage": "met", "vmin": -10, "vmax": 10, "unit": "m/s", "colormap": "RdBu_r"},
    "v10": {"stage": "met", "vmin": -10, "vmax": 10, "unit": "m/s", "colormap": "RdBu_r"},
    "blh": {"stage": "met", "vmin": 0, "vmax": 3000, "unit": "m", "colormap": "YlOrRd"},
    "tcc": {"stage": "met", "vmin": 0, "vmax": 1, "unit": "fraction", "colormap": "Blues"},
    "WS10": {"stage": "met", "vmin": 0, "vmax": 15, "unit": "m/s", "colormap": "Purples"},
    "RH": {"stage": "met", "vmin": 0, "vmax": 100, "unit": "%", "colormap": "Blues"},
    "VPD": {"stage": "met", "vmin": 0, "vmax": 50, "unit": "hPa", "colormap": "YlOrRd"},
    "VC": {"stage": "met", "vmin": 0, "vmax": 50000, "unit": "m2/s", "colormap": "viridis"},
    "msl": {"stage": "met", "vmin": 95000, "vmax": 105000, "unit": "Pa", "colormap": "viridis"},
    # AOD features
    "optical_depth_047": {"stage": "aod", "vmin": 0, "vmax": 2.0, "unit": "unitless", "colormap": "YlOrRd"},
    "optical_depth_055": {"stage": "aod", "vmin": 0, "vmax": 2.0, "unit": "unitless", "colormap": "YlOrRd"},
    # TROPOMI features
    "no2_median": {"stage": "tropomi", "vmin": 0, "vmax": 0.0002, "unit": "mol/m2", "colormap": "Reds"},
    "so2_median": {"stage": "tropomi", "vmin": -0.001, "vmax": 0.005, "unit": "mol/m2", "colormap": "Purples"},
    "co_median": {"stage": "tropomi", "vmin": 0.01, "vmax": 0.06, "unit": "mol/m2", "colormap": "YlOrRd"},
    "o3_median": {"stage": "tropomi", "vmin": 0.1, "vmax": 0.16, "unit": "mol/m2", "colormap": "viridis"},
    "hcho_median": {"stage": "tropomi", "vmin": 0, "vmax": 0.001, "unit": "mol/m2", "colormap": "Reds"},
}


def _build_matplotlib_colormap(name: str) -> Dict[int, tuple]:
    """Build a 256-entry colormap dict from a matplotlib colormap name."""
    try:
        from matplotlib import colormaps
        cmap = colormaps[name]
    except Exception:
        import matplotlib.pyplot as plt
        cmap = plt.get_cmap(name)

    result = {}
    for i in range(256):
        r, g, b, a = cmap(i / 255.0)
        result[i] = (
            max(0, min(255, int(round(r * 255)))),
            max(0, min(255, int(round(g * 255)))),
            max(0, min(255, int(round(b * 255)))),
            255,
        )
    return result


# Precompute all needed colormaps
_FEATURE_CMAPS: Dict[str, Dict[int, tuple]] = {}

def _get_feature_cmap(name: str) -> Dict[int, tuple]:
    """Get or build a colormap by name (lazy + cached)."""
    if name not in _FEATURE_CMAPS:
        _FEATURE_CMAPS[name] = _build_matplotlib_colormap(name)
    return _FEATURE_CMAPS[name]


# =============================================================================
# PAKISTAN BOUNDARY CLIPPING FOR TILES
# =============================================================================


# _turbo_colormap, _load_pakistan_boundary_3857, _tile_mercator_bounds,
# _clip_tile_alpha, and TURBO_CMAP are imported from ._tile_utils


def _download_cog_to_temp(bucket_name: str, blob_path: str) -> str:
    """Download COG from GCS to a temp file and return the path."""
    import tempfile
    try:
        client = _gcs_client()
        blob = client.bucket(bucket_name).blob(blob_path)
        if not blob.exists(client):
            raise HTTPException(
                status_code=404,
                detail=f"COG not found: gs://{bucket_name}/{blob_path}"
            )

        # Create temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
        blob.download_to_filename(tmp.name)
        return tmp.name
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download COG: gs://{bucket_name}/{blob_path}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to download COG: {str(e)}"
        )


@router.get(
    "/tiles/{pred_date}/{z}/{x}/{y}.png",
    summary="Get PM2.5 prediction tile",
    description="Returns a PNG tile from COG prediction for map visualization.",
    responses={
        200: {"content": {"image/png": {}}},
        404: {"description": "COG not found for date"},
        501: {"description": "rio-tiler not installed"},
    }
)
async def get_prediction_tile(
    pred_date: str,
    z: int,
    x: int,
    y: int,
    smoothed: bool = Query(False, description="Use Gaussian-smoothed predictions"),
    model: str = Query("backbone", description="Model variant: 'backbone' or 'support_aware'"),
    _: bool = Depends(verify_tasks_token),
):
    """
    Serve XYZ tiles from Cloud Optimized GeoTIFF.

    Args:
        pred_date: Date in YYYY-MM-DD format
        z: Zoom level
        x: Tile X coordinate
        y: Tile Y coordinate
        smoothed: If True, serve from the Gaussian-smoothed COG
        model: 'backbone' (default) or 'support_aware'
    """
    from fastapi.responses import Response
    import os

    Reader, _ = _require_rio_tiler()
    outputs_bucket = _get_outputs_bucket()

    # Download COG to temp file (GCS client uses Application Default Credentials)
    suffix = "_smoothed" if smoothed else ""
    if model.startswith("urban/"):
        # City-level 1 km predictions: model="urban/lahore"
        city_key = model.split("/", 1)[1]
        blob_path = f"predictions/urban/date={pred_date}/{city_key}{suffix}.tif"
    elif model == "support_aware":
        prefix = "predictions/support_aware"
        suffix = "_gaussian_smoothed" if smoothed else ""
        blob_path = f"{prefix}/date={pred_date}/pm25_{pred_date}{suffix}.tif"
    else:
        suffix = "_gaussian_smoothed" if smoothed else ""
        blob_path = f"predictions/date={pred_date}/pm25_{pred_date}{suffix}.tif"
    tmp_path = _download_cog_to_temp(outputs_bucket, blob_path)

    try:
        import numpy as np
        from PIL import Image
        import io
        from rio_tiler.errors import TileOutsideBounds

        # Helper to create empty transparent tile
        def empty_tile_png():
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        def tile_response(png_bytes):
            return Response(
                content=png_bytes,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "X-Tile-Date": pred_date,
                }
            )

        with Reader(tmp_path) as src:
            # Try to read tile - may be outside bounds
            try:
                tile = src.tile(x, y, z, indexes=1, resampling_method="cubic")
            except TileOutsideBounds:
                # Tile outside raster coverage - return transparent tile
                return tile_response(empty_tile_png())

            # Get data and mask
            data = tile.data[0].astype(np.float32)
            mask = tile.mask

            # If entire tile is nodata, return empty tile
            if mask is None or np.max(mask) == 0:
                return tile_response(empty_tile_png())

            # Rescale data to 0-255 for colormap lookup
            rescaled = np.clip(
                (data - PM25_VMIN) / (PM25_VMAX - PM25_VMIN) * 255,
                0, 255
            ).astype(np.uint8)

            # Create RGBA image with proper transparency
            h, w = rescaled.shape
            rgba = np.zeros((h, w, 4), dtype=np.uint8)

            # Apply colormap to get RGB values
            for idx, color in TURBO_CMAP.items():
                color_mask = (rescaled == idx)
                rgba[color_mask, 0] = color[0]  # R
                rgba[color_mask, 1] = color[1]  # G
                rgba[color_mask, 2] = color[2]  # B

            # Set alpha from mask (0 = transparent, 255 = opaque)
            # Use robust alpha: any mask > 0 becomes fully opaque
            alpha = (mask > 0).astype(np.uint8) * 255
            rgba[:, :, 3] = alpha

            # Clip to Pakistan boundary at tile resolution
            rgba = _clip_tile_alpha(rgba, x, y, z)

            # Convert to PNG
            img = Image.fromarray(rgba, mode='RGBA')
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return tile_response(buffer.getvalue())

    except HTTPException:
        raise
    except Exception as e:
        # For tile errors, return empty tile instead of 500
        # This prevents MapLibre from breaking on tiles outside coverage
        logger.warning(f"Tile error for {pred_date}/{z}/{x}/{y}: {e}")
        try:
            from PIL import Image
            import io
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return Response(
                content=buf.getvalue(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"}
            )
        except:
            raise HTTPException(status_code=500, detail="Tile generation failed")
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get(
    "/tiles/{pred_date}/tilejson",
    summary="Get TileJSON for prediction",
    description="Returns TileJSON metadata for MapLibre tile source."
)
async def get_prediction_tilejson(
    pred_date: str,
    request: Request,
    model: str = Query("backbone", description="Model variant: 'backbone' or 'support_aware'"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get TileJSON metadata for a prediction date.

    Args:
        pred_date: Date in YYYY-MM-DD format
        model: 'backbone' (default) or 'support_aware'
    """
    import os

    Reader, _ = _require_rio_tiler()
    outputs_bucket = _get_outputs_bucket()

    # Download COG to temp file
    prefix = "predictions/support_aware" if model == "support_aware" else "predictions"
    blob_path = f"{prefix}/date={pred_date}/pm25_{pred_date}.tif"
    tmp_path = _download_cog_to_temp(outputs_bucket, blob_path)

    try:
        with Reader(tmp_path) as src:
            info = src.info()

            # Build tile URL template - use correct path /ops/pipeline
            base_url = str(request.base_url).rstrip("/")
            model_param = f"&model={model}" if model != "backbone" else ""
            tile_url = f"{base_url}/api/v1/ops/pipeline/tiles/{pred_date}/{{z}}/{{x}}/{{y}}.png?smoothed=true{model_param}"

            return {
                "tilejson": "3.0.0",
                "name": f"PM2.5 Predictions {pred_date}",
                "description": f"PM2.5 predictions for {pred_date}",
                "version": "1.0.0",
                "attribution": "Hawanama ML Pipeline",
                "tiles": [tile_url],
                "minzoom": 0,
                "maxzoom": 12,
                "bounds": list(info.bounds),
                "center": [
                    (info.bounds[0] + info.bounds[2]) / 2,
                    (info.bounds[1] + info.bounds[3]) / 2,
                    6  # Default zoom
                ],
                "colorscale": {
                    "name": "turbo",
                    "vmin": PM25_VMIN,
                    "vmax": PM25_VMAX,
                    "unit": "µg/m³"
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"TileJSON error for {pred_date}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"TileJSON generation failed: {error_msg}"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _gcs_list_cog_dates(limit: int = 365) -> List[str]:
    """
    List prediction dates that have COG files available.
    Reads from OUTPUTS bucket.
    """
    bucket_name = _get_outputs_bucket()
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        # List all .tif files in predictions folder
        blobs = bucket.list_blobs(prefix="predictions/date=")

        dates = set()
        for blob in blobs:
            if blob.name.endswith(".tif"):
                # Extract date from path: predictions/date=YYYY-MM-DD/pm25_YYYY-MM-DD.tif
                try:
                    d = blob.name.split("predictions/date=")[1].split("/")[0]
                    dates.add(d)
                except Exception:
                    continue

        dates_list = sorted(list(dates))
        return dates_list[-limit:]
    except Exception as e:
        logger.error(f"Failed to list COG dates from gs://{bucket_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list COG dates: {str(e)}"
        )


@router.get(
    "/tiles/dates",
    summary="List dates with COG tiles",
    description="Returns list of dates that have COG tiles available for serving."
)
async def list_cog_dates(
    limit: int = Query(365, ge=1, le=1000, description="Maximum number of dates to return"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """List available COG prediction dates for tile serving."""
    dates = _gcs_list_cog_dates(limit=limit)
    return {
        "dates": dates,
        "count": len(dates),
        "tile_url_template": "/api/v1/ops/pipeline/tiles/{date}/{z}/{x}/{y}.png",
        "tilejson_url_template": "/api/v1/ops/pipeline/tiles/{date}/tilejson"
    }


@router.get(
    "/tiles/{pred_date}/point",
    summary="Get PM2.5 value at point",
    description="Returns PM2.5 prediction value at a specific lat/lon coordinate."
)
async def get_point_value(
    pred_date: str,
    lat: float = Query(..., ge=20.0, le=40.0, description="Latitude"),
    lon: float = Query(..., ge=60.0, le=80.0, description="Longitude"),
    smoothed: bool = Query(False, description="Use Gaussian-smoothed predictions"),
    _: bool = Depends(verify_tasks_token),
) -> Dict[str, Any]:
    """
    Query PM2.5 prediction value at a specific coordinate.

    Args:
        pred_date: Date in YYYY-MM-DD format
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        smoothed: If True, query from the Gaussian-smoothed COG
    """
    import os
    import math

    Reader, _ = _require_rio_tiler()
    outputs_bucket = _get_outputs_bucket()

    # Download COG to temp file
    suffix = "_gaussian_smoothed" if smoothed else ""
    blob_path = f"predictions/date={pred_date}/pm25_{pred_date}{suffix}.tif"
    tmp_path = _download_cog_to_temp(outputs_bucket, blob_path)

    try:
        with Reader(tmp_path) as src:
            # Read point value
            point_data = src.point(lon, lat, indexes=1)

            value = point_data.data[0] if point_data.data is not None else None

            # Check for nodata
            if value is not None and (value < -9000 or not math.isfinite(value)):
                value = None

            return {
                "date": pred_date,
                "lat": lat,
                "lon": lon,
                "pm25": round(float(value), 2) if value is not None else None,
                "unit": "µg/m³",
                "colorscale": {
                    "vmin": PM25_VMIN,
                    "vmax": PM25_VMAX,
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "outside" in error_msg.lower() or "bounds" in error_msg.lower():
            raise HTTPException(
                status_code=400,
                detail=f"Coordinates ({lat}, {lon}) outside prediction bounds"
            )
        logger.error(f"Point query error for {pred_date} at ({lat}, {lon}): {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Point query failed: {error_msg}"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# =============================================================================
# FEATURE TILE SERVING ENDPOINTS
# =============================================================================

@router.get(
    "/tiles/features",
    summary="List available features",
    description="Returns list of features with metadata (stage, unit, vmin, vmax, colormap)."
)
async def list_features(
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """List all available features with their metadata."""
    features = [
        {
            "name": name,
            "stage": cfg["stage"],
            "unit": cfg["unit"],
            "vmin": cfg["vmin"],
            "vmax": cfg["vmax"],
            "colormap": cfg["colormap"],
        }
        for name, cfg in FEATURE_CONFIG.items()
    ]
    return {"features": features, "count": len(features)}


def _gcs_list_feature_cog_dates(feature: str, limit: int = 365) -> List[str]:
    """List dates that have COG files for a specific feature.
    Reads from FEATURES bucket (path: cog/{feature}/date=).
    """
    bucket_name = _get_features_bucket()
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        # Path in features bucket: cog/{feature}/date=
        prefix = f"cog/{feature}/date="
        blobs = bucket.list_blobs(prefix=prefix)

        dates = set()
        for blob in blobs:
            if blob.name.endswith(".tif"):
                try:
                    d = blob.name.split(f"cog/{feature}/date=")[1].split("/")[0]
                    dates.add(d)
                except Exception:
                    continue

        dates_list = sorted(list(dates))
        return dates_list[-limit:]
    except Exception as e:
        logger.error(f"Failed to list feature COG dates for {feature}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list feature COG dates: {str(e)}"
        )


@router.get(
    "/tiles/features/dates",
    summary="List dates with feature COGs",
    description="Returns list of dates that have COG tiles for a given feature."
)
async def list_feature_cog_dates(
    feature: str = Query(..., description="Feature name (e.g. t2m, optical_depth_047)"),
    limit: int = Query(365, ge=1, le=1000, description="Maximum number of dates to return"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """List available COG dates for a specific feature."""
    if feature not in FEATURE_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    dates = _gcs_list_feature_cog_dates(feature, limit=limit)
    return {"dates": dates, "count": len(dates), "feature": feature}


@router.get(
    "/tiles/features/{feature}/{feat_date}/{z}/{x}/{y}.png",
    summary="Get feature tile",
    description="Returns a PNG tile from a feature COG.",
    responses={
        200: {"content": {"image/png": {}}},
        404: {"description": "COG not found"},
    }
)
async def get_feature_tile(
    feature: str,
    feat_date: str,
    z: int,
    x: int,
    y: int,
    _: bool = Depends(verify_tasks_token)
):
    """Serve XYZ tiles from a feature COG."""
    from fastapi.responses import Response
    import os

    if feature not in FEATURE_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    cfg = FEATURE_CONFIG[feature]
    Reader, _ = _require_rio_tiler()
    features_bucket = _get_features_bucket()

    # Path in features bucket: cog/{feature}/date={date}/{feature}.tif
    blob_path = f"cog/{feature}/date={feat_date}/{feature}.tif"
    tmp_path = _download_cog_to_temp(features_bucket, blob_path)

    try:
        import numpy as np
        from PIL import Image
        import io
        from rio_tiler.errors import TileOutsideBounds

        # Helper to create empty transparent tile
        def empty_tile_png():
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        def tile_response(png_bytes):
            return Response(
                content=png_bytes,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "X-Tile-Date": feat_date,
                    "X-Feature": feature,
                }
            )

        with Reader(tmp_path) as src:
            # Try to read tile - may be outside bounds
            try:
                tile = src.tile(x, y, z, indexes=1, resampling_method="cubic")
            except TileOutsideBounds:
                return tile_response(empty_tile_png())

            # Get data and mask
            data = tile.data[0].astype(np.float32)
            mask = tile.mask

            # If entire tile is nodata, return empty tile
            if mask is None or np.max(mask) == 0:
                return tile_response(empty_tile_png())

            vmin = cfg["vmin"]
            vmax = cfg["vmax"]
            rescaled = np.clip(
                (data - vmin) / (vmax - vmin) * 255,
                0, 255
            ).astype(np.uint8)

            # Create RGBA image with proper transparency
            h, w = rescaled.shape
            rgba = np.zeros((h, w, 4), dtype=np.uint8)

            # Apply colormap to get RGB values
            colormap = _get_feature_cmap(cfg["colormap"])
            for idx, color in colormap.items():
                color_mask = (rescaled == idx)
                rgba[color_mask, 0] = color[0]  # R
                rgba[color_mask, 1] = color[1]  # G
                rgba[color_mask, 2] = color[2]  # B

            # Set alpha from mask - robust: any mask > 0 becomes fully opaque
            alpha = (mask > 0).astype(np.uint8) * 255
            rgba[:, :, 3] = alpha

            # Clip to Pakistan boundary at tile resolution
            rgba = _clip_tile_alpha(rgba, x, y, z)

            # Convert to PNG
            img = Image.fromarray(rgba, mode='RGBA')
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return tile_response(buffer.getvalue())

    except HTTPException:
        raise
    except Exception as e:
        # Return empty tile instead of 500 for any error
        logger.warning(f"Feature tile error for {feature}/{feat_date}/{z}/{x}/{y}: {e}")
        try:
            from PIL import Image
            import io
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return Response(
                content=buf.getvalue(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"}
            )
        except:
            raise HTTPException(status_code=500, detail="Tile generation failed")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get(
    "/tiles/features/{feature}/{feat_date}/point",
    summary="Get feature value at point",
    description="Returns feature value at a specific lat/lon coordinate."
)
async def get_feature_point_value(
    feature: str,
    feat_date: str,
    lat: float = Query(..., ge=20.0, le=40.0, description="Latitude"),
    lon: float = Query(..., ge=60.0, le=80.0, description="Longitude"),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """Query feature value at a specific coordinate."""
    import os
    import math

    if feature not in FEATURE_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    cfg = FEATURE_CONFIG[feature]
    Reader, _ = _require_rio_tiler()
    features_bucket = _get_features_bucket()

    # Path in features bucket: cog/{feature}/date={date}/{feature}.tif
    blob_path = f"cog/{feature}/date={feat_date}/{feature}.tif"
    tmp_path = _download_cog_to_temp(features_bucket, blob_path)

    try:
        with Reader(tmp_path) as src:
            point_data = src.point(lon, lat, indexes=1)
            value = point_data.data[0] if point_data.data is not None else None

            if value is not None and (value < -9000 or not math.isfinite(value)):
                value = None

            return {
                "date": feat_date,
                "feature": feature,
                "lat": lat,
                "lon": lon,
                "value": round(float(value), 6) if value is not None else None,
                "unit": cfg["unit"],
                "colorscale": {
                    "vmin": cfg["vmin"],
                    "vmax": cfg["vmax"],
                    "colormap": cfg["colormap"],
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "outside" in error_msg.lower() or "bounds" in error_msg.lower():
            raise HTTPException(status_code=400, detail=f"Coordinates ({lat}, {lon}) outside bounds")
        logger.error(f"Feature point query error for {feature}/{feat_date} at ({lat}, {lon}): {e}")
        raise HTTPException(status_code=500, detail=f"Point query failed: {error_msg}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


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
    reference_date: Optional[str] = Query(
        None,
        description="Reference date for waterline calculation (YYYY-MM-DD). For retrain job only.",
        regex=r"^\d{4}-\d{2}-\d{2}$"
    ),
    date: Optional[str] = Query(
        None,
        description="Date to process (YYYY-MM-DD). For daily pipeline only.",
        regex=r"^\d{4}-\d{2}-\d{2}$"
    ),
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Trigger a Cloud Run pipeline job.

    Args:
        which: Job type - "daily" for daily estimation pipeline, "retrain" for model retraining
        reference_date: Reference date for waterline calculation (retrain only, YYYY-MM-DD)
        date: Date to process (daily pipeline only, YYYY-MM-DD)
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

    # Build request body with overrides if parameters provided
    # Cloud Run Jobs API: https://cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs/run
    request_body: Dict[str, Any] = {}

    if which == "retrain" and reference_date:
        # Override args for retrain job to pass reference_date
        request_body["overrides"] = {
            "containerOverrides": [{
                "args": ["retrain_job.py", "--reference_date", reference_date]
            }]
        }
        logger.info(f"Retrain job will use reference_date: {reference_date}")
    elif which == "daily" and date:
        # Override args for daily pipeline to pass date
        request_body["overrides"] = {
            "containerOverrides": [{
                "args": ["--date", date]
            }]
        }
        logger.info(f"Daily pipeline will use date: {date}")

    try:
        sess = _cloudrun_session()
        resp = sess.post(url, json=request_body)

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
