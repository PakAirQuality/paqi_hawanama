"""geo_utils province rule: polygons, the city-first decision and the border tolerance (real ADM1 file)."""

import pytest

from app.services import geo_utils as g


@pytest.mark.parametrize("place, lat, lon, expected", [
    ("Peshawar", 34.0, 71.55, "Khyber Pakhtunkhwa"), ("Charsadda", 34.1529, 71.7475, "Khyber Pakhtunkhwa"),
    ("Karachi", 24.86, 67.0, "Sindh"), ("Islamabad F-6", 33.72, 73.06, "Islamabad"), ("Skardu", 35.3, 75.6, "Gilgit-Baltistan"),
    ("Muzaffarabad", 34.37, 73.47, "Azad Kashmir"), ("Quetta", 30.2, 67.0, "Balochistan"), ("Lahore", 31.52, 74.35, "Punjab"),
    ("Karachi coast", 24.7518, 67.0728, None), ("RS Pura, India", 32.5721, 74.6686, None), ("no coordinates", None, None, None)])
def test_province_for_point_uses_the_adm1_boundaries(place, lat, lon, expected):
    assert g.province_for_point(lat, lon) == expected


def test_all_seven_shapes_map_to_states_names():
    assert {n for n, _ in g.province_polygons()} == {"Azad Kashmir", "Balochistan", "Gilgit-Baltistan", "Islamabad",
                                                     "Khyber Pakhtunkhwa", "Punjab", "Sindh"}
    assert g.distance_to_province_border_km(31.52, 74.35, "Punjab") > 20
    assert g.distance_to_province_border_km(31.52, 74.35, "Narnia") is None


def test_station_province_is_the_citys_else_the_polygon_else_unknown():
    assert g.resolve_station_province(lat=33.60, lon=73.14, city_state="Punjab") == g.ProvinceDecision("Punjab", "city", "Islamabad")
    assert g.resolve_station_province(lat=31.5, lon=74.3, city_state=None) == g.ProvinceDecision("Punjab", "geography", "Punjab")
    assert g.resolve_station_province(lat=24.7518, lon=67.0728, city_state=None) == g.ProvinceDecision(None, "unknown", None)
    assert g.resolve_station_province(lat=None, lon=None, city_state=None).rule == "unknown"


def test_city_province_follows_the_station_median_but_keeps_the_source_near_a_border():
    # Rawalpindi: most stations sit inside the simplified ICT polygon, 1.2 km from its border → keep Punjab
    d = g.resolve_city_province(stored_state="Punjab", station_points=[(33.60, 73.14), (33.60, 73.05), (33.62, 73.07)])
    assert d.rule == "border_keep" and d.province == "Punjab" and d.geo_province == "Islamabad" and d.border_km < g.BORDER_KM
    # Charsadda filed under Punjab: 58 km inside KP → change
    d = g.resolve_city_province(stored_state="Punjab", station_points=[(34.15, 71.75)])
    assert d == g.ProvinceDecision("Khyber Pakhtunkhwa", "geography", "Khyber Pakhtunkhwa", 58.6)
    # agreement, no state, and no stations
    assert g.resolve_city_province(stored_state="Punjab", station_points=[(31.5, 74.3)]).rule == "geography"
    assert g.resolve_city_province(stored_state=None, station_points=[(31.5, 74.3)]).province == "Punjab"
    assert g.resolve_city_province(stored_state="Punjab", station_points=[]) == g.ProvinceDecision("Punjab", "unknown", None)
    assert g.resolve_city_province(stored_state="Punjab", station_points=[(24.7518, 67.0728)]).rule == "unknown"


async def test_pakistan_state_ids_degrades_to_empty():
    class Boom:
        async def execute(self, *a):
            raise RuntimeError("no db")

    class NoneResult:
        async def execute(self, *a):
            return None

    assert await g.pakistan_state_ids(Boom()) == {}
    assert await g.pakistan_state_ids(NoneResult()) == {}
