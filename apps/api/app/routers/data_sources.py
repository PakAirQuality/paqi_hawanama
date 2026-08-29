"""
Data-source endpoints: wind texture + satellite PM2.5 tiles.

Wind: reads gridded u/v wind from Open-Meteo AWS Open Data (ECMWF IFS 0.25°),
      encodes as PNG texture for GPU particle rendering.
SatPM25: serves pre-processed V5GL04 HybridPM25 COG as XYZ raster tiles.
"""

import io
import json
import logging
import os
import struct
import time
import zlib
from datetime import datetime, timezone

import fsspec
import numpy as np
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from omfiles import OmFileReader

from ._tile_utils import TURBO_CMAP, _clip_tile_alpha

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# WIND ENDPOINTS (unchanged from wind.py)
# =============================================================================

_GLOBAL_LAT_START = -90.0
_GLOBAL_LON_START = -180.0
_DLAT = _DLON = 0.25

LAT_MIN, LAT_MAX = -10.0, 45.0
LON_MIN, LON_MAX = 25.0, 130.0

_Y_LO = round((LAT_MIN - _GLOBAL_LAT_START) / _DLAT)
_Y_HI = round((LAT_MAX - _GLOBAL_LAT_START) / _DLAT)
_X_LO = round((LON_MIN - _GLOBAL_LON_START) / _DLON)
_X_HI = round((LON_MAX - _GLOBAL_LON_START) / _DLON)

GRID_HEIGHT = _Y_HI - _Y_LO + 1
GRID_WIDTH = _X_HI - _X_LO + 1

_S3_BASE = "s3://openmeteo/data_spatial/ecmwf_ifs025"

_CACHE_TTL = 3600
_cache: dict = {
    "png_bytes": None,
    "metadata": None,
    "generated_at": 0.0,
}


def _find_closest_timestep(manifest: dict) -> tuple[str, str]:
    """Return (run_path, timestamp_str) for the valid_time closest to now."""
    ref = datetime.fromisoformat(manifest["reference_time"])
    run_path = f"{ref.year}/{ref.month:02}/{ref.day:02}/{ref.hour:02}{ref.minute:02}Z"

    now = datetime.now(timezone.utc)
    valid_times = manifest["valid_times"]
    closest = min(
        valid_times,
        key=lambda vt: abs(
            (datetime.fromisoformat(vt.replace("Z", "+00:00")) - now).total_seconds()
        ),
    )
    vt = datetime.fromisoformat(closest.replace("Z", "+00:00"))
    ts = vt.strftime("%Y-%m-%dT%H%M")
    return run_path, ts


def _read_south_asia_wind() -> tuple[np.ndarray, np.ndarray]:
    """Read u/v 10m wind for South Asia from Open-Meteo AWS Open Data."""
    manifest_uri = f"{_S3_BASE}/latest.json"
    with fsspec.open(manifest_uri, mode="r", s3={"anon": True}) as f:
        manifest = json.load(f)

    run_path, ts = _find_closest_timestep(manifest)
    om_uri = f"{_S3_BASE}/{run_path}/{ts}.om"
    print(f"[wind] Reading {om_uri}")

    backend = fsspec.open(om_uri, mode="rb", s3={"anon": True})
    with OmFileReader(backend) as root:
        u = root.get_child_by_name("wind_u_component_10m")[_Y_LO : _Y_HI + 1, _X_LO : _X_HI + 1]
        v = root.get_child_by_name("wind_v_component_10m")[_Y_LO : _Y_HI + 1, _X_LO : _X_HI + 1]

    return u, v


