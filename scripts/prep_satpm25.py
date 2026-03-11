"""
Batch-process V5GL04 HybridPM25 NetCDF files → Pakistan-subset COGs → GCS.

Handles both annual (25 files, 1998-2022) and monthly (300 files) datasets.
Uploads raw NetCDFs and processed COGs to gs://global-sat-pm25/.

Usage:
    python scripts/prep_satpm25.py                  # both annual + monthly
    python scripts/prep_satpm25.py --mode annual     # annual only
    python scripts/prep_satpm25.py --mode monthly    # monthly only

Requires: netCDF4, rasterio, google-cloud-storage
"""

import argparse
import glob
import os
import re
import tempfile

import numpy as np
import netCDF4 as nc
import rasterio
from rasterio.transform import from_bounds
from google.cloud import storage

# --- Config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)  # hawanama-main/

ANNUAL_DIR = os.path.join(ROOT, "sat_annual")
MONTHLY_DIR = os.path.join(ROOT, "Monthly")

BUCKET_NAME = "global-sat-pm25"

# Pakistan bbox (generous)
LAT_MIN, LAT_MAX = 23.5, 37.5
LON_MIN, LON_MAX = 60.5, 77.5

NODATA = float("nan")


def get_or_create_bucket(client: storage.Client) -> storage.Bucket:
    """Get bucket, creating it if it doesn't exist."""
    try:
        bucket = client.get_bucket(BUCKET_NAME)
        print(f"Using existing bucket: gs://{BUCKET_NAME}")
    except Exception:
        bucket = client.create_bucket(BUCKET_NAME, location="asia-south1")
        print(f"Created bucket: gs://{BUCKET_NAME}")
    return bucket


def blob_exists(bucket: storage.Bucket, blob_name: str) -> bool:
    """Check if a blob exists in the bucket."""
    return storage.Blob(blob_name, bucket).exists()


def upload_file(bucket: storage.Bucket, local_path: str, blob_name: str):
    """Upload a local file to GCS."""
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path)


def nc_to_cog(nc_path: str, out_path: str):
    """Convert a NetCDF PM2.5 file to a Pakistan-subset COG."""
    ds = nc.Dataset(nc_path)

    lat = ds.variables["lat"][:]
    lon = ds.variables["lon"][:]

    # Find PM2.5 variable
    pm25_var = None
    for name in ds.variables:
        if name.lower() not in ("lat", "lon", "latitude", "longitude", "time"):
            pm25_var = name
            break
    if pm25_var is None:
        ds.close()
        raise ValueError(f"No PM2.5 variable found in {nc_path}")

    pm25 = ds.variables[pm25_var][:]
    if pm25.ndim == 3:
        pm25 = np.nanmean(pm25, axis=0)
    pm25 = np.array(pm25, dtype=np.float32)

    lat_ascending = lat[1] > lat[0]

    # Subset to Pakistan
    lat_mask = (lat >= LAT_MIN) & (lat <= LAT_MAX)
    lon_mask = (lon >= LON_MIN) & (lon <= LON_MAX)

    lat_sub = lat[lat_mask]
    lon_sub = lon[lon_mask]
    pm25_sub = pm25[np.ix_(lat_mask, lon_mask)]

    # Ensure north-up
    if lat_ascending:
        lat_sub = lat_sub[::-1]
        pm25_sub = pm25_sub[::-1, :]

    # Clean invalid values
    pm25_sub = np.where(
        np.isfinite(pm25_sub) & (pm25_sub >= 0), pm25_sub, np.float32("nan")
    )

    height, width = pm25_sub.shape
    res_lat = abs(lat_sub[1] - lat_sub[0]) if len(lat_sub) > 1 else 0.01
    res_lon = abs(lon_sub[1] - lon_sub[0]) if len(lon_sub) > 1 else 0.01

    west = float(lon_sub.min()) - res_lon / 2
    east = float(lon_sub.max()) + res_lon / 2
    south = float(lat_sub.min()) - res_lat / 2
    north = float(lat_sub.max()) + res_lat / 2

    transform = from_bounds(west, south, east, north, width, height)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    tmp_path = out_path + ".tmp.tif"
    with rasterio.open(
        tmp_path, "w",
        driver="GTiff",
        height=height, width=width, count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=float("nan"),
        compress="lzw",
        tiled=True,
        blockxsize=256, blockysize=256,
    ) as dst:
        dst.write(pm25_sub, 1)

    with rasterio.open(tmp_path, "r+") as dst:
        dst.build_overviews([2, 4, 8], rasterio.enums.Resampling.average)
        dst.update_tags(ns="rio_overview", resampling="average")

    os.replace(tmp_path, out_path)
    ds.close()
    return width, height


