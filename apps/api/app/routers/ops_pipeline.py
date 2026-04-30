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
import secrets
import threading
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


# In-process cache for COG temp files. Keyed by "bucket/blob_path".
# Avoids re-downloading the same COG on every tile request within a container lifetime.
_COG_FILE_CACHE: Dict[str, str] = {}
_COG_FILE_CACHE_LOCK = threading.Lock()
_COG_ABSENT: set = set()  # blob paths known to not exist — skips repeated GCS checks


def _get_or_download_cog(bucket_name: str, blob_path: str) -> str:
    """Return cached temp file path for COG, downloading once per process if needed.
    Raises HTTPException(404) for missing blobs and caches that result too."""
    cache_key = f"{bucket_name}/{blob_path}"
    if cache_key in _COG_ABSENT:
        raise HTTPException(status_code=404, detail=f"COG not found: gs://{cache_key}")
    if cache_key in _COG_FILE_CACHE:
        return _COG_FILE_CACHE[cache_key]
    with _COG_FILE_CACHE_LOCK:
        if cache_key in _COG_ABSENT:
            raise HTTPException(status_code=404, detail=f"COG not found: gs://{cache_key}")
        if cache_key in _COG_FILE_CACHE:
            return _COG_FILE_CACHE[cache_key]
        try:
            path = _download_cog_to_temp(bucket_name, blob_path)
            _COG_FILE_CACHE[cache_key] = path
            logger.info(f"COG cached: gs://{bucket_name}/{blob_path} → {path}")
            return path
        except HTTPException as e:
            if e.status_code == 404:
                _COG_ABSENT.add(cache_key)
            raise


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
    model: str = Query("backbone", description="Model variant: 'backbone', 'support_aware', or 'urban/{city}'"),
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
    from starlette.concurrency import run_in_threadpool

    Reader, _ = _require_rio_tiler()
    outputs_bucket = _get_outputs_bucket()

    # Resolve blob path (and optional backbone fallback for support_aware dates)
    suffix = "_smoothed" if smoothed else ""
    fallback_blob_path = None
    if model == "population":
        blob_path = "static/pak_pop_2025_100m.tif"
    elif model.startswith("urban/"):
        city_key = model.split("/", 1)[1]
        blob_path = f"predictions/urban/date={pred_date}/{city_key}{suffix}.tif"
    elif model == "support_aware":
        gs_suffix = "_gaussian_smoothed" if smoothed else ""
        blob_path = f"predictions/support_aware/date={pred_date}/pm25_{pred_date}{gs_suffix}.tif"
        # Fallback: if support_aware COG absent for this date, serve backbone instead.
        # Older dates only have backbone; support_aware was introduced later.
        fallback_blob_path = f"predictions/date={pred_date}/pm25_{pred_date}{gs_suffix}.tif"
    else:
        gs_suffix = "_gaussian_smoothed" if smoothed else ""
        blob_path = f"predictions/date={pred_date}/pm25_{pred_date}{gs_suffix}.tif"

    # Use cached temp file; download only once per container lifetime per COG.
    # If support_aware COG is absent, fall back to backbone automatically.
    try:
        tmp_path = await run_in_threadpool(_get_or_download_cog, outputs_bucket, blob_path)
    except HTTPException as e:
        if e.status_code == 404 and fallback_blob_path:
            tmp_path = await run_in_threadpool(_get_or_download_cog, outputs_bucket, fallback_blob_path)
        else:
            raise

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

    etag = f'"{pred_date}-{model}-{"s" if smoothed else "n"}-{z}-{x}-{y}"'
    cache_headers = {
        "Cache-Control": "public, max-age=86400, s-maxage=604800, stale-while-revalidate=86400, immutable",
        "ETag": etag,
        "X-Tile-Date": pred_date,
    }

    def tile_response(png_bytes):
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers=cache_headers,
        )

    def _render_tile_to_png() -> bytes:
        """Render COG tile to PNG bytes. Runs in threadpool (blocking I/O + CPU)."""
        with Reader(tmp_path) as src:
            try:
                tile = src.tile(x, y, z, indexes=1, resampling_method="cubic")
            except TileOutsideBounds:
                return empty_tile_png()

            data = tile.data[0].astype(np.float32)
            mask = tile.mask

            if mask is None or np.max(mask) == 0:
                return empty_tile_png()

            if model == "population":
                pop_data = np.where(data > 0, np.log1p(data), 0)
                vmin_pop, vmax_pop = 0, np.log1p(500)
                rescaled = np.clip(
                    (pop_data - vmin_pop) / (vmax_pop - vmin_pop) * 255,
                    0, 255
                ).astype(np.uint8)
            else:
                vmin = 5.0 if model.startswith("urban/") else PM25_VMIN
                vmax = 80.0 if model.startswith("urban/") else PM25_VMAX
                rescaled = np.clip(
                    (data - vmin) / (vmax - vmin) * 255,
                    0, 255
                ).astype(np.uint8)

            h, w = rescaled.shape
            rgba = np.zeros((h, w, 4), dtype=np.uint8)

            cmap = TURBO_CMAP
            if model == "population":
                try:
                    import matplotlib.cm as mplcm
                    inferno = mplcm.get_cmap('inferno')
                    cmap = {}
                    for i in range(256):
                        r, g, b, _ = inferno(i / 255.0)
                        cmap[i] = (int(r * 255), int(g * 255), int(b * 255))
                except ImportError:
                    pass

            for idx, color in cmap.items():
                color_mask = (rescaled == idx)
                rgba[color_mask, 0] = color[0]
                rgba[color_mask, 1] = color[1]
                rgba[color_mask, 2] = color[2]

            alpha = (mask > 0).astype(np.uint8) * 255
            rgba[:, :, 3] = alpha
            rgba = _clip_tile_alpha(rgba, x, y, z)

            if model.startswith("urban/") and z >= 12:
                import math
                n = 2 ** z
                lon_min = x / n * 360.0 - 180.0
                lon_max = (x + 1) / n * 360.0 - 180.0
                lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
                lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
                cell = 0.01
                ga = 50 if z < 14 else 80

                lon = math.ceil(lon_min / cell) * cell
                while lon < lon_max:
                    px = int((lon - lon_min) / (lon_max - lon_min) * w)
                    if 0 <= px < w:
                        m = rgba[:, px, 3] > 0
                        rgba[m, px, 0] = 255
                        rgba[m, px, 1] = 255
                        rgba[m, px, 2] = 255
                        rgba[m, px, 3] = ga
                    lon += cell

                lat = math.ceil(lat_min / cell) * cell
                while lat < lat_max:
                    py = int((lat_max - lat) / (lat_max - lat_min) * h)
                    if 0 <= py < h:
                        m = rgba[py, :, 3] > 0
                        rgba[py, m, 0] = 255
                        rgba[py, m, 1] = 255
                        rgba[py, m, 2] = 255
                        rgba[py, m, 3] = ga
                    lat += cell

            img = Image.fromarray(rgba, mode='RGBA')
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return buffer.getvalue()

    try:
        png_bytes = await run_in_threadpool(_render_tile_to_png)
        return tile_response(png_bytes)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Tile error for {pred_date}/{z}/{x}/{y}: {e}")
        try:
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return Response(
                content=buf.getvalue(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400, s-maxage=604800, immutable"},
            )
        except Exception:
            raise HTTPException(status_code=500, detail="Tile generation failed")


@router.get(
    "/tiles/{pred_date}/tilejson",
    summary="Get TileJSON for prediction",
    description="Returns TileJSON metadata for MapLibre tile source."
)
async def get_prediction_tilejson(
    pred_date: str,
    request: Request,
    model: str = Query("backbone", description="Model variant"),
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
    model: str = Query("backbone", description="Model variant: 'backbone' or 'support_aware'"),
) -> Dict[str, Any]:
    """List available COG prediction dates for tile serving."""
    backbone_dates = set(_gcs_list_cog_dates(limit=limit))

    # Always include support_aware dates so the timeline shows all available dates
    # regardless of which model toggle is active
    try:
        client = _gcs_client()
        bucket_name = _get_outputs_bucket()
        bucket = client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix="predictions/support_aware/date=")
        sa_dates = set()
        for blob in blobs:
            if blob.name.endswith(".tif"):
                try:
                    d = blob.name.split("support_aware/date=")[1].split("/")[0]
                    sa_dates.add(d)
                except Exception:
                    continue
        all_dates = sorted(backbone_dates | sa_dates)
    except Exception as e:
        logger.warning(f"Failed to list support_aware dates: {e}")
        all_dates = sorted(backbone_dates)

    dates = all_dates[-limit:]
    return {
        "dates": dates,
        "count": len(dates),
        "tile_url_template": "/api/v1/ops/pipeline/tiles/{date}/{z}/{x}/{y}.png",
        "tilejson_url_template": "/api/v1/ops/pipeline/tiles/{date}/tilejson"
    }


