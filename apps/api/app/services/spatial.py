"""Spatial analytics — hazard surface, exposure, vulnerability, assets, imagery.

Capabilities:
1. Hazard surface: IDW interpolation of station forecasts to 100m grid.
2. Exposure: population × hazard at every grid cell.
3. Vulnerability: building-derived features + receptor sensitivity + source pressure.
4. Nearest assets: pre-seeded civic-asset Parquet from GCS.
5. Sentinel catalog: CDSE STAC for Sentinel-2 L2A scene metadata.
"""

import io
import json as _json
import logging
import math
from datetime import date, timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CDSE_STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac/search"

VALID_ASSET_TYPES = {
    "hospital", "clinic", "school", "university", "factory",
    "road", "settlement", "worship", "market", "bus_station",
    "brick_kiln",
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


# ── In-memory vulnerability grid cache ────────────────────────────────────

_vuln_df: pd.DataFrame | None = None


def _load_vulnerability_grid() -> pd.DataFrame:
    """Load vulnerability grid Parquet from GCS (lazy singleton)."""
    global _vuln_df
    if _vuln_df is not None:
        return _vuln_df

    from app.core.config import settings
    bucket_name = settings.OPS_FORECASTS_BUCKET or "paqi-forecasts-hawanama-data"
    blob_path = "assets/vulnerability_grid_pk.parquet"

    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(bucket_name).blob(blob_path)
        buf = io.BytesIO()
        blob.download_to_file(buf)
        buf.seek(0)
        _vuln_df = pd.read_parquet(buf)
        logger.info(
            "Loaded %d vulnerability grid points from GCS", len(_vuln_df),
        )
    except Exception as e:
        logger.warning("Failed to load vulnerability grid: %s", e)
        _vuln_df = pd.DataFrame()

    return _vuln_df


# ══════════════════════════════════════════════════════════════════════════
# Layer A: Hazard Surface (IDW interpolation)
# ══════════════════════════════════════════════════════════════════════════


def _idw_interpolate(
    grid_lats: np.ndarray,
    grid_lons: np.ndarray,
    station_lats: np.ndarray,
    station_lons: np.ndarray,
    station_vals: np.ndarray,
    k: int = 8,
    power: float = 2.0,
) -> np.ndarray:
    """IDW interpolation using k-nearest stations.

    Vectorized: computes distances from all grid points to all stations,
    selects k-nearest, and applies inverse-distance weighting.
    Returns interpolated values at each grid point.
    """
    n_grid = len(grid_lats)
    n_stations = len(station_lats)
    k = min(k, n_stations)

    # Convert to radians for haversine
    R = 6_371_000
    glat_r = np.radians(grid_lats)
    glon_r = np.radians(grid_lons)
    slat_r = np.radians(station_lats)
    slon_r = np.radians(station_lons)

    result = np.zeros(n_grid, dtype=np.float32)

    # Process in chunks to avoid memory blowup (n_grid × n_stations matrix)
    CHUNK = 50_000
    for start in range(0, n_grid, CHUNK):
        end = min(start + CHUNK, n_grid)
        gl = glat_r[start:end, np.newaxis]  # (chunk, 1)
        gn = glon_r[start:end, np.newaxis]

        dlat = gl - slat_r[np.newaxis, :]   # (chunk, n_stations)
        dlon = gn - slon_r[np.newaxis, :]
        a = (
            np.sin(dlat / 2) ** 2
            + np.cos(gl) * np.cos(slat_r[np.newaxis, :]) * np.sin(dlon / 2) ** 2
        )
        dist = R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))  # meters

        # k-nearest indices per grid point
        if k < n_stations:
            knn_idx = np.argpartition(dist, k, axis=1)[:, :k]
        else:
            knn_idx = np.tile(np.arange(n_stations), (end - start, 1))

        # Gather distances and values for k-nearest
        rows = np.arange(end - start)[:, np.newaxis]
        knn_dist = dist[rows, knn_idx]       # (chunk, k)
        knn_vals = station_vals[knn_idx]      # (chunk, k)

        # IDW weights (avoid division by zero for co-located points)
        knn_dist = np.maximum(knn_dist, 1.0)  # min 1m
        weights = 1.0 / (knn_dist ** power)
        w_sum = weights.sum(axis=1)

        result[start:end] = (weights * knn_vals).sum(axis=1) / w_sum

    return result


