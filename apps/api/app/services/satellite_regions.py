"""The regions the satellite column series are kept for, and how a place name maps to one.

The 24 ids and geometries follow air_copilot's ``atminvest`` region registry so that the 2020–2025
history exported from its grids and the days fetched here on Earth Engine describe the same
polygons: nine boxes (the Lahore study boxes, the Pakistan analysis domain, the neighbouring
source regions), eight cities as 25 km geodesic buffers around a receptor, and the seven Pakistan
provinces/territories from apps/api/data/pakistan_provinces.geojson (geoBoundaries ADM1).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
PROVINCES_FILE = os.path.join(DATA_DIR, "pakistan_provinces.geojson")

CITY_BUFFER_KM = 25.0

# slug -> (label, lat, lon)
CITIES: Dict[str, Tuple[str, float, float]] = {
    "lahore": ("Lahore", 31.4977, 74.3007),
    "karachi": ("Karachi", 24.8607, 67.0011),
    "isb_rwp": ("Islamabad/Rawalpindi", 33.6248, 73.0324),
    "peshawar": ("Peshawar", 34.0151, 71.5249),
    "faisalabad": ("Faisalabad", 31.4504, 73.1350),
    "multan": ("Multan", 30.1575, 71.5249),
    "quetta": ("Quetta", 30.1798, 66.9750),
    "delhi": ("Delhi", 28.6139, 77.2090),
}

# id -> (label, (lat_min, lat_max, lon_min, lon_max))
BOXES: Dict[str, Tuple[str, Tuple[float, float, float, float]]] = {
    "lahore": ("Lahore box", (31.0, 32.0, 73.75, 74.75)),
    "upwind_w": ("Central Punjab west of Lahore", (30.5, 32.5, 71.5, 73.75)),
    "upwind_e": ("Indian Punjab and Haryana (Lahore box set)", (29.5, 32.0, 74.75, 77.5)),
    "wide": ("Lahore satellite extraction box", (29.5, 33.5, 71.5, 76.5)),
    "pk_domain": ("Pakistan analysis domain", (23.0, 37.5, 60.5, 78.0)),
    "in_punjab_haryana": ("Indian Punjab and Haryana", (28.5, 32.5, 74.5, 77.6)),
    "af_east": ("Eastern Afghanistan", (31.0, 36.0, 66.0, 71.0)),
    "thar_rajasthan": ("Thar and western Rajasthan", (24.0, 29.0, 69.5, 74.0)),
    "arabian_sea_coast": ("Makran and Sindh coast", (23.0, 25.8, 61.5, 68.5)),
}

# key -> (label, shapeName in the ADM1 file)
PROVINCES: Dict[str, Tuple[str, str]] = {
    "punjab": ("Punjab", "Punjab"),
    "sindh": ("Sindh", "Sindh"),
    "kp": ("Khyber Pakhtunkhwa", "Khyber Pakhtunkhwa"),
    "balochistan": ("Balochistan", "Balochistan"),
    "gb": ("Gilgit-Baltistan", "Gilgit-Baltistan"),
    "ajk": ("Azad Jammu & Kashmir", "Azad Kashmir"),
    "ict": ("Islamabad Capital Territory", "Islamabad Capital Territory"),
}

PROVINCE_SIMPLIFY_DEG = 0.005


def city_id(slug: str) -> str:
    return f"city:{slug}:r{int(CITY_BUFFER_KM)}"


def province_id(key: str) -> str:
    return f"province:{key}"


REGION_IDS: List[str] = [*BOXES.keys(), *(city_id(s) for s in CITIES), *(province_id(k) for k in PROVINCES)]


def kind_of(region_id: str) -> str:
    if region_id.startswith("city:"):
        return "city"
    if region_id.startswith("province:"):
        return "province"
    return "box"


def label(region_id: str) -> str:
    if region_id in BOXES:
        return BOXES[region_id][0]
    m = re.fullmatch(r"city:([a-z_]+):r(\d+)", region_id)
    if m and m.group(1) in CITIES:
        return f"{CITIES[m.group(1)][0]} ({m.group(2)} km)"
    if region_id.startswith("province:") and region_id[9:] in PROVINCES:
        return PROVINCES[region_id[9:]][0]
    return region_id


def receptor(region_id: str) -> Optional[Tuple[float, float]]:
    m = re.fullmatch(r"city:([a-z_]+):r(\d+)", region_id)
    if m and m.group(1) in CITIES:
        _, lat, lon = CITIES[m.group(1)]
        return lat, lon
    return None


# ── geometry ──────────────────────────────────────────────────────────────────

def _buffer(lat: float, lon: float, km: float):
    """Geodesic circle: a planar buffer in an azimuthal-equidistant projection centred on the point."""
    from pyproj import Transformer
    from shapely.geometry import Point
    from shapely.ops import transform

    inv = Transformer.from_crs(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +units=km", "EPSG:4326", always_xy=True)
    circle = Point(0, 0).buffer(km, quad_segs=64)
    return transform(lambda x, y, z=None: inv.transform(x, y), circle)


@lru_cache(maxsize=1)
def _province_shapes() -> Dict[str, object]:
    from shapely.geometry import shape

    with open(PROVINCES_FILE) as f:
        feats = json.load(f)["features"]
    by_name = {feat["properties"].get("shapeName"): shape(feat["geometry"]) for feat in feats}
    out = {}
    for key, (_, shape_name) in PROVINCES.items():
        geom = by_name.get(shape_name)
        if geom is None:
            raise KeyError(f"province {shape_name!r} not in {PROVINCES_FILE}")
        out[key] = geom.simplify(PROVINCE_SIMPLIFY_DEG, preserve_topology=True).buffer(0)
    return out


@lru_cache(maxsize=1)
def geometries() -> Dict[str, object]:
    """region id -> shapely geometry (WGS84), in REGION_IDS order."""
    from shapely.geometry import box

    out: Dict[str, object] = {}
    for rid, (_, (la0, la1, lo0, lo1)) in BOXES.items():
        out[rid] = box(lo0, la0, lo1, la1)
    for slug, (_, lat, lon) in CITIES.items():
        out[city_id(slug)] = _buffer(lat, lon, CITY_BUFFER_KM)
    shapes = _province_shapes()
    for key in PROVINCES:
        out[province_id(key)] = shapes[key]
    return out


def geom_hash(region_id: str) -> str:
    from shapely import wkt

    g = geometries()[region_id]
    return hashlib.sha1(wkt.dumps(g, rounding_precision=5).encode()).hexdigest()[:12]


def to_geojson() -> Dict[str, object]:
    from shapely.geometry import mapping

    feats = []
    for rid, g in geometries().items():
        props = {"id": rid, "kind": kind_of(rid), "label": label(rid), "geom_hash": geom_hash(rid)}
        r = receptor(rid)
        if r:
            props["receptor"] = {"lat": r[0], "lon": r[1]}
        feats.append({"type": "Feature", "properties": props, "geometry": mapping(g)})
    return {"type": "FeatureCollection", "features": feats}


# ── place names ───────────────────────────────────────────────────────────────

_ALIASES: Dict[str, str] = {
    "pakistan": "pk_domain", "national": "pk_domain", "pk": "pk_domain", "pk domain": "pk_domain",
    "lahore": city_id("lahore"), "karachi": city_id("karachi"),
    "islamabad": city_id("isb_rwp"), "rawalpindi": city_id("isb_rwp"), "isb": city_id("isb_rwp"),
    "islamabad rawalpindi": city_id("isb_rwp"), "isb rwp": city_id("isb_rwp"), "twin cities": city_id("isb_rwp"),
    "peshawar": city_id("peshawar"), "faisalabad": city_id("faisalabad"), "multan": city_id("multan"),
    "quetta": city_id("quetta"), "delhi": city_id("delhi"), "new delhi": city_id("delhi"),
    "punjab": province_id("punjab"), "pakistan punjab": province_id("punjab"), "sindh": province_id("sindh"),
    "kp": province_id("kp"), "kpk": province_id("kp"), "khyber pakhtunkhwa": province_id("kp"), "khyber": province_id("kp"),
    "balochistan": province_id("balochistan"), "baluchistan": province_id("balochistan"),
    "gb": province_id("gb"), "gilgit baltistan": province_id("gb"), "gilgit": province_id("gb"),
    "ajk": province_id("ajk"), "azad kashmir": province_id("ajk"), "azad jammu kashmir": province_id("ajk"),
    "ict": province_id("ict"), "islamabad capital territory": province_id("ict"),
    "indian punjab": "in_punjab_haryana", "haryana": "in_punjab_haryana", "india punjab": "in_punjab_haryana",
    "indian punjab haryana": "in_punjab_haryana", "punjab haryana": "in_punjab_haryana",
    "afghanistan": "af_east", "eastern afghanistan": "af_east", "east afghanistan": "af_east",
    "thar": "thar_rajasthan", "rajasthan": "thar_rajasthan", "western rajasthan": "thar_rajasthan",
    "coast": "arabian_sea_coast", "makran": "arabian_sea_coast", "sindh coast": "arabian_sea_coast",
    "arabian sea": "arabian_sea_coast", "lahore box": "lahore", "upwind west": "upwind_w", "upwind east": "upwind_e",
}


def resolve_place(text: str) -> Optional[str]:
    """A region id for a place name (city, province, named box, 'Pakistan') or a region id itself; None if unknown."""
    s = (text or "").strip()
    if not s:
        return None
    if s in geometries():
        return s
    key = re.sub(r"[^a-z0-9 ]+", " ", s.lower().replace("&", " "))
    key = re.sub(r"\s+", " ", key).strip()
    key = re.sub(r"\b(the|city of|province of|province|territory|region|area|city|of)\b", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    if key in _ALIASES:
        return _ALIASES[key]
    for slug in CITIES:
        if key == slug.replace("_", " "):
            return city_id(slug)
    return None