def _encode_png(width: int, height: int, r_data: bytes, g_data: bytes) -> bytes:
    """Encode a width x height 2-channel image as an RGB PNG (B=128) using raw zlib."""

    def _make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        raw = chunk_type + data
        crc = zlib.crc32(raw) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + raw + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _make_chunk(b"IHDR", ihdr_data)

    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)
        for x in range(width):
            idx = y * width + x
            raw_rows.append(r_data[idx])
            raw_rows.append(g_data[idx])
            raw_rows.append(128)

    compressed = zlib.compress(bytes(raw_rows))
    idat = _make_chunk(b"IDAT", compressed)
    iend = _make_chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def _refresh_cache() -> None:
    """Fetch wind data from AWS Open Data and update the in-memory cache."""
    u, v = _read_south_asia_wind()

    u = np.flipud(u)
    v = np.flipud(v)

    u_min, u_max = float(np.nanmin(u)), float(np.nanmax(u))
    v_min, v_max = float(np.nanmin(v)), float(np.nanmax(v))

    u_range = u_max - u_min if u_max != u_min else 1.0
    v_range = v_max - v_min if v_max != v_min else 1.0

    u_norm = np.where(np.isnan(u), 128, ((u - u_min) / u_range * 255).clip(0, 255)).astype(np.uint8)
    v_norm = np.where(np.isnan(v), 128, ((v - v_min) / v_range * 255).clip(0, 255)).astype(np.uint8)

    r_data = bytes(u_norm.flatten())
    g_data = bytes(v_norm.flatten())

    png_bytes = _encode_png(GRID_WIDTH, GRID_HEIGHT, r_data, g_data)

    now = datetime.now(timezone.utc)
    _cache["png_bytes"] = png_bytes
    _cache["metadata"] = {
        "width": GRID_WIDTH,
        "height": GRID_HEIGHT,
        "lat_min": LAT_MIN,
        "lat_max": LAT_MAX,
        "lon_min": LON_MIN,
        "lon_max": LON_MAX,
        "u_min": round(u_min, 2),
        "u_max": round(u_max, 2),
        "v_min": round(v_min, 2),
        "v_max": round(v_max, 2),
        "generated_at": now.isoformat(),
        "attribution": "Weather data by Open-Meteo.com (CC-BY 4.0)",
    }
    _cache["generated_at"] = time.time()
    print(f"[wind] Cache refreshed: {GRID_WIDTH}x{GRID_HEIGHT}, "
          f"u=[{u_min:.1f},{u_max:.1f}], v=[{v_min:.1f},{v_max:.1f}], "
          f"PNG={len(png_bytes)} bytes")


def _ensure_cache() -> None:
    """Ensure the cache is populated and fresh."""
    age = time.time() - _cache["generated_at"]
    if _cache["png_bytes"] is None or age > _CACHE_TTL:
        try:
            _refresh_cache()
        except Exception as e:
            if _cache["png_bytes"] is not None:
                print(f"[wind] Refresh failed, serving stale: {e}")
            else:
                raise


@router.get("/wind/texture")
async def get_wind_texture():
    """Return wind data as a PNG texture (R=normalized u, G=normalized v)."""
    _ensure_cache()
    return Response(
        content=_cache["png_bytes"],
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=1800",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/wind/metadata")
async def get_wind_metadata():
    """Return wind grid metadata (bounds, dimensions, u/v min/max)."""
    _ensure_cache()
    return JSONResponse(
        content=_cache["metadata"],
        headers={
            "Cache-Control": "public, max-age=1800",
            "Access-Control-Allow-Origin": "*",
        },
    )


# =============================================================================
# SATELLITE PM2.5 TILE ENDPOINTS (GCS-backed)
# =============================================================================

_SAT_BUCKET = "global-sat-pm25"
_SAT_COG_CACHE_DIR = "/tmp/satpm25_cogs"
_SAT_MAX_READERS = 30

# Rescale range for colormap
_SAT_VMIN = 0.0
_SAT_VMAX = 120.0

# LRU-style reader cache: {cog_filename: Reader}
_sat_readers: dict = {}

# Catalog cache: {listing dict, fetched_at timestamp}
_catalog_cache: dict = {"data": None, "fetched_at": 0.0}
_CATALOG_TTL = 3600  # 1 hour


def _download_cog_from_gcs(cog_filename: str) -> str:
    """Download a COG from GCS to local cache dir. Returns local path."""
    from google.cloud import storage as gcs

    local_path = os.path.join(_SAT_COG_CACHE_DIR, cog_filename)
    if os.path.exists(local_path):
        return local_path

    os.makedirs(_SAT_COG_CACHE_DIR, exist_ok=True)

    # Determine GCS path from filename pattern
    if len(cog_filename) == len("satpm25_199801.tif") and cog_filename.startswith("satpm25_") and len(cog_filename.replace(".tif", "").split("_")[1]) == 6:
        blob_name = f"cog/monthly/{cog_filename}"
    else:
        blob_name = f"cog/annual/{cog_filename}"

    client = gcs.Client()
    bucket = client.bucket(_SAT_BUCKET)
    blob = bucket.blob(blob_name)

    if not blob.exists():
        raise FileNotFoundError(f"COG not found: {cog_filename}")

    tmp_path = local_path + ".tmp"
    blob.download_to_filename(tmp_path)
    os.replace(tmp_path, local_path)
    logger.info(f"Downloaded COG from GCS: {blob_name} → {local_path}")
    return local_path


def _get_sat_reader(cog_filename: str):
    """Get or create a rio-tiler Reader for the given COG file."""
    from rio_tiler.io import Reader

    if cog_filename in _sat_readers:
        return _sat_readers[cog_filename]

    local_path = _download_cog_from_gcs(cog_filename)
    reader = Reader(local_path)

    # Evict oldest if at capacity
    if len(_sat_readers) >= _SAT_MAX_READERS:
        oldest_key = next(iter(_sat_readers))
        old_reader = _sat_readers.pop(oldest_key)
        try:
            old_reader.close()
        except Exception:
            pass

    _sat_readers[cog_filename] = reader
    return reader


