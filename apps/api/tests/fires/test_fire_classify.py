"""fire_classify: the crop / other / uncertain rules, reasons, inputs round trip, and the store columns they feed."""

import io
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.services import fire_aggregates as fa
from app.services import fire_classify as fc
from app.services import fire_public as fp
from app.services import fire_regions as fr
from tests.copilot.test_fire_analytics import A, B, C, D1, D2, D3, FAR, META, FakeStore, _csv

NOV, JUL = date(2026, 11, 3), date(2026, 7, 3)


def _inputs(sources=(), persistent=(), hole=None) -> fc.ClassInputs:
    """A 1° × 1° cropland grid (31–32N, 74–75E) at 80 % crop, with an optional non-crop hole (lat, lon, half-width deg)."""
    frac = np.full((200, 200), 80, dtype=np.uint8)
    if hole:
        lat, lon, hw = hole
        r0, c0 = int((lat - 31.0) / 0.005), int((lon - 74.0) / 0.005)
        k = int(hw / 0.005)
        frac[max(r0 - k, 0):r0 + k + 1, max(c0 - k, 0):c0 + k + 1] = 5
    buf = io.BytesIO()
    np.savez(buf, frac=frac, lat0=31.0, lon0=74.0, step=0.005)
    src = None
    if sources:
        sbuf = io.BytesIO()
        pd.DataFrame([{"lat": la, "lon": lo, "kind": "kiln", "name": "k", "source": "test"} for la, lo in sources]).to_parquet(sbuf)
        src = sbuf.getvalue()
    per = json.dumps({"class_version": fc.CLASS_VERSION, "cells": [int(c) for c in persistent]}).encode() if persistent else None
    return fc.inputs_from_parts(buf.getvalue(), src, per, paths={"cropfrac": "x", "sources": "y" if src else None, "persistent": "z" if per else None})


def test_rules_reasons_and_windows():
    ci = _inputs(sources=[B], hole=(A[0], A[1] + 0.03, 0.01))           # a 2 km non-crop patch 3 km east of A
    lats = [A[0], B[0], C[0], A[0], A[0], A[0] + 0.0]
    lons = [A[1], B[1], C[1], A[1], A[1] + 0.03, A[1]]
    days = [NOV, NOV, NOV, JUL, NOV, NOV]
    dn = ["D", "D", "D", "D", "D", "N"]
    cells = fr.cell_id(lats, lons)
    cls, reasons, frac = fc.classify(lats, lons, days, dn, cells, ci)
    assert cls.tolist() == ["crop", "other", "uncertain", "uncertain", "other", "crop"]
    assert frac[0] == pytest.approx(0.8) and np.isnan(frac[2])          # C is east of the grid: no mask
    assert fc.reasons_text(int(reasons[0])) == ["cropland", "harvest_window"]
    assert fc.reasons_text(int(reasons[1])) == ["cropland", "harvest_window", "listed_source_within_1km"]
    assert fc.reasons_text(int(reasons[2])) == ["harvest_window", "no_mask_coverage"]
    assert fc.reasons_text(int(reasons[3])) == ["cropland"]              # July: cropland but no harvest window → uncertain
    assert fc.reasons_text(int(reasons[4])) == ["not_cropland", "harvest_window"]
    assert fc.reasons_text(int(reasons[5])) == ["cropland", "harvest_window", "night_detection"]   # night is a reason, not a verdict
    # a persistent out-of-season cell is 'other' whatever the cover
    cp = _inputs(persistent=[int(cells[0])])
    assert fc.classify([A[0]], [A[1]], [NOV], ["D"], [cells[0]], cp)[0].tolist() == ["other"]
    # no inputs at all → uncertain with the no-mask reason
    c0, r0, f0 = fc.classify([A[0]], [A[1]], [NOV], ["D"], [cells[0]], None)
    assert c0.tolist() == ["uncertain"] and fc.reasons_text(int(r0[0])) == ["harvest_window", "no_mask_coverage"] and np.isnan(f0[0])
    assert fc.in_harvest_window(date(2026, 9, 15)) and fc.in_harvest_window(date(2026, 5, 31)) and not fc.in_harvest_window(date(2026, 9, 14))
    assert fc.classify([], [], [], [], [], ci)[0].shape == (0,)


