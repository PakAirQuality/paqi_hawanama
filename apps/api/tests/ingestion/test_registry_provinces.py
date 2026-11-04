"""registry_provinces: the planner on the live cases, apply's SQL, and the task's dry run / apply."""

from types import SimpleNamespace as NS

from app.ingestion import registry_provinces as rp
from app.ingestion.runs import RunStatus
from tests.ingestion.fakes import CapturingRecorder, make_settings

KP, PB, SD, GB, IS = "Khyber Pakhtunkhwa", "Punjab", "Sindh", "Gilgit-Baltistan", "Islamabad"
STATE_IDS = {KP: 5, PB: 9, SD: 33, GB: 3, IS: 4, "Azad Kashmir": 3379, "Balochistan": 1}


def _rows():
    cities = [
        rp.CityRow(10, "Lahore", PB, has_city_readings=True),
        rp.CityRow(11, "Peshawar", KP),
        rp.CityRow(30, "Rawalpindi", PB),
        rp.CityRow(4, "Islamabad", IS),
        rp.CityRow(5139, "Charsadda", PB),                # csv import: wrong province, one station, no readings
        rp.CityRow(5145, "Gilgit", PB),                   # duplicate of 92693 under the wrong province
        rp.CityRow(92693, "Gilgit", GB),
        rp.CityRow(77, "Hadali", PB),
        rp.CityRow(99, "Ghost Town", PB),                 # no stations
    ]
    stations = [
        rp.StationRow("lhr1", "Lahore One", "airvisual", 31.52, 74.35, 10, PB),
        rp.StationRow("pes1", "US Consulate", "airvisual", 34.0, 71.55, 11, KP),
        rp.StationRow("pes2", "CSV Peshawar", "other", 34.01, 71.56, 11, PB),            # city right, state wrong
        rp.StationRow("rwp1", "Gulberg Greens", "airvisual-paqi", 33.60, 73.14, 30, PB),  # inside the ICT polygon
        rp.StationRow("rwp2", "Saddar", "airvisual", 33.60, 73.05, 30, PB),
        rp.StationRow("rwp3", "Chaklala", "airvisual", 33.62, 73.07, 30, PB),
        rp.StationRow("isb1", "F-6", "airvisual", 33.72, 73.06, 4, IS),
        rp.StationRow("chs1", "Charsadda Station", "other", 34.15, 71.75, 5139, PB),
        rp.StationRow("glt1", "WWF Gilgit", "other", 35.92, 74.31, 5145, PB),
        rp.StationRow("glt2", "Gilgit Airport", "airvisual", 35.91, 74.33, 92693, GB),
        rp.StationRow("epd1", "EPA Lahore", "punjab", 31.5, 74.3, None, None),            # no links at all
        rp.StationRow("bam1", "BAM Karachi", "bam", 24.86, 67.0, None, None),
        rp.StationRow("sea1", "Emaar coast", "other", 24.7518, 67.0728, None, None),      # outside every polygon, no city
        rp.StationRow("had1", "Hadali Town", "airvisual", 32.29, 72.19, 77, PB),
        rp.StationRow("ind1", "Suchetgarh, RS Pura", "airvisual", 32.5721, 74.6686, 77, PB),  # in India, far from Hadali
        rp.StationRow("ici1", "ICIMOD shadow", "icimod", 31.5, 74.3, None, None, shadow=True),
        rp.StationRow("nocoord", "No coordinates", "other", None, None, None, None),
    ]
    return cities, stations


