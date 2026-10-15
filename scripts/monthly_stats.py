"""Monthly comparison statistics for two candidate networks (PAQI / IQAir,
AirGradient) against each available reference (Regulatory: Punjab AQMS, AirNow:
US Consulate).

Writes:
  data/monthly_stats.csv                One row per (city, month, candidate, reference)
  plots/monthly_stats_<slug>.png        Per-city rendered table (R²-colored cells)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from combined_panel import (
    CITY_CONFIGS, DATA, PLOTS, daily_means_by_city, lookup,
)

CANDIDATE_LABEL = {
    "PAQI / IQAir": "PAQI / IQAir",
    "AirGradient":  "AirGradient",
}
REF_LABEL = {
    "Regulatory Monitors": "Regulatory Monitors",
    "AirNow":              "AirNow",
}
REF_GROUP_COLOR = {
    "Regulatory Monitors": "#cfd7e3",
    "AirNow":              "#c8e5dd",
}


def stats(merged: pd.DataFrame) -> dict:
    n = len(merged)
    if n < 5:
        return {"N": n, "R2": float("nan"), "MAE": float("nan"), "RMSE": float("nan")}
    x = merged["value_ref"].to_numpy()
    y = merged["value_cand"].to_numpy()
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    mae = float(np.mean(np.abs(y - x)))
    rmse = float(np.sqrt(np.mean((y - x) ** 2)))
    return {"N": n, "R2": round(r2, 3), "MAE": round(mae, 1), "RMSE": round(rmse, 1)}


def collect_monthly(city: str, candidate_label: str, ref_label: str,
                    ref_df: pd.DataFrame, cand_df: pd.DataFrame) -> list[dict]:
    if ref_df.empty or cand_df.empty:
        return []
    m = ref_df.merge(cand_df, on="date", suffixes=("_ref", "_cand")).dropna()
    if m.empty:
        return []
    m["month"] = m["date"].dt.to_period("M").astype(str)
    rows = []
    for month, grp in m.groupby("month"):
        s = stats(grp)
        rows.append({
            "city": city,
            "month": month,
            "candidate": candidate_label,
            "reference": ref_label,
            **s,
        })
    return rows


def r2_color(r2: float) -> str:
    if pd.isna(r2):   return "#f1f1f1"
    if r2 >= 0.8:     return "#d5efd5"
    if r2 >= 0.6:     return "#fff2cc"
    if r2 >= 0.3:     return "#fde0c0"
    return "#f5cccc"


def render_city_table(city: str, slug: str, rows: list[dict], out: Path):
    if not rows:
        print(f"  {city}: no rows to render")
        return
    df = pd.DataFrame(rows)

    # Ordered (reference, candidate) column groups — skip empty pairs
    refs_used = [r for r in REF_LABEL if r in df["reference"].unique()]
    cands_used = [c for c in CANDIDATE_LABEL if c in df["candidate"].unique()]
    groups = []
    for ref in refs_used:
        for cand in cands_used:
            if not df[(df["reference"] == ref) & (df["candidate"] == cand)].empty:
                groups.append((ref, cand))
    if not groups:
        print(f"  {city}: no non-empty (ref, cand) groups — skipping render")
        return

    months = sorted(df["month"].unique())

    # Group label only in the FIRST sub-column; the matching background color
    # visually unites the four sub-columns of a group.
    def group_cells(r: str, c: str) -> list[str]:
        return [f"{r}\n{c}", "", "", ""]
    header_top    = ["Month"] + sum((group_cells(r, c) for r, c in groups), [])
    header_bottom = [""]      + sum((["N", "R²", "MAE", "RMSE"] for _ in groups), [])

    table_data = [header_bottom]
    cell_colors = [["#dde6f0"] + sum(([REF_GROUP_COLOR[r]] * 4 for r, _ in groups), [])]

    for month in months:
        row = [month]
        colors = ["#ffffff"]
        for ref, cand in groups:
            sub = df[(df["month"] == month) &
                     (df["reference"] == ref) &
                     (df["candidate"] == cand)]
            if sub.empty:
                row += ["", "", "", ""]; colors += ["#f1f1f1"] * 4
            else:
                r = sub.iloc[0]
                row += [int(r["N"]), r["R2"], r["MAE"], r["RMSE"]]
                c = r2_color(r["R2"])
                colors += [c, c, c, c]
        table_data.append(row)
        cell_colors.append(colors)

    n_rows = len(table_data)
    n_cols = len(header_top)
    # Each group needs ~4 inches (4 sub-columns × ~1 in/col) to hold the wrapped header
    fig_h = 2.6 + 0.32 * n_rows
    fig_w = 3.0 + 4.0 * len(groups)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_axis_off()
    col_colors = ["#dde6f0"] + sum(([REF_GROUP_COLOR[r]] * 4 for r, _ in groups), [])
    tbl = ax.table(cellText=table_data, colLabels=header_top,
                   cellColours=cell_colors, colColours=col_colors,
                   cellLoc="center", colLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 1.35)
    for j in range(n_cols):
        tbl[(1, j)].set_text_props(weight="bold")

    ax.set_title(f"{city} — Monthly candidate-network performance vs references",
                 fontsize=12, pad=12)
    footer = "R² color:  ≥0.8 green  ·  0.6–0.8 yellow  ·  0.3–0.6 orange  ·  <0.3 red"
    fig.text(0.5, 0.03, footer, ha="center", va="bottom", fontsize=9, color="#444")

    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}  (groups={len(groups)}, months={len(months)})")


def main():
    punjab = daily_means_by_city(DATA / "punjab_aqms_24m.csv")
    paqi   = daily_means_by_city(DATA / "lcs_24m.csv")
    ag     = daily_means_by_city(DATA / "airgradient_24m.csv")
    cons   = daily_means_by_city(DATA / "us_consulate_24m.csv")

    all_rows: list[dict] = []
    for cfg in CITY_CONFIGS:
        city = cfg["display"]
        pu = lookup(punjab, cfg["punjab_city"])
        lc = lookup(paqi,   cfg["lcs_city"])
        a  = lookup(ag,     cfg["ag_city"])
        co = lookup(cons,   cfg["consulate_city"])

        rows: list[dict] = []
        references = []
        if not pu.empty: references.append(("Regulatory Monitors", pu))
        if not co.empty: references.append(("AirNow", co))
        candidates = []
        if not lc.empty: candidates.append(("PAQI / IQAir", lc))
        if not a.empty:  candidates.append(("AirGradient", a))

        for ref_label, ref_df in references:
            for cand_label, cand_df in candidates:
                rows += collect_monthly(city, cand_label, ref_label, ref_df, cand_df)

        all_rows.extend(rows)
        render_city_table(city, cfg["slug"], rows, PLOTS / f"monthly_stats_{cfg['slug']}.png")

    csv_out = DATA / "monthly_stats.csv"
    pd.DataFrame(all_rows).to_csv(csv_out, index=False)
    print(f"\nwrote {csv_out} with {len(all_rows)} rows")


if __name__ == "__main__":
    main()
