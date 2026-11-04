"""fire_analytics: exposure (rings, wind source order, cone), trends (series, comparison, regions), hotspots, activity."""

import math
from datetime import date, timedelta
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

from app.services import fire_aggregates as fa
from app.services import fire_analytics as x

LAHORE = (31.52, 74.35)
D1, D2, D3 = date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)
HEADER = "latitude,longitude,frp,confidence,acq_date,acq_time,acq_datetime_utc,satellite\n"


def _at(bearing_deg, km, lat0=LAHORE[0], lon0=LAHORE[1]):
    lat = lat0 + km * math.cos(math.radians(bearing_deg)) / 111.0
    lon = lon0 + km * math.sin(math.radians(bearing_deg)) / (111.0 * math.cos(math.radians(lat0)))
    return round(lat, 4), round(lon, 4)


A = _at(315, 30)     # NW, Sheikhupura district, Pakistan
B = _at(135, 30)     # SE, across the border (Indian Punjab)
C = _at(90, 80)      # E, Amritsar side (Indian Punjab)
FAR = _at(0, 400)    # far north, outside the 200 km rings


def _csv(day, rows):
    out = HEADER
    for (lat, lon), frp, conf, sat, hhmm in rows:
        out += f"{lat},{lon},{frp},{conf},{day.isoformat()},{hhmm},{day.isoformat()}T{hhmm[:2]}:{hhmm[2:]}:00Z,{sat}\n"
    return out


META = {"status": "ok", "fetched_at": "2026-11-03T12:00:00Z", "observation_period": {"start": "2026-11-02T20:30:00Z", "end": "2026-11-03T08:40:00Z"},
        "sources": [{"source": "VIIRS_NOAA20_NRT", "status": "ok", "rows": 4}, {"source": "VIIRS_NOAA21_NRT", "status": "ok", "rows": 2}]}


def _builds():
    return {
        D1: fa.build_day(D1, _csv(D1, [(A, 40.0, "h", "N20", "0815")]), META),
        D2: fa.build_day(D2, _csv(D2, [(A, 30.0, "n", "N20", "0815"), (B, 20.0, "h", "N21", "0816")]), META),
        D3: fa.build_day(D3, _csv(D3, [(A, 50.0, "h", "N20", "0815"), (A, 45.0, "h", "N21", "0905"),      # one fire seen twice
                                      (B, 20.0, "n", "N20", "0815"), (C, 120.0, "h", "N20", "0815"),
                                      (FAR, 9.0, "l", "N20", "0815")]), META),
    }


class FakeStore:
    """AggStore stand-in: day builds plus optional extra daily-region rows."""

    def __init__(self, builds, extra_daily=None, suspect=None):
        self.builds = builds
        regions = [b.regions for b in builds.values()]
        if extra_daily is not None:
            regions.append(extra_daily)
        self._daily = pd.concat(regions, ignore_index=True)
        self._daily["pk_day"] = pd.to_datetime(self._daily["pk_day"]).dt.date
        days = {d.isoformat(): {"csv_updated": "t", **b.info} for d, b in builds.items()}
        if extra_daily is not None:
            for d in extra_daily["pk_day"].unique():
                days.setdefault(pd.Timestamp(d).date().isoformat(), {"csv_updated": "t", "rows": 1, "format": "utc_v1", "status": "archive"})
        self._manifest = {"built_at": "2026-11-03T13:00:00Z", "days": days, "suspect_days": suspect or []}

    def manifest(self):
        return self._manifest

    def daily_regions(self):
        return self._daily

    def detections(self, start, end):
        frames = [b.detections for d, b in self.builds.items() if start <= d <= end]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=fa.DET_COLUMNS)

    def day_from_csv(self, day):
        return self.builds.get(day)


