"""station_queries: the SQL the three precise tools run, checked against a recording fake db."""

from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest

from app.services.copilot import station_queries as q

PK_STATES = [NS(id=1, name="Azad Kashmir", code=None), NS(id=4, name="Islamabad", code="IS"),
             NS(id=5, name="Khyber Pakhtunkhwa", code="KP"), NS(id=6, name="Punjab", code="PB"), NS(id=7, name="Sindh", code="SD")]
PK_CITIES = [NS(id=10, name="Lahore", province="Punjab", lat=31.52, lon=74.35),
             NS(id=11, name="Peshawar", province="Khyber Pakhtunkhwa", lat=34.01, lon=71.55),
             NS(id=12, name="Mardan", province="Khyber Pakhtunkhwa", lat=None, lon=None),
             NS(id=13, name="Vehari", province="Punjab", lat=30.03, lon=72.35),
             NS(id=14, name="Vihari", province="Punjab", lat=30.04, lon=72.36),
             NS(id=15, name="Kotli", province="Azad Kashmir", lat=33.5, lon=73.9),
             NS(id=16, name="Kotla", province="Punjab", lat=32.0, lon=74.0)]
T = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def mappings(self):
        dicts = [dict(r.__dict__) if isinstance(r, NS) else r for r in self.rows]
        return NS(first=lambda: dicts[0] if dicts else None, all=lambda: dicts)


# registered stations as station_provinces() reads them: coordinates decide the province,
# the registry (st/cst) is wrong for the Karachi and Peshawar rows on purpose
REGISTRY = [NS(station_id="k" * 16, lat=24.86, lon=67.0, city_id=20, registry_province="Punjab"),      # Karachi filed under Punjab
            NS(station_id="p" * 16, lat=34.0, lon=71.55, city_id=11, registry_province="Punjab"),      # Peshawar filed under Punjab
            NS(station_id="q" * 16, lat=34.01, lon=71.56, city_id=11, registry_province="Khyber Pakhtunkhwa"),
            NS(station_id="l" * 16, lat=31.52, lon=74.35, city_id=10, registry_province="Punjab"),
            NS(station_id="n" * 16, lat=None, lon=None, city_id=None, registry_province="Sindh")]       # no coordinates


@pytest.fixture(autouse=True)
def _fresh_province_cache():
    q._STATION_PROVINCES.update(at=0.0, map={})
    yield
    q._STATION_PROVINCES.update(at=0.0, map={})


class FakeDB:
    def __init__(self, *, list_rows=None, station=None, period_rows=None, nearest_rows=None):
        self.calls: list[tuple[str, dict]] = []
        self.list_rows = list_rows or []
        self.station = station
        self.period_rows = period_rows or []
        self.nearest_rows = nearest_rows or []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        if sql.startswith("SET LOCAL"):
            return Result([])
        if "AS registry_province" in sql:
            return Result(REGISTRY)
        if "FROM states st JOIN countries co" in sql:
            return Result(PK_STATES)
        if "SELECT c.id, c.name, st.name AS province" in sql:
            return Result(PK_CITIES)
        if "AVG(s.lat) AS lat" in sql:
            return Result([NS(lat=34.2, lon=72.04)])
        if "FROM states WHERE id = :sid" in sql:
            return Result([NS(lat=34.0, lon=71.5)])
        if "LOWER(s.name) = LOWER(:name)" in sql or "WHERE s.station_id = :sid" in sql:
            return Result([self.station] if self.station else [])
        if "s.active = true AND s.name IS NOT NULL" in sql:
            return Result([])
        if "obs.first_obs" in sql:
            return Result(self.list_rows)
        if "ST_Azimuth" in sql:
            return Result(self.nearest_rows)
        if "FROM daily" in sql:
            return Result(self.period_rows)
        if "COUNT(*) AS registered" in sql and "GROUP BY 1, 2" in sql:
            return Result([NS(code="airvisual", display_name="IQAir", registered=40, active=38, reporting=35),
                           NS(code="punjab", display_name="Punjab EPA", registered=2, active=2, reporting=1)])
        if "COUNT(*) AS registered" in sql and "ORDER BY registered DESC, city" in sql:
            return Result([NS(city="Peshawar", registered=37, active=35, reporting=33)])
        if "COUNT(*) AS registered" in sql:
            return Result([NS(registered=42, active=40, reporting=36)])
        raise AssertionError("unexpected SQL: " + sql[:160])

    def sql(self, needle):
        return next((s, p) for s, p in self.calls if needle in s)