def _render_satpm25_tile(reader, x: int, y: int, z: int) -> bytes:
    """Render a satellite PM2.5 tile to PNG bytes using turbo colormap."""
    from PIL import Image
    from rio_tiler.errors import TileOutsideBounds

    try:
        img = reader.tile(x, y, z, resampling_method="cubic")
    except TileOutsideBounds:
        return None

    data = img.data[0]
    mask = img.mask

    scaled = np.clip((data - _SAT_VMIN) / (_SAT_VMAX - _SAT_VMIN), 0, 1)
    idx = (scaled * 255).astype(np.uint8)

    h, w = idx.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for val, color in TURBO_CMAP.items():
        where = idx == val
        if np.any(where):
            rgba[where] = color

    rgba = _clip_tile_alpha(rgba, x, y, z)
    rgba[mask == 0] = 0

    img_pil = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img_pil.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get("/satpm25/catalog")
async def get_satpm25_catalog():
    """List available annual and monthly COGs on GCS."""
    from google.cloud import storage as gcs

    age = time.time() - _catalog_cache["fetched_at"]
    if _catalog_cache["data"] is not None and age < _CATALOG_TTL:
        return JSONResponse(
            content=_catalog_cache["data"],
            headers={
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
            },
        )

    client = gcs.Client()
    bucket = client.bucket(_SAT_BUCKET)

    annual_years = []
    for blob in bucket.list_blobs(prefix="cog/annual/satpm25_"):
        name = blob.name.split("/")[-1]  # satpm25_2022.tif
        year = name.replace("satpm25_", "").replace(".tif", "")
        if year.isdigit():
            annual_years.append(int(year))

    monthly_entries = []
    for blob in bucket.list_blobs(prefix="cog/monthly/satpm25_"):
        name = blob.name.split("/")[-1]  # satpm25_199801.tif
        ym = name.replace("satpm25_", "").replace(".tif", "")
        if len(ym) == 6 and ym.isdigit():
            monthly_entries.append({"year": int(ym[:4]), "month": int(ym[4:])})

    catalog = {
        "annual": sorted(annual_years),
        "monthly": sorted(monthly_entries, key=lambda e: (e["year"], e["month"])),
    }

    _catalog_cache["data"] = catalog
    _catalog_cache["fetched_at"] = time.time()

    return JSONResponse(
        content=catalog,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/satpm25/tilejson")
async def get_satpm25_tilejson(request=None):
    """TileJSON metadata for the satellite PM2.5 tile source."""
    base = ""
    if request:
        base = str(request.base_url).rstrip("/")

    return JSONResponse(
        content={
            "tilejson": "3.0.0",
            "name": "Typical PM2.5 (2022 satellite baseline)",
            "description": "Annual mean PM2.5 from WashU V5GL04 HybridPM25 (0.01° resolution)",
            "tiles": [f"{base}/api/v1/data-sources/satpm25/{{z}}/{{x}}/{{y}}.png"],
            "minzoom": 3,
            "maxzoom": 10,
            "bounds": [60.5, 23.5, 77.5, 37.5],
            "center": [69.0, 30.5, 5],
            "attribution": "WashU V5GL04 HybridPM25 (van Donkelaar et al.)",
        },
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/satpm25/monthly/{year}/{month}/{z}/{x}/{y}.png")
async def get_satpm25_monthly_tile(year: int, month: int, z: int, x: int, y: int):
    """Serve monthly satellite PM2.5 tile from GCS-backed COG."""
    if not (1998 <= year <= 2100) or not (1 <= month <= 12):
        return Response(content="Invalid year or month", status_code=400)
    cog_filename = f"satpm25_{year}{month:02d}.tif"

    try:
        reader = _get_sat_reader(cog_filename)
    except FileNotFoundError:
        return Response(content="COG not found", status_code=404)

    png_bytes = _render_satpm25_tile(reader, x, y, z)
    if png_bytes is None:
        return Response(content=b"", status_code=204)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=604800",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/satpm25/{z}/{x}/{y}.png")
async def get_satpm25_tile(z: int, x: int, y: int, year: int = 2022):
    """Serve annual satellite PM2.5 tile from GCS-backed COG."""
    if not (1998 <= year <= 2100):
        return Response(content="Invalid year", status_code=400)
    cog_filename = f"satpm25_{year}.tif"

    try:
        reader = _get_sat_reader(cog_filename)
    except FileNotFoundError:
        return Response(content="COG not found", status_code=404)

    png_bytes = _render_satpm25_tile(reader, x, y, z)
    if png_bytes is None:
        return Response(content=b"", status_code=204)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=604800",
            "Access-Control-Allow-Origin": "*",
        },
    )
