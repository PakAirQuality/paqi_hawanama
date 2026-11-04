"""Shared geo utilities — Pakistan boundary check, province rule, FIRMS CSV reader, city centroid."""

import csv
import io
import json
import logging
import math
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

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


# ── Provinces: one rule for the registry, the writers and the copilot ───────
#
# Polygons: geoBoundaries PAK ADM1 (2019, CC0, commit 9469f09), simplified file at
# apps/api/data/pakistan_provinces.geojson. Its shapeName values are mapped to states.name.
#
# The rule ("city first, geography second, tolerant near borders"):
#   * a station's province is its city's province when the city has one — the simplified
#     polygon puts 24 Rawalpindi stations inside Islamabad Capital Territory, the registry is
#     right there, so coordinates alone must not decide;
#   * a station without a city (Punjab EPA, BAM) takes the polygon containing its coordinates;
#   * a city's province is the polygon containing the median of its stations' coordinates,
#     unless the stored province differs and that median is within BORDER_KM of the polygon's
#     border — then the stored (source) province is kept (border_keep).

PROVINCE_SHAPE_TO_STATE = {"Islamabad Capital Territory": "Islamabad", "Azad Jammu and Kashmir": "Azad Kashmir"}
BORDER_KM = 10.0
_PROVINCE_POLYS: Optional[List[Tuple[str, Any]]] = None     # [(states.name, prepared polygon)]
_PROVINCE_SHAPES: Dict[str, Any] = {}                      # states.name -> raw shapely geometry
_KM_PER_DEGREE = 111.0


@dataclass(frozen=True)
class ProvinceDecision:
    province: Optional[str]      # the province the rule decides on (None: cannot decide)
    rule: str                    # city | geography | border_keep | unknown
    geo_province: Optional[str]  # the polygon containing the point, if any
    border_km: Optional[float] = None   # distance from the point to geo_province's border


def province_polygons() -> List[Tuple[str, Any]]:
    """[(states.name, prepared polygon)] for the 7 Pakistan provinces/territories; [] if the file fails."""
    global _PROVINCE_POLYS
    if _PROVINCE_POLYS is None:
        try:
            from shapely.geometry import shape
            from shapely.prepared import prep
            data_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
            with open(os.path.join(data_dir, "pakistan_provinces.geojson")) as f:
                feats = json.load(f)["features"]
            polys = []
            for feat in feats:
                name = PROVINCE_SHAPE_TO_STATE.get(feat["properties"]["shapeName"], feat["properties"]["shapeName"])
                geom = shape(feat["geometry"])
                _PROVINCE_SHAPES[name] = geom
                polys.append((name, prep(geom)))
            _PROVINCE_POLYS = polys
        except Exception as exc:  # noqa: BLE001 — without polygons the callers keep the registry link
            logger.warning("Failed to load province polygons: %s", exc)
            _PROVINCE_POLYS = []
    return _PROVINCE_POLYS


def province_for_point(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    """states.name of the province polygon containing the point, or None (no coordinates, sea, abroad)."""
    if lat is None or lon is None:
        return None
    from shapely.geometry import Point
    pt = Point(float(lon), float(lat))
    for name, poly in province_polygons():
        if poly.contains(pt):
            return name
    return None


def distance_to_province_border_km(lat: float, lon: float, province: str) -> Optional[float]:
    """Approximate distance (km) from the point to the border of the named province polygon."""
    province_polygons()
    geom = _PROVINCE_SHAPES.get(province)
    if geom is None:
        return None
    from shapely.geometry import Point
    return float(geom.boundary.distance(Point(float(lon), float(lat)))) * _KM_PER_DEGREE


def resolve_station_province(*, lat: Optional[float], lon: Optional[float], city_state: Optional[str]) -> ProvinceDecision:
    """The province a station belongs to: its city's, else the polygon containing it, else unknown."""
    geo = province_for_point(lat, lon)
    if city_state:
        return ProvinceDecision(city_state, "city", geo)
    if geo:
        return ProvinceDecision(geo, "geography", geo)
    return ProvinceDecision(None, "unknown", None)


def resolve_city_province(*, stored_state: Optional[str], station_points: Iterable[Tuple[float, float]],
                          border_km: float = BORDER_KM) -> ProvinceDecision:
    """The province a city belongs to, from the median of its stations' coordinates (see the rule above)."""
    pts = [(float(a), float(b)) for a, b in station_points if a is not None and b is not None]
    if not pts:
        return ProvinceDecision(stored_state, "unknown", None)
    lat = statistics.median(p[0] for p in pts)
    lon = statistics.median(p[1] for p in pts)
    geo = province_for_point(lat, lon)
    if geo is None:
        return ProvinceDecision(stored_state, "unknown", None)
    if stored_state and stored_state != geo:
        d = distance_to_province_border_km(lat, lon, geo)
        if d is not None and d < border_km:
            return ProvinceDecision(stored_state, "border_keep", geo, round(d, 1))
        return ProvinceDecision(geo, "geography", geo, round(d, 1) if d is not None else None)
    return ProvinceDecision(geo, "geography", geo)


async def pakistan_state_ids(db: AsyncSession) -> Dict[str, int]:
    """states.name -> states.id for Pakistan. {} when the lookup fails (callers then leave state_id NULL)."""
    try:
        res = await db.execute(text("""
            SELECT st.id, st.name FROM states st JOIN countries co ON co.id = st.country_id
            WHERE co.name = 'Pakistan'
        """))
        rows = res.fetchall() if res is not None else []
        return {r.name: int(r.id) for r in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pakistan states lookup failed; state_id stays NULL until the registry reconcile: %s", exc)
        return {}


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
