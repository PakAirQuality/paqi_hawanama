"""fire_public: the pre-pivot matches _series, season alignment and headline, districts, split, meta, memo."""

from datetime import date, timedelta

import pandas as pd
import pytest

from app.services import fire_analytics as fa
from app.services import fire_public as fp
from tests.copilot.test_fire_analytics import D1, D2, D3, FakeStore, _builds, _ref_daily

TODAY = date(2026, 11, 4)          # so the season-to-date window ends on D3 (3 Nov)


@pytest.fixture(autouse=True)
def _fresh():
    fp._TABLE = None
    fp._MEMO.clear()
    yield
    fp._TABLE = None
    fp._MEMO.clear()


def _store():
    return FakeStore(_builds(), _ref_daily())


def test_region_table_matches_series_semantics_and_sums_the_box():
    store = _store()
    t = fp.region_table(store)
    daily = store.daily_regions()
    days_with_file = {date.fromisoformat(k) for k in store.manifest()["days"]}
    for kind, region in (("country", "Pakistan"), ("india_state", "Punjab (IN)"), ("district", "Sheikhpura"), ("province", "Punjab"), ("country", "Narnia")):
        a = t.series(kind, region, date(2026, 10, 30), D3)
        b = fa._series(daily, kind, region, date(2026, 10, 30), D3, days_with_file)
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True), check_dtype=False)
    box = t.series("bbox", "bbox", D1, D3)
    pk = t.series("country", "Pakistan", D1, D3)
    ind = t.series("country", "India (Punjab+Haryana)", D1, D3)
    assert box["n_dedup_hn"].tolist() == (pk["n_dedup_hn"] + ind["n_dedup_hn"]).tolist()
    assert t.series("country", "Pakistan", date(2026, 10, 30), date(2026, 10, 31))["n_dedup_hn"].isna().all()      # no files → gaps
    assert fp.region_table(store) is t                                                                             # cached on built_at
    store._manifest["built_at"] = "later"
    assert fp.region_table(store) is not t


def test_seasons_alignment_headline_and_comparison():
    out = fp.seasons("pakistan", "rice", store=_store(), today=TODAY)
    assert out["region"] == {"kind": "country", "name": "Pakistan", "label": "Pakistan"}
    assert out["season"]["year"] == 2026 and out["season"]["complete"] is False and out["season"]["end_effective"] == "2026-11-03"
    assert len(out["days"]) == 77 and out["days"][0] == "09-15" and out["days"][-1] == "11-30" and out["today_index"] == 49
    years = {y["year"]: y for y in out["years"]}
    assert set(years) == {2020, 2021, 2022, 2023, 2024, 2025, 2026}
    cur = years[2026]
    assert cur["role"] == "current" and cur["fires"][:47] == [None] * 47 and cur["fires"][47:50] == [1, 1, 1] and cur["fires"][50] is None
    assert cur["cum"][:47] == [None] * 47 and cur["cum"][47:50] == [1, 2, 3] and cur["cum"][50] is None and cur["complete"] is False and cur["timing"] is None
    # today's partial day is cut: with today = 3 Nov the 3 Nov file exists but the series ends on 2 Nov
    cut = fp.seasons("pakistan", "rice", store=_store(), today=D3)
    cur_cut = next(y for y in cut["years"] if y["year"] == 2026)
    assert cur_cut["fires"][49] is None and cur_cut["fires"][48] == 1 and cut["headline"]["fires"] == 2 and cut["today_index"] == 48
    assert cur["r7"][47:50] == [None, None, None]                       # fewer than 4 days with a file
    assert cur["total"] == 3 and cur["total_to_date"] == 3 and cur["days_with_data"] == 3 and cur["first_day_with_data"] == "2026-11-01"
    assert years[2025]["role"] == "last" and years[2025]["total"] == 27 and years[2025]["total_to_date"] == 27 and years[2025]["complete"] is True
    assert years[2025]["timing"]["note"].startswith("74 of 77 days unobserved")        # too thin for 10/50/90 dates
    assert years[2024]["role"] == "reference" and years[2021]["total"] is None and years[2021]["days_with_data"] == 0
    h = out["headline"]
    assert h["basis"] == "all" and out["basis"] == "all"
    assert h["window"] == {"start": "2026-09-15", "end": "2026-11-03", "days": 50, "days_with_data": 3, "days_missing": 47, "compared_dates": "1 Nov – 3 Nov"}
    assert h["fires"] == 3 and h["fires_per_day"] == 1.0 and h["day"] == 5 and h["night"] == 0 and h["night_share"] == 0.0   # day/night count detections
    assert h["last_year"] == {"year": 2025, "fires": 27, "pct_change": -89, "days_with_data": 3}
    ref = h["reference"]
    assert ref["used_years"] == [2024, 2025] and ref["mean"] == 21 and ref["pct_change"] == -86 and ref["higher_than_n_of"] == [0, 2]
    assert ref["rank_text"] == "lower than every reference year"
    # the year-on-year block on NOAA-20 alone rides along with the all-satellite headline
    c20 = h["comparison_n20"]
    assert c20["basis"] == "n20" and c20["fires"] == 3 and c20["last_year"] == {"year": 2025, "fires": 24, "pct_change": -88, "days_with_data": 3}
    assert c20["reference"]["mean"] == 18 and c20["reference"]["rank_text"] == "lower than every reference year"
    assert any("47 day(s)" in c for c in out["caveats"]) and any("ISRO/CAQM" in c for c in out["caveats"])
    # basis=n20 as the main series
    b20 = fp.seasons("pakistan", "rice", "n20", store=_store(), today=TODAY)
    assert b20["basis"] == "n20" and b20["headline"]["fires"] == 3 and "comparison_n20" not in b20["headline"]
    assert next(y for y in b20["years"] if y["year"] == 2025)["total"] == 24
    assert fp.seasons("pakistan", "rice", "snpp", store=_store(), today=TODAY) == {"error": "basis must be one of all, n20, crop, crop_n20"}
    # a plain "Punjab" chip is Pakistan's Punjab
    pb = fp.seasons("punjab", "rice", store=_store(), today=TODAY)
    assert pb["region"]["name"] == "Punjab" and pb["headline"]["fires"] == 3
    assert fp.seasons("Narnia", "rice", store=_store(), today=TODAY) == {"error": "region 'Narnia' not recognised"}
    assert "season must be" in fp.seasons("pakistan", "monsoon", store=_store(), today=TODAY)["error"]