@router.get(
    "/tiles/{pred_date}/urban/{city_key}.json",
    summary="Get urban 1km grid data",
    description="Returns the full 1km PM2.5 grid for a city as JSON."
)
async def get_urban_grid_json(
    pred_date: str,
    city_key: str,
) -> Dict[str, Any]:
    """Serve the urban prediction JSON for client-side hover lookup."""
    import json as _json
    import tempfile

    valid_cities = {'lahore', 'isb_rwp', 'peshawar', 'karachi'}
    if city_key not in valid_cities:
        raise HTTPException(status_code=404, detail=f"Unknown city: {city_key}")

    bucket_name = _get_outputs_bucket()
    blob_path = f"predictions/urban/date={pred_date}/{city_key}.json"

    try:
        client = _gcs_client()
        blob = client.bucket(bucket_name).blob(blob_path)
        if not blob.exists(client):
            raise HTTPException(status_code=404, detail=f"No urban data for {city_key} on {pred_date}")

        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        blob.download_to_filename(tmp.name)
        with open(tmp.name) as f:
            data = _json.load(f)
        import os
        os.unlink(tmp.name)

        # Return grid info + values + population
        return {
            "city": city_key,
            "date": pred_date,
            "grid": data.get("grid", {}),
            "stats": data.get("stats", {}),
            "lats": data.get("lats", []),
            "lons": data.get("lons", []),
            "pm25": data.get("pm25", []),
            "population": data.get("population", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load urban grid for {city_key}/{pred_date}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    model: str = Query("backbone", description="Model variant: 'backbone', 'support_aware', or 'urban/{city}'"),
    _: bool = Depends(verify_tasks_token),
) -> Dict[str, Any]:
    """
    Query PM2.5 prediction value at a specific coordinate.

    Args:
        pred_date: Date in YYYY-MM-DD format
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        smoothed: If True, query from the Gaussian-smoothed COG
        model: Model variant to query
    """
    import os
    import math

    Reader, _ = _require_rio_tiler()
    outputs_bucket = _get_outputs_bucket()

    # Download COG to temp file
    if model.startswith("urban/"):
        city_key = model.split("/", 1)[1]
        suffix = "_smoothed" if smoothed else ""
        blob_path = f"predictions/urban/date={pred_date}/{city_key}{suffix}.tif"
    elif model == "support_aware":
        suffix = "_gaussian_smoothed" if smoothed else ""
        blob_path = f"predictions/support_aware/date={pred_date}/pm25_{pred_date}{suffix}.tif"
    else:
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


# =============================================================================
# STATION DAILY OBSERVATIONS (QA-filtered, same as model training labels)
# =============================================================================

@router.get(
    "/stations/daily/{obs_date}",
    summary="Get QA-filtered station daily PM2.5 for a date",
    description=(
        "Returns daily average PM2.5 per station from the pre-aggregated "
        "station_daily parquets — the same labels used for model training. "
        "Includes QA filtering (spike removal, flatline, min-hours threshold)."
    ),
)
async def get_station_daily_observations(
    obs_date: str,
    min_hours: int = Query(6, ge=1, le=24, description="Minimum valid hours to include a station"),
    country: Optional[str] = Query(None, description="Filter to a country (e.g. 'Pakistan') using exact boundary polygon"),
) -> Any:
    """Serve QA-filtered station daily means. Uses pre-computed JSON (fast) with parquet fallback."""
    from fastapi.responses import JSONResponse

    bucket_name = "paqi-raw-hawanama-data"
    filter_pakistan = country and country.lower() == "pakistan"

    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        # ── Fast path: pre-computed stations.json ──
        json_path = f"raw/station_daily/date={obs_date}/stations.json"
        json_blob = bucket.blob(json_path)
        if json_blob.exists(client):
            data = json.loads(json_blob.download_as_text())
            # Apply min_hours filter if stricter than default (6)
            if min_hours > 6:
                data["stations"] = [
                    s for s in data["stations"]
                    if (s.get("valid_hours") or 0) >= min_hours
                ]
            # Apply country filter
            if filter_pakistan:
                data["stations"] = [
                    s for s in data["stations"]
                    if _point_in_pakistan(s.get("lat") or 0, s.get("lon") or 0)
                ]
            data["count"] = len(data["stations"])
            return JSONResponse(
                content=data,
                headers={"Cache-Control": "public, max-age=86400"},
            )

        # ── Slow fallback: parse parquets ──
        import tempfile
        import os
        import shutil

        prefix = f"raw/station_daily/date={obs_date}"
        blobs = list(bucket.list_blobs(prefix=prefix))
        parquet_blobs = [b for b in blobs if b.name.endswith(".parquet")]

        if not parquet_blobs:
            raise HTTPException(status_code=404, detail=f"No station daily data for {obs_date}")

        import pandas as pd
        tmp_dir = tempfile.mkdtemp()
        try:
            dfs = []
            for blob in parquet_blobs:
                tmp_path = os.path.join(tmp_dir, os.path.basename(blob.name))
                blob.download_to_filename(tmp_path)
                dfs.append(pd.read_parquet(tmp_path))

            df = pd.concat(dfs, ignore_index=True)

            # Apply country filter (parquets have country_name column)
            if filter_pakistan:
                if "country_name" in df.columns:
                    df = df[df["country_name"].str.lower() == "pakistan"]
                else:
                    # Fallback to boundary polygon if no country column
                    df = df[df.apply(
                        lambda r: _point_in_pakistan(
                            float(r.get("latitude") or r.get("lat") or 0),
                            float(r.get("longitude") or r.get("lon") or 0),
                        ), axis=1
                    )]

            hours_col = "pm25_ugm3_valid_hours" if "pm25_ugm3_valid_hours" in df.columns else None
            if hours_col:
                df = df[df[hours_col] >= min_hours]

            pm25_col = "pm25_ugm3_mean" if "pm25_ugm3_mean" in df.columns else "pm25_daily_mean"
            lat_col = next((c for c in ["latitude", "lat"] if c in df.columns), None)
            lon_col = next((c for c in ["longitude", "lon"] if c in df.columns), None)

            if pm25_col not in df.columns or lat_col is None or lon_col is None:
                raise HTTPException(status_code=500, detail="Unexpected parquet schema")

            df = df.dropna(subset=[pm25_col, lat_col, lon_col])

            stations = []
            for _, row in df.iterrows():
                stations.append({
                    "station_id": str(row.get("station_id", "")).strip(),
                    "name": str(row.get("station_name", "")),
                    "city": str(row.get("city_name", "")),
                    "lat": round(float(row[lat_col]), 5),
                    "lon": round(float(row[lon_col]), 5),
                    "pm25": round(float(row[pm25_col]), 1),
                    "valid_hours": int(row[hours_col]) if hours_col and pd.notna(row.get(hours_col)) else None,
                    "complete": bool(row.get("pm25_ugm3_complete", 0)),
                })

            return {
                "date": obs_date,
                "stations": stations,
                "count": len(stations),
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load station daily for {obs_date}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DAILY BRIEF GENERATION (LLM-powered, GCS-cached)
# =============================================================================

FORECASTS_BUCKET = settings.OPS_FORECASTS_BUCKET or "paqi-forecasts-hawanama-data"
RAW_DATA_BUCKET = "paqi-raw-hawanama-data"

_BRIEF_PROMPT_TEMPLATE = """\
You are an air quality analyst writing the daily operational brief for Pakistan on {date}.

## DATA

### Station Observations
- {station_count} stations reporting
- National mean PM2.5: {obs_mean} µg/m³
- National max PM2.5: {obs_max} µg/m³
- Band breakdown: {band_breakdown}
- Stations exceeding unhealthy thresholds (>75 µg/m³): {unhealthy_count} ({unhealthy_pct}%)

### Most Polluted Cities (by daily mean)
{worst_cities}

### Satellite Model (backbone — AOD + meteorology only)
- Data track: {data_track}
- Predicted national mean: {pred_mean}
- Grid coverage: {coverage}
- Model bias (predicted − observed): {bias}

### Enhanced Model (support-aware — incorporates station PM2.5 lags)
- Predicted national mean: {enhanced_mean}
- Model bias (predicted − observed): {enhanced_bias}

### Fire Activity
{fires_text}

## INSTRUCTIONS

Write a 3–4 sentence narrative brief covering:
1. Overall conditions and national average, how many stations reported
2. How many stations exceeded unhealthy thresholds and which city was worst
3. Fire activity if present and noteworthy
4. Model performance: compare both satellite and enhanced model bias if available

Be precise with numbers. Use µg/m³ units. Do not hedge when data is present. \
If a data section says "unavailable", skip it — do not mention its absence. \
Keep the tone professional and concise, like an analyst shift handoff note.\
"""


def _date_to_compact(date_str: str) -> str:
    """Convert YYYY-MM-DD to YYYYMMDD."""
    return date_str.replace("-", "")


# ── Pakistan boundary — shared utility ──
from app.services.geo_utils import point_in_pakistan as _point_in_pakistan


def _compute_tif_stats(bucket_name: str, blob_path: str) -> Optional[Dict[str, float]]:
    """Download a COG and compute basic stats (mean, n_valid). Returns None on failure."""
    import tempfile
    try:
        client = _gcs_client()
        blob = client.bucket(bucket_name).blob(blob_path)
        if not blob.exists(client):
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
        blob.download_to_filename(tmp.name)
        try:
            import numpy as np
            import rasterio
            with rasterio.open(tmp.name) as ds:
                data = ds.read(1)
                nodata = ds.nodata
                if nodata is not None:
                    valid = data[(data != nodata) & np.isfinite(data)]
                else:
                    valid = data[np.isfinite(data)]
                if len(valid) == 0:
                    return None
                return {
                    "mean": float(np.mean(valid)),
                    "n_valid": int(len(valid)),
                    "n_total": int(data.size),
                }
        finally:
            _os.unlink(tmp.name)
    except Exception as e:
        logger.warning(f"Failed to compute TIF stats for {blob_path}: {e}")
        return None


def _load_forecasts_json_safe(blob_path: str) -> Optional[Dict[str, Any]]:
    """Load JSON from the forecasts bucket, returning None on failure."""
    try:
        client = _gcs_client()
        blob = client.bucket(FORECASTS_BUCKET).blob(blob_path)
        if not blob.exists(client):
            return None
        return json.loads(blob.download_as_text())
    except Exception:
        return None


def _load_forecasts_text_safe(blob_path: str) -> Optional[str]:
    """Load raw text from the forecasts bucket, returning None on failure."""
    try:
        client = _gcs_client()
        blob = client.bucket(FORECASTS_BUCKET).blob(blob_path)
        if not blob.exists(client):
            return None
        return blob.download_as_text()
    except Exception:
        return None


def _get_band(pm25: float) -> str:
    if pm25 <= 35:
        return "good"
    if pm25 <= 75:
        return "moderate"
    if pm25 <= 150:
        return "unhealthy"
    if pm25 <= 250:
        return "very_unhealthy"
    return "severe"


def _build_brief_context(
    stations: List[Dict],
    pred_stats: Optional[Dict],
    enhanced_stats: Optional[Dict],
    fires_csv: Optional[str],
) -> Dict[str, str]:
    """Build template variables from raw data sources."""

    # ── Station observations ──
    valid = [s for s in stations if s.get("pm25") is not None]
    station_count = len(valid)
    if valid:
        values = [s["pm25"] for s in valid]
        obs_mean = round(sum(values) / len(values), 1)
        obs_max = round(max(values), 1)
        bands = {"good": 0, "moderate": 0, "unhealthy": 0, "very_unhealthy": 0, "severe": 0}
        for v in values:
            bands[_get_band(v)] += 1
        band_breakdown = ", ".join(f"{cnt} {band.replace('_', ' ')}" for band, cnt in bands.items() if cnt)
        unhealthy_count = bands["unhealthy"] + bands["very_unhealthy"] + bands["severe"]
        unhealthy_pct = round(unhealthy_count / station_count * 100)

        # Worst cities
        city_map: Dict[str, List[float]] = {}
        for s in valid:
            city = s.get("city")
            if city:
                city_map.setdefault(city, []).append(s["pm25"])
        worst = sorted(
            [{"city": c, "avg": round(sum(v) / len(v), 1), "n": len(v)} for c, v in city_map.items()],
            key=lambda x: -x["avg"],
        )[:5]
        worst_cities = "\n".join(f"- {w['city']}: {w['avg']} µg/m³ ({w['n']} stations)" for w in worst) or "No city data"
    else:
        obs_mean = obs_max = "unavailable"
        band_breakdown = "unavailable"
        unhealthy_count = unhealthy_pct = 0
        worst_cities = "No station observations available"

    # ── Prediction stats ──
    if pred_stats and pred_stats.get("mean") is not None:
        track = pred_stats.get("data_track", "unknown")
        data_track = "NRT (near-real-time)" if track == "nrt" else "Final (reanalysis)" if track == "final" else track
        pred_mean = f"{round(pred_stats['mean'], 1)} µg/m³"
        n_valid = pred_stats.get("n_valid", 0)
        n_total = pred_stats.get("n_total", 0)
        coverage = f"{round(n_valid / n_total * 100)}%" if n_total else "unavailable"
        if isinstance(obs_mean, (int, float)):
            bias_val = round(pred_stats["mean"] - obs_mean, 1)
            bias = f"{'+' if bias_val > 0 else ''}{bias_val} µg/m³"
        else:
            bias = "unavailable (no observations)"
    else:
        pred_mean = coverage = bias = "unavailable"
        data_track = "unavailable"

    # ── Enhanced (support_aware) model stats ──
    if enhanced_stats and enhanced_stats.get("mean") is not None:
        enhanced_mean = f"{round(enhanced_stats['mean'], 1)} µg/m³"
        if isinstance(obs_mean, (int, float)):
            e_bias_val = round(enhanced_stats["mean"] - obs_mean, 1)
            enhanced_bias = f"{'+' if e_bias_val > 0 else ''}{e_bias_val} µg/m³"
        else:
            enhanced_bias = "unavailable (no observations)"
    else:
        enhanced_mean = enhanced_bias = "unavailable"

    # ── FIRMS fires (Pakistan only — exact boundary) ──
    if fires_csv and fires_csv.strip():
        import csv
        import io
        reader = csv.DictReader(io.StringIO(fires_csv))
        fire_rows = [
            r for r in reader
            if _point_in_pakistan(float(r.get("latitude", 0)), float(r.get("longitude", 0)))
        ]
        fire_count = len(fire_rows)
        if fire_count > 0:
            high_conf = sum(1 for r in fire_rows if r.get("confidence", "").lower() in ("high", "h"))
            fires_text = f"{fire_count} VIIRS fire detections in Pakistan ({high_conf} high-confidence)."
        else:
            fires_text = "No fire detections in Pakistan."
    else:
        fires_text = "FIRMS fire data unavailable for this date."

    return {
        "station_count": str(station_count),
        "obs_mean": str(obs_mean),
        "obs_max": str(obs_max),
        "band_breakdown": band_breakdown if isinstance(band_breakdown, str) else "unavailable",
        "unhealthy_count": str(unhealthy_count),
        "unhealthy_pct": str(unhealthy_pct),
        "worst_cities": worst_cities,
        "data_track": data_track,
        "pred_mean": str(pred_mean),
        "coverage": str(coverage),
        "bias": str(bias),
        "enhanced_mean": str(enhanced_mean),
        "enhanced_bias": str(enhanced_bias),
        "fires_text": fires_text,
    }


async def _generate_brief_llm(date: str, context: Dict[str, str]) -> str:
    """Call Gemini to generate the narrative brief."""
    import google.generativeai as genai

    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=501, detail="GEMINI_API_KEY not configured")

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = _BRIEF_PROMPT_TEMPLATE.format(date=date, **context)

    response = model.generate_content(prompt)
    if not response.text:
        raise HTTPException(status_code=502, detail="Empty response from Gemini")

    return response.text.strip()


def _has_valid_tasks_token(authorization: str) -> bool:
    """Check bearer token without raising — used for optional auth inside handlers."""
    if not authorization.lower().startswith("bearer "):
        return False
    token = authorization[7:]
    if not settings.TASKS_API_SECRET:
        return False
    return secrets.compare_digest(token, settings.TASKS_API_SECRET)


@router.get(
    "/briefs/{date}",
    summary="Get daily operational brief for a date",
    description=(
        "Returns an LLM-generated narrative brief for a given prediction date. "
        "Cached briefs are publicly readable. Generation requires authorization."
    ),
)
async def get_daily_brief(
    date: str,
    request: Request,
    regenerate: bool = Query(False, description="Force regeneration even if cached"),
) -> Dict[str, Any]:
    """
    Get or generate the daily operational brief.

    Public: returns cached brief (or 404 if not yet generated).
    Authorized: can also trigger regeneration via ?regenerate=true.

    1. Check GCS cache (outputs bucket → briefs/ops_{date}.json)
    2. If cached and not regenerating, return immediately (publicly)
    3. Otherwise require auth — gather data, call Gemini, cache, return
    """
    from fastapi.responses import JSONResponse as _JSONResponse
    outputs_bucket = _get_outputs_bucket()
    cache_path = f"briefs/ops_{date}.json"

    # ── 1. Check cache ──
    if not regenerate:
        try:
            cached = _gcs_read_json(outputs_bucket, cache_path)
            return _JSONResponse(
                content=cached,
                headers={"Cache-Control": "public, max-age=300, s-maxage=86400, stale-while-revalidate=86400"},
            )
        except HTTPException as e:
            if e.status_code != 404:
                raise
            # Not cached yet — fall through to generation

    # Cache miss or forced regen — require auth to invoke LLM
    auth_header = request.headers.get("authorization", "")
    if not _has_valid_tasks_token(auth_header):
        raise HTTPException(status_code=404, detail="Brief not yet generated for this date")

    return await _generate_and_cache_brief(date, outputs_bucket)


async def _generate_and_cache_brief(date: str, outputs_bucket: str) -> Dict[str, Any]:
    """Gather data, call Gemini, write to GCS, and return the brief dict."""
    from datetime import datetime, timedelta

    # ── Gather station observations ──
    stations: List[Dict] = []
    try:
        client = _gcs_client()
        bucket = client.bucket(RAW_DATA_BUCKET)

        json_path = f"raw/station_daily/date={date}/stations.json"
        json_blob = bucket.blob(json_path)
        if json_blob.exists(client):
            data = json.loads(json_blob.download_as_text())
            all_stations = data.get("stations", [])
            stations = [s for s in all_stations
                        if _point_in_pakistan(s.get("lat") or 0, s.get("lon") or 0)]
        else:
            prefix = f"raw/station_daily/date={date}"
            blobs = list(bucket.list_blobs(prefix=prefix))
            parquet_blobs = [b for b in blobs if b.name.endswith(".parquet")]
            if parquet_blobs:
                import tempfile, os, shutil
                import pandas as pd
                tmp_dir = tempfile.mkdtemp()
                try:
                    dfs = []
                    for blob in parquet_blobs:
                        tmp_path = os.path.join(tmp_dir, os.path.basename(blob.name))
                        blob.download_to_filename(tmp_path)
                        dfs.append(pd.read_parquet(tmp_path))
                    df = pd.concat(dfs, ignore_index=True)
                    if "country_name" in df.columns:
                        df = df[df["country_name"].str.lower() == "pakistan"]
                    pm25_col = "pm25_ugm3_mean" if "pm25_ugm3_mean" in df.columns else "pm25_daily_mean"
                    lat_col = next((c for c in ["latitude", "lat"] if c in df.columns), None)
                    lon_col = next((c for c in ["longitude", "lon"] if c in df.columns), None)
                    if pm25_col in df.columns and lat_col and lon_col:
                        df = df.dropna(subset=[pm25_col, lat_col, lon_col])
                        for _, row in df.iterrows():
                            stations.append({
                                "name": str(row.get("station_name", "")),
                                "city": str(row.get("city_name", "")),
                                "pm25": round(float(row[pm25_col]), 1),
                                "lat": round(float(row[lat_col]), 5),
                                "lon": round(float(row[lon_col]), 5),
                            })
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Brief: failed to load stations for {date}: {e}")

    # ── Prediction stats (backbone) ──
    pred_stats: Optional[Dict] = None
    try:
        pred_data = _gcs_read_json(outputs_bucket, f"predictions/date={date}/pm25_{date}.json")
        pred_stats = pred_data.get("stats")
        if pred_stats is not None and pred_data.get("data_track"):
            pred_stats["data_track"] = pred_data["data_track"]
    except Exception:
        pass

    # ── Enhanced (support_aware) model stats ──
    enhanced_stats: Optional[Dict] = _compute_tif_stats(
        outputs_bucket,
        f"predictions/support_aware/date={date}/pm25_{date}.tif",
    )

    # ── FIRMS fire detections ──
    fires_csv: Optional[str] = None
    for offset in range(3):
        d = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=offset)
        trial_ds = d.strftime("%Y%m%d")
        fires_csv = _load_forecasts_text_safe(f"hindcast/firms/firms_{trial_ds}.csv")
        if fires_csv and fires_csv.strip():
            break

    # ── Generate ──
    context = _build_brief_context(stations, pred_stats, enhanced_stats, fires_csv)
    narrative = await _generate_brief_llm(date, context)

    result = {
        "date": date,
        "narrative": narrative,
        "station_count": int(context["station_count"]),
        "obs_mean": float(context["obs_mean"]) if context["obs_mean"] != "unavailable" else None,
        "data_sources": {
            "stations": len(stations) > 0,
            "predictions": pred_stats is not None,
            "fires": fires_csv is not None and bool(fires_csv.strip()),
        },
    }

    # ── Cache to GCS ──
    cache_path = f"briefs/ops_{date}.json"
    try:
        client = _gcs_client()
        blob = client.bucket(outputs_bucket).blob(cache_path)
        blob.upload_from_string(
            json.dumps(result, ensure_ascii=False),
            content_type="application/json",
        )
        logger.info(f"Cached brief for {date} at gs://{outputs_bucket}/{cache_path}")
    except Exception as e:
        logger.warning(f"Failed to cache brief for {date}: {e}")

    return result


