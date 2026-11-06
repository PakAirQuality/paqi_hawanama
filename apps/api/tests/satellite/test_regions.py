"""satellite_regions: the 24 region polygons and the place-name resolver."""

import math

from app.services import satellite_regions as sr


def test_the_registry_has_the_24_regions_in_a_fixed_order():
    assert len(sr.REGION_IDS) == 24   # 9 boxes, 8 cities, 7 provinces
    assert sr.REGION_IDS[:9] == list(sr.BOXES)
    assert sr.REGION_IDS[9] == "city:lahore:r25" and sr.REGION_IDS[-1] == "province:ict"
    assert {sr.kind_of(r) for r in sr.REGION_IDS} == {"box", "city", "province"}
    assert sr.label("city:isb_rwp:r25") == "Islamabad/Rawalpindi (25 km)"
    assert sr.label("province:kp") == "Khyber Pakhtunkhwa"
    assert sr.label("upwind_e").startswith("Indian Punjab")


def test_city_buffers_are_25_km_circles_and_provinces_come_from_the_adm1_file():
    g = sr.geometries()
    assert set(g) == set(sr.REGION_IDS)
    lat, lon = sr.receptor("city:lahore:r25")
    ring = list(g["city:lahore:r25"].exterior.coords)
    # every vertex is ~25 km from the receptor (equirectangular check is good to a few hundred metres here)
    dists = [math.hypot((y - lat) * 111.195, (x - lon) * 111.195 * math.cos(math.radians(lat))) for x, y in ring]
    assert 24.5 < min(dists) and max(dists) < 25.5
    pb = g["province:punjab"]
    assert pb.contains(g["city:lahore:r25"].centroid)
    assert not pb.contains(g["city:karachi:r25"].centroid)
    assert g["pk_domain"].bounds == (60.5, 23.0, 78.0, 37.5)
    assert g["province:sindh"].contains(g["city:karachi:r25"].centroid)


def test_geojson_and_hashes_are_stable():
    geo = sr.to_geojson()
    ids = [f["properties"]["id"] for f in geo["features"]]
    assert ids == sr.REGION_IDS
    h1 = {f["properties"]["id"]: f["properties"]["geom_hash"] for f in geo["features"]}
    h2 = {r: sr.geom_hash(r) for r in sr.REGION_IDS}
    assert h1 == h2 and all(len(v) == 12 for v in h1.values())
    lahore = next(f for f in geo["features"] if f["properties"]["id"] == "city:lahore:r25")
    assert lahore["properties"]["receptor"] == {"lat": 31.4977, "lon": 74.3007}


def test_place_names_resolve_to_region_ids():
    assert sr.resolve_place("Lahore") == "city:lahore:r25"
    assert sr.resolve_place("the city of Lahore") == "city:lahore:r25"
    assert sr.resolve_place("Rawalpindi") == "city:isb_rwp:r25"
    assert sr.resolve_place("KP") == "province:kp"
    assert sr.resolve_place("Khyber Pakhtunkhwa province") == "province:kp"
    assert sr.resolve_place("Azad Jammu & Kashmir") == "province:ajk"
    assert sr.resolve_place("Pakistan") == "pk_domain"
    assert sr.resolve_place("Indian Punjab") == "in_punjab_haryana"
    assert sr.resolve_place("Haryana") == "in_punjab_haryana"
    assert sr.resolve_place("province:sindh") == "province:sindh"       # ids pass through
    assert sr.resolve_place("Timbuktu") is None
    assert sr.resolve_place("") is None
