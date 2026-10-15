"""Diagnose whether the deployed `support_aware` PM2.5 model would benefit from
post-hoc calibration. Pairs daily station observations with COG predictions,
computes calibration diagnostics, fits a candidate isotonic + piecewise-linear
calibrator with K-fold CV grouped by date, and writes a verdict report.

Usage:
    python scripts/calibration_check.py --days 90 --country Pakistan --min-hours 6
    python scripts/calibration_check.py --rebuild   # force re-pairing from GCS
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from google.cloud import storage

OUTPUTS_BUCKET = "paqi-outputs-hawanama-data"
RAW_BUCKET = "paqi-raw-hawanama-data"
SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "calibration_check"
PAKISTAN_GEOJSON = (
    SCRIPT_DIR.parent / "apps" / "api" / "data" / "pakistan_country.geojson"
)


# ── Pakistan boundary (cached per process) ────────────────────────────────────
_PAKISTAN_POLY = None


def _pakistan_poly():
    global _PAKISTAN_POLY
    if _PAKISTAN_POLY is None:
        from shapely.geometry import shape

        with open(PAKISTAN_GEOJSON) as f:
            gj = json.load(f)
        _PAKISTAN_POLY = shape(gj["features"][0]["geometry"])
    return _PAKISTAN_POLY


def _in_pakistan(lat: float, lon: float) -> bool:
    from shapely.geometry import Point

    return _pakistan_poly().contains(Point(lon, lat))


# ── GCS helpers ───────────────────────────────────────────────────────────────


def _list_dates_with_support_aware(client: storage.Client, n_days: int) -> List[str]:
    """Find recent dates with both a support_aware COG and a station_daily parquet."""
    today = datetime.now(timezone.utc).date()
    candidates = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, n_days + 5)
    ]
    out_bucket = client.bucket(OUTPUTS_BUCKET)
    raw_bucket = client.bucket(RAW_BUCKET)
    keep: List[str] = []
    for d in candidates:
        cog = out_bucket.blob(f"predictions/support_aware/date={d}/pm25_{d}.tif")
        # cheap existence check on parquet directory
        parquets = list(
            raw_bucket.list_blobs(prefix=f"raw/station_daily/date={d}/", max_results=5)
        )
        has_parquet = any(b.name.endswith(".parquet") for b in parquets)
        if cog.exists(client) and has_parquet:
            keep.append(d)
        if len(keep) >= n_days:
            break
    return keep


def _download_to_tmp(client: storage.Client, bucket: str, path: str) -> Optional[str]:
    blob = client.bucket(bucket).blob(path)
    if not blob.exists(client):
        return None
    f = tempfile.NamedTemporaryFile(suffix=Path(path).suffix, delete=False)
    blob.download_to_filename(f.name)
    return f.name


def _load_station_daily(
    client: storage.Client, date: str, min_hours: int
) -> pd.DataFrame:
    """Read the station_daily parquet for `date`. Returns a DataFrame with
    columns: station_id, lat, lon, pm25_obs, valid_hours."""
    raw = client.bucket(RAW_BUCKET)
    blobs = [
        b
        for b in raw.list_blobs(prefix=f"raw/station_daily/date={date}/")
        if b.name.endswith(".parquet")
    ]
    if not blobs:
        return pd.DataFrame()

    dfs = []
    for blob in blobs:
        with tempfile.NamedTemporaryFile(suffix=".parquet") as f:
            blob.download_to_filename(f.name)
            dfs.append(pd.read_parquet(f.name))
    df = pd.concat(dfs, ignore_index=True)

    pm_col = "pm25_ugm3_mean" if "pm25_ugm3_mean" in df.columns else "pm25_daily_mean"
    hr_col = "pm25_ugm3_valid_hours" if "pm25_ugm3_valid_hours" in df.columns else None
    lat_col = next(c for c in ["latitude", "lat"] if c in df.columns)
    lon_col = next(c for c in ["longitude", "lon"] if c in df.columns)
    sid_col = "station_id" if "station_id" in df.columns else None

    df = df.dropna(subset=[pm_col, lat_col, lon_col])
    if hr_col:
        df = df[df[hr_col] >= min_hours]
    if sid_col is None:
        df["station_id"] = (
            df.get("station_name", "")
            .astype(str)
            .str.cat(df[lat_col].round(4).astype(str), sep="@")
        )
        sid_col = "station_id"

    return pd.DataFrame(
        {
            "station_id": df[sid_col].astype(str).values,
            "lat": df[lat_col].astype(float).values,
            "lon": df[lon_col].astype(float).values,
            "pm25_obs": df[pm_col].astype(float).round(2).values,
            "valid_hours": (df[hr_col].astype(int).values if hr_col else None),
        }
    )


def _sample_cog(tif_path: str, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Sample a raster at given coordinates. Returns NaN where nodata or off-grid."""
    import rasterio

    with rasterio.open(tif_path) as ds:
        nodata = ds.nodata
        coords = list(zip(lons.tolist(), lats.tolist()))
        out = np.full(len(coords), np.nan, dtype=np.float64)
        # ds.sample yields iterables of band values
        for i, vals in enumerate(ds.sample(coords)):
            v = vals[0]
            if v is None:
                continue
            if nodata is not None and v == nodata:
                continue
            if not np.isfinite(v):
                continue
            out[i] = float(v)
    return out


