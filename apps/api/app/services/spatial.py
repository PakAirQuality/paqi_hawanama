"""Spatial analytics — GCS-backed civic assets + CDSE Sentinel-2 catalog.

Two capabilities for the analyst desk copilot:
1. nearest_assets: query pre-seeded civic-asset Parquet (from GCS) for
   nearby hospitals, schools, factories, etc.
2. sentinel_catalog: query CDSE STAC for Sentinel-2 L2A scene metadata.
"""

import io
import logging
import math
from datetime import date, timedelta
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

CDSE_STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac/search"

VALID_ASSET_TYPES = {
    "hospital", "clinic", "school", "university", "factory",
    "road", "settlement", "worship", "market", "bus_station",
}


# ── In-memory asset cache ────────────────────────────────────────────────
# Loaded once from GCS on first query, then reused for the process lifetime.

_asset_df: pd.DataFrame | None = None


def _load_assets() -> pd.DataFrame:
    """Load civic-asset Parquet from GCS into memory (lazy singleton)."""
    global _asset_df
    if _asset_df is not None:
        return _asset_df

    from app.core.config import settings
    bucket_name = settings.OPS_FORECASTS_BUCKET or "paqi-forecasts-hawanama-data"
    blob_path = "assets/civic_assets_pk.parquet"

    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(bucket_name).blob(blob_path)
        buf = io.BytesIO()
        blob.download_to_file(buf)
        buf.seek(0)
        _asset_df = pd.read_parquet(buf)
        logger.info(
            "Loaded %d civic assets from gs://%s/%s",
            len(_asset_df), bucket_name, blob_path,
        )
    except Exception as e:
        logger.warning("Failed to load civic assets from GCS: %s", e)
        _asset_df = pd.DataFrame(
            columns=["name", "asset_type", "lat", "lon", "osm_id",
                     "city_name", "state_name", "source"],
        )

    return _asset_df


# ── Helpers ───────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters."""
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _bbox_filter(
    df: pd.DataFrame, lat: float, lon: float, radius_m: int,
) -> pd.DataFrame:
    """Fast rectangular pre-filter before exact haversine check."""
    # ~111 km per degree of latitude; adjust longitude for latitude
    margin_deg = (radius_m / 111_000) * 1.2  # 20% safety margin
    lon_margin = margin_deg / max(math.cos(math.radians(lat)), 0.01)
    return df[
        (df["lat"] >= lat - margin_deg)
        & (df["lat"] <= lat + margin_deg)
        & (df["lon"] >= lon - lon_margin)
        & (df["lon"] <= lon + lon_margin)
    ]


# ── Public: get_nearest_assets ────────────────────────────────────────────

async def get_nearest_assets(
    lat: float,
    lon: float,
    asset_types: list[str],
    radius_m: int = 5000,
    limit: int = 20,
    sort_by: str = "distance",
) -> dict[str, Any]:
    """Find nearby civic assets from the pre-seeded GCS Parquet.

    Args:
        lat, lon: Anchor point (decimal degrees).
        asset_types: List of types to search (see VALID_ASSET_TYPES).
        radius_m: Search radius in meters (500–25 000).
        limit: Max results to return.
        sort_by: "distance" or "name".

    Returns:
        Dict with anchor, radius_m, assets, counts_by_type, notes, status.
    """
    radius_m = max(500, min(25_000, radius_m))
    valid_types = [t for t in asset_types if t in VALID_ASSET_TYPES]
    if not valid_types:
        valid_types = ["hospital", "school"]

    df = _load_assets()
    if df.empty:
        return {
            "anchor": {"lat": lat, "lon": lon},
            "radius_m": radius_m,
            "assets": [],
            "counts_by_type": {},
            "notes": ["Civic asset data not loaded — run seed_civic_assets.py and upload to GCS."],
            "status": "no_data",
        }

    # Filter by asset type
    subset = df[df["asset_type"].isin(valid_types)]

    # Fast bbox pre-filter
    subset = _bbox_filter(subset, lat, lon, radius_m)

    # Exact haversine distances
    assets: list[dict] = []
    for _, row in subset.iterrows():
        dist = round(_haversine_m(lat, lon, row["lat"], row["lon"]))
        if dist <= radius_m:
            assets.append({
                "name": row.get("name", ""),
                "asset_type": row["asset_type"],
                "lat": round(row["lat"], 6),
                "lon": round(row["lon"], 6),
                "distance_m": dist,
                "source": "OSM",
                "osm_id": row.get("osm_id", ""),
                "admin": {
                    "district": row.get("city_name", ""),
                    "province": row.get("state_name", ""),
                },
            })

    # Sort
    if sort_by == "name":
        assets.sort(key=lambda a: a["name"])
    else:
        assets.sort(key=lambda a: a["distance_m"])

    # Counts by type (before truncation)
    counts: dict[str, int] = {}
    for a in assets:
        counts[a["asset_type"]] = counts.get(a["asset_type"], 0) + 1

    # Truncate
    total_found = len(assets)
    assets = assets[:limit]

    notes: list[str] = []
    if total_found > limit:
        notes.append(
            f"Showing {limit} of {total_found} assets within {radius_m}m."
        )
    if not assets:
        notes.append(
            f"No {', '.join(valid_types)} found within {radius_m}m of the anchor point."
        )

    return {
        "anchor": {"lat": lat, "lon": lon},
        "radius_m": radius_m,
        "assets": assets,
        "counts_by_type": counts,
        "notes": notes,
        "status": "ok" if assets else "no_results",
    }


