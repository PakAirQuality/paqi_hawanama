#!/usr/bin/env python3
"""Seed civic-asset Parquet files from OpenStreetMap via Overpass.

Bulk-extracts schools, hospitals, clinics, factories, and other POIs
for all Pakistani cities in the monitoring network.  Outputs one
consolidated Parquet file per asset type to data/assets/, then
optionally uploads to GCS.

Usage:
    # Extract + save locally
    python scripts/seed_civic_assets.py

    # Extract + upload to GCS
    python scripts/seed_civic_assets.py --upload

    # Single city for testing
    python scripts/seed_civic_assets.py --city Lahore

    # Custom radius (default 25 km around city centroid)
    python scripts/seed_civic_assets.py --radius 15
"""

import argparse
import json
import logging
import math
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ── Asset type → Overpass selectors ──────────────────────────────────────

ASSET_SPECS: dict[str, list[str]] = {
    "hospital": ['nwr["amenity"="hospital"]'],
    "clinic": ['nwr["amenity"="clinic"]'],
    "school": ['nwr["amenity"="school"]'],
    "university": ['nwr["amenity"="university"]'],
    "factory": ['nwr["man_made"="works"]', 'nwr["industrial"]'],
    "road": ['way["highway"~"trunk|primary|secondary|motorway"]'],
    "worship": ['nwr["amenity"="place_of_worship"]'],
    "market": ['nwr["amenity"="marketplace"]', 'nwr["shop"="mall"]'],
    "bus_station": [
        'nwr["amenity"="bus_station"]',
        'nwr["public_transport"="station"]',
    ],
}

# ── City centroids from stations.csv ─────────────────────────────────────


def _load_city_centroids(stations_path: Path) -> pd.DataFrame:
    """Derive city centroids from the station registry."""
    df = pd.read_csv(stations_path)
    cities = (
        df.groupby(["city_name", "state_name"], sort=False)
        .agg(lat=("latitude", "mean"), lon=("longitude", "mean"))
        .reset_index()
    )
    return cities


# ── Overpass query helpers ────────────────────────────────────────────────


def _build_city_query(
    lat: float, lon: float, radius_m: int, asset_types: list[str],
) -> str:
    """Build Overpass QL for all requested asset types around a point."""
    selectors = []
    for atype in asset_types:
        for sel in ASSET_SPECS.get(atype, []):
            selectors.append(f"  {sel}(around:{radius_m},{lat},{lon});")
    union = "\n".join(selectors)
    return f"[out:json][timeout:60];\n(\n{union}\n);\nout center body qt;"


def _classify(tags: dict) -> str:
    """Classify OSM tags into a canonical asset_type."""
    amenity = tags.get("amenity", "")
    if amenity == "hospital":
        return "hospital"
    if amenity == "clinic":
        return "clinic"
    if amenity == "school":
        return "school"
    if amenity == "university":
        return "university"
    if amenity == "place_of_worship":
        return "worship"
    if amenity in ("bus_station",):
        return "bus_station"
    if amenity == "marketplace" or tags.get("shop") == "mall":
        return "market"
    if tags.get("man_made") == "works" or tags.get("industrial"):
        return "factory"
    if tags.get("highway") in ("trunk", "primary", "secondary", "motorway"):
        return "road"
    return "other"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _admin_lookup(lat: float, lon: float) -> dict:
    """Reverse-geocode admin boundaries via Overpass is_in."""
    query = (
        f'[out:json][timeout:10];\n'
        f'is_in({lat},{lon})->.a;\n'
        f'area.a["boundary"="administrative"]["admin_level"~"^(3|4|5|6)$"];\n'
        f'out tags;'
    )
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    admin: dict[str, str] = {}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        level = tags.get("admin_level", "")
        name = tags.get("name", "") or tags.get("name:en", "")
        if level == "4":
            admin["province"] = name
        elif level == "6":
            admin["district"] = name
    return admin


