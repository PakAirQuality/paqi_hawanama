"""
Wind data endpoints for animated wind particle layer.

Reads gridded u/v wind components from Open-Meteo's AWS Open Data bucket
(s3://openmeteo) using the ECMWF IFS 0.25° model. Encodes the South Asia
subset as a PNG texture for GPU-based particle rendering on the frontend.
"""

import json
import struct
import time
import zlib
from datetime import datetime, timezone

import fsspec
import numpy as np
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from omfiles import OmFileReader

router = APIRouter()

# --- Grid configuration ---
# ECMWF IFS 0.25° regular lat/lon grid parameters
_GLOBAL_LAT_START = -90.0
_GLOBAL_LON_START = -180.0
_DLAT = _DLON = 0.25

# South Asia bounding box
LAT_MIN, LAT_MAX = 6.0, 37.0
LON_MIN, LON_MAX = 61.0, 93.0

# Pre-computed grid indices for South Asia subset
_Y_LO = round((LAT_MIN - _GLOBAL_LAT_START) / _DLAT)  # 384
_Y_HI = round((LAT_MAX - _GLOBAL_LAT_START) / _DLAT)  # 508
_X_LO = round((LON_MIN - _GLOBAL_LON_START) / _DLON)  # 964
_X_HI = round((LON_MAX - _GLOBAL_LON_START) / _DLON)  # 1092

# Output dimensions (rows=lat, cols=lon)
GRID_HEIGHT = _Y_HI - _Y_LO + 1  # 125
GRID_WIDTH = _X_HI - _X_LO + 1   # 129

# S3 bucket
_S3_BASE = "s3://openmeteo/data_spatial/ecmwf_ifs025"

# Cache: 1 hour TTL
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
    # Fetch manifest to discover latest run
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
        raw_rows.append(0)  # filter byte: None
        for x in range(width):
            idx = y * width + x
            raw_rows.append(r_data[idx])
            raw_rows.append(g_data[idx])
            raw_rows.append(128)  # blue channel unused

    compressed = zlib.compress(bytes(raw_rows))
    idat = _make_chunk(b"IDAT", compressed)
    iend = _make_chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def _refresh_cache() -> None:
    """Fetch wind data from AWS Open Data and update the in-memory cache."""
    u, v = _read_south_asia_wind()

    # The grid comes south-to-north (lat increasing with row index).
    # For the PNG texture, we want north at the top (row 0), so flip vertically.
    u = np.flipud(u)
    v = np.flipud(v)

    u_min, u_max = float(np.nanmin(u)), float(np.nanmax(u))
    v_min, v_max = float(np.nanmin(v)), float(np.nanmax(v))

    u_range = u_max - u_min if u_max != u_min else 1.0
    v_range = v_max - v_min if v_max != v_min else 1.0

    # Normalize to 0-255, replace NaN with 128 (neutral)
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
    _cache["generated_at"] = time.monotonic()
    print(f"[wind] Cache refreshed: {GRID_WIDTH}x{GRID_HEIGHT}, "
          f"u=[{u_min:.1f},{u_max:.1f}], v=[{v_min:.1f},{v_max:.1f}], "
          f"PNG={len(png_bytes)} bytes")


def _ensure_cache() -> None:
    """Ensure the cache is populated and fresh (synchronous — runs in thread)."""
    age = time.monotonic() - _cache["generated_at"]
    if _cache["png_bytes"] is None or age > _CACHE_TTL:
        try:
            _refresh_cache()
        except Exception as e:
            if _cache["png_bytes"] is not None:
                print(f"[wind] Refresh failed, serving stale: {e}")
            else:
                raise


@router.get("/texture")
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


@router.get("/metadata")
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