# ── definitions ──────────────────────────────────────────────────────────────

def test_registered_definition_is_pakistan_non_shadow_non_test():
    w = q.REGISTERED_WHERE
    assert "co.name = 'Pakistan'" in w and "'openaq'" in w and "'icimod'" in w
    assert "ingest_mode', '') <> 'shadow'" in w and "'status', '') <> 'test'" in w
    assert "punjab" not in w and "bam" not in w            # real monitors are counted


def test_pakistan_day_window_is_utc_minus_five_hours():
    w0, w1 = q.day_window_utc(date(2026, 11, 4))
    assert w0 == datetime(2026, 11, 3, 19, 0, tzinfo=timezone.utc) and w1 == datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)


# ── resolution ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("typed, expected", [("Lahore", "Lahore"), ("lahore", "Lahore"), ("Lahore!", "Lahore"), ("Pehsawar", "Peshawar")])
async def test_resolve_city_exact_punctuation_and_typo(typed, expected):
    city, cands = await q.resolve_city(FakeDB(), typed)
    assert city.name == expected and cands == []


async def test_resolve_city_returns_candidates_when_ambiguous_and_none_when_unknown():
    city, cands = await q.resolve_city(FakeDB(), "Kotl")              # equally close to Kotli and Kotla
    assert city is None and {c.name for c in cands} == {"Kotli", "Kotla"}
    city, cands = await q.resolve_city(FakeDB(), "Vehar")             # clearly closer to Vehari than Vihari
    assert city.name == "Vehari" and cands == []
    assert await q.resolve_city(FakeDB(), "Atlantis") == (None, [])


@pytest.mark.parametrize("place, lat, lon, expected", [
    ("Peshawar", 34.0, 71.55, "Khyber Pakhtunkhwa"), ("Charsadda", 34.1529, 71.7475, "Khyber Pakhtunkhwa"),
    ("Karachi", 24.86, 67.0, "Sindh"), ("Islamabad F-6", 33.72, 73.06, "Islamabad"), ("Skardu", 35.3, 75.6, "Gilgit-Baltistan"),
    ("Muzaffarabad", 34.37, 73.47, "Azad Kashmir"), ("Quetta", 30.2, 67.0, "Balochistan"), ("Lahore", 31.52, 74.35, "Punjab"),
    ("Arabian Sea", 23.0, 66.0, None), ("Delhi", 28.6, 77.2, None), ("no coordinates", None, None, None)])
def test_province_for_point_uses_the_adm1_boundaries(place, lat, lon, expected):
    assert q.province_for_point(lat, lon) == expected
    assert {n for n, _ in q.province_polygons()} == {"Azad Kashmir", "Balochistan", "Gilgit-Baltistan", "Islamabad",
                                                       "Khyber Pakhtunkhwa", "Punjab", "Sindh"}


async def test_station_provinces_follow_coordinates_and_keep_the_registry_only_without_them():
    db = FakeDB()
    m = await q.station_provinces(db)
    assert m["k" * 16] == {"province": "Sindh", "registry_province": "Punjab", "geo": True, "city_id": 20}
    assert m["p" * 16]["province"] == "Khyber Pakhtunkhwa" and m["n" * 16] == {"province": "Sindh", "registry_province": "Sindh", "geo": False, "city_id": None}
    sql, _ = db.sql("AS registry_province")
    assert "co.name = 'Pakistan'" in sql and "'openaq'" in sql
    await q.station_provinces(db)
    assert sum(1 for s, _ in db.calls if "AS registry_province" in s) == 1          # cached