def _process_date(date: str, country: str, min_hours: int) -> pd.DataFrame:
    """Build paired (date, station, obs, pred_support_aware, pred_backbone) rows."""
    client = storage.Client()
    obs = _load_station_daily(client, date, min_hours=min_hours)
    if obs.empty:
        return pd.DataFrame()

    # Country filter
    if country.lower() == "pakistan":
        keep = obs.apply(lambda r: _in_pakistan(r["lat"], r["lon"]), axis=1).values
        obs = obs[keep].reset_index(drop=True)
        if obs.empty:
            return pd.DataFrame()

    sa_path = _download_to_tmp(
        client,
        OUTPUTS_BUCKET,
        f"predictions/support_aware/date={date}/pm25_{date}.tif",
    )
    bb_path = _download_to_tmp(
        client,
        OUTPUTS_BUCKET,
        f"predictions/date={date}/pm25_{date}.tif",
    )

    try:
        lats = obs["lat"].to_numpy()
        lons = obs["lon"].to_numpy()
        pred_sa = _sample_cog(sa_path, lats, lons) if sa_path else np.full(len(obs), np.nan)
        pred_bb = _sample_cog(bb_path, lats, lons) if bb_path else np.full(len(obs), np.nan)
    finally:
        for p in (sa_path, bb_path):
            if p and os.path.exists(p):
                os.unlink(p)

    return pd.DataFrame(
        {
            "date": date,
            "station_id": obs["station_id"].values,
            "lat": lats,
            "lon": lons,
            "obs": obs["pm25_obs"].values,
            "pred_support_aware": pred_sa,
            "pred_backbone": pred_bb,
        }
    )


def build_pairs(days: int, country: str, min_hours: int) -> pd.DataFrame:
    client = storage.Client()
    dates = _list_dates_with_support_aware(client, days)
    print(f"Found {len(dates)} dates with both support_aware COG + station_daily parquet")
    print(f"   range: {dates[-1] if dates else '?'} → {dates[0] if dates else '?'}")
    if not dates:
        return pd.DataFrame()

    all_pairs: List[pd.DataFrame] = []
    with ProcessPoolExecutor(max_workers=min(8, len(dates))) as pool:
        futures = {
            pool.submit(_process_date, d, country, min_hours): d for d in dates
        }
        for fut in as_completed(futures):
            d = futures[fut]
            try:
                df = fut.result()
                if not df.empty:
                    all_pairs.append(df)
                    print(f"   {d}: {len(df)} paired rows")
                else:
                    print(f"   {d}: no rows")
            except Exception as e:
                print(f"   {d}: ERROR {e}", file=sys.stderr)

    if not all_pairs:
        return pd.DataFrame()
    pairs = pd.concat(all_pairs, ignore_index=True)
    # Drop rows where either prediction is NaN — can't compare
    n0 = len(pairs)
    pairs = pairs.dropna(subset=["obs", "pred_support_aware"]).reset_index(drop=True)
    print(f"Pairs: {n0} → {len(pairs)} after dropna on (obs, pred_support_aware)")
    return pairs


# ── Diagnostics ───────────────────────────────────────────────────────────────


