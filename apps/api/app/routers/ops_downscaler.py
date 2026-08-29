"""
Ops Downscaler API endpoints — 1 km urban PM2.5 predictions.

Serves tile imagery, grid JSON, date listings, and model metadata
for the estimation-context downscaler (trained on ERA5+OFFL features).

Data path: predictions/estimation_urban/  (with fallback to predictions/urban/)
Model: estimation_v1 (LightGBM, ~300 features incl. 38 urban morphology)

Separate from the national estimation pipeline (ops_pipeline.py).
"""

import json
import logging
import math
import os
import tempfile
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.core.config import settings
from app.core.security import verify_tasks_token
from ._tile_utils import (
    TURBO_CMAP,
    _clip_tile_alpha,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ── City definitions (mirrors Downscaler/inference/config.py) ──────────────

CITIES = {
    "lahore": {
        "name": "Lahore",
        "lat_min": 31.20, "lat_max": 31.80,
        "lon_min": 74.00, "lon_max": 74.60,
        "grid_shape": [60, 60],
    },
    "isb_rwp": {
        "name": "Islamabad / Rawalpindi",
        "lat_min": 33.30, "lat_max": 33.90,
        "lon_min": 72.60, "lon_max": 73.30,
        "grid_shape": [60, 70],
    },
    "peshawar": {
        "name": "Peshawar",
        "lat_min": 33.80, "lat_max": 34.30,
        "lon_min": 71.30, "lon_max": 71.90,
        "grid_shape": [50, 60],
    },
    "karachi": {
        "name": "Karachi",
        "lat_min": 24.70, "lat_max": 25.30,
        "lon_min": 66.70, "lon_max": 67.30,
        "grid_shape": [60, 60],
    },
}

GRID_RES = 0.01  # degrees (~1 km)
URBAN_VMIN = 5.0
URBAN_VMAX = 80.0


# ── Helpers ────────────────────────────────────────────────────────────────

def _require_gcs():
    try:
        from google.cloud import storage
        return storage
    except ImportError as e:
        raise HTTPException(status_code=501, detail="GCS not available") from e


def _gcs_client():
    storage = _require_gcs()
    return storage.Client()


def _require_rio_tiler():
    try:
        from rio_tiler.io import Reader
        return Reader
    except ImportError as e:
        raise HTTPException(status_code=501, detail="rio-tiler not available") from e


def _get_outputs_bucket() -> str:
    val = settings.OPS_OUTPUTS_BUCKET
    if not val:
        raise HTTPException(status_code=500, detail="OPS_OUTPUTS_BUCKET not set")
    return val.replace("gs://", "").strip("/")


def _get_models_bucket() -> str:
    val = settings.OPS_MODELS_BUCKET
    if not val:
        raise HTTPException(status_code=500, detail="OPS_MODELS_BUCKET not set")
    return val.replace("gs://", "").strip("/")


def _validate_city(city_key: str):
    if city_key not in CITIES:
        raise HTTPException(status_code=404, detail=f"Unknown city: {city_key}. Valid: {list(CITIES.keys())}")


def _download_to_temp(bucket_name: str, blob_path: str, suffix: str = ".tif") -> str:
    client = _gcs_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    if not blob.exists(client):
        raise HTTPException(status_code=404, detail=f"Not found: gs://{bucket_name}/{blob_path}")
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    blob.download_to_filename(tmp.name)
    return tmp.name


def _resolve_urban_blob(bucket_name: str, pred_date: str, filename: str) -> str:
    """Resolve blob path: try estimation_urban first, fall back to urban (NRT)."""
    client = _gcs_client()
    bucket = client.bucket(bucket_name)

    # Primary: estimation-context outputs
    est_path = f"predictions/estimation_urban/date={pred_date}/{filename}"
    if bucket.blob(est_path).exists(client):
        return est_path

    # Fallback: NRT outputs (during transition)
    nrt_path = f"predictions/urban/date={pred_date}/{filename}"
    if bucket.blob(nrt_path).exists(client):
        logger.debug(f"Falling back to NRT path for {filename} on {pred_date}")
        return nrt_path

    raise HTTPException(status_code=404, detail=f"No urban data for {filename} on {pred_date}")


def _empty_tile_png() -> bytes:
    from PIL import Image
    import io
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/cities", summary="List supported cities")
async def list_cities() -> Dict[str, Any]:
    """City catalog with bounds, grid shape, center coordinates."""
    result = {}
    for key, c in CITIES.items():
        result[key] = {
            "name": c["name"],
            "bounds": [c["lon_min"], c["lat_min"], c["lon_max"], c["lat_max"]],
            "grid_shape": c["grid_shape"],
            "center": [(c["lon_min"] + c["lon_max"]) / 2, (c["lat_min"] + c["lat_max"]) / 2],
            "resolution": GRID_RES,
        }
    return {"cities": result, "count": len(result)}


@router.get("/dates", summary="List available prediction dates")
async def list_dates(
    city: str = Query("lahore", description="City key"),
    limit: int = Query(365, ge=1, le=1000),
) -> Dict[str, Any]:
    """List dates with urban COG tiles available for a city."""
    _validate_city(city)
    bucket_name = _get_outputs_bucket()

    try:
        client = _gcs_client()
        bucket = client.bucket(bucket_name)
        dates = set()

        # Primary: estimation_urban outputs
        for blob in bucket.list_blobs(prefix="predictions/estimation_urban/date="):
            if blob.name.endswith(f"{city}.tif") or blob.name.endswith(f"{city}_smoothed.tif"):
                try:
                    d = blob.name.split("date=")[1].split("/")[0]
                    dates.add(d)
                except Exception:
                    continue

        # Fallback: also include NRT urban dates (during transition)
        for blob in bucket.list_blobs(prefix="predictions/urban/date="):
            if blob.name.endswith(f"{city}.tif") or blob.name.endswith(f"{city}_smoothed.tif"):
                try:
                    d = blob.name.split("date=")[1].split("/")[0]
                    dates.add(d)
                except Exception:
                    continue

        sorted_dates = sorted(dates)[-limit:]
        return {"city": city, "dates": sorted_dates, "count": len(sorted_dates)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list downscaler dates for {city}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/tiles/{city}/{pred_date}/{z}/{x}/{y}.png",
    summary="Get 1km PM2.5 tile",
    responses={200: {"content": {"image/png": {}}}, 404: {"description": "COG not found"}},
)
async def get_downscaler_tile(
    city: str,
    pred_date: str,
    z: int,
    x: int,
    y: int,
    smoothed: bool = Query(True, description="Use Gaussian-smoothed COG"),
):
    """Serve XYZ tiles from urban 1 km COG. Tighter colorscale (5-80 µg/m³), grid lines at z≥12."""
    import numpy as np
    from PIL import Image
    import io
    from rio_tiler.errors import TileOutsideBounds

    _validate_city(city)
    Reader = _require_rio_tiler()
    bucket = _get_outputs_bucket()

    suffix = "_smoothed" if smoothed else ""
    filename = f"{city}{suffix}.tif"
    blob_path = _resolve_urban_blob(bucket, pred_date, filename)
    tmp_path = _download_to_temp(bucket, blob_path)

    try:
        with Reader(tmp_path) as src:
            try:
                tile = src.tile(x, y, z, indexes=1, resampling_method="cubic")
            except TileOutsideBounds:
                return Response(content=_empty_tile_png(), media_type="image/png",
                                headers={"Cache-Control": "public, max-age=86400"})

            data = tile.data[0].astype(np.float32)
            mask = tile.mask

            if mask is None or np.max(mask) == 0:
                return Response(content=_empty_tile_png(), media_type="image/png",
                                headers={"Cache-Control": "public, max-age=86400"})

            rescaled = np.clip(
                (data - URBAN_VMIN) / (URBAN_VMAX - URBAN_VMIN) * 255, 0, 255
            ).astype(np.uint8)

            h, w = rescaled.shape
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            for idx, color in TURBO_CMAP.items():
                m = rescaled == idx
                rgba[m, 0] = color[0]
                rgba[m, 1] = color[1]
                rgba[m, 2] = color[2]

            alpha = (mask > 0).astype(np.uint8) * 255
            rgba[:, :, 3] = alpha

            # Clip to Pakistan boundary
            rgba = _clip_tile_alpha(rgba, x, y, z)

            # Grid cell outlines at z >= 12
            if z >= 12:
                n = 2 ** z
                lon_min = x / n * 360.0 - 180.0
                lon_max = (x + 1) / n * 360.0 - 180.0
                lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
                lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
                cell = GRID_RES
                ga = 50 if z < 14 else 80

                lon = math.ceil(lon_min / cell) * cell
                while lon < lon_max:
                    px = int((lon - lon_min) / (lon_max - lon_min) * w)
                    if 0 <= px < w:
                        vm = rgba[:, px, 3] > 0
                        rgba[vm, px, 0] = 255
                        rgba[vm, px, 1] = 255
                        rgba[vm, px, 2] = 255
                        rgba[vm, px, 3] = ga
                    lon += cell

                lat = math.ceil(lat_min / cell) * cell
                while lat < lat_max:
                    py = int((lat_max - lat) / (lat_max - lat_min) * h)
                    if 0 <= py < h:
                        hm = rgba[py, :, 3] > 0
                        rgba[py, hm, 0] = 255
                        rgba[py, hm, 1] = 255
                        rgba[py, hm, 2] = 255
                        rgba[py, hm, 3] = ga
                    lat += cell

            img = Image.fromarray(rgba, mode='RGBA')
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return Response(
                content=buffer.getvalue(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400", "X-Tile-Date": pred_date},
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Downscaler tile error {city}/{pred_date}/{z}/{x}/{y}: {e}")
        return Response(content=_empty_tile_png(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get(
    "/grid/{city}/{pred_date}",
    summary="Get 1km grid JSON for hover lookup",
)
async def get_grid_json(
    city: str,
    pred_date: str,
    _: bool = Depends(verify_tasks_token),
) -> Dict[str, Any]:
    """Full 1km grid data (lats, lons, pm25 values) for client-side O(1) hover."""
    import json as _json

    _validate_city(city)
    bucket_name = _get_outputs_bucket()
    blob_path = _resolve_urban_blob(bucket_name, pred_date, f"{city}.json")
    tmp_path = _download_to_temp(bucket_name, blob_path, suffix=".json")

    try:
        with open(tmp_path) as f:
            data = _json.load(f)
        return {
            "city": city,
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
        logger.error(f"Downscaler grid error {city}/{pred_date}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get("/summary", summary="Downscaler model card")
async def get_summary(
    _: bool = Depends(verify_tasks_token),
) -> Dict[str, Any]:
    """Model metadata: version, MAE, feature count, cities covered."""
    bucket_name = _get_models_bucket()

    # Try estimation_v1 model pointer first, fall back to v8
    pointer = None
    model_version = "estimation_v1"
    n_features = 320  # approx, varies with feature audit

    for model_path in ["downscaler/estimation_v1/latest.json", "downscaler/v8/latest.json"]:
        try:
            client = _gcs_client()
            blob = client.bucket(bucket_name).blob(model_path)
            if blob.exists(client):
                import json as _json
                tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
                blob.download_to_filename(tmp.name)
                with open(tmp.name) as f:
                    pointer = _json.load(f)
                os.unlink(tmp.name)
                model_version = pointer.get("version", model_path.split("/")[1])
                n_features = pointer.get("n_features", n_features)
                break
        except Exception as e:
            logger.warning(f"Failed to load {model_path}: {e}")

    return {
        "model": f"downscaler_{model_version}",
        "version": model_version,
        "algorithm": "LightGBM (Huber)",
        "resolution_deg": GRID_RES,
        "resolution_approx": "~1 km",
        "n_features": n_features,
        "colorscale": {"vmin": URBAN_VMIN, "vmax": URBAN_VMAX, "unit": "µg/m³"},
        "cities": {k: v["name"] for k, v in CITIES.items()},
        "pointer": pointer,
    }