async def test_resolve_area_province_is_the_set_of_stations_inside_the_boundary():
    area = await q.resolve_area(FakeDB(), "province", "KPK")
    assert isinstance(area, q.Area) and area.name == "Khyber Pakhtunkhwa"
    assert area.where == "s.station_id = ANY(:area_ids)"
    assert area.params["area_ids"] == ["p" * 16, "q" * 16] and area.params["area_city_ids"] == [11] and area.params["area_sid"] == 5
    assert area.mismatch == 1                                                        # the Peshawar row filed under Punjab
    sindh = await q.resolve_area(FakeDB(), "province", "Sindh")
    assert sindh.params["area_ids"] == ["k" * 16, "n" * 16]        # Karachi by coordinates; the no-coordinate row by its registry link
    assert sindh.mismatch == 1 and sindh.params["area_city_ids"] == [20]   # the Karachi row is filed under Punjab


async def test_resolve_area_province_falls_back_to_registry_links_without_polygons(monkeypatch):
    monkeypatch.setattr(q, "_PROVINCE_POLYS", [])
    area = await q.resolve_area(FakeDB(), "province", "KPK")
    assert area.params == {"area_sid": 5} and "s.state_id = :area_sid" in area.where and "c.state_id = :area_sid" in area.where
    assert "FROM city_centroids cc WHERE ST_DWithin(cc.g, s.geom, 25000)" in area.where     # Punjab EPA / BAM rows


async def test_resolve_area_city_and_unknown_and_ambiguous():
    area = await q.resolve_area(FakeDB(), "city", "Peshawar")
    assert area.name == "Peshawar" and area.params == {"area_cid": 11} and "s.city_id IS NULL AND (SELECT cc.city_id FROM city_centroids" in area.where
    assert "not found" in (await q.resolve_area(FakeDB(), "city", "Atlantis"))["message"]
    assert "several cities" in (await q.resolve_area(FakeDB(), "city", "Kotl"))["message"]
    assert "Known provinces" in (await q.resolve_area(FakeDB(), "province", "Narnia"))["message"]


async def test_resolve_area_radius_from_place_name_and_clamped():
    area = await q.resolve_area(FakeDB(), "radius", "Peshawar", radius_km=10)
    assert area.kind == "radius" and area.params["area_m"] == 10000.0 and area.lat == 34.01
    assert "ST_DWithin(s.geom, ST_SetSRID(ST_MakePoint(:area_lon, :area_lat), 4326)::geography, :area_m)" in area.where
    big = await q.resolve_area(FakeDB(), "radius", "", lat=33.0, lon=73.0, radius_km=9999)
    assert big.radius_km == 200.0 and big.params["area_m"] == 200000.0


async def test_resolve_place_city_centroid_falls_back_to_station_average_then_station_then_province():
    assert (await q.resolve_place(FakeDB(), "Mardan")) == {"lat": 34.2, "lon": 72.04, "name": "Mardan", "kind": "city"}
    st = NS(station_id="ab12" * 4, station_name="GT Road Peshawar", city_name="Peshawar", lat=34.0, lon=71.6)
    out = await q.resolve_place(FakeDB(station=st), "GT Road Peshawar")
    assert out["kind"] == "station" and out["station_id"] == "ab12" * 4
    assert (await q.resolve_place(FakeDB(), "Sindh"))["kind"] == "province"
    assert "not found" in (await q.resolve_place(FakeDB(), "Atlantis"))["message"]


async def test_resolve_place_falls_back_to_a_district_centroid_for_towns_without_stations():
    out = await q.resolve_place(FakeDB(), "Swat")                  # not a registry city, is an ADM2 district
    assert out["kind"] == "district centroid" and out["name"] == "Swat district"
    assert 34.5 < out["lat"] < 35.5 and 72.0 < out["lon"] < 73.0
    assert (await q.resolve_place(FakeDB(), "sawat"))["name"] == "Swat district"      # typo within 0.8
    assert len(q.district_centroids()) == 126