class FakeDB:
    def __init__(self, wind_rows=None, cities=None):
        self.wind_rows = wind_rows or []
        self.cities = cities if cities is not None else [NS(id=10, name="Lahore", province="Punjab", lat=LAHORE[0], lon=LAHORE[1]),
                                                           NS(id=11, name="Mardan", province="Khyber Pakhtunkhwa", lat=None, lon=None),
                                                           NS(id=15, name="Kotli", province="Azad Kashmir", lat=33.5, lon=73.9),
                                                           NS(id=16, name="Kotla", province="Punjab", lat=32.0, lon=74.0)]
        self.calls = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        if "SELECT c.id, c.name, st.name AS province" in sql:
            return NS(fetchall=lambda: self.cities)
        if "r.wind_dir_deg AS d" in sql:
            return NS(fetchall=lambda: self.wind_rows)
        if "AVG(s.lat) AS lat" in sql:
            return NS(fetchone=lambda: NS(lat=None, lon=None))
        if "AT TIME ZONE 'Asia/Karachi')::date AS d" in sql:
            return NS(fetchall=lambda: [])                       # no station wind unless a subclass provides it
        raise AssertionError("unexpected SQL: " + sql[:120])


def _loaders(era5=None, summary=None, driver=None, traj=None):
    return x.Loaders(era5_uv=lambda lat, lon, d: era5, summary=lambda d: summary, driver_summary=lambda d: driver,
                     trajectory=lambda c, d: traj)


# ── exposure ──────────────────────────────────────────────────────────────────

async def test_exposure_rings_cone_nearest_and_era5_wind():
    out = await x.fire_exposure(FakeDB(), "lahore", D3, store=FakeStore(_builds()), loaders=_loaders(era5=(3.0, -3.0)))
    assert out["city"] == "Lahore" and out["wind"]["source"] == "era5" and out["wind"]["from_deg"] == 315.0 and out["wind"]["from_compass"] == "NW"
    assert out["rings"]["50km"] == {"fires": 2, "detections": 3, "frp_mw": 70.0, "by_country": {"Pakistan": 1, "India (Punjab+Haryana)": 1}}
    assert out["rings"]["100km"]["fires"] == 3 and out["rings"]["200km"]["fires"] == 3          # FAR is 400 km away and low confidence
    assert out["upwind"]["fires_200km"] == 1 and out["upwind"]["frp_mw_200km"] == 50.0 and out["upwind"]["by_country"] == {"Pakistan": 1}
    top = out["top_upwind_fires"][0]
    assert top["district"] == "Sheikhpura" and top["country"] == "Pakistan" and 29 < top["km"] < 31 and top["direction"] == "NW"
    assert top["transport_h_at_10m_wind"] == pytest.approx(30 / (math.hypot(3, 3) * 3.6), abs=0.1) and top["acq_pkt"] == "2026-11-03 13:15 PKT"
    assert out["nearest_fire"]["km"] == top["km"] and out["top_districts_in_radius"] == [{"district": "Sheikhpura", "fires": 1}]
    assert out["passes"]["satellites"] == ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"] and out["passes"]["observation_period"]["end"] == "2026-11-03T08:40:00Z"
    assert out["definitions"] is x.FIRE_DEFINITIONS and out["caveats"] == []


async def test_exposure_wind_source_order_summary_then_stations_then_none():
    store = FakeStore(_builds())
    summary = {"city_summaries": [{"name": "Lahore", "met_fire": {"met_wd10_prevailing": 90, "met_ws10_mean": 2.5, "fire_count_100km": 7}}]}
    out = await x.fire_exposure(FakeDB(), "Lahore", D3, store=store, loaders=_loaders(summary=summary))
    assert out["wind"]["source"] == "pipeline_summary" and out["wind"]["from_deg"] == 90.0
    assert out["upwind"]["fires_200km"] == 2 and out["upwind"]["by_country"] == {"India (Punjab+Haryana)": 2}     # B (135°) and C (90°)
    assert out["context"]["pipeline_met_fire"]["fire_count_100km"] == 7
    db = FakeDB(wind_rows=[NS(d=300, s=2.0), NS(d=330, s=2.0)])
    out = await x.fire_exposure(db, "Lahore", D3, store=store, loaders=_loaders())
    assert out["wind"]["source"] == "station_vector_mean" and out["wind"]["from_deg"] == 315.0 and out["wind"]["n_observations"] == 2
    assert out["upwind"]["fires_200km"] == 1
    sql, params = next((s, p) for s, p in db.calls if "r.wind_dir_deg AS d" in s)
    assert params["cid"] == 10 and params["w0"].hour == 19 and params["w0"].day == 2                 # Pakistan day in UTC
    out = await x.fire_exposure(FakeDB(), "Lahore", D3, store=store, loaders=_loaders())
    assert out["wind"]["source"] == "none" and out["upwind"] is None and out["top_upwind_fires"] == []
    assert any("upwind figures are not available" in c for c in out["caveats"]) and out["rings"]["200km"]["fires"] == 3