@router.post(
    "/generate-briefs",
    summary="Generate daily briefs for recent dates",
    description=(
        "Scans the last `days_back` prediction dates, generates a brief for any that "
        "are missing a cached GCS entry, and returns a summary. Called nightly by Cloud "
        "Scheduler and can be used for historical backfill with a larger days_back value."
    ),
)
async def generate_briefs_batch(
    days_back: int = Query(7, ge=1, le=730, description="Number of recent dates to check"),
    _: bool = Depends(verify_tasks_token),
) -> Dict[str, Any]:
    """Generate missing briefs for the most recent `days_back` prediction dates."""
    outputs_bucket = _get_outputs_bucket()

    all_dates = _gcs_list_cog_dates(limit=days_back + 10)
    target_dates = all_dates[-days_back:]

    generated: List[str] = []
    skipped: List[str] = []
    errors: List[Dict[str, str]] = []

    for date in target_dates:
        cache_path = f"briefs/ops_{date}.json"
        # Skip dates that already have a cached brief
        try:
            _gcs_read_json(outputs_bucket, cache_path)
            skipped.append(date)
            continue
        except HTTPException as e:
            if e.status_code != 404:
                errors.append({"date": date, "error": f"Cache read failed: {e.detail}"})
                continue
        except Exception as e:
            errors.append({"date": date, "error": f"Cache check error: {e}"})
            continue

        # Generate
        try:
            await _generate_and_cache_brief(date, outputs_bucket)
            generated.append(date)
            logger.info(f"Batch brief generation: generated {date}")
        except Exception as e:
            logger.warning(f"Batch brief generation: failed for {date}: {e}")
            errors.append({"date": date, "error": str(e)})

    logger.info(
        f"Batch brief generation complete: {len(generated)} generated, "
        f"{len(skipped)} skipped, {len(errors)} errors"
    )
    return {
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "summary": {
            "generated_count": len(generated),
            "skipped_count": len(skipped),
            "error_count": len(errors),
        },
    }