# ── inventory ────────────────────────────────────────────────────────────────

async def test_inventory_counts_window_and_sql():
    db = FakeDB()
    area = await q.resolve_area(db, "province", "KP")
    out = await q.station_inventory(db, area)
    assert out["counts"] == {"registered": 42, "active": 40, "reporting": 36}
    assert out["by_provider"][1]["code"] == "punjab" and out["by_city"][0]["city"] == "Peshawar"
    assert out["definitions"] is q.DEFINITIONS and out["window"]["label"] == "last 24 hours"
    sql, params = db.sql("COUNT(*) AS registered")
    assert "co.name = 'Pakistan'" in sql and "s.station_id = ANY(:area_ids)" in sql and "EXISTS (SELECT 1 FROM readings r" in sql
    assert params["area_ids"] == ["p" * 16, "q" * 16] and (params["w1"] - params["w0"]).total_seconds() == 86400
    assert out["registry_mismatch"] == 1 and "filed under a different province" in out["registry_note"]
    assert any("SET LOCAL statement_timeout" in s for s, _ in db.calls)


async def test_inventory_as_of_day_is_a_pakistan_day_and_provider_filter():
    db = FakeDB()
    out = await q.station_inventory(db, q.Area("national", "Pakistan"), as_of_day=date(2026, 11, 2), provider="punjab")
    sql, params = db.sql("COUNT(*) AS registered")
    assert params["w0"] == datetime(2026, 11, 1, 19, tzinfo=timezone.utc) and params["w1"] == datetime(2026, 11, 2, 19, tzinfo=timezone.utc)
    assert params["prov"] == "punjab" and "LOWER(COALESCE(p.code, '')) = LOWER(:prov)" in sql
    assert out["window"]["label"] == "Pakistan day 2026-11-02" and out["window"]["start_pkt"] == "2026-11-02 00:00"


async def test_inventory_list_is_capped_and_flags_truncation():
    rows = [NS(station_id=f"{i:016x}", name=f"S{i}", city="Peshawar", province="Khyber Pakhtunkhwa", provider="airvisual",
               lat=34.0 + i / 1000, lon=71.5, active=True, reporting=True, first_obs=T, last_obs=T) for i in range(101)]
    db = FakeDB(list_rows=rows)
    out = await q.station_inventory(db, q.Area("city", "Peshawar", "s.city_id = :area_cid", {"area_cid": 11}), list_stations=True, limit=500)
    assert out["list_limit"] == 100 and len(out["stations"]) == 100 and out["truncated"] is True
    assert out["stations"][0] == {"station_id": "0" * 16, "name": "S0", "city": "Peshawar", "province": "Khyber Pakhtunkhwa",
                                  "provider": "airvisual", "lat": 34.0, "lon": 71.5, "active": True, "reporting": True,
                                  "first_obs": "2026-11-03", "last_obs": "2026-11-03 12:00Z"}
    sql, params = db.sql("obs.first_obs")
    assert params["lim"] == 101 and "ORDER BY s.active DESC, s.name" in sql
    assert sql.startswith("WITH city_centroids AS") and "COALESCE(st.name, cst.name, ncst.name) AS province" in sql
    assert "nc ON s.city_id IS NULL" in sql


# ── nearest ──────────────────────────────────────────────────────────────────