def test_seasons_r7_and_complete_season():
    """Seven consecutive days with files: r7 becomes non-null from the fourth; a past season is complete."""
    from tests.copilot.test_fire_analytics import A, META, _csv, fa as _fa
    builds = {}
    for i in range(7):
        d = date(2026, 4, 20 + i)
        builds[d] = _fa.build_day(d, _csv(d, [(A, 10.0 * (i + 1), "h", "N20", "0815")]), META)
    out = fp.seasons("pakistan", "wheat", store=FakeStore(builds), today=TODAY)
    assert out["season"]["complete"] is True and out["today_index"] is None and len(out["days"]) == 47
    cur = next(y for y in out["years"] if y["year"] == 2026)
    assert cur["fires"][5:12] == [1] * 7 and cur["r7"][5:8] == [None, None, None] and cur["r7"][8] == 1.0
    assert cur["r7"][12] is None and cur["r7"][13] is None                 # the mean stops with the data, no run-on
    assert cur["cum"][5:12] == [1, 2, 3, 4, 5, 6, 7] and cur["cum"][12] is None
    assert cur["complete"] is True and cur["timing"]["note"].startswith("40 of 47 days unobserved")
    assert out["headline"]["window"]["end"] == "2026-05-31" and out["headline"]["fires"] == 7


def test_seasons_timing_dates_on_a_fully_observed_season():
    """A complete season with a file every day: 10/50/90 % dates come from the cumulative curve; gaps stay null."""
    from tests.copilot.test_fire_analytics import A, META, _csv, fa as _fa
    builds = {}
    d = date(2025, 4, 15)
    while d <= date(2025, 5, 31):
        n = 3 if d.day == 1 and d.month == 5 else (1 if d.month == 5 else 0)      # 1 May: 3 fires, then 1 a day in May, none in April
        builds[d] = _fa.build_day(d, _csv(d, [(A, 10.0, "h", "N20", "0815")] * n), META)
        d += timedelta(days=1)
    del builds[date(2025, 5, 20)]                                                   # one gap day
    out = fp.seasons("pakistan", "wheat", store=FakeStore(builds), today=date(2025, 6, 10))
    y = next(r for r in out["years"] if r["year"] == 2025)
    assert y["complete"] is True and y["days_missing"] == 1 and y["total"] == 32
    assert y["cum"][15] == 0 and y["cum"][16] == 3 and y["cum"][35] is None and y["cum"][36] == 22 and y["cum"][-1] == 32
    assert y["timing"] == {"p10": "05-02", "p50": "05-14", "p90": "05-28", "days_unobserved": 1}
    assert out["season"]["complete"] is True and out["headline"]["fires"] == 32