def _basic_metrics(obs: np.ndarray, pred: np.ndarray) -> dict:
    resid = obs - pred
    rmse = float(np.sqrt(np.mean(resid**2)))
    mae = float(np.mean(np.abs(resid)))
    bias = float(np.mean(resid))
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((obs - obs.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    # OLS slope/intercept of obs ~ pred
    if pred.std() > 1e-9:
        slope, intercept = np.polyfit(pred, obs, 1)
    else:
        slope, intercept = float("nan"), float("nan")
    return {
        "rmse": rmse,
        "mae": mae,
        "bias_mean": bias,
        "r2": float(r2),
        "ols_slope": float(slope),
        "ols_intercept": float(intercept),
        "n": int(len(obs)),
    }


def _per_bin_bias(obs: np.ndarray, pred: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Equal-frequency bins of pred → bin stats."""
    qs = np.linspace(0, 1, n_bins + 1)
    edges = np.unique(np.quantile(pred, qs))
    if len(edges) < 3:
        return pd.DataFrame()
    rows = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        mask = (pred >= lo) & (pred <= hi if i == len(edges) - 2 else pred < hi)
        if mask.sum() < 5:
            continue
        rows.append(
            {
                "bin": f"{lo:.0f}–{hi:.0f}",
                "n": int(mask.sum()),
                "pred_mean": float(pred[mask].mean()),
                "obs_mean": float(obs[mask].mean()),
                "bias_mean": float((obs[mask] - pred[mask]).mean()),
                "rmse": float(np.sqrt(np.mean((obs[mask] - pred[mask]) ** 2))),
            }
        )
    return pd.DataFrame(rows)


def _kfold_calibrate(pairs: pd.DataFrame, n_folds: int = 5) -> dict:
    """5-fold CV grouped by date. For each fold:
       fit calibrator on train, transform test, accumulate held-out predictions.
       Returns {raw, isotonic, piecewise} metrics + arrays for plotting."""
    from sklearn.isotonic import IsotonicRegression

    rng = np.random.default_rng(seed=42)
    dates = np.array(sorted(pairs["date"].unique()))
    rng.shuffle(dates)
    fold_assignment = {d: i % n_folds for i, d in enumerate(dates)}
    pairs = pairs.copy()
    pairs["fold"] = pairs["date"].map(fold_assignment)

    obs = pairs["obs"].to_numpy()
    pred = pairs["pred_support_aware"].to_numpy()
    iso_pred = np.full_like(pred, np.nan, dtype=float)
    pwl_pred = np.full_like(pred, np.nan, dtype=float)

    for k in range(n_folds):
        train_mask = pairs["fold"].values != k
        test_mask = ~train_mask
        if train_mask.sum() < 50 or test_mask.sum() < 5:
            continue
        x_tr, y_tr = pred[train_mask], obs[train_mask]
        x_te = pred[test_mask]

        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(x_tr, y_tr)
        iso_pred[test_mask] = iso.predict(x_te)

        # 5-knot piecewise-linear (quantile-based)
        knots = np.quantile(x_tr, np.linspace(0, 1, 6))
        knots = np.unique(knots)
        if len(knots) < 3:
            pwl_pred[test_mask] = x_te  # fall through if degenerate
        else:
            # Means inside each bin
            train_bin = np.digitize(x_tr, knots[1:-1])
            knot_means_x = np.array(
                [
                    x_tr[train_bin == j].mean() if (train_bin == j).any() else (knots[j] + knots[j + 1]) / 2 if j + 1 < len(knots) else knots[-1]
                    for j in range(len(knots) - 1)
                ]
            )
            knot_means_y = np.array(
                [
                    y_tr[train_bin == j].mean() if (train_bin == j).any() else y_tr.mean()
                    for j in range(len(knots) - 1)
                ]
            )
            order = np.argsort(knot_means_x)
            xp = knot_means_x[order]
            yp = knot_means_y[order]
            pwl_pred[test_mask] = np.interp(x_te, xp, yp)

    # Drop test rows where calibrator never assigned (small folds) for fair compare
    good = ~np.isnan(iso_pred) & ~np.isnan(pwl_pred)
    return {
        "raw": _basic_metrics(obs[good], pred[good]),
        "isotonic": _basic_metrics(obs[good], iso_pred[good]),
        "piecewise": _basic_metrics(obs[good], pwl_pred[good]),
        "obs": obs[good],
        "pred": pred[good],
        "iso_pred": iso_pred[good],
        "pwl_pred": pwl_pred[good],
    }


# ── Plots ─────────────────────────────────────────────────────────────────────


def _plot_scatter(obs, pred, title: str, out_path: Path):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(pred, obs, s=4, alpha=0.25)
    lim = max(np.percentile(pred, 99.5), np.percentile(obs, 99.5))
    ax.plot([0, lim], [0, lim], "k--", lw=1, label="y=x")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("predicted PM2.5 (µg/m³)")
    ax.set_ylabel("observed PM2.5 (µg/m³)")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _plot_reliability(per_bin: pd.DataFrame, title: str, out_path: Path):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(per_bin["pred_mean"], per_bin["obs_mean"], "o-", label="binned mean")
    lim = max(per_bin["pred_mean"].max(), per_bin["obs_mean"].max()) * 1.1
    ax.plot([0, lim], [0, lim], "k--", lw=1, label="y=x")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("predicted PM2.5 bin mean")
    ax.set_ylabel("observed PM2.5 bin mean")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _plot_residual_vs_pred(obs, pred, title: str, out_path: Path):
    import matplotlib.pyplot as plt

    resid = obs - pred
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(pred, resid, s=4, alpha=0.2)
    ax.axhline(0, color="k", lw=1)
    # rolling mean
    order = np.argsort(pred)
    p = pred[order]
    r = resid[order]
    win = max(50, len(p) // 30)
    if len(p) >= win:
        kernel = np.ones(win) / win
        rolling = np.convolve(r, kernel, mode="valid")
        ax.plot(p[win - 1 :], rolling, "r-", lw=2, label=f"rolling mean (n={win})")
        ax.legend()
    ax.set_xlabel("predicted PM2.5")
    ax.set_ylabel("residual (obs − pred)")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _plot_before_after(cv: dict, out_path: Path):
    import matplotlib.pyplot as plt

    obs = cv["obs"]
    pred = cv["pred"]
    iso = cv["iso_pred"]

    bins = np.quantile(pred, np.linspace(0, 1, 11))
    bins = np.unique(bins)
    centers, raw_rmse, iso_rmse, ns = [], [], [], []
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        mask = (pred >= lo) & (pred <= hi if i == len(bins) - 2 else pred < hi)
        if mask.sum() < 5:
            continue
        centers.append((lo + hi) / 2)
        raw_rmse.append(np.sqrt(np.mean((obs[mask] - pred[mask]) ** 2)))
        iso_rmse.append(np.sqrt(np.mean((obs[mask] - iso[mask]) ** 2)))
        ns.append(mask.sum())

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(centers, raw_rmse, "o-", label="raw")
    ax.plot(centers, iso_rmse, "s-", label="after isotonic (held-out)")
    for i, n in enumerate(ns):
        ax.annotate(f"n={n}", (centers[i], max(raw_rmse[i], iso_rmse[i])), fontsize=7)
    ax.set_xlabel("predicted PM2.5 bin center")
    ax.set_ylabel("RMSE inside bin")
    ax.set_title("RMSE per prediction-value bin: raw vs calibrated")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--country", default="Pakistan")
    ap.add_argument("--min-hours", type=int, default=6)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pairs_path = OUT_DIR / "pairs.parquet"

    if pairs_path.exists() and not args.rebuild:
        print(f"Loading cached pairs from {pairs_path}")
        pairs = pd.read_parquet(pairs_path)
    else:
        pairs = build_pairs(args.days, args.country, args.min_hours)
        if pairs.empty:
            print("No pairs collected. Aborting.", file=sys.stderr)
            sys.exit(1)
        pairs.to_parquet(pairs_path, index=False)
        print(f"Wrote {len(pairs)} pairs to {pairs_path}")

    # ── Diagnostics on support_aware ──
    obs = pairs["obs"].to_numpy()
    pred_sa = pairs["pred_support_aware"].to_numpy()
    pred_bb = pairs["pred_backbone"].to_numpy()
    bb_mask = ~np.isnan(pred_bb)

    metrics_sa = _basic_metrics(obs, pred_sa)
    metrics_bb = (
        _basic_metrics(obs[bb_mask], pred_bb[bb_mask]) if bb_mask.sum() > 50 else None
    )

    bins_sa = _per_bin_bias(obs, pred_sa, n_bins=10)
    cv = _kfold_calibrate(pairs.dropna(subset=["pred_support_aware"]).copy())

    # ── Plots ──
    _plot_scatter(obs, pred_sa, "support_aware: obs vs pred", OUT_DIR / "scatter.png")
    _plot_reliability(
        bins_sa, "support_aware reliability (per pred bin)", OUT_DIR / "reliability.png"
    )
    _plot_residual_vs_pred(
        obs, pred_sa, "support_aware: residual vs pred", OUT_DIR / "residual_vs_pred.png"
    )
    _plot_before_after(cv, OUT_DIR / "before_after_rmse_by_bin.png")

    # ── Verdict rules ──
    rmse_raw = cv["raw"]["rmse"]
    rmse_iso = cv["isotonic"]["rmse"]
    rmse_pwl = cv["piecewise"]["rmse"]
    iso_improvement = (rmse_raw - rmse_iso) / rmse_raw * 100.0
    pwl_improvement = (rmse_raw - rmse_pwl) / rmse_raw * 100.0

    # Reliability curvature: range of bin biases
    if not bins_sa.empty:
        bias_range = float(bins_sa["bias_mean"].max() - bins_sa["bias_mean"].min())
    else:
        bias_range = float("nan")

    if iso_improvement > 10 and bias_range > 5:
        verdict = "**YES** — calibration would materially help."
        rec = (
            "Held-out RMSE improvement >10% AND reliability bins span "
            f">{bias_range:.1f} µg/m³ in mean bias. "
            "Recommend shipping isotonic calibration as an inference-time step on the "
            "support_aware COG."
        )
    elif iso_improvement > 3 or (pwl_improvement > 3 and abs(iso_improvement - pwl_improvement) < 2):
        verdict = "**MAYBE** — calibration gives a modest, range-localised improvement."
        rec = (
            f"RMSE improvement {iso_improvement:.1f}% (isotonic), "
            f"{pwl_improvement:.1f}% (piecewise). "
            "Consider a simpler piecewise correction in the bins with the largest bias; "
            "do NOT ship a global isotonic — risk of over-fitting."
        )
    else:
        verdict = "**NO** — calibration would not materially help."
        rec = (
            f"Held-out RMSE only changes by {iso_improvement:.1f}% (isotonic) and "
            f"{pwl_improvement:.1f}% (piecewise). "
            "support_aware is already approximately well-calibrated; effort is better "
            "spent on improving feature inputs / model architecture."
        )

    # ── Report ──
    report = []
    report.append("# support_aware calibration check\n")
    report.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_\n")
    report.append(f"_Country: {args.country} · min valid hours: {args.min_hours} · days: {args.days}_\n\n")
    report.append(f"## Verdict\n\n{verdict}\n\n{rec}\n\n")

    report.append("## Headline accuracy (raw, no calibration)\n\n")
    report.append("| metric | support_aware | backbone |\n")
    report.append("|---|---|---|\n")
    keys = ["n", "rmse", "mae", "bias_mean", "r2", "ols_slope", "ols_intercept"]
    for k in keys:
        sa_v = metrics_sa[k]
        bb_v = metrics_bb[k] if metrics_bb else None
        sa_s = f"{sa_v:.3f}" if isinstance(sa_v, float) else str(sa_v)
        bb_s = (f"{bb_v:.3f}" if isinstance(bb_v, float) else str(bb_v)) if bb_v is not None else "—"
        report.append(f"| {k} | {sa_s} | {bb_s} |\n")
    report.append("\n")

    report.append("## Held-out (5-fold CV grouped by date) on support_aware\n\n")
    report.append("| metric | raw | isotonic | piecewise (5 knots) |\n")
    report.append("|---|---|---|---|\n")
    for k in ["n", "rmse", "mae", "bias_mean", "r2"]:
        rv = cv["raw"][k]
        iv = cv["isotonic"][k]
        pv = cv["piecewise"][k]
        report.append(
            f"| {k} | "
            f"{rv:.3f}".rstrip("0").rstrip(".") + " | "
            f"{iv:.3f}".rstrip("0").rstrip(".") + " | "
            f"{pv:.3f}".rstrip("0").rstrip(".") + " |\n"
        )
    report.append(f"\n_RMSE Δ vs raw: isotonic={iso_improvement:+.1f}%, piecewise={pwl_improvement:+.1f}%_\n\n")

    report.append("## Bias by predicted-value bin (raw support_aware)\n\n")
    report.append("| bin | n | pred mean | obs mean | bias (obs−pred) | RMSE |\n")
    report.append("|---|---|---|---|---|---|\n")
    for _, r in bins_sa.iterrows():
        report.append(
            f"| {r['bin']} | {int(r['n'])} | {r['pred_mean']:.1f} | "
            f"{r['obs_mean']:.1f} | {r['bias_mean']:+.2f} | {r['rmse']:.2f} |\n"
        )
    report.append(f"\n_Bias range across bins: {bias_range:.1f} µg/m³_\n\n")

    report.append("## Plots\n\n")
    report.append("- `scatter.png` — full scatter of obs vs pred with y=x reference\n")
    report.append("- `reliability.png` — reliability diagram (bin-mean obs vs pred)\n")
    report.append("- `residual_vs_pred.png` — residual cloud + rolling mean vs pred\n")
    report.append("- `before_after_rmse_by_bin.png` — held-out RMSE per bin, raw vs isotonic\n")

    report_path = OUT_DIR / "REPORT.md"
    report_path.write_text("".join(report))
    print(f"\n✔ wrote {report_path}\n")
    print("--- VERDICT ---")
    print(verdict)
    print(rec)


if __name__ == "__main__":
    main()