def test_plan_reproduces_the_live_cases():
    cities, stations = _rows()
    p = rp.plan(cities, stations)
    assert p.examined_cities == 9 and p.examined_stations == 16                 # the shadow row is not examined

    city = {c.city_id: c for c in p.cities}
    assert set(city) == {5139, 5145}
    assert city[5139].to_state == KP and city[5139].merge_into_city_id is None and city[5139].rule == "geography"
    assert city[5145].to_state == GB and city[5145].merge_into_city_id == 92693    # Gilgit merges into the GB row

    st = {s.station_id: s for s in p.stations}
    assert set(st) == {"pes2", "chs1", "glt1", "epd1", "bam1"}
    assert st["pes2"].from_state == PB and st["pes2"].to_state == KP and st["pes2"].rule == "city"
    assert st["chs1"].to_state == KP and st["chs1"].rule == "city"                 # follows its corrected city
    assert st["glt1"].to_state == GB and st["glt1"].from_city_id == 5145 and st["glt1"].to_city_id == 92693
    assert st["epd1"] == rp.StationChange("epd1", "EPA Lahore", "punjab", None, PB, "geography", PB)
    assert st["bam1"].to_state == SD
    # untouched: Rawalpindi stays Punjab (border), Lahore/Islamabad agree, India row keeps its city's province,
    # the coast row has no decision, no-coordinate and shadow rows are skipped
    for sid in ("rwp1", "rwp2", "rwp3", "lhr1", "isb1", "ind1", "had1", "sea1", "ici1", "nocoord", "glt2", "pes1"):
        assert sid not in st

    flags = {(f.kind, f.key) for f in p.flags}
    assert ("geo_differs", "30") in flags and ("geo_differs", "rwp1") in flags and ("geo_differs", "rwp2") not in flags
    assert ("outside_polygons", "sea1") in flags and ("outside_polygons", "ind1") in flags
    assert ("far_from_city", "ind1") in flags and ("no_decision", "sea1") in flags
    assert not any(f.kind == "city_has_readings" for f in p.flags)
    s = p.summary()
    assert s["city_changes"] == 2 and s["city_merges"] == 1 and s["station_changes"] == 5
    assert s["station_fills"] == 2 and s["station_corrections"] == 3 and s["by_provider"]["other"] == 3
    assert s["by_transition"]["Punjab -> Khyber Pakhtunkhwa"] == 2


def test_plan_skips_a_row_whose_corrected_key_another_station_holds():
    cities, stations = _rows()
    # the CSV import copied an IQAir station: same name, coordinates and city, filed under Punjab
    stations.append(rp.StationRow("pes1dup", "US Consulate", "other", 34.0, 71.55, 11, PB))
    # a Punjab EPA device that IQAir also carries: identical key once its NULL state is filled
    stations.append(rp.StationRow("pb_x", "DC Office Lahore", "punjab", 31.55, 74.33, 10, None))
    stations.append(rp.StationRow("iq_x", "DC Office Lahore", "airvisual", 31.55, 74.33, 10, PB))
    p = rp.plan(cities, stations)
    ids = {s.station_id for s in p.stations}
    assert "pes1dup" not in ids and "pb_x" not in ids and "pes2" in ids
    dups = {f.key: f.detail for f in p.flags if f.kind == "duplicate_registration"}
    assert set(dups) == {"pes1dup", "pb_x"} and "pes1" in dups["pes1dup"] and "iq_x" in dups["pb_x"]
    assert p.summary()["flags"]["duplicate_registration"] == 2


def test_plan_refuses_to_move_a_city_with_city_scope_readings():
    cities, stations = _rows()
    cities[4] = rp.CityRow(5139, "Charsadda", PB, has_city_readings=True)
    p = rp.plan(cities, stations)
    assert all(c.city_id != 5139 for c in p.cities)
    assert any(f.kind == "city_has_readings" and f.key == "5139" for f in p.flags)
    assert all(s.station_id != "chs1" for s in p.stations)       # the station follows its (unchanged) city


def test_plan_is_idempotent_once_applied():
    cities, stations = _rows()
    p = rp.plan(cities, stations)
    cm = {c.city_id: c for c in p.cities}
    cities2 = []
    for c in cities:
        ch = cm.get(c.id)
        if ch is None:
            cities2.append(c)
        elif ch.merge_into_city_id is None:
            cities2.append(rp.CityRow(c.id, c.name, ch.to_state, c.has_city_readings))
        else:
            cities2.append(c)                                         # the orphan keeps its old state, loses its stations
    sm = {s.station_id: s for s in p.stations}
    stations2 = [rp.StationRow(s.station_id, s.name, s.provider, s.lat, s.lon,
                               sm[s.station_id].to_city_id or s.city_id, sm[s.station_id].to_state, s.shadow)
                 if s.station_id in sm else s for s in stations]
    again = rp.plan(cities2, stations2)
    assert again.cities == [] and again.stations == []


