"""fire_regions: attribution against the real boundary files, dedup, cells, wind and cone rules."""

import numpy as np
import pytest

from app.services import fire_regions as fr


@pytest.mark.parametrize("place, lat, lon, country, province, district", [
    ("Lahore", 31.52, 74.35, "PK", "Punjab", "Lahore"),
    ("Peshawar", 34.0, 71.55, "PK", "Khyber Pakhtunkhwa", "Peshawar"),
    ("Amritsar", 31.63, 74.87, "IN", "Punjab (IN)", None),
    ("Karnal", 29.69, 76.99, "IN", "Haryana (IN)", None),
    ("Kabul", 34.5, 69.2, "XX", None, None),
    ("Jaipur (Rajasthan, in bbox)", 26.9, 75.8, "XX", None, None),
    ("Arabian Sea", 23.5, 66.0, "XX", None, None),
])
def test_attribution_by_country_province_and_district(place, lat, lon, country, province, district):
    a = fr.attribute_points([lat], [lon])
    assert (a["country"][0], a["province"][0], a["district"][0]) == (country, province, district)


def test_attribution_is_vectorised_and_districts_sit_inside_their_province():
    rng = np.random.default_rng(1)
    lats, lons = rng.uniform(23, 37, 5000), rng.uniform(60, 78, 5000)
    a = fr.attribute_points(lats, lons)
    assert set(a["country"]) <= {"PK", "IN", "XX"} and (a["country"] == "PK").sum() > 500
    idx = fr.load_region_index()
    for prov, dist in zip(a["province"], a["district"]):
        if dist is not None:
            assert idx.district_province[dist] == prov
    assert len(idx.district_province) == 126 and all(idx.district_province.values())
    assert fr.attribute_points([], [])["country"].shape == (0,)


def test_dedup_merges_different_satellites_close_in_space_and_time_only():
    #            A: N20       B: N21 400 m, 50 min   D: N21 2 km    E: N21 3 h later
    lats = [31.5000, 31.5036, 31.5180, 31.5000]
    lons = [74.3000, 74.3000, 74.3000, 74.3000]
    sats = ["N20", "N21", "N21", "N21"]
    t0 = 1000.0
    g = fr.dedup_groups(lats, lons, sats, [t0, t0 + 50, t0 + 50, t0 + 180])
    assert g[0] == g[1]                       # one fire seen twice
    assert g[0] != g[2] and g[1] != g[2]      # 2 km apart
    assert g[0] != g[3]                       # 3 h apart
    # the same satellite never merges on its own: two pixels of one pass are two burning pixels
    g_same = fr.dedup_groups([31.5, 31.5036], [74.3, 74.3], ["N20", "N20"], [t0, t0])
    assert g_same[0] != g_same[1]
    # groups are transitive: N20–N21–N20 within 1 km of each other collapse to one fire
    g_chain = fr.dedup_groups([31.5, 31.5036, 31.5072], [74.3, 74.3, 74.3], ["N20", "N21", "N20"], [t0, t0 + 50, t0])
    assert g_chain[0] == g_chain[1] == g_chain[2]
    # old rows without times merge on distance alone
    g2 = fr.dedup_groups([31.5, 31.5072], [74.3, 74.3], ["N20", "N21"], [None, None])
    assert g2[0] == g2[1]
    assert fr.dedup_groups([], [], [], []).shape == (0,)
    prim = fr.primary_mask(np.array([0, 0, 1]), [5.0, 9.0, 1.0])
    assert prim.tolist() == [False, True, True]


def test_wind_conventions_cone_and_compass():
    assert round(fr.wind_from_deg(-3, -3)) == 45            # blowing towards SW comes FROM the NE
    assert round(fr.wind_from_deg(0, -1)) == 0 and round(fr.wind_from_deg(-1, 0)) == 90
    d, s = fr.vector_mean_from_deg([350, 10], [2, 2])
    assert d == 0.0 and s == 2.0
    assert fr.vector_mean_from_deg([], []) == (None, None)
    assert fr.vector_mean_from_deg([0, 180], [2, 2])[0] is None          # opposing winds cancel
    assert fr.in_cone([59, 61, 301, 299], 0).tolist() == [True, False, True, False]
    assert fr.in_cone([359, 1], 0).tolist() == [True, True]
    assert fr.compass(0) == "N" and fr.compass(315) == "NW" and fr.compass(None) is None
    b = fr.bearing_deg(31.5, 74.3, [32.5, 31.5], [74.3, 75.3])
    assert round(b[0]) == 0 and 85 <= b[1] <= 95
    assert abs(fr.haversine_km_vec(31.5, 74.3, [31.5], [75.3])[0] - 94.8) < 1


def test_cells_day_night_and_clusters():
    cid = fr.cell_id([31.5, 31.5, 31.53, 40.0], [74.3, 74.31, 74.3, 70.0])
    assert cid[0] == cid[1] and cid[0] != cid[2]
    lat, lon = fr.cell_center(int(cid[0]))
    assert abs(lat - 31.5) < 0.02 and abs(lon - 74.3) < 0.02
    assert fr.day_night([21.27, 8.25, None, float("nan")]).tolist() == ["N", "D", None, None]
    labels = fr.cluster_cells(cid)
    assert labels[0] == labels[1] == labels[2] and labels[3] != labels[0]      # touching cells join, far cell alone
    diag = fr.cell_id([31.50, 31.52], [74.30, 74.32])
    assert fr.cluster_cells(diag)[0] == fr.cluster_cells(diag)[1]              # diagonal neighbours join
    apart = fr.cell_id([31.50, 31.56], [74.30, 74.30])
    assert fr.cluster_cells(apart)[0] != fr.cluster_cells(apart)[1]            # three cells apart do not
