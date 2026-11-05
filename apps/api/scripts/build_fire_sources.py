#!/usr/bin/env python3
"""Build two of the three fire-classification inputs (see app/services/fire_classify.py) and upload them:

  thermal_sources_v1.parquet   brick kilns (APAD/Zenodo via the civic-asset table), OSM factories, and the
                               power, cement, steel, sugar, industrial and mining sites of emission_sources.json
  persistent_cells_v1.json     0.02° cells with detections on >= 10 distinct days *outside* both harvest
                               windows in at least one calendar year of the detection store

    python3 scripts/build_fire_sources.py --emission-sources ../dashboard-frontend/public/emission_sources.json [--dry-run]

Needs application default credentials for GCS. Run from apps/api. The cropland grid is built by
build_cropland_fraction.py. Re-running overwrites the same paths: bump the version in fire_classify
when a rule or an input changes materially.
"""
import argparse
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import fire_classify as fc  # noqa: E402
AGG_PREFIX = "hindcast/firms/agg"
BUCKET = "paqi-forecasts-hawanama-data"          # the day-file bucket (no settings import: the scripts need no database)


def default_bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)

CIVIC_PATH = "assets/civic_assets_pk.parquet"
EMISSION_KINDS = {"power_plants": "power_plant", "cement_plants": "cement_plant", "steel_sites": "steel", "sugar_mills": "sugar_mill",
                  "industrial_sites": "industrial", "mines_quarries": "mine_quarry"}


def thermal_sources(bucket, emission_path: str) -> pd.DataFrame:
    civic = pd.read_parquet(io.BytesIO(bucket.blob(CIVIC_PATH).download_as_bytes()))
    rows = []
    for _, r in civic[civic["asset_type"].isin(["brick_kiln", "factory"])].iterrows():
        rows.append({"lat": float(r["lat"]), "lon": float(r["lon"]), "kind": "brick_kiln" if r["asset_type"] == "brick_kiln" else "factory",
                     "name": str(r.get("name") or ""), "source": str(r.get("source") or "OSM")})
    doc = json.load(open(emission_path, encoding="utf-8"))
    for key, kind in EMISSION_KINDS.items():
        for f in doc.get(key, {}).get("features", []):
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = g["coordinates"][:2]
            rows.append({"lat": float(lat), "lon": float(lon), "kind": kind, "name": str(f.get("properties", {}).get("name") or ""),
                         "source": "emission_sources.json"})
    df = pd.DataFrame(rows).dropna(subset=["lat", "lon"])
    df = df[(df["lat"].between(23, 37)) & (df["lon"].between(60, 78))].drop_duplicates(subset=["lat", "lon", "kind"]).reset_index(drop=True)
    return df


def persistent_cells(bucket, years: range) -> dict:
    """Cells with >= PERSISTENT_MIN_DAYS distinct out-of-season detection days in one calendar year."""
    import pyarrow.parquet as pq
    days_by_cell_year = defaultdict(set)
    used = []
    for y in years:
        path = f"{AGG_PREFIX}/detections/year={y}/detections.parquet"
        try:
            raw = bucket.blob(path).download_as_bytes()
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "NotFound" or getattr(exc, "code", None) == 404:
                continue
            raise
        t = pq.read_table(io.BytesIO(raw), columns=["pk_day", "cell_id", "confidence"]).to_pandas()
        t = t[t["confidence"].isin(["h", "n", "high", "nominal"])]
        t["pk_day"] = pd.to_datetime(t["pk_day"]).dt.date
        t = t[[not fc.in_harvest_window(d) for d in t["pk_day"]]]
        for cell, d in zip(t["cell_id"].tolist(), t["pk_day"].tolist()):
            days_by_cell_year[(int(cell), d.year)].add(d)
        used.append(y)
    cells = sorted({cell for (cell, _), ds in days_by_cell_year.items() if len(ds) >= fc.PERSISTENT_MIN_DAYS})
    return {"class_version": fc.CLASS_VERSION, "rule": f">= {fc.PERSISTENT_MIN_DAYS} distinct high/nominal detection days outside the harvest windows "
                                                      f"{fc.HARVEST_WINDOWS} in one calendar year; 0.02° cells", "years": used, "cells": cells}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emission-sources", required=True)
    ap.add_argument("--years", default="2020-2026")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    y0, y1 = (int(x) for x in a.years.split("-"))
    bucket = default_bucket()
    src = thermal_sources(bucket, a.emission_sources)
    print("thermal sources:", len(src), src["kind"].value_counts().to_dict())
    per = persistent_cells(bucket, range(y0, y1 + 1))
    print("persistent out-of-season cells:", len(per["cells"]), "years", per["years"])
    if a.dry_run:
        return 0
    buf = io.BytesIO()
    src.to_parquet(buf, index=False)
    bucket.blob(fc.SOURCES_PATH).upload_from_string(buf.getvalue(), content_type="application/octet-stream")
    bucket.blob(fc.PERSISTENT_PATH).upload_from_string(json.dumps(per), content_type="application/json")
    print("uploaded", fc.SOURCES_PATH, fc.PERSISTENT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
