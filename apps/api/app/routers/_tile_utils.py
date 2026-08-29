"""
Shared tile utilities for raster XYZ tile endpoints.

Used by ops_pipeline.py (prediction tiles) and data_sources.py (satellite PM2.5).
"""

import json
import logging
import math
import os
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# TURBO COLORMAP
# =============================================================================

def _turbo_colormap() -> Dict[int, tuple]:
    """Generate turbo colormap: maps 0-255 grayscale to turbo RGBA."""

    def turbo_rgb(t: float) -> tuple:
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

    return {i: turbo_rgb(i / 255.0) for i in range(256)}


TURBO_CMAP = _turbo_colormap()


# =============================================================================
# PAKISTAN BOUNDARY CLIPPING
# =============================================================================

_PAKISTAN_GEOMS_3857: List | None = None


def _load_pakistan_boundary_3857():
    """Load dissolved ADM2 boundary and transform to EPSG:3857.

    Uses the union of all ADM2 district polygons so the raster clip edge
    aligns exactly with the district outlines rendered on the frontend.
    Cached on first call.
    """
    global _PAKISTAN_GEOMS_3857
    if _PAKISTAN_GEOMS_3857 is not None:
        return _PAKISTAN_GEOMS_3857

    from rasterio.warp import transform_geom

    data_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    boundary_path = os.path.join(data_dir, "pakistan_adm2_dissolved.geojson")

    if not os.path.exists(boundary_path):
        logger.warning(f"Pakistan boundary not found in {data_dir}, tile clipping disabled")
        _PAKISTAN_GEOMS_3857 = []
        return _PAKISTAN_GEOMS_3857

    with open(boundary_path) as f:
        geojson = json.load(f)

    geoms_3857 = []
    for feature in geojson.get("features", []):
        geom = feature.get("geometry")
        if geom:
            transformed = transform_geom("EPSG:4326", "EPSG:3857", geom)
            geoms_3857.append(transformed)

    _PAKISTAN_GEOMS_3857 = geoms_3857
    logger.info(f"Loaded Pakistan boundary for tile clipping: {len(geoms_3857)} geometries")
    return _PAKISTAN_GEOMS_3857


# =============================================================================
# TILE MATH
# =============================================================================

def _tile_mercator_bounds(x: int, y: int, z: int):
    """Compute Web Mercator bounds for an XYZ tile."""
    EXTENT = 20037508.342789244
    n = 2 ** z
    res = 2 * EXTENT / n
    x_min = -EXTENT + x * res
    x_max = x_min + res
    y_max = EXTENT - y * res
    y_min = y_max - res
    return (x_min, y_min, x_max, y_max)


def _clip_tile_alpha(rgba, x: int, y: int, z: int):
    """Clip tile RGBA alpha channel to dissolved ADM2 boundary.

    Supersamples the boundary at 4x resolution, then applies majority-rule
    thresholding: a pixel is fully opaque if >= 50% of its area is inside the
    boundary, otherwise fully transparent.
    """
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds

    geoms = _load_pakistan_boundary_3857()
    if not geoms:
        return rgba

    bounds = _tile_mercator_bounds(x, y, z)
    h, w = rgba.shape[:2]

    SS = 4
    hi_h, hi_w = h * SS, w * SS
    hi_transform = from_bounds(*bounds, hi_w, hi_h)

    hi_mask = rasterize(
        [(g, 1) for g in geoms],
        out_shape=(hi_h, hi_w),
        transform=hi_transform,
        fill=0,
        dtype='uint8',
        all_touched=False,
    )

    coverage = hi_mask.reshape(h, SS, w, SS).mean(axis=(1, 3))
    boundary_mask = (coverage >= 0.5).astype(np.uint8) * 255

    outside = boundary_mask == 0
    rgba[outside, :3] = 0
    rgba[:, :, 3] = np.minimum(rgba[:, :, 3], boundary_mask)
    return rgba