def _query_city(
    city_name: str,
    state_name: str,
    lat: float,
    lon: float,
    radius_m: int,
    asset_types: list[str],
) -> list[dict]:
    """Query Overpass for all asset types around a city centroid."""
    query = _build_city_query(lat, lon, radius_m, asset_types)

    try:
        resp = requests.post(
            OVERPASS_URL, data={"data": query}, timeout=90,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        logger.error("Overpass failed for %s: %s", city_name, e)
        return []

    elements = raw.get("elements", [])
    logger.info(
        "  %s: %d raw elements from Overpass", city_name, len(elements),
    )

    seen: set[str] = set()
    rows: list[dict] = []
    for el in elements:
        osm_key = f"{el['type']}/{el['id']}"
        if osm_key in seen:
            continue
        seen.add(osm_key)

        tags = el.get("tags", {})

        # Coordinates
        if el["type"] == "node":
            elat, elon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center", {})
            elat, elon = center.get("lat"), center.get("lon")
        if elat is None or elon is None:
            continue

        name = tags.get("name") or tags.get("name:en") or tags.get("name:ur") or ""
        asset_type = _classify(tags)
        if asset_type == "other":
            continue

        rows.append({
            "name": name,
            "asset_type": asset_type,
            "lat": round(elat, 6),
            "lon": round(elon, 6),
            "osm_id": osm_key,
            "city_name": city_name,
            "state_name": state_name,
            "source": "OSM",
        })

    return rows


# ── Main ──────────────────────────────────────────────────────────────────


def seed(
    stations_path: Path,
    output_dir: Path,
    radius_km: int = 25,
    city_filter: str | None = None,
    upload: bool = False,
) -> Path:
    """Run the full seed pipeline."""
    cities = _load_city_centroids(stations_path)
    if city_filter:
        cities = cities[cities["city_name"].str.lower() == city_filter.lower()]
        if cities.empty:
            logger.error("City '%s' not found in stations.csv", city_filter)
            raise SystemExit(1)

    logger.info(
        "Extracting civic assets for %d cities (radius %d km)",
        len(cities), radius_km,
    )

    asset_types = list(ASSET_SPECS.keys())
    radius_m = radius_km * 1000
    all_rows: list[dict] = []

    for _, row in cities.iterrows():
        rows = _query_city(
            row["city_name"], row["state_name"],
            row["lat"], row["lon"],
            radius_m, asset_types,
        )
        all_rows.extend(rows)
        # Be polite to the public Overpass server
        time.sleep(2)

    if not all_rows:
        logger.warning("No assets extracted — nothing to write.")
        raise SystemExit(1)

    # Deduplicate by osm_id (cities can overlap)
    df = pd.DataFrame(all_rows)
    before = len(df)
    df = df.drop_duplicates(subset="osm_id", keep="first")
    logger.info(
        "Deduplicated: %d → %d assets (%d cross-city duplicates removed)",
        before, len(df), before - len(df),
    )

    # Write consolidated Parquet
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "civic_assets_pk.parquet"
    df.to_parquet(parquet_path, index=False)
    logger.info("Wrote %s (%d rows)", parquet_path, len(df))

    # Write manifest
    counts = df["asset_type"].value_counts().to_dict()
    manifest = {
        "version": 1,
        "extract_date": date.today().isoformat(),
        "source": "OpenStreetMap via Overpass API",
        "radius_km": radius_km,
        "n_cities": len(cities),
        "total_assets": len(df),
        "counts_by_type": counts,
        "cities": sorted(df["city_name"].unique().tolist()),
    }
    manifest_path = output_dir / "assets_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Wrote %s", manifest_path)

    # Per-type summary
    for atype, count in sorted(counts.items(), key=lambda x: -x[1]):
        logger.info("  %-14s %6d", atype, count)

    # Upload to GCS
    if upload:
        _upload_to_gcs(output_dir, parquet_path, manifest_path)

    return parquet_path


def _upload_to_gcs(output_dir: Path, parquet_path: Path, manifest_path: Path):
    """Upload asset files to GCS bucket."""
    try:
        from google.cloud import storage
    except ImportError:
        logger.error("google-cloud-storage not installed — skipping upload")
        return

    import os
    bucket_name = os.getenv("GCS_FORECAST_BUCKET", "paqi-forecasts-hawanama-data")
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    for local_path, blob_name in [
        (parquet_path, "assets/civic_assets_pk.parquet"),
        (manifest_path, "assets/assets_manifest.json"),
    ]:
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local_path))
        logger.info("Uploaded → gs://%s/%s", bucket_name, blob_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed civic-asset Parquet files from OSM Overpass",
    )
    parser.add_argument(
        "--stations", default=None,
        help="Path to stations.csv. Auto-detects from Operational_Forecasting or current repo.",
    )
    parser.add_argument(
        "--output", default="data/assets",
        help="Output directory (default: data/assets)",
    )
    parser.add_argument(
        "--radius", type=int, default=25,
        help="Search radius in km around each city centroid (default: 25)",
    )
    parser.add_argument(
        "--city", type=str, default=None,
        help="Extract for a single city only (e.g. --city Lahore)",
    )
    parser.add_argument(
        "--upload", action="store_true",
        help="Upload Parquet + manifest to GCS after extraction",
    )
    args = parser.parse_args()

    # Resolve paths
    repo_root = Path(__file__).resolve().parent.parent
    output_dir = repo_root / args.output

    if args.stations:
        stations_path = Path(args.stations)
    else:
        # Auto-detect: try Operational_Forecasting first, then local
        candidates = [
            Path.home() / "Desktop" / "Operational_Forecasting" / "data" / "stations" / "stations.csv",
            repo_root / "data" / "stations" / "stations.csv",
        ]
        stations_path = next((p for p in candidates if p.exists()), candidates[0])

    seed(stations_path, output_dir, args.radius, args.city, args.upload)
