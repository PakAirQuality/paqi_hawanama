"""fire_public: the pre-pivot matches _series, season alignment and headline, districts, split, meta, memo."""

from datetime import date

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
    assert len(out["days"]) == 61 and out["days"][0] == "10-01" and out["days"][-1] == "11-30" and out["today_index"] == 33
    years = {y["year"]: y for y in out["years"]}
    assert set(years) == {2020, 2021, 2022, 2023, 2024, 2025, 2026}
    cur = years[2026]
    assert cur["role"] == "current" and cur["fires"][:31] == [None] * 31 and cur["fires"][31:34] == [1, 1, 1] and cur["fires"][34] is None
    assert cur["r7"][31:34] == [None, None, None]                       # fewer than 4 days with a file
    assert cur["total"] == 3 and cur["total_to_date"] == 3 and cur["days_with_data"] == 3 and cur["first_day_with_data"] == "2026-11-01"
    assert years[2025]["role"] == "last" and years[2025]["total"] == 27 and years[2025]["total_to_date"] == 27
    assert years[2024]["role"] == "reference" and years[2021]["total"] is None and years[2021]["days_with_data"] == 0
    h = out["headline"]
    assert h["window"] == {"start": "2026-10-01", "end": "2026-11-03", "days": 34, "days_with_data": 3, "days_missing": 31, "compared_dates": "1 Nov – 3 Nov"}
    assert h["fires"] == 3 and h["fires_per_day"] == 1.0 and h["day"] == 5 and h["night"] == 0 and h["night_share"] == 0.0   # day/night count detections
    assert h["last_year"] == {"year": 2025, "fires": 27, "pct_change": -89, "days_with_data": 3}
    ref = h["reference"]
    assert ref["used_years"] == [2024, 2025] and ref["mean"] == 21 and ref["pct_change"] == -86 and ref["higher_than_n_of"] == [0, 2]
    assert ref["rank_text"] == "lower than every reference year"
    assert any("31 day(s)" in c for c in out["caveats"])
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
    assert out["headline"]["window"]["end"] == "2026-05-31" and out["headline"]["fires"] == 7


def test_districts_split_persistent_and_meta():
    store = _store()
    d = fp.districts("rice", "punjab", store=store, today=TODAY)
    assert d["window"]["compared_dates"] == "1 Nov – 3 Nov" and d["last_year"] == 2025
    assert d["rows"] == [{"district": "Sheikhpura", "province": "Punjab", "fires": 3, "fires_last": 0, "pct_change": None, "frp_mw": 120,
                          "night_share": 0.0, "days_active": 3, "lat": d["rows"][0]["lat"], "lon": d["rows"][0]["lon"]}]
    assert d["rows"][0]["lat"] and d["totals"] == {"fires": 3, "fires_last": 0}
    assert fp.districts("rice", "haryana", store=store, today=TODAY)["note"] == "District tables cover Pakistan only."
    assert fp.districts("rice", "sindh", store=store, today=TODAY)["rows"] == []
    s = fp.split("rice", store=store, today=TODAY)
    assert set(s["series"]) == {"pakistan", "indian_punjab", "haryana", "other"} and len(s["series"]["pakistan"]) == 61
    assert s["totals"] == {"pakistan": 3, "indian_punjab": 3, "haryana": 0, "other": 0} and s["shares"]["pakistan"] == 0.5 and s["days_missing"] == 31
    p = fp.persistent("pakistan", min_days=3, store=store, today=TODAY)
    assert p["region"]["label"] == "Pakistan" and p["persistent_cells"] == 1 and p["window"]["end_pkt_day"] == "2026-11-03"
    assert "error" in fp.persistent("Narnia", store=store, today=TODAY)
    m = fp.meta(store=store, today=TODAY)
    assert m["current_season"] == "rice" and m["seasons"]["rice"]["start"] == "10-01" and len(m["districts"]) == 126
    assert m["archive"]["gaps"]["rice"]["2026"] == [["2026-10-01", "2026-10-31"]] and "2024" in m["archive"]["gaps"]["rice"]
    assert m["satellites_by_year"]["2026"] == ["NOAA-20", "NOAA-21"] and m["regions"][0]["id"] == "pakistan" and len(m["notes"]) == 5
    assert m["archive"]["first_day"] == "2024-11-01" and m["archive"]["last_day"] == "2026-11-03"


def test_memo_keys_and_resolution():
    calls = []
    assert fp.memo(("a", 1), lambda: calls.append(1) or "x") == "x" and fp.memo(("a", 1), lambda: calls.append(2) or "y") == "x"
    assert len(calls) == 1
    assert fp.resolve_public_region("bbox")[0] == ("bbox", "bbox") and fp.resolve_public_region("Whole box")[0] == ("bbox", "bbox")
    assert fp.resolve_public_region("kp")[0] == ("province", "Khyber Pakhtunkhwa") and fp.resolve_public_region("indian-punjab")[1] == "Indian Punjab"
    assert fp.resolve_public_region("Haryana")[0] == ("india_state", "Haryana (IN)") and fp.resolve_public_region("Sheikhpura")[0] == ("district", "Sheikhpura")
    assert fp.resolve_public_region("Narnia")[0] is None
