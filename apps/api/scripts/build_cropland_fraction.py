#!/usr/bin/env python3
"""Reduce ESA WorldCover 2021 v200 tiles (10 m, class 40 = cropland) to the cropland share of each
0.005° cell over the FIRMS box (60–78E, 23–37N) and upload it as the classifier's cropland input:

    python3 scripts/build_cropland_fraction.py --tiles /path/to/ESA_WorldCover_10m_2021_v200_*_Map.tif [--dry-run]

Tiles are 3° × 3°, 36,000 px square, named by their south-west corner; 3° / 0.005° = 600 cells, so
each cell is exactly 60 × 60 pixels and the grid needs no resampling. Missing tiles (open sea) stay
no-data (255). Output: an .npz with frac (uint8 percent, rows south→north), lat0, lon0, step.
WorldCover is © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021),
CC BY 4.0. Needs rasterio locally; the API reads the .npz with numpy only.
"""
import argparse
import io
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import fire_classify as fc  # noqa: E402

LAT0, LAT1, LON0, LON1, STEP = 23.0, 37.0, 60.0, 78.0, 0.005
BUCKET = "paqi-forecasts-hawanama-data"
CELL_PX = 60
CROP_CLASS = 40


def main() -> int:
    import rasterio
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", nargs="+", required=True)
    ap.add_argument("--out", default=None, help="also save the .npz locally")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    nrows, ncols = int(round((LAT1 - LAT0) / STEP)), int(round((LON1 - LON0) / STEP))
    frac = np.full((nrows, ncols), 255, dtype=np.uint8)
    for path in a.tiles:
        m = re.search(r"_(N|S)(\d{2})(E|W)(\d{3})_", Path(path).name)
        if not m:
            print("skip (name)", path)
            continue
        tlat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
        tlon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
        with rasterio.open(path) as ds:
            assert ds.width == ds.height == 36000, (path, ds.width, ds.height)
            # tile rows run north→south; process in bands of CELL_PX*10 rows to keep memory modest
            band = CELL_PX * 10
            for r0 in range(0, 36000, band):
                arr = ds.read(1, window=((r0, r0 + band), (0, 36000)))
                crop = (arr == CROP_CLASS).astype(np.float32)
                cells = crop.reshape(band // CELL_PX, CELL_PX, 36000 // CELL_PX, CELL_PX).mean(axis=(1, 3))     # (10, 600)
                for i in range(cells.shape[0]):
                    tile_row = r0 // CELL_PX + i                         # 0 = northern edge of the tile
                    lat_cell_south = tlat + 3.0 - (tile_row + 1) * STEP  # south edge of this cell row
                    gr = int(round((lat_cell_south - LAT0) / STEP))
                    if gr < 0 or gr >= nrows:
                        continue
                    gc0 = int(round((tlon - LON0) / STEP))
                    cols = slice(max(gc0, 0), min(gc0 + 600, ncols))
                    src = cells[i, max(0, -gc0):600 - max(0, gc0 + 600 - ncols)]
                    frac[gr, cols] = np.round(src * 100).astype(np.uint8)
        print("done", Path(path).name)
    covered = int((frac != 255).sum())
    print(f"grid {nrows}×{ncols}, cells with data {covered} ({covered / frac.size:.1%}), mean crop share {frac[frac != 255].mean() / 100:.3f}")
    buf = io.BytesIO()
    np.savez_compressed(buf, frac=frac, lat0=LAT0, lon0=LON0, step=STEP)
    data = buf.getvalue()
    print("npz bytes", len(data))
    if a.out:
        Path(a.out).write_bytes(data)
    if a.dry_run:
        return 0
    from google.cloud import storage
    storage.Client().bucket(BUCKET).blob(fc.CROPFRAC_PATH).upload_from_string(data, content_type="application/octet-stream")
    print("uploaded", fc.CROPFRAC_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