def test_districts_split_persistent_and_meta():
    store = _store()
    d = fp.districts("rice", "punjab", store=store, today=TODAY)
    assert d["window"]["compared_dates"] == "1 Nov – 3 Nov" and d["last_year"] == 2025 and d["basis"] == "all"
    assert d["rows"] == [{"district": "Sheikhpura", "province": "Punjab", "fires": 3, "fires_last": 0, "pct_change": None, "frp_mw": 120,
                          "night_share": 0.0, "days_active": 3, "lat": d["rows"][0]["lat"], "lon": d["rows"][0]["lon"]}]
    assert d["rows"][0]["lat"] and d["totals"] == {"fires": 3, "fires_last": 0}
    assert fp.districts("rice", "haryana", store=store, today=TODAY)["note"] == "District tables cover Pakistan only."
    assert fp.districts("rice", "sindh", store=store, today=TODAY)["rows"] == []
    s = fp.split("rice", store=store, today=TODAY)
    assert set(s["series"]) == {"pakistan", "pakistan_punjab", "indian_punjab", "haryana", "other"} and len(s["series"]["pakistan"]) == 77
    assert s["totals"] == {"pakistan": 3, "pakistan_punjab": 3, "indian_punjab": 3, "haryana": 0, "other": 0} and s["shares"]["pakistan"] == 0.5
    assert set(s["shares"]) == {"pakistan", "indian_punjab", "haryana", "other"} and s["days_missing"] == 47 and s["basis"] == "all"
    s20 = fp.split("rice", "n20", store=store, today=TODAY)
    assert s20["totals"]["pakistan"] == 3 and s20["basis"] == "n20"
    d20 = fp.districts("rice", "punjab", "n20", store=store, today=TODAY)
    assert d20["rows"][0]["fires"] == 3 and d20["basis"] == "n20"
    p = fp.persistent("pakistan", min_days=3, store=store, today=TODAY)
    assert p["region"]["label"] == "Pakistan" and p["persistent_cells"] == 1 and p["window"]["end_pkt_day"] == "2026-11-03"
    assert "error" in fp.persistent("Narnia", store=store, today=TODAY)
    m = fp.meta(store=store, today=TODAY)
    assert m["current_season"] == "rice" and m["seasons"]["rice"]["start"] == "09-15" and len(m["districts"]) == 126
    assert m["archive"]["gaps"]["rice"]["2026"] == [["2026-09-15", "2026-10-31"]] and "2024" in m["archive"]["gaps"]["rice"]
    assert m["satellites_by_year"]["2026"] == ["NOAA-20", "NOAA-21"] and m["regions"][0]["id"] == "pakistan" and len(m["notes"]) == 7
    assert m["archive"]["first_day"] == "2024-11-01" and m["archive"]["last_day"] == "2026-11-03"
    assert m["n20_basis_available"] is True and m["consistent_satellite"] == "NOAA-20" and set(m["bases"]) == {"all", "n20", "crop", "crop_n20"}
    assert "ISRO/CAQM" in m["season_window_note"] and m["archive"]["days_without_pass_by_year"] == {"2026": {"n21": 1}}   # 1 Nov has N20 rows only


def test_brief_lines_cover_the_two_punjabs_in_season_only():
    store = _store()
    lines = fp.brief_lines(store=store, today=TODAY)
    assert len(lines) == 3 and lines[0].startswith("Two Punjabs, rice stubble season to date (1 Nov – 3 Nov, 3 days observed)")
    assert "Pakistan Punjab 3 clusters season to date" in lines[1] and "Indian Punjab 3 clusters" in lines[1] and "Haryana 0 clusters" in lines[1]
    assert "NOAA-20 only 3 vs 24 on the same dates in 2025 (-88 %), lower than every reference year" in lines[1]   # Punjab rows are the Pakistan rows here
    assert "late season" in lines[2]
    assert fp.brief_lines(store=store, today=date(2026, 7, 1)) == []