async def test_nearest_uses_the_geom_index_orders_by_distance_and_clamps():
    rows = [NS(station_id="a" * 16, name="Mardan Node", city="Mardan", province="Khyber Pakhtunkhwa", provider="airvisual",
               lat=34.2, lon=72.05, active=True, dist_m=1234.5, bearing=87.6, latest_pm25=88.2, latest_ts=T),
            NS(station_id="b" * 16, name="Takht Bhai", city=None, province="Khyber Pakhtunkhwa", provider="punjab",
               lat=34.3, lon=71.9, active=True, dist_m=15600.0, bearing=300.0, latest_pm25=None, latest_ts=None)]
    db = FakeDB(nearest_rows=rows)
    out = await q.nearest_stations(db, 34.2, 72.04, k=99, max_km=9999, origin_name="Mardan (city)")
    sql, params = db.sql("ST_Azimuth")
    assert "ST_DWithin(s.geom, pt.g, :max_m)" in sql and "ORDER BY dist_m" in sql and "s.active = true" in sql
    assert params == {**params, "k": 25, "max_m": 500000.0}
    assert out["stations"][0]["distance_km"] == 1.23 and out["stations"][0]["reporting"] is True
    assert out["stations"][1]["reporting"] is False and out["stations"][1]["latest_pm25"] is None
    assert "registry_province" not in out["stations"][0]            # not a registered id in the fake map → row untouched
    assert out["origin"]["name"] == "Mardan (city)" and out["message"] is None


async def test_lists_report_the_geographic_province_and_flag_the_registry_when_it_differs():
    rows = [NS(station_id="p" * 16, name="Peshawar Node", city="Peshawar", province="Punjab", provider="airvisual-paqi",
               lat=34.0, lon=71.55, active=True, reporting=True, first_obs=T, last_obs=T),
            NS(station_id="q" * 16, name="GT Road", city="Peshawar", province="Khyber Pakhtunkhwa", provider="airvisual",
               lat=34.01, lon=71.56, active=True, reporting=False, first_obs=T, last_obs=T)]
    out = await q.station_inventory(FakeDB(list_rows=rows), q.Area("city", "Peshawar", "s.city_id = :area_cid", {"area_cid": 11}), list_stations=True)
    first, second = out["stations"]
    assert first["province"] == "Khyber Pakhtunkhwa" and first["registry_province"] == "Punjab"
    assert second["province"] == "Khyber Pakhtunkhwa" and "registry_province" not in second


async def test_nearest_with_no_station_in_range_says_so():
    out = await q.nearest_stations(FakeDB(), 30.0, 70.0, max_km=2)
    assert out["stations"] == [] and out["message"] == "No active registered station within 2 km."


# ── period statistics ─────────────────────────────────────────────────────────

def test_parse_period_date_and_bucket_counts():
    assert q.parse_period_date("2025-10", end=True) == date(2025, 10, 31) and q.parse_period_date("2024") == date(2024, 1, 1)
    assert q.parse_period_date("2024", end=True) == date(2024, 12, 31) and q.parse_period_date("") is None
    assert q._count_buckets(date(2025, 1, 1), date(2026, 11, 4), "month") == 23


async def test_same_calendar_date_gives_one_row_per_year_with_one_indexed_window_per_year():
    rows = [NS(b=date(2024, 1, 1), mean=180.2, median=170.0, max=210.0, min=150.0, n_station_days=48, n_sk=48, n_st_max=1, n_days=1),
            NS(b=date(2025, 1, 1), mean=120.0, median=120.0, max=120.0, min=120.0, n_station_days=51, n_sk=51, n_st_max=1, n_days=1)]
    db = FakeDB(period_rows=rows)
    out = await q.period_stats(db, entity="city", name="Lahore", start="10-29", same_calendar_date=True)
    sql, params = db.sql("FROM daily")
    assert "FROM city_hourly_from_stations" not in sql and "JOIN members m" in sql and params["area_cid"] == 10
    years = list(range(q.HISTORY_START.year, q.pkt_today().year + 1))
    assert params["cw0a"] == datetime(years[0], 10, 28, 19, tzinfo=timezone.utc) and f"cw{len(years) - 1}b" in params
    assert "(r.ts_utc >= :cw0a AND r.ts_utc < :cw0b) OR (r.ts_utc >= :cw1a" in sql and "EXTRACT(month FROM d) = :mm" in sql
    assert out["bucket"] == "year" and out["same_calendar_date"] is True
    assert out["rows"][0] == {"bucket": "2024", "mean": 180.2, "median": 170.0, "max": 210.0, "min": 150.0, "n_station_days": 48,
                              "n_days": 1, "n_stations": 48, "calendar_date": "2024-10-29"}
    assert out["statistic"] == "reporting-station mean of station daily means" and out["unit"] == "µg/m³ PM2.5"


