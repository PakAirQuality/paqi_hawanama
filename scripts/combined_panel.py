"""Combined panel for each AirNow-covered city in Pakistan.

Top row: time-series with one line per available network.
Bottom row: scatter grid — PAQI/IQAir vs each reference AND AirGradient vs each
reference (omitting any reference the city lacks).

Sources:
  Regulatory Monitors  — providers.code='punjab'                  (Lahore + Islamabad-via-Rawalpindi)
  PAQI / IQAir              — providers.display_name='Airvisual/PAQI'  (all 4 cities)
  AirGradient               — stations.monitor_type='AirGradient'      (all 4 cities, from Feb 2025)
  AirNow     — pulled via AirNow data API               (all 4 cities)

Reads the CSVs produced by compare_aqms_lcs_consulate.py and writes:
  plots/combined_<slug>.png
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path("/Users/rehanahmad/Desktop/hawanama-main")
DATA = REPO / "data"
PLOTS = REPO / "plots"

COLOR = {
    "Regulatory Monitors": "#1f3a93",   # dark blue
    "PAQI / IQAir":             "#e67e22",   # orange
    "AirGradient":              "#8e44ad",   # purple
    "AirNow":    "#16a085",   # green
}

# Per-city pairing config. None for punjab_city = no regulatory line.
# AirGradient + PAQI city tags use the literal city name (no airshed proxy).
CITY_CONFIGS = [
    {"display": "Lahore",    "slug": "lahore",
     "punjab_city": "Lahore",    "lcs_city": "Lahore",    "consulate_city": "Lahore",    "ag_city": "Lahore",
     "note": None},
    {"display": "Islamabad", "slug": "islamabad",
     "punjab_city": "Rawalpindi", "lcs_city": "Islamabad", "consulate_city": "Islamabad", "ag_city": "Islamabad",
     "note": "Punjab AQMS line uses 3 Rawalpindi stations (7–22 km from US Embassy); Punjab EPA has no monitor in Islamabad."},
    {"display": "Karachi",   "slug": "karachi",
     "punjab_city": None,         "lcs_city": "Karachi",   "consulate_city": "Karachi",   "ag_city": "Karachi",
     "note": None},
    {"display": "Peshawar",  "slug": "peshawar",
     "punjab_city": None,         "lcs_city": "Peshawar",  "consulate_city": "Peshawar",  "ag_city": "Peshawar",
     "note": None},
]


def daily_means_by_city(csv: Path) -> pd.DataFrame:
    if not csv.exists() or csv.stat().st_size == 0:
        return pd.DataFrame(columns=["city", "date", "value"])
    df = pd.read_csv(csv)
    if df.empty:
        return pd.DataFrame(columns=["city", "date", "value"])
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], errors="coerce", utc=True)
    df = df[df["datetime_utc"].notna()]
    df["city"] = df["city"].astype(str).str.strip()
    df = df[df["city"].astype(bool) & (df["city"].str.lower() != "nan")]
    if df.empty:
        return pd.DataFrame(columns=["city", "date", "value"])
    df["date"] = df["datetime_utc"].dt.tz_convert(None).dt.floor("D")
    return df.groupby(["city", "date"], as_index=False)["value"].mean()


def ols(x: np.ndarray, y: np.ndarray):
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return slope, intercept, r2


def lookup(daily: pd.DataFrame, city: Optional[str]) -> pd.DataFrame:
    if not city or daily.empty:
        return pd.DataFrame(columns=["date", "value"])
    return daily[daily["city"].str.lower() == city.lower()][["date", "value"]]


def scatter_panel(ax, candidate_label: str, ref_label: str,
                  ref_df: pd.DataFrame, cand_df: pd.DataFrame):
    candidate_color = COLOR[candidate_label]
    ax.set_title(f"{candidate_label} vs {ref_label}", fontsize=10)
    ax.set_xlabel(f"{ref_label} (µg/m³)", fontsize=9)
    ax.set_ylabel(f"{candidate_label} (µg/m³)", fontsize=9)
    ax.grid(alpha=0.25)
    ax.set_aspect("equal", adjustable="box")
    m = ref_df.merge(cand_df, on="date", suffixes=("_ref", "_cand")).dropna()
    if len(m) < 5:
        ax.text(0.5, 0.5, f"insufficient overlap\n(N={len(m)})",
                transform=ax.transAxes, ha="center", va="center")
        return
    x, y = m["value_ref"].to_numpy(), m["value_cand"].to_numpy()
    slope, intercept, r2 = ols(x, y)
    lim = max(x.max(), y.max()) * 1.05
    ax.scatter(x, y, s=8, alpha=0.45, color=candidate_color, edgecolors="none")
    ax.plot([0, lim], [0, lim], "k--", alpha=0.5, label="1:1", linewidth=0.9)
    xs = np.linspace(0, lim, 100)
    ax.plot(xs, slope * xs + intercept, color="#c0392b",
            label=f"OLS y = {slope:.2f}x + {intercept:.1f}", linewidth=1.1)
    ax.text(0.04, 0.96,
            f"N = {len(m)}\nR² = {r2:.3f}\nslope = {slope:.2f}\nint = {intercept:.1f}",
            transform=ax.transAxes, va="top", ha="left", fontsize=8,
            bbox=dict(boxstyle="round", fc="white", ec="#888", alpha=0.85))
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.tick_params(labelsize=8)
    ax.legend(loc="lower right", fontsize=7)


def main():
    punjab = daily_means_by_city(DATA / "punjab_aqms_24m.csv")
    paqi   = daily_means_by_city(DATA / "lcs_24m.csv")
    ag     = daily_means_by_city(DATA / "airgradient_24m.csv")
    cons   = daily_means_by_city(DATA / "us_consulate_24m.csv")

    for cfg in CITY_CONFIGS:
        city = cfg["display"]
        pu = lookup(punjab, cfg["punjab_city"])
        lc = lookup(paqi,   cfg["lcs_city"])
        a  = lookup(ag,     cfg["ag_city"])
        co = lookup(cons,   cfg["consulate_city"])
        has_regulatory = not pu.empty
        print(f"\n{city}: Reg={len(pu):,}d  PAQI={len(lc):,}d  AG={len(a):,}d  AN={len(co):,}d")
        if lc.empty and a.empty:
            print("  skipping — need at least one candidate (PAQI or AG)")
            continue

        # y-axis cap based on 99th percentile to keep spikes from flattening the panel
        all_vals = pd.concat([df["value"] for df in (pu, lc, a, co) if not df.empty])
        y_cap = float(np.nanpercentile(all_vals, 99)) * 1.1 if not all_vals.empty else 200.0
        y_cap = max(y_cap, 50.0)

        # Build the list of available references for scatter pairs
        references = []
        if has_regulatory:
            references.append(("Regulatory Monitors", pu))
        references.append(("AirNow", co))

        # Two candidates → up to 2 × len(references) scatter panels
        scatters = []
        for ref_label, ref_df in references:
            if not lc.empty:
                scatters.append(("PAQI / IQAir", ref_label, ref_df, lc))
            if not a.empty:
                scatters.append(("AirGradient", ref_label, ref_df, a))
        n_scatters = len(scatters)

        # Layout: row 1 = time series (wide); row 2 = n_scatters panels in a grid
        ts_height = 5.5
        scatter_height = 5.5
        scatter_width  = 5.5
        fig_w = max(scatter_width * n_scatters, 18)
        fig_h = ts_height + scatter_height + 1.4
        fig = plt.figure(figsize=(fig_w, fig_h))
        gs = fig.add_gridspec(2, max(n_scatters, 1),
                              height_ratios=[ts_height, scatter_height],
                              hspace=0.45, wspace=0.30)

        # Time series spans the full top row
        ax_ts = fig.add_subplot(gs[0, :])
        for label, df in [("Regulatory Monitors", pu), ("PAQI / IQAir", lc),
                          ("AirGradient", a), ("AirNow", co)]:
            if df is None or df.empty:
                continue
            ax_ts.plot(df["date"], df["value"], label=label,
                       color=COLOR[label], linewidth=1.2, alpha=0.9)
        ax_ts.set_title(f"PM2.5 daily mean — {city}  (2024-05-13 → 2026-05-13)")
        ax_ts.set_ylabel("PM2.5 (µg/m³)")
        ax_ts.set_xlabel("Date")
        ax_ts.set_ylim(0, y_cap)
        ax_ts.grid(alpha=0.25)
        ax_ts.legend(loc="upper right", framealpha=0.9, ncol=4, fontsize=9)
        for lab in ax_ts.get_xticklabels():
            lab.set_rotation(30); lab.set_ha("right")

        # Scatters
        for i, (cand_label, ref_label, ref_df, cand_df) in enumerate(scatters):
            ax = fig.add_subplot(gs[1, i])
            scatter_panel(ax, cand_label, ref_label, ref_df, cand_df)

        suptitle = f"{city} — candidate networks vs reference networks"
        if cfg["note"]:
            suptitle += f"\n{cfg['note']}"
        fig.suptitle(suptitle, fontsize=13, y=0.995)

        out = PLOTS / f"combined_{cfg['slug']}.png"
        fig.savefig(out, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"  wrote {out}  (n_scatters={n_scatters}, y_cap={y_cap:.0f})")


if __name__ == "__main__":
    main()