async def test_exposure_messages_never_fall_back_to_national_numbers():
    store = FakeStore(_builds())
    assert "not found" in (await x.fire_exposure(FakeDB(), "Atlantis", D3, store=store, loaders=_loaders()))["message"]
    assert "several cities" in (await x.fire_exposure(FakeDB(), "Kotl", D3, store=store, loaders=_loaders()))["message"]
    assert "no coordinates" in (await x.fire_exposure(FakeDB(), "Mardan", D3, store=store, loaders=_loaders()))["message"]
    assert "No fire file" in (await x.fire_exposure(FakeDB(), "Lahore", date(2026, 11, 9), store=store, loaders=_loaders()))["message"]
    broken = fa.build_day(D3, HEADER, {"status": "unavailable", "sources": []})
    out = await x.fire_exposure(FakeDB(), "Lahore", D3, store=FakeStore({D3: broken}), loaders=_loaders())
    assert "every satellite source failed" in out["message"]
    partial = fa.build_day(D3, _csv(D3, [(A, 50.0, "h", "N20", "0815")]), {"status": "partial", "sources": [{"source": "VIIRS_NOAA20_NRT", "status": "ok"}]})
    out = await x.fire_exposure(FakeDB(), "Lahore", D3, store=FakeStore({D3: partial}), loaders=_loaders(era5=(3.0, -3.0)))
    assert any("Partial satellite coverage" in c for c in out["caveats"]) and out["rings"]["50km"]["fires"] == 1


# ── trends ────────────────────────────────────────────────────────────────────

def _ref_daily():
    """Daily Pakistan/India rows for 2024 and 2025 over 1–3 Nov, plus a long 2026 Sept–Nov run for week bucketing."""
    rows = []
    for y, n in ((2024, 5), (2025, 9)):
        for d in (date(y, 11, 1), date(y, 11, 2), date(y, 11, 3)):
            rows.append({"pk_day": d, "region_kind": "country", "region": "Pakistan", "n_raw": n + 1, "n_hn": n + 1, "n_dedup": n, "n_dedup_hn": n,
                         "n_high": n, "n_nominal": 0, "n_low": 0, "n_day": n, "n_night": 0, "frp_raw": 10.0 * n, "frp_hn": 10.0 * n, "frp_dedup_hn": 10.0 * n, "frp_max": 10.0})
    return pd.DataFrame(rows)


def test_trends_daily_rows_summary_country_share_and_comparison():
    store = FakeStore(_builds(), _ref_daily())
    out = x.fire_trends("Pakistan", D1, D3, store=store, today=D3)
    assert out["region"] == {"kind": "country", "name": "Pakistan"} and out["bucket"] == "day" and out["window"]["days"] == 3
    assert [r["fires"] for r in out["rows"]] == [1, 1, 1] and out["rows"][2]["detections"] == 3 and out["rows"][0]["rolling7_fires"] == 1.0   # FAR (low) is in GB
    s = out["summary"]
    assert s["fires"] == 3 and s["days_with_data"] == 3 and s["by_country"] == {"Pakistan": 3, "India (Punjab+Haryana)": 3, "other in bbox": 0}
    assert s["top_districts"] == [{"district": "Sheikhpura", "fires": 3, "frp_mw": 120.0}] and s["peak_day"]["frp_mw"] == 50.0
    c = out["comparison"]
    assert c["window"] == "11-01 to 11-03 in each year" and [y["fires"] for y in c["years"] if y["fires"] is not None] == [15, 27]
    assert c["reference_mean"] == 21.0 and c["higher_than_n_of"] == [0, 2] and c["ratio_to_mean"] == pytest.approx(3 / 21, abs=0.01)
    assert c["days_compared"] == 3 and "note" not in c and c["rank_text"] == "lower than every reference year"
    assert any("satellite roster" in cv for cv in out["caveats"])
    # a gap in the current window → reference years are summed over the same calendar days only
    gap = x.fire_trends("Pakistan", date(2026, 10, 30), D3, store=store, today=D3)
    cg = gap["comparison"]
    assert cg["days_compared"] == 3 and "no 2026 file" in cg["note"] and [y["fires"] for y in cg["years"] if y["fires"] is not None] == [15, 27]
    assert gap["summary"]["days_missing"] == 2


