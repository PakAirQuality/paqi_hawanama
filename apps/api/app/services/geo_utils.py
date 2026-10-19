"""Shared geo utilities — Pakistan boundary check, FIRMS CSV reader, city centroid."""

import csv
import io
import json
import logging
import math
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Pakistan boundary (cached) ──────────────────────────────────────────

_PAKISTAN_POLYGON = None


def _load_pakistan_polygon():
    """Load and cache the Pakistan country boundary as a shapely geometry."""
    global _PAKISTAN_POLYGON
    if _PAKISTAN_POLYGON is not None:
        return _PAKISTAN_POLYGON
    try:
        from shapely.geometry import shape

        data_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data")
        )
        boundary_path = os.path.join(data_dir, "pakistan_country.geojson")
        with open(boundary_path) as f:
            geojson = json.load(f)
        _PAKISTAN_POLYGON = shape(geojson["features"][0]["geometry"])
        logger.info("Loaded Pakistan boundary for geo_utils")
    except Exception as e:
        logger.warning(f"Failed to load Pakistan boundary: {e}")
        _PAKISTAN_POLYGON = None
    return _PAKISTAN_POLYGON


def point_in_pakistan(lat: float, lon: float) -> bool:
    """Check if a lat/lon point falls within Pakistan's boundary."""
    poly = _load_pakistan_polygon()
    if poly is None:
        return 23.5 <= lat <= 37.5 and 60.0 <= lon <= 78.0
    from shapely.geometry import Point

    return poly.contains(Point(lon, lat))


# ── FIRMS CSV from GCS ──────────────────────────────────────────────────


def load_firms_csv_from_gcs(date_str: str, fallback_days: int = 2) -> tuple[Optional[str], str]:
    """Read FIRMS CSV from GCS for a date, with fallback to adjacent days.

    Returns (csv_text, actual_date_used). csv_text is None if no data found.
    """
    from app.routers.analyst_desk import _gcs_read_text

    for offset in range(fallback_days + 1):
        d = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=offset)
        ds = d.strftime("%Y%m%d")
        raw = _gcs_read_text(f"hindcast/firms/firms_{ds}.csv")
        if raw and raw.strip() and "latitude" in raw.split("\n")[0]:
            return raw, d.strftime("%Y-%m-%d")

    return None, date_str


def parse_firms_csv_pakistan(csv_text: str) -> list[dict]:
    """Parse FIRMS CSV text and filter to Pakistan. Returns list of fire dicts."""
    fires = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        if not point_in_pakistan(lat, lon):
            continue
        try:
            frp = float(row.get("frp", 0))
        except (ValueError, TypeError):
            frp = 0.0
        fires.append({
            "latitude": lat,
            "longitude": lon,
            "frp": round(frp, 1),
            "confidence": row.get("confidence", ""),
            "acq_date": row.get("acq_date", ""),
            "satellite": row.get("satellite", ""),
        })
    return fires


# ── City centroid ────────────────────────────────────────────────────────


async def resolve_city_centroid(
    db: AsyncSession, city_name: str
) -> Optional[tuple[float, float]]:
    """Return (lat, lon) centroid for a city from its active stations."""
    result = await db.execute(
        text("""
            SELECT AVG(s.lat) AS lat, AVG(s.lon) AS lon
            FROM stations s
            JOIN cities c ON s.city_id = c.id
            WHERE LOWER(c.name) = LOWER(:city)
              AND s.active = true
              AND s.lat IS NOT NULL AND s.lon IS NOT NULL
        """),
        {"city": city_name},
    )
    row = result.mappings().first()
    if row and row["lat"] is not None and row["lon"] is not None:
        return (float(row["lat"]), float(row["lon"]))
    return None


# ── Haversine distance ───────────────────────────────────────────────────


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