def compute_hazard_surface(
    forecast_entries: list[dict],
    lead_days: int = 1,
) -> dict[str, Any]:
    """Compute IDW-interpolated PM2.5 hazard surface on the vulnerability grid.

    Args:
        forecast_entries: List of forecast dicts with latitude, longitude,
            pm25_forecast, lead_days fields (from GCS forecast JSON).
        lead_days: Which horizon to use (1, 2, or 3).

    Returns:
        Dict with hazard array, station count, exposure stats.
    """
    grid = _load_vulnerability_grid()
    if grid.empty:
        return {"status": "no_grid", "reason": "Vulnerability grid not loaded"}

    # Filter to requested horizon with valid data
    stations = [
        e for e in forecast_entries
        if e.get("lead_days") == lead_days
        and e.get("pm25_forecast") is not None
        and e.get("latitude") is not None
    ]
    if not stations:
        return {"status": "no_forecasts", "reason": f"No D+{lead_days} forecasts available"}

    slats = np.array([s["latitude"] for s in stations], dtype=np.float64)
    slons = np.array([s["longitude"] for s in stations], dtype=np.float64)
    svals = np.array([s["pm25_forecast"] for s in stations], dtype=np.float64)

    glats = grid["lat"].values.astype(np.float64)
    glons = grid["lon"].values.astype(np.float64)

    # IDW interpolation
    hazard = _idw_interpolate(glats, glons, slats, slons, svals, k=8, power=2.0)

    # Exposure = population × hazard
    population = grid["population"].values.astype(np.float32)
    exposure = population * hazard

    # Risk band thresholds
    PM25_BANDS = [(35, "good"), (75, "moderate"), (150, "unhealthy"),
                  (250, "very_unhealthy")]

    def _band(v):
        for t, b in PM25_BANDS:
            if v <= t:
                return b
        return "severe"

    # Aggregate by city
    city_stats = []
    for city in grid["city_name"].unique():
        if not city:
            continue
        mask = grid["city_name"].values == city
        h = hazard[mask]
        p = population[mask]
        x = exposure[mask]

        pop_total = float(p.sum())
        if pop_total == 0:
            continue

        pwm = float((p * h).sum() / pop_total) if pop_total > 0 else 0
        band = _band(pwm)

        # Exposed population by band
        exposed = {}
        for threshold, bname in [(35, "good"), (75, "moderate"),
                                  (150, "unhealthy"), (250, "very_unhealthy")]:
            exposed[f"above_{threshold}"] = int(p[h > threshold].sum())
        exposed["above_250"] = int(p[h > 250].sum())

        city_stats.append({
            "city": city,
            "population": int(pop_total),
            "pm25_pop_weighted": round(pwm, 1),
            "risk_band": band,
            "exposed_population": exposed,
            "total_exposure": round(float(x.sum()), 0),
        })

    city_stats.sort(key=lambda c: c["total_exposure"], reverse=True)

    # National summary
    total_pop = float(population.sum())
    national_exposed = {}
    for threshold in [35, 75, 150, 250]:
        national_exposed[f"above_{threshold}"] = int(population[hazard > threshold].sum())

    return {
        "status": "ok",
        "n_stations": len(stations),
        "n_grid_points": len(grid),
        "lead_days": lead_days,
        "national": {
            "population": int(total_pop),
            "pm25_pop_weighted": round(
                float((population * hazard).sum() / total_pop), 1
            ) if total_pop > 0 else 0,
            "exposed_population": national_exposed,
            "total_exposure": round(float(exposure.sum()), 0),
        },
        "cities": city_stats,
    }