def test_trends_regions_seasons_weeks_and_messages():
    store = FakeStore(_builds(), _ref_daily())
    assert "not recognised" in x.fire_trends("Narnia", D1, D3, store=store, today=D3)["message"]
    pb = x.fire_trends("Punjab", D1, D3, store=store, today=D3)
    assert pb["region"]["name"] == "Punjab" and "Indian Punjab" in pb["note"] and pb["summary"]["top_districts"][0]["district"] == "Sheikhpura"
    ipb = x.fire_trends("Indian Punjab", D1, D3, store=store, today=D3, compare_years=())
    assert ipb["region"] == {"kind": "india_state", "name": "Punjab (IN)"} and ipb["summary"]["fires"] == 3 and ipb["comparison"] is None
    assert "top_districts" not in ipb["summary"]
    hr = x.fire_trends("haryana", D1, D3, store=store, today=D3)
    assert hr["region"]["name"] == "Haryana (IN)" and hr["summary"]["fires"] == 0
    dist = x.fire_trends("sheikhpura", D1, D3, store=store, today=D3)
    assert dist["region"] == {"kind": "district", "name": "Sheikhpura"} and dist["summary"]["fires"] == 3
    assert x.resolve_region("Shekhupura")[0] == ("district", "Sheikhpura")
    # the season window and the current-season default
    assert x.season_window("rice", today=D3) == (date(2026, 10, 1), D3, "kharif_rice_residue")
    assert x.season_window("wheat", today=D3) == (date(2026, 4, 15), date(2026, 5, 31), "rabi_wheat_residue")
    assert x.season_window("monsoon", today=D3) is None and x.current_season(D3) == "kharif_rice_residue" and x.current_season(date(2026, 7, 1)) is None
    season = x.fire_trends("Pakistan", season="rice", store=store, today=D3, compare_years=())
    assert season["season"] == "kharif_rice_residue" and season["window"]["start_pkt_day"] == "2026-10-01" and season["window"]["end_pkt_day"] == "2026-11-03"
    assert season["summary"]["days_missing"] == 31 and any("no fire file" in c for c in season["caveats"])
    assert "Unknown season" in x.fire_trends("Pakistan", season="monsoon", store=store, today=D3)["message"]
    # > 60 days → ISO-week rows
    long = x.fire_trends("Pakistan", date(2026, 8, 1), D3, store=store, today=D3, compare_years=())
    assert long["bucket"] == "week" and len(long["rows"]) <= 60 and long["rows"][-1]["fires"] == 2 and "week_start" in long["rows"][0]   # 1 Nov is a Sunday
    assert "after end" in x.fire_trends("Pakistan", D3, D1, store=store, today=D3)["message"]


# ── hotspots ──────────────────────────────────────────────────────────────────