def test_memo_keys_and_resolution():
    calls = []
    assert fp.memo(("a", 1), lambda: calls.append(1) or "x") == "x" and fp.memo(("a", 1), lambda: calls.append(2) or "y") == "x"
    assert len(calls) == 1
    assert fp.resolve_public_region("bbox")[0] == ("bbox", "bbox") and fp.resolve_public_region("Whole box")[0] == ("bbox", "bbox")
    assert fp.resolve_public_region("kp")[0] == ("province", "Khyber Pakhtunkhwa") and fp.resolve_public_region("indian-punjab")[1] == "Indian Punjab"
    assert fp.resolve_public_region("Haryana")[0] == ("india_state", "Haryana (IN)") and fp.resolve_public_region("Sheikhpura")[0] == ("district", "Sheikhpura")
    assert fp.resolve_public_region("Narnia")[0] is None


def test_audit_counts_files_products_and_missing_passes():
    store = _store()
    m = store.manifest()
    m["days"]["2026-11-02"]["rows"] = 500                       # a busy peak-month day …
    m["days"]["2026-11-02"]["rows_by_satellite"] = {"n21": 500}  # … on which NOAA-20 contributed nothing: a missing pass
    out = fp.audit(store=store, today=TODAY)
    y26 = out["years"]["2026"]
    assert y26["days_with_file"] == 3 and y26["day_basis"] == {"acq_pkt": 3, "acq_utc": 0} and y26["products"] == {"NRT": 6}
    assert y26["peak_days"] == 3 and y26["peak_days_busy"] == 1
    assert y26["satellites"]["n20"]["busy_days_missing"] == 1 and y26["satellites"]["n20"]["busy_days_missing_dates"] == ["2026-11-02"]
    assert y26["satellites"]["n21"]["days_with_rows"] == 2 and y26["satellites"]["n20"]["days_with_rows"] == 2
    assert "snpp" not in y26["satellites"]                                                            # retired on 1 Nov 2026: not expected after that
    y25 = out["years"]["2025"]
    assert y25["products"] == {"legacy": 6} and y25["satellites"] == {} and y25["suspect_days"] == []   # no rows_by_satellite before schema 2
    assert "missing_pass" in out["method"]


def test_export_rows_header_and_csv():
    store = _store()
    out = fp.export("rice", None, "all", store=store, today=TODAY)
    h = out["header"]
    assert h["season"]["year"] == 2026 and h["basis"] == "all" and h["regions"]["pakistan_punjab"] == "Pakistan Punjab" and h["class_version"] is None
    assert len(out["rows"]) == 77 and out["columns"][:3] == ["day", "pakistan_detections", "pakistan_r7"]
    r = {row["day"]: row for row in out["rows"]}
    assert r["2026-11-01"]["pakistan_detections"] == 1 and r["2026-11-03"]["pakistan_cum"] == 3 and r["2026-11-03"]["pakistan_r7"] is None
    assert r["2026-10-31"]["pakistan_observed"] is False and r["2026-10-31"]["pakistan_detections"] is None      # a gap
    assert r["2026-11-04"]["pakistan_observed"] is None and r["2026-11-04"]["pakistan_cum"] is None                 # not yet
    assert r["2026-11-03"]["indian_punjab_detections"] == 2 and r["2026-11-03"]["haryana_detections"] == 0      # B and C on 3 Nov
    past = fp.export("rice", 2025, "n20", store=store, today=TODAY)
    assert past["header"]["season"]["complete"] is True and past["header"]["satellites_in_year"] == ["NOAA-20", "Suomi NPP"]
    assert {row["day"]: row for row in past["rows"]}["2025-11-02"]["pakistan_detections"] == 8 and past["header"]["basis"] == "n20"
    assert "year must be" in fp.export("rice", 2030, store=store, today=TODAY)["error"]
    csv_text = fp.export_csv(out)
    lines = csv_text.splitlines()
    assert lines[0].startswith("# season: ") and any(l.startswith("# caveat: ") for l in lines) and any(l.startswith("day,pakistan_detections,") for l in lines)
    assert "2026-11-03,1," in csv_text and csv_text.count("\n") == 77 + sum(1 for l in lines if l.startswith("#")) + 1


def test_brief_lines_mention_the_cumulative_position():
    lines = fp.brief_lines(store=_store(), today=TODAY)
    assert "cumulative so far = 11% of the whole 2025 season" in lines[1]