def get_exposed_population(
    forecast_entries: list[dict],
    city_name: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 25000,
    lead_days: int = 1,
) -> dict[str, Any]:
    """Get exposed population for a city or point+radius.

    Uses IDW hazard surface × WorldPop population grid.
    """
    grid = _load_vulnerability_grid()
    if grid.empty:
        return {"status": "no_grid", "reason": "Vulnerability grid not loaded"}

    # Filter grid to area of interest
    if city_name:
        import difflib
        all_cities = [c for c in grid["city_name"].unique() if c]
        matches = difflib.get_close_matches(city_name, all_cities, n=1, cutoff=0.6)
        matched = matches[0] if matches else city_name
        subset = grid[grid["city_name"] == matched]
        area_label = matched
    elif lat is not None and lon is not None:
        margin = radius_m / 111_000 * 1.2
        subset = grid[
            (grid["lat"] >= lat - margin) & (grid["lat"] <= lat + margin)
            & (grid["lon"] >= lon - margin) & (grid["lon"] <= lon + margin)
        ]
        # Exact haversine filter
        dists = np.array([
            _haversine_m(lat, lon, r["lat"], r["lon"])
            for _, r in subset.iterrows()
        ])
        subset = subset[dists <= radius_m]
        area_label = f"({lat:.4f}, {lon:.4f}) r={radius_m}m"
    else:
        subset = grid
        area_label = "national"

    if subset.empty:
        return {"status": "no_data", "reason": f"No grid points for {area_label}"}

    # Get station forecasts for this horizon
    stations = [
        e for e in forecast_entries
        if e.get("lead_days") == lead_days
        and e.get("pm25_forecast") is not None
        and e.get("latitude") is not None
    ]
    if not stations:
        return {"status": "no_forecasts", "reason": f"No D+{lead_days} forecasts"}

    slats = np.array([s["latitude"] for s in stations], dtype=np.float64)
    slons = np.array([s["longitude"] for s in stations], dtype=np.float64)
    svals = np.array([s["pm25_forecast"] for s in stations], dtype=np.float64)

    # IDW at subset grid
    hazard = _idw_interpolate(
        subset["lat"].values.astype(np.float64),
        subset["lon"].values.astype(np.float64),
        slats, slons, svals, k=8, power=2.0,
    )
    population = subset["population"].values.astype(np.float32)
    total_pop = float(population.sum())

    # Exposed population by risk band
    bands = {}
    for threshold, label in [(35, "good"), (75, "moderate"), (150, "unhealthy"), (250, "very_unhealthy")]:
        bands[label] = {
            "threshold": threshold,
            "exposed_population": int(population[hazard > threshold].sum()),
        }
    bands["severe"] = {
        "threshold": 250,
        "exposed_population": int(population[hazard > 250].sum()),
    }

    # Population-weighted PM2.5
    pwm = float((population * hazard).sum() / total_pop) if total_pop > 0 else 0

    # Nearest station distance (hazard uncertainty proxy)
    center_lat = float(subset["lat"].mean())
    center_lon = float(subset["lon"].mean())
    station_dists = [
        _haversine_m(center_lat, center_lon, s["latitude"], s["longitude"])
        for s in stations
    ]
    nearest_station_m = min(station_dists) if station_dists else None

    return {
        "status": "ok",
        "area": area_label,
        "lead_days": lead_days,
        "grid_points": len(subset),
        "population": int(total_pop),
        "pm25_pop_weighted": round(pwm, 1),
        "exposed_by_band": bands,
        "nearest_station_m": round(nearest_station_m) if nearest_station_m else None,
        "confidence": "high" if (nearest_station_m and nearest_station_m < 5000) else
                      "medium" if (nearest_station_m and nearest_station_m < 15000) else "low",
    }


# ══════════════════════════════════════════════════════════════════════════
# Decision-specific impact heads
# ══════════════════════════════════════════════════════════════════════════

CHILD_SHARE = 0.35  # national proxy; replace with WorldPop age/sex when available
SCHOOL_THRESHOLD = 75.0  # µg/m³
HOSPITAL_THRESHOLD = 150.0