def test_hotspots_clusters_districts_and_persistent():
    builds = _builds()
    # a second fire in the cell next to A on D3 → one cluster of two; B and C are their own clusters
    near_a = (round(A[0] + 0.02, 4), A[1])
    builds[D3] = fa.build_day(D3, _csv(D3, [(A, 50.0, "h", "N20", "0815"), (near_a, 10.0, "n", "N20", "0815"),
                                           (B, 20.0, "n", "N20", "0815"), (C, 120.0, "h", "N20", "2116")]), META)
    store = FakeStore(builds)
    out = x.fire_hotspots(region="Pakistan", start=D3, end=D3, group="cluster", store=store, today=D3)
    assert out["fires_in_area"] == 2 and out["clusters_total"] == 1 and out["rows"][0]["fires"] == 2 and out["rows"][0]["district"] == "Sheikhpura"
    assert out["rows"][0]["day_night"] == {"D": 2, "N": 0} and out["passes"]["satellites"] == ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
    ind = x.fire_hotspots(region="Indian Punjab", start=D3, end=D3, group="cluster", store=store, today=D3)
    assert ind["clusters_total"] == 2 and ind["rows"][0]["frp_mw"] == 120.0 and ind["rows"][0]["day_night"] == {"D": 0, "N": 1}
    rad = x.fire_hotspots(center=(LAHORE[0], LAHORE[1], "Lahore"), radius_km=50, start=D1, end=D3, group="cluster", store=store, today=D3)
    assert rad["area"]["kind"] == "radius" and rad["fires_in_area"] == 6 and rad["clusters_total"] == 5
    dist = x.fire_hotspots(region="Punjab", start=D1, end=D3, group="district", store=store, today=D3)
    assert dist["rows"] == [{"district": "Sheikhpura", "province": "Punjab", "fires": 4, "frp_mw": 130.0, "days_active": 3, "night_share": 0.0,
                             "confidence": {"h": 2, "n": 2}}]
    assert "Pakistan only" in x.fire_hotspots(region="Indian Punjab", start=D3, end=D3, group="district", store=store, today=D3)["message"]
    # persistent: cell A active on 3 of the last 30 days → persistent at min_days=3, not at 10
    per = x.fire_hotspots(region="Pakistan", end=D3, group="persistent", min_days=3, store=store, today=D3)
    assert per["window"]["start_pkt_day"] == (D3 - timedelta(days=29)).isoformat() and per["persistent_cells"] == 1
    assert per["rows"][0]["days_active"] == 3 and per["rows"][0]["district"] == "Sheikhpura" and per["cells_total"] == 2 and per["one_off_share"] == 0.5
    assert x.fire_hotspots(region="Pakistan", end=D3, group="persistent", store=store, today=D3)["persistent_cells"] == 0
    assert "group must be" in x.fire_hotspots(region="Pakistan", start=D3, end=D3, group="blob", store=store, today=D3)["message"]
    assert "No deduplicated" in x.fire_hotspots(region="Balochistan", start=D3, end=D3, store=store, today=D3)["message"]


# ── activity (the old tool) ───────────────────────────────────────────────────

async def test_fire_activity_city_is_exposure_and_national_is_trends():
    store = FakeStore(_builds())
    city = await x.fire_activity(FakeDB(), D3, "Lahore", store=store, loaders=_loaders(era5=(3.0, -3.0)))
    assert city["city"] == "Lahore" and city["radius_km"] == 50.0 and "upwind" in city
    nat = await x.fire_activity(FakeDB(), D3, None, store=store)
    assert nat["summary"]["fires"] == 1 and nat["summary"]["by_country"]["India (Punjab+Haryana)"] == 2 and nat["passes"]["status"] == "ok"
    missing = await x.fire_activity(FakeDB(), date(2026, 10, 20), None, store=store)
    assert "No fire file" in missing["message"] and missing["summary"]["days_missing"] == 1


# ── fire vs PM2.5 linkage ─────────────────────────────────────────────────────

def test_correlations_rank_ties_and_small_n():
    c = x.correlations([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6])
    assert c["n"] == 11 and c["spearman"] > 0.95 and c["strength"] == "strong"
    assert x.correlations([1, 2, 3], [1, 2, 3])["strength"] == "insufficient"
    assert x.correlations([1] * 12, list(range(12)))["strength"] == "undefined"
    assert x._rank(np.array([3.0, 1.0, 3.0, 2.0])).tolist() == [3.5, 1.0, 3.5, 2.0]