async def test_long_range_city_uses_the_hourly_city_aggregate():
    db = FakeDB(period_rows=[NS(b=date(2025, 1, 1), mean=100.0, median=98.0, max=300.0, min=20.0, n_station_days=365, n_sk=1, n_st_max=50, n_days=365)])
    out = await q.period_stats(db, entity="province", name="Punjab", start="2025", end="2025", bucket="year")
    sql, params = db.sql("FROM daily")
    assert "FROM city_hourly_from_stations h" in sql and "c.id = ANY(:area_city_ids)" in sql and params["area_city_ids"] == [10]
    assert out["rows"][0]["max_stations_per_hour"] == 50 and "hourly city aggregate" in out["statistic"]
    assert "leap" not in sql
    assert "limit is 120" not in out.get("message", "")


async def test_short_range_city_uses_readings_with_the_six_hour_rule_and_registered_filter():
    rows = [NS(b=date(2026, 10, 1), mean=95.5, median=90.0, max=140.0, min=40.0, n_station_days=1500, n_sk=51, n_st_max=1, n_days=31)]
    db = FakeDB(period_rows=rows)
    out = await q.period_stats(db, entity="city", name="Lahore", start="2026-10", end="2026-10", bucket="month")
    sql, params = db.sql("FROM daily")
    assert "time_bucket('1 hour', r.ts_utc)" in sql and "HAVING COUNT(*) >= 6" in sql and "co.name = 'Pakistan'" in sql
    assert "'openaq'" in sql and "date_trunc('month', d)" in sql
    assert params["w0"] == datetime(2026, 9, 30, 19, tzinfo=timezone.utc) and params["w1"] == datetime(2026, 10, 31, 19, tzinfo=timezone.utc)
    assert out["rows"][0]["n_stations"] == 51 and out["range"] == {"start_pkt_day": "2026-10-01", "end_pkt_day": "2026-10-31"}
    assert out["statistic"] == "reporting-station mean of station daily means"


async def test_station_entity_resolves_the_station_and_buckets_by_day():
    st = NS(station_id="c" * 16, station_name="US Consulate, Peshawar", city_name="Peshawar", lat=34.0, lon=71.5)
    db = FakeDB(station=st, period_rows=[NS(b=date(2026, 11, 1), mean=70.0, median=70.0, max=90.0, min=50.0,
                                             n_station_days=1, n_sk=1, n_st_max=1, n_days=1)])
    out = await q.period_stats(db, entity="station", name="US Consulate Peshawar", start="2026-11-01", end="2026-11-02")
    sql, params = db.sql("FROM daily")
    assert params["sid"] == "c" * 16 and "r.scope_key = :sid" in sql
    assert out["entity"] == {"kind": "station", "name": "US Consulate, Peshawar"} and "n_stations" not in out["rows"][0]


async def test_period_stats_guards():
    assert "limit is 120" in (await q.period_stats(FakeDB(), entity="city", name="Lahore", start="2016-01-01", end="2026-01-01", bucket="day"))["message"]
    assert "bucket must be" in (await q.period_stats(FakeDB(), entity="city", name="Lahore", bucket="week"))["message"]
    assert "MM-DD" in (await q.period_stats(FakeDB(), entity="city", name="Lahore", start="October 29", same_calendar_date=True))["message"]
    assert "not found" in (await q.period_stats(FakeDB(), entity="station", name="Nowhere"))["message"]
    assert "after end" in (await q.period_stats(FakeDB(), entity="national", start="2026-10-10", end="2026-10-01"))["message"]
    empty = await q.period_stats(FakeDB(), entity="national", start="2026-10-01", end="2026-10-02")
    assert empty["rows"] == [] and "No station-days" in empty["message"]