class FakeDB:
    """In-memory registry: answers the load queries from rows and applies the update statements to them."""

    def __init__(self, cities, stations):
        self.cities, self.stations = cities, stations
        self.executed = []
        self.committed = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.executed.append((sql, dict(params or {})))
        if "FROM cities c" in sql and sql.startswith("SELECT c.id"):
            return NS(fetchall=lambda: [NS(id=c.id, name=c.name, state=c.state, has_city_readings=c.has_city_readings) for c in self.cities])
        if sql.startswith("SELECT s.station_id"):
            return NS(fetchall=lambda: [NS(station_id=s.station_id, name=s.name, provider=s.provider, lat=s.lat, lon=s.lon,
                                           city_id=s.city_id, state=s.state, shadow=s.shadow) for s in self.stations])
        if "FROM states st JOIN countries co" in sql:
            return NS(fetchall=lambda: [NS(id=v, name=k) for k, v in STATE_IDS.items()])
        name_of = {v: k for k, v in STATE_IDS.items()}
        if sql.startswith("UPDATE cities SET state_id"):
            for c in self.cities:
                if c.id == params["cid"]:
                    c.state = name_of[params["sid"]]
        elif sql.startswith("UPDATE stations SET city_id"):
            for s in self.stations:
                if s.city_id == params["from_cid"]:
                    s.city_id = params["to_cid"]
        elif sql.startswith("UPDATE cities SET active = false"):
            pass
        elif sql.startswith("UPDATE stations SET state_id"):
            for s in self.stations:
                if s.station_id == params["station_id"]:
                    s.state = name_of[params["sid"]]
        else:
            raise AssertionError("unexpected SQL: " + sql[:120])
        return None

    async def commit(self):
        self.committed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def test_task_dry_run_writes_nothing_and_reports_the_plan(tmp_path):
    db = FakeDB(*_rows())
    rec = CapturingRecorder(tmp_path / "runs")
    t = rp.RegistryProvincesTask(settings=make_settings(tmp_path), session_factory=lambda: db, recorder=rec)
    out = await t.run(dry_run=True, trigger="scheduler")
    assert out.status is RunStatus.success and out.task == "registry-provinces" and out.trigger == "scheduler"
    assert out.counts.expected == 16 and out.counts.rows_written == 0 and out.counts.rows_unchanged == 7
    assert out.details["dry_run"] is True and out.details["summary"]["station_changes"] == 5
    assert {c["city_id"] for c in out.details["cities"]} == {5139, 5145}
    assert not any(sql.startswith("UPDATE") for sql, _ in db.executed) and db.committed == 0
    assert rec.finished is out


async def test_task_apply_writes_the_plan_once_and_converges(tmp_path):
    db = FakeDB(*_rows())
    t = rp.RegistryProvincesTask(settings=make_settings(tmp_path), session_factory=lambda: db, recorder=CapturingRecorder(tmp_path / "runs"))
    out = await t.run(dry_run=False)
    assert out.status is RunStatus.success and db.committed == 1
    assert out.details["written"] == {"cities": 1, "merges": 1, "stations": 5}
    assert out.counts.rows_written == 7 and out.details["remaining_after_apply"] == {"cities": 0, "stations": 0}
    updates = [(sql, p) for sql, p in db.executed if sql.startswith("UPDATE")]
    assert ("UPDATE cities SET state_id = :sid, updated_at = NOW() WHERE id = :cid", {"sid": 5, "cid": 5139}) in updates
    assert any(sql.startswith("UPDATE stations SET city_id") and p == {"to_cid": 92693, "from_cid": 5145} for sql, p in updates)
    assert any(sql.startswith("UPDATE cities SET active = false") and p == {"cid": 5145} for sql, p in updates)
    st = next(p for sql, p in updates if sql.startswith("UPDATE stations SET state_id") and p["station_id"] == "pes2")
    assert st["sid"] == 5 and '"set_by": "registry-provinces"' in st["stamp"] and '"previous_state": "Punjab"' in st["stamp"]
    sql = next(sql for sql, _ in updates if sql.startswith("UPDATE stations SET state_id"))
    assert "COALESCE(metadata_json->'registry', '{}'::jsonb) || jsonb_build_object('province'" in sql   # registry.status survives
    # the registry now satisfies the rule
    assert rp.plan(*await rp.load_rows(db)).stations == []
    assert {s.station_id: s.state for s in db.stations}["pes2"] == KP and db.cities[4].state == KP


async def test_task_apply_refuses_when_a_state_row_is_missing(tmp_path):
    db = FakeDB(*_rows())
    missing = dict(STATE_IDS); del missing[GB]

    async def no_gb(_db):
        return missing
    import app.ingestion.registry_provinces as mod
    orig = mod.pakistan_state_ids
    mod.pakistan_state_ids = no_gb
    try:
        out = await rp.RegistryProvincesTask(settings=make_settings(tmp_path), session_factory=lambda: db,
                                             recorder=CapturingRecorder(tmp_path / "runs")).run(dry_run=False)
    finally:
        mod.pakistan_state_ids = orig
    assert out.status is RunStatus.failed and out.error_class == "RuntimeError" and "Gilgit-Baltistan" in out.error_message
    assert db.committed == 0