async def test_fire_pm25_link_lag_one_series_flags_and_wording(monkeypatch):
    """Fires upwind on day d, PM2.5 jumps on day d+1: the lag-1 correlation is the strongest and the jump days are flagged."""
    from app.services.copilot import station_queries as sq
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(30)]
    fire_days = {days[9], days[19]}                      # two burning days (upwind, NW)
    builds = {}
    for d in days:
        rows = [(A, 300.0, "h", "N20", "0815"), (A, 280.0, "h", "N21", "0905")] if d in fire_days else [(B, 5.0, "n", "N20", "0815")]
        builds[d] = fa.build_day(d, _csv(d, rows), META)
    store = FakeStore(builds)
    pm = {d: 60.0 for d in days}
    pm[days[10]] = 110.0; pm[days[20]] = 125.0            # the day after each burn
    pm[days[25]] = 95.0                                    # a rise with no upwind fire → not flagged

    async def fake_period_stats(db, *, entity, name, start, end, bucket, same_calendar_date=False):
        return {"statistic": "reporting-station mean of station daily means",
                "rows": [{"bucket": d.isoformat(), "mean": pm[d], "n_stations": 20} for d in days if start <= d.isoformat() <= end]}
    monkeypatch.setattr(sq, "period_stats", fake_period_stats)

    class WindDB(FakeDB):
        async def execute(self, stmt, params=None):
            sql = " ".join(str(stmt).split())
            if "AT TIME ZONE 'Asia/Karachi')::date AS d" in sql:
                return NS(fetchall=lambda: [NS(d=d, wd=315.0, ws=2.0) for d in days])        # NW wind every day
            return await super().execute(stmt, params)

    out = await x.fire_pm25_link(WindDB(), "Lahore", days[0], days[-1], store=store, today=days[-1])
    assert out["city"] == "Lahore" and out["days"] == 30 and out["days_with_pm25"] == 30 and out["days_with_upwind"] == 30
    rows = {r["day"]: r for r in out["rows"]}
    assert rows[days[9].isoformat()]["frp_upwind"] == 300.0 and rows[days[9].isoformat()]["fires_100"] == 1       # deduplicated, max FRP
    assert rows[days[0].isoformat()]["frp_upwind"] == 0.0 and rows[days[0].isoformat()]["frp_200"] == 5.0            # B is SE, not upwind
    assert out["fire_influenced_days"] == [days[10].isoformat(), days[20].isoformat()] and rows[days[10].isoformat()]["pm25_prior3"] == 60.0
    c = out["correlations"]["frp_upwind"]
    assert c["lag1"]["spearman"] > c["lag0"]["spearman"] and c["lag1"]["strength"] in ("moderate", "strong") and c["lag1"]["n"] == 29
    assert "consistent with smoke transport" in out["summary"] and "caused" not in out["summary"] and "upwind fire FRP with PM2.5 the next day" in out["summary"]
    assert out["upwind_p75_mw"] == 0.0 and out["definitions"]["not_causation"] and out["rows_truncated"] is False
    # guards
    assert "after end" in (await x.fire_pm25_link(WindDB(), "Lahore", days[5], days[0], store=store, today=days[-1]))["message"]
    assert "limited to 120" in (await x.fire_pm25_link(WindDB(), "Lahore", date(2026, 1, 1), days[-1], store=store, today=days[-1]))["message"]
    assert "not found" in (await x.fire_pm25_link(WindDB(), "Atlantis", days[0], days[-1], store=store, today=days[-1]))["message"]
    # no wind at all → upwind undefined, the ring series still correlates, and the caveat says so
    out2 = await x.fire_pm25_link(FakeDB(), "Lahore", days[0], days[-1], store=store, today=days[-1])
    assert out2["days_with_upwind"] == 0 and out2["fire_influenced_days"] == [] and out2["correlations"]["frp_200"]["lag1"]["n"] == 29
    assert any("Upwind FRP is defined on 0" in cv for cv in out2["caveats"])