# ══════════════════════════════════════════════════════════════════════════
# Sentinel-2 catalog via CDSE STAC
# ══════════════════════════════════════════════════════════════════════════

def _bbox_around(lat: float, lon: float, buffer_km: float = 10.0) -> list[float]:
    """Create a bounding box [west, south, east, north] around a point."""
    dlat = buffer_km / 111.0
    dlon = buffer_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return [
        round(lon - dlon, 4),
        round(lat - dlat, 4),
        round(lon + dlon, 4),
        round(lat + dlat, 4),
    ]


async def get_sentinel_catalog(
    lat: float,
    lon: float,
    date_from: str | None = None,
    date_to: str | None = None,
    max_cloud_cover: float = 20.0,
    collection: str = "sentinel-2-l2a",
    mode: str = "latest",
    buffer_km: float = 10.0,
) -> dict[str, Any]:
    """Query CDSE STAC for Sentinel-2 scenes intersecting the AOI.

    Modes:
        latest — most recent scene below cloud threshold.
        nearest_to_date — closest to date_from.
        before_after — one scene before and one scene after date_from.

    Returns dict with status, scene metadata, preview URL, etc.
    """
    today = date.today()
    if not date_to:
        date_to = today.isoformat()
    if not date_from:
        date_from = (today - timedelta(days=30)).isoformat()

    max_cloud_cover = max(0, min(100, max_cloud_cover))
    bbox = _bbox_around(lat, lon, buffer_km)

    search_body = {
        "collections": ["SENTINEL-2"],
        "bbox": bbox,
        "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
        "limit": 50,
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(CDSE_STAC_URL, json=search_body)
            resp.raise_for_status()
            stac_resp = resp.json()
    except httpx.TimeoutException:
        return {
            "status": "timeout",
            "reason": "CDSE STAC API timed out",
            "collection": collection,
        }
    except Exception as e:
        logger.error("CDSE STAC query failed: %s", e)
        return {
            "status": "error",
            "reason": f"CDSE catalog query failed: {type(e).__name__}",
            "collection": collection,
        }

    # Filter for L2A + cloud cover
    scenes: list[dict] = []
    for f in stac_resp.get("features", []):
        props = f.get("properties", {})
        cloud = props.get("eo:cloud_cover")
        title = (props.get("title") or f.get("id") or "").upper()
        if "L2A" not in title and "MSIL2A" not in title:
            continue
        if cloud is not None and cloud > max_cloud_cover:
            continue

        # Extract preview URL
        stac_assets = f.get("assets", {})
        preview_url = ""
        for key in ("thumbnail", "preview", "rendered_preview"):
            if key in stac_assets:
                preview_url = stac_assets[key].get("href", "")
                break

        scenes.append({
            "scene_id": f.get("id", ""),
            "acquisition_date": (props.get("datetime") or "")[:10],
            "cloud_cover": round(cloud, 1) if cloud is not None else None,
            "processing_level": "L2A",
            "preview_url": preview_url,
            "bbox": f.get("bbox"),
        })

    if not scenes:
        return {
            "status": "no_suitable_scene",
            "reason": (
                f"No Sentinel-2 L2A scene intersecting AOI with "
                f"cloud cover <= {max_cloud_cover}% "
                f"in {date_from} to {date_to}"
            ),
            "collection": collection,
            "bbox": bbox,
        }

    # ── Mode selection ──
    if mode == "nearest_to_date":
        target = date_from
        scenes.sort(
            key=lambda s: abs(
                (date.fromisoformat(s["acquisition_date"])
                 - date.fromisoformat(target)).days
            )
        )
        return {
            "status": "ok",
            "collection": collection,
            "mode": "nearest_to_date",
            "target_date": target,
            "scene": scenes[0],
            "total_candidates": len(scenes),
            "bbox": bbox,
            "notes": [f"Closest scene to {target} ({len(scenes)} candidates)"],
        }

    if mode == "before_after":
        target_d = date.fromisoformat(date_from)
        before = [
            s for s in scenes
            if date.fromisoformat(s["acquisition_date"]) < target_d
        ]
        after = [
            s for s in scenes
            if date.fromisoformat(s["acquisition_date"]) >= target_d
        ]

        before_scene = None
        if before:
            before.sort(key=lambda s: s["acquisition_date"], reverse=True)
            before_scene = before[0]

        after_scene = None
        if after:
            after.sort(key=lambda s: s["acquisition_date"])
            after_scene = after[0]

        if before_scene is None and after_scene is None:
            return {
                "status": "no_suitable_scene",
                "reason": "No suitable before or after scenes found",
                "collection": collection,
                "bbox": bbox,
            }

        return {
            "status": "ok",
            "collection": collection,
            "mode": "before_after",
            "target_date": date_from,
            "before": before_scene,
            "after": after_scene,
            "total_candidates": len(scenes),
            "bbox": bbox,
            "notes": [
                f"Before: {before_scene['acquisition_date'] if before_scene else 'none found'}",
                f"After: {after_scene['acquisition_date'] if after_scene else 'none found'}",
            ],
        }

    # Default: latest
    return {
        "status": "ok",
        "collection": collection,
        "mode": "latest",
        "scene": scenes[0],
        "total_candidates": len(scenes),
        "bbox": bbox,
        "notes": [
            f"Latest low-cloud scene intersecting AOI "
            f"({len(scenes)} candidates in window)"
        ],
    }
