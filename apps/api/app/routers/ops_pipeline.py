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


def _find_model_results_file(bucket_name: str, waterline: str) -> Optional[str]:
    """
    Find the results JSON file for a given waterline.

    Results files are named like: operational_results_W20250713_20260122_172806.json
    We match by waterline (W{date}) and return the most recent one.
    """
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        # List all results files
        waterline_compact = waterline.replace("-", "")
        prefix = f"models/operational/results/operational_results_W{waterline_compact}_"

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
    bucket = _get_derived_bucket()

    # First get the model pointer to find the waterline
    try:
        model_ptr = _gcs_read_json(bucket, "models/operational/latest.json")
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="No model pointer found")
        raise

    waterline = model_ptr.get("waterline")
    if not waterline:
        raise HTTPException(status_code=404, detail="Model pointer missing waterline")

    # Find the results file
    results_path = _find_model_results_file(bucket, waterline)
    if not results_path:
        raise HTTPException(
            status_code=404,
            detail=f"Model results not found for waterline {waterline}"
        )

    # Read and return the results
    results = _gcs_read_json(bucket, results_path)

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


def _gcs_list_model_history(bucket_name: str, limit: int = 30) -> List[str]:
    """
    List model history entries like models/history/ref_YYYYMMDD.json.
    Returns reference dates (sorted, most recent last).
    """
    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)

        blobs = bucket.list_blobs(prefix="models/history/ref_")

        dates = []
        for blob in blobs:
            # blob.name: models/history/ref_20250101.json
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
    bucket = _get_derived_bucket()
    dates = _gcs_list_model_history(bucket, limit=limit)
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
    bucket = _get_derived_bucket()

    # Convert YYYY-MM-DD to YYYYMMDD for the filename
    date_compact = reference_date.replace("-", "")
    blob_path = f"models/history/ref_{date_compact}.json"

    try:
        results = _gcs_read_json(bucket, blob_path)
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


def _gcs_list_prediction_dates(bucket_name: str, limit: int = 30) -> List[str]:
    """
    List prediction date prefixes like predictions/date=YYYY-MM-DD/.
    """
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
    bucket = _get_derived_bucket()
    dates = _gcs_list_prediction_dates(bucket, limit=limit)
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
    bucket = _get_derived_bucket()

    # Try JSON format first (new format with grid data)
    try:
        return _gcs_read_json(bucket, f"predictions/date={pred_date}/pm25_{pred_date}.json")
    except HTTPException as e:
        if e.status_code != 404:
            raise

    # Fallback: check if GeoTIFF exists (older predictions)
    try:
        client = _gcs_client()
        tif_blob = client.bucket(bucket).blob(f"predictions/date={pred_date}/pm25_{pred_date}.tif")
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


def _turbo_colormap() -> Dict[int, tuple]:
    """
    Generate turbo colormap for PM2.5 visualization.
    Maps 0-255 grayscale to turbo RGB colors.
    """
    import math

    def turbo_rgb(t: float) -> tuple:
        """Compute turbo RGB for t in [0, 1]."""
        t = max(0.0, min(1.0, t))
        r = 34.61 + t * (1172.33 - t * (10793.56 - t * (33300.12 - t * (38394.49 - t * 14825.05))))
        g = 23.31 + t * (557.33 + t * (1225.33 - t * (3574.96 - t * (1073.77 + t * 707.56))))
        b = 27.2 + t * (3211.1 - t * (15327.97 - t * (27814 - t * (22569.18 - t * 6838.66))))
        return (
            max(0, min(255, int(round(r)))),
            max(0, min(255, int(round(g)))),
            max(0, min(255, int(round(b)))),
            255
        )

    # Build colormap dict: {value: (r, g, b, a)}
    return {i: turbo_rgb(i / 255.0) for i in range(256)}


# Precompute turbo colormap once
TURBO_CMAP = _turbo_colormap()

# PM2.5 colorscale range (fixed)
PM25_VMIN = 20.0
PM25_VMAX = 180.0


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
    _: bool = Depends(verify_tasks_token)
):
    """
    Serve XYZ tiles from Cloud Optimized GeoTIFF.

    Args:
        pred_date: Date in YYYY-MM-DD format
        z: Zoom level
        x: Tile X coordinate
        y: Tile Y coordinate
    """
    from fastapi.responses import Response
    import os

    Reader, _ = _require_rio_tiler()
    bucket = _get_derived_bucket()

    # Download COG to temp file (GCS client uses Application Default Credentials)
    blob_path = f"predictions/date={pred_date}/pm25_{pred_date}.tif"
    tmp_path = _download_cog_to_temp(bucket, blob_path)

    try:
        import numpy as np
        from rio_tiler.models import ImageData

        with Reader(tmp_path) as src:
            # Read tile
            tile = src.tile(
                x, y, z,
                indexes=1,
                resampling_method="bilinear"
            )

            # Rescale data to 0-255 range based on PM2.5 colorscale
            data = tile.data[0].astype(np.float32)
            mask = tile.mask

            # Linear rescale: (value - vmin) / (vmax - vmin) * 255
            rescaled = np.clip(
                (data - PM25_VMIN) / (PM25_VMAX - PM25_VMIN) * 255,
                0, 255
            ).astype(np.uint8)

            # Create new ImageData with rescaled values
            rescaled_tile = ImageData(
                rescaled.reshape(1, *rescaled.shape),
                mask,
                crs=tile.crs,
                bounds=tile.bounds,
            )

            # Render with turbo colormap
            img = rescaled_tile.render(
                img_format="PNG",
                colormap=TURBO_CMAP,
            )

            return Response(
                content=img,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=86400",  # Cache for 1 day
                    "X-Tile-Date": pred_date,
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail=f"COG not found for date: {pred_date}"
            )
        logger.error(f"Tile error for {pred_date}/{z}/{x}/{y}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Tile generation failed: {error_msg}"
        )
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
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Get TileJSON metadata for a prediction date.

    Args:
        pred_date: Date in YYYY-MM-DD format
    """
    import os

    Reader, _ = _require_rio_tiler()
    bucket = _get_derived_bucket()

    # Download COG to temp file
    blob_path = f"predictions/date={pred_date}/pm25_{pred_date}.tif"
    tmp_path = _download_cog_to_temp(bucket, blob_path)

    try:
        with Reader(tmp_path) as src:
            info = src.info()

            # Build tile URL template - use correct path /ops/pipeline
            base_url = str(request.base_url).rstrip("/")
            tile_url = f"{base_url}/api/v1/ops/pipeline/tiles/{pred_date}/{{z}}/{{x}}/{{y}}.png"

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


def _gcs_list_cog_dates(bucket_name: str, limit: int = 365) -> List[str]:
    """
    List prediction dates that have COG files available.
    """
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
    bucket = _get_derived_bucket()
    dates = _gcs_list_cog_dates(bucket, limit=limit)
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
    _: bool = Depends(verify_tasks_token)
) -> Dict[str, Any]:
    """
    Query PM2.5 prediction value at a specific coordinate.

    Args:
        pred_date: Date in YYYY-MM-DD format
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
    """
    import os
    import math

    Reader, _ = _require_rio_tiler()
    bucket = _get_derived_bucket()

    # Download COG to temp file
    blob_path = f"predictions/date={pred_date}/pm25_{pred_date}.tif"
    tmp_path = _download_cog_to_temp(bucket, blob_path)

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