def parse_year_from_annual(filename: str) -> str:
    """Extract 4-digit year from annual NetCDF filename."""
    m = re.search(r"\.(\d{4})01-\d{4}12\.nc$", filename)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot parse year from {filename}")


def parse_yearmonth_from_monthly(filename: str) -> str:
    """Extract YYYYMM from monthly NetCDF filename (e.g. 199801-199801)."""
    m = re.search(r"\.(\d{6})-\d{6}\.nc$", filename)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot parse year-month from {filename}")


def process_files(bucket: storage.Bucket, nc_dir: str, mode: str):
    """Process all NetCDFs in a directory: upload raw + create/upload COG."""
    nc_files = sorted(glob.glob(os.path.join(nc_dir, "*.nc")))
    if not nc_files:
        print(f"  No .nc files found in {nc_dir}")
        return

    total = len(nc_files)
    print(f"  Found {total} NetCDF files in {nc_dir}")

    for i, nc_path in enumerate(nc_files, 1):
        filename = os.path.basename(nc_path)

        if mode == "annual":
            year = parse_year_from_annual(filename)
            cog_name = f"satpm25_{year}.tif"
            raw_blob = f"raw/annual/{filename}"
            cog_blob = f"cog/annual/{cog_name}"
        else:
            ym = parse_yearmonth_from_monthly(filename)
            cog_name = f"satpm25_{ym}.tif"
            raw_blob = f"raw/monthly/{filename}"
            cog_blob = f"cog/monthly/{cog_name}"

        prefix = f"  [{i}/{total}]"

        # Skip if COG already exists on GCS
        if blob_exists(bucket, cog_blob):
            print(f"{prefix} {cog_name} — already on GCS, skipping")
            continue

        # Upload raw NetCDF
        if not blob_exists(bucket, raw_blob):
            print(f"{prefix} Uploading raw {filename}...")
            upload_file(bucket, nc_path, raw_blob)
        else:
            print(f"{prefix} Raw {filename} already on GCS")

        # Create COG in temp dir
        with tempfile.TemporaryDirectory() as tmp_dir:
            cog_path = os.path.join(tmp_dir, cog_name)
            print(f"{prefix} Processing {filename} → {cog_name}...")
            w, h = nc_to_cog(nc_path, cog_path)
            size_kb = os.path.getsize(cog_path) / 1024
            print(f"{prefix} COG: {w}x{h}, {size_kb:.0f} KB → uploading...")
            upload_file(bucket, cog_path, cog_blob)

        print(f"{prefix} Done: gs://{BUCKET_NAME}/{cog_blob}")


def main():
    parser = argparse.ArgumentParser(description="Batch process satellite PM2.5 to GCS")
    parser.add_argument(
        "--mode", choices=["annual", "monthly", "both"], default="both",
        help="Which dataset to process (default: both)",
    )
    args = parser.parse_args()

    client = storage.Client(project="hawanama-data")
    bucket = get_or_create_bucket(client)

    if args.mode in ("annual", "both"):
        print("\n=== Annual files ===")
        process_files(bucket, ANNUAL_DIR, "annual")

    if args.mode in ("monthly", "both"):
        print("\n=== Monthly files ===")
        process_files(bucket, MONTHLY_DIR, "monthly")

    print("\nDone!")


if __name__ == "__main__":
    main()