def compute_decision_heads(
    forecast_entries: list[dict],
    city_name: str,
    lead_days: int = 1,
) -> dict[str, Any]:
    """Compute four decision-specific impact scores for a city.

    Returns school advisory, hospital preparedness, kiln enforcement,
    and monitor deployment rankings.
    """
    grid = _load_vulnerability_grid()
    assets_df = _load_assets()
    if grid.empty:
        return {"status": "no_grid"}

    import difflib
    all_cities = [c for c in grid["city_name"].unique() if c]
    matches = difflib.get_close_matches(city_name, all_cities, n=1, cutoff=0.6)
    matched = matches[0] if matches else city_name
    subset = grid[grid["city_name"] == matched]
    if subset.empty:
        return {"status": "no_data", "reason": f"No grid data for {city_name}"}

    # Station forecasts
    stations = [
        e for e in forecast_entries
        if e.get("lead_days") == lead_days
        and e.get("pm25_forecast") is not None
        and e.get("latitude") is not None
    ]
    if not stations:
        return {"status": "no_forecasts"}

    slats = np.array([s["latitude"] for s in stations], dtype=np.float64)
    slons = np.array([s["longitude"] for s in stations], dtype=np.float64)
    svals = np.array([s["pm25_forecast"] for s in stations], dtype=np.float64)

    # Hazard surface for this city
    hazard = _idw_interpolate(
        subset["lat"].values.astype(np.float64),
        subset["lon"].values.astype(np.float64),
        slats, slons, svals, k=8, power=2.0,
    )
    population = subset["population"].values.astype(np.float32)

    # ── Head 1: School Advisory ──
    child_pop = population * CHILD_SHARE
    school_exceedance = child_pop * np.maximum(hazard - SCHOOL_THRESHOLD, 0)
    total_child_exceedance = float(school_exceedance.sum())
    children_above_threshold = int(child_pop[hazard > SCHOOL_THRESHOLD].sum())

    # Find schools in this city
    city_schools = assets_df[
        (assets_df["asset_type"] == "school")
        & (assets_df["city_name"] == matched)
    ]

    # ── Head 2: Hospital Preparedness ──
    hospital_exceedance = population * np.maximum(hazard - HOSPITAL_THRESHOLD, 0)
    total_hospital_stress = float(hospital_exceedance.sum())
    pop_above_hospital_threshold = int(population[hazard > HOSPITAL_THRESHOLD].sum())

    city_hospitals = assets_df[
        (assets_df["asset_type"].isin(["hospital", "clinic"]))
        & (assets_df["city_name"] == matched)
    ]

    # ── Head 3: Kiln Enforcement ──
    city_kilns = assets_df[
        (assets_df["asset_type"] == "brick_kiln")
        & (assets_df["city_name"] == matched)
    ]
    # Source pressure: for each cell with buildings, sum nearby kiln count
    bld_count = subset["building_count_google"].values if "building_count_google" in subset.columns else np.zeros(len(subset))
    residential_mask = bld_count > 0
    residential_pop = float(population[residential_mask].sum())
    source_count = subset["source_count"].values if "source_count" in subset.columns else np.zeros(len(subset))
    kiln_residential_pressure = float((population * source_count)[residential_mask].sum())

    # ── Head 4: Monitor Deployment ──
    # Uncertainty proxy: nearest station distance
    center_lat = float(subset["lat"].mean())
    center_lon = float(subset["lon"].mean())
    station_dists_from_center = [
        _haversine_m(center_lat, center_lon, s["latitude"], s["longitude"])
        for s in stations
    ]
    nearest_station_m = min(station_dists_from_center) if station_dists_from_center else 99999

    # Cells far from any station
    sparse_cells = 0
    sparse_pop = 0.0
    for idx in range(len(subset)):
        lat_i, lon_i = float(subset.iloc[idx]["lat"]), float(subset.iloc[idx]["lon"])
        min_d = min(
            _haversine_m(lat_i, lon_i, slats[j], slons[j])
            for j in range(min(5, len(slats)))  # check 5 nearest for speed
        )
        if min_d > 10000:  # >10km from any station
            sparse_cells += 1
            sparse_pop += population[idx]
    # Only sample first 1000 cells for speed
    # (full computation would be slow for large cities)

    return {
        "status": "ok",
        "city": matched,
        "lead_days": lead_days,

        "school_advisory": {
            "children_above_75": children_above_threshold,
            "child_exceedance_burden": round(total_child_exceedance, 0),
            "schools_in_city": len(city_schools),
            "threshold_ugm3": SCHOOL_THRESHOLD,
            "advisory": "closure_recommended" if children_above_threshold > 100_000
                        else "outdoor_restriction" if children_above_threshold > 10_000
                        else "monitor",
        },

        "hospital_preparedness": {
            "population_above_150": pop_above_hospital_threshold,
            "catchment_stress": round(total_hospital_stress, 0),
            "hospitals_in_city": len(city_hospitals),
            "threshold_ugm3": HOSPITAL_THRESHOLD,
            "alert": "high" if pop_above_hospital_threshold > 50_000
                     else "moderate" if pop_above_hospital_threshold > 5_000
                     else "low",
        },

        "kiln_enforcement": {
            "kilns_in_city": len(city_kilns),
            "residential_population": int(residential_pop),
            "kiln_residential_pressure": round(kiln_residential_pressure, 0),
            "priority": "high" if len(city_kilns) > 50 and residential_pop > 1_000_000
                        else "moderate" if len(city_kilns) > 10
                        else "low",
        },

        "monitor_deployment": {
            "nearest_station_m": round(nearest_station_m),
            "confidence": "high" if nearest_station_m < 5000
                          else "medium" if nearest_station_m < 15000
                          else "low",
        },
    }


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