def test_near_source_confirms_in_kilometres():
    ci = _inputs(sources=[A])
    east_900m = (A[0], A[1] + 0.9 / (111.0 * np.cos(np.radians(A[0]))))
    east_1200m = (A[0], A[1] + 1.2 / (111.0 * np.cos(np.radians(A[0]))))
    assert ci.near_source([east_900m[0], east_1200m[0]], [east_900m[1], east_1200m[1]]).tolist() == [True, False]


def test_crop_frac_window_and_edges():
    ci = _inputs(hole=(31.5, 74.5, 0.002))                                # one 5 % cell at the centre
    assert ci.crop_frac([31.5025], [74.5025])[0] == pytest.approx((80 * 8 + 5) / 9 / 100, abs=1e-3)   # 3 × 3 mean
    assert np.isnan(ci.crop_frac([30.0], [74.5])[0]) and ci.crop_frac([31.0001], [74.0001])[0] == pytest.approx(0.8)
    assert fc.describe(ci)["complete"] is False and fc.describe(ci)["inputs"]["cropfrac"] == "x"
    assert fc.describe(None)["class_version"] == fc.CLASS_VERSION and fc.describe(None)["complete"] is False


def test_build_day_carries_classes_into_the_store_and_the_crop_bases():
    ci = _inputs(sources=[B])
    b = fa.build_day(D3, _csv(D3, [(A, 50.0, "h", "N20", "0815"), (A, 45.0, "h", "N21", "0905"), (B, 20.0, "n", "N20", "0815"),
                                   (C, 120.0, "h", "N20", "0815"), (FAR, 9.0, "l", "N20", "0815")]), META, None, ci)
    det = b.detections
    assert det["source_class"].tolist() == ["crop", "crop", "other", "uncertain", "uncertain"]
    assert det["crop_frac"].iloc[0] == pytest.approx(0.8) and np.isnan(det["crop_frac"].iloc[3]) and b.info["n_crop_hn"] == 1
    r = b.regions.set_index(["region_kind", "region"])
    pk = r.loc[("country", "Pakistan")]
    assert (pk["n_dedup_hn"], pk["n_crop_hn"], pk["n_other_hn"], pk["n_uncertain_hn"]) == (1, 1, 0, 0)
    assert (pk["n_crop_n20_hn"], pk["frp_crop_hn"], pk["frp_crop_n20_hn"]) == (1, 50.0, 50.0)       # the N21 twin is not NOAA-20
    ind = r.loc[("country", "India (Punjab+Haryana)")]
    assert (ind["n_dedup_hn"], ind["n_crop_hn"], ind["n_other_hn"], ind["n_uncertain_hn"]) == (2, 0, 1, 1)
    # without a classifier the same day is all 'uncertain' and the crop metrics are zero
    plain = fa.build_day(D3, _csv(D3, [(A, 50.0, "h", "N20", "0815")]), META)
    assert plain.detections["source_class"].tolist() == ["uncertain"] and plain.regions.iloc[0]["n_crop_hn"] == 0
    # the public page on the crop basis
    builds = {d: fa.build_day(d, _csv(d, [(A, 40.0, "h", "N20", "0815"), (B, 20.0, "h", "N20", "0815")]), META, None, ci) for d in (D1, D2, D3)}
    store = FakeStore(builds)
    out = fp.seasons("pakistan", "rice", "crop", store=store, today=date(2026, 11, 4))
    assert out["basis"] == "crop" and out["headline"]["fires"] == 3 and out["headline"]["comparison_n20"]["basis"] == "crop_n20"
    assert any("unvalidated" in c for c in out["caveats"])
    sp = fp.split("rice", store=store, today=date(2026, 11, 4))
    assert sp["classes"]["pakistan"] == {"crop": 3, "other": 0, "uncertain": 0} and sp["classes"]["indian_punjab"] == {"crop": 0, "other": 3, "uncertain": 0}
    assert sp["class_version"] == fc.CLASS_VERSION
    m = fp.meta(store=store, today=date(2026, 11, 4))
    assert m["bases_available"] == ["all", "n20", "crop", "crop_n20"] and m["classification"]["available"] is True
    # an older store refuses the crop basis with a clear message
    store.manifest()["schema_version"] = 2
    fp._TABLE = None
    assert "schema 3" in fp.seasons("pakistan", "rice", "crop", store=store, today=date(2026, 11, 4))["error"]


def test_rules_state_source_coverage():
    import app.services.fire_classify as fc
    import app.services.fire_analytics as fa
    assert "Pakistan lists only" in fc.RULES["coverage"]
    assert "Pakistan lists only" in fa.FIRE_DEFINITIONS["classification"]
