#!/usr/bin/env python3
"""Validation sample for the fire source classification (app/services/fire_classify.py).

Draw mode: a stratified sample of detections — class × region × season × day/night, plus the
site-adjacent and persistent-cell strata — written as a CSV a person labels in Copernicus Browser
(before/after Sentinel-2 at the point). The script never labels anything.

    python3 scripts/fire_class_sample.py draw --start 2026-09-15 --end 2026-11-30 --per-stratum 12 --out sample.csv

Score mode: read the labelled CSV back (column `label` ∈ crop | other | uncertain | cannot_tell) and
report precision per class and region. Precision of the classifier on detected hotspots says
nothing about the crop fires the satellites never saw (completeness is a separate question).

    python3 scripts/fire_class_sample.py score --labels sample_labelled.csv

Needs application default credentials for GCS (reads the detection store). Run from apps/api.
"""
import argparse
import io
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import fire_classify as fc  # noqa: E402

BUCKET = "paqi-forecasts-hawanama-data"
AGG_PREFIX = "hindcast/firms/agg"
REGIONS = {"PK Punjab": ("PK", "Punjab"), "IN Punjab": ("IN", "Punjab (IN)"), "Haryana": ("IN", "Haryana (IN)"), "PK other": ("PK", None)}


def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def load_detections(start: date, end: date) -> pd.DataFrame:
    import pyarrow.parquet as pq
    b = _bucket()
    frames = []
    for y in range(start.year, end.year + 1):
        raw = b.blob(f"{AGG_PREFIX}/detections/year={y}/detections.parquet").download_as_bytes()
        t = pq.read_table(io.BytesIO(raw), filters=[("pk_day", ">=", start), ("pk_day", "<=", end)]).to_pandas()
        frames.append(t)
    df = pd.concat(frames, ignore_index=True)
    if "source_class" not in df.columns:
        sys.exit("the detection store has no source_class column: rebuild it (schema 3) first")
    return df[df["is_primary"] & df["grp_hn"]].reset_index(drop=True)


def region_of(row) -> str:
    for name, (country, province) in REGIONS.items():
        if row["country"] == country and (province is None or row["province"] == province):
            return name
    return "other"


def browser_link(lat: float, lon: float, day: date) -> str:
    """Copernicus Browser at the point, Sentinel-2 true colour, the week around the detection."""
    return (f"https://browser.dataspace.copernicus.eu/?zoom=14&lat={lat:.5f}&lng={lon:.5f}&themeId=DEFAULT-THEME"
            f"&datasetId=S2_L2A_CDAS&fromTime={day.isoformat()}T00%3A00%3A00.000Z&toTime={day.isoformat()}T23%3A59%3A59.999Z&layerId=1_TRUE_COLOR")


def draw(a) -> int:
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    df = load_detections(start, end)
    df["region"] = df.apply(region_of, axis=1)
    df = df[df["region"] != "other"]
    df["stratum_extra"] = np.where((df["class_reasons"] & fc.R_NEAR_SOURCE) != 0, "near_source",
                                   np.where((df["class_reasons"] & fc.R_PERSISTENT) != 0, "persistent", "plain"))
    df["dn"] = df["daynight"].fillna("?")
    rng = np.random.default_rng(a.seed)
    parts = []
    for keys, g in df.groupby(["source_class", "region", "dn", "stratum_extra"]):
        take = min(a.per_stratum, len(g))
        parts.append(g.iloc[rng.choice(len(g), size=take, replace=False)])
    sample = pd.concat(parts).sort_values(["region", "source_class", "pk_day"]).reset_index(drop=True)
    out = pd.DataFrame({
        "sample_id": [f"S{i:04d}" for i in range(len(sample))],
        "pk_day": sample["pk_day"].astype(str), "lat": sample["lat"].round(5), "lon": sample["lon"].round(5),
        "region": sample["region"], "district": sample["district"], "day_night": sample["dn"], "satellite": sample["satellite"],
        "frp": sample["frp"].round(1), "confidence": sample["confidence"],
        "classifier": sample["source_class"], "reasons": [";".join(fc.reasons_text(int(r))) for r in sample["class_reasons"]],
        "crop_frac": sample["crop_frac"].round(2), "stratum": sample["stratum_extra"],
        "browser": [browser_link(la, lo, pd.Timestamp(d).date()) for la, lo, d in zip(sample["lat"], sample["lon"], sample["pk_day"])],
        "label": "", "label_note": "",
    })
    out.to_csv(a.out, index=False)
    print(f"{len(out)} detections drawn from {len(df)} headline clusters ({start} – {end}); strata = class × region × day/night × "
          f"{{plain, near_source, persistent}}, up to {a.per_stratum} each; class version {fc.CLASS_VERSION}")
    print(out.groupby(["region", "classifier"]).size().unstack(fill_value=0).to_string())
    print("label each row crop | other | uncertain | cannot_tell, then: fire_class_sample.py score --labels", a.out)
    return 0


def score(a) -> int:
    df = pd.read_csv(a.labels)
    df = df[df["label"].isin(["crop", "other", "uncertain", "cannot_tell"])]
    judged = df[df["label"] != "cannot_tell"]
    print(f"{len(df)} labelled rows, {len(judged)} judged ({len(df) - len(judged)} cannot_tell)")
    rows = []
    for (region, cls), g in judged.groupby(["region", "classifier"]):
        hit = int((g["label"] == cls).sum())
        rows.append({"region": region, "classifier": cls, "n": len(g), "agree": hit, "precision": round(hit / len(g), 2)})
    for cls, g in judged.groupby("classifier"):
        hit = int((g["label"] == cls).sum())
        rows.append({"region": "ALL", "classifier": cls, "n": len(g), "agree": hit, "precision": round(hit / len(g), 2)})
    print(pd.DataFrame(rows).to_string(index=False))
    print("Confusion (rows = classifier, cols = label):")
    print(pd.crosstab(judged["classifier"], judged["label"]).to_string())
    print("Precision is per detected hotspot; it does not measure the crop fires the satellites missed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--start", required=True)
    d.add_argument("--end", required=True)
    d.add_argument("--per-stratum", type=int, default=12)
    d.add_argument("--seed", type=int, default=20261105)
    d.add_argument("--out", default="fire_class_sample.csv")
    s = sub.add_parser("score")
    s.add_argument("--labels", required=True)
    a = ap.parse_args()
    return draw(a) if a.cmd == "draw" else score(a)


if __name__ == "__main__":
    raise SystemExit(main())
