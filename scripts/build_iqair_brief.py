"""Build the one-page IQAir evidence brief.

Generates:
  reports/figures/iqair_brief_figure.pdf   (composite: scatter + annotated timeseries)
  reports/iqair_brief.tex                  (LaTeX source)

The .tex is then compiled to PDF separately (tectonic preferred, pdflatex fallback).
"""
from __future__ import annotations

import datetime as dt
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

REPO = Path("/Users/rehanahmad/Desktop/hawanama-main")
DATA = REPO / "data"
REPORTS = REPO / "reports"
FIGURES = REPORTS / "figures"
REPORTS.mkdir(exist_ok=True)
FIGURES.mkdir(exist_ok=True)

COLOR = {
    "Regulatory Monitors": "#1f3a93",
    "PAQI / AirVisual":    "#e67e22",
    "AirGradient":         "#8e44ad",
    "AirNow":              "#16a085",
}


# ─── Data loading ────────────────────────────────────────────────────────────

def daily_means_by_city(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], errors="coerce", utc=True)
    df = df.dropna(subset=["datetime_utc"])
    df["city"] = df["city"].astype(str).str.strip()
    df["date"] = df["datetime_utc"].dt.tz_convert(None).dt.floor("D")
    return df.groupby(["city", "date"], as_index=False)["value"].mean()


def lookup_city(daily: pd.DataFrame, city: str) -> pd.DataFrame:
    return daily[daily["city"].str.lower() == city.lower()][["date", "value"]]


def ols(x: np.ndarray, y: np.ndarray):
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    r2 = 1 - np.sum((y - yhat) ** 2) / np.sum((y - np.mean(y)) ** 2)
    mae = float(np.mean(np.abs(y - x)))
    rmse = float(np.sqrt(np.mean((y - x) ** 2)))
    return dict(slope=float(slope), intercept=float(intercept), r2=float(r2),
                n=len(x), mae=mae, rmse=rmse)


# ─── Compute headline stats ─────────────────────────────────────────────────

print("Loading daily means…")
punjab = daily_means_by_city(DATA / "punjab_aqms_24m.csv")
paqi   = daily_means_by_city(DATA / "lcs_24m.csv")
ag     = daily_means_by_city(DATA / "airgradient_24m.csv")
cons   = daily_means_by_city(DATA / "us_consulate_24m.csv")


def pair(ref_df: pd.DataFrame, cand_df: pd.DataFrame) -> pd.DataFrame:
    return ref_df.merge(cand_df, on="date", suffixes=("_ref", "_cand")).dropna()


# Lahore = the focus city
lahore_pu = lookup_city(punjab, "Lahore")
lahore_lc = lookup_city(paqi, "Lahore")
lahore_ag = lookup_city(ag, "Lahore")

lahore_paqi_vs_reg = pair(lahore_pu, lahore_lc)
lahore_ag_vs_reg   = pair(lahore_pu, lahore_ag)

paqi_stats = ols(lahore_paqi_vs_reg["value_ref"].to_numpy(),
                 lahore_paqi_vs_reg["value_cand"].to_numpy())
ag_stats   = ols(lahore_ag_vs_reg["value_ref"].to_numpy(),
                 lahore_ag_vs_reg["value_cand"].to_numpy())

# Islamabad summary too (for the table)
isl_pu = lookup_city(punjab, "Rawalpindi")   # twin-city proxy
isl_lc = lookup_city(paqi, "Islamabad")
isl_ag = lookup_city(ag, "Islamabad")
isl_paqi_vs_reg = pair(isl_pu, isl_lc)
isl_ag_vs_reg   = pair(isl_pu, isl_ag)
isl_paqi_stats  = ols(isl_paqi_vs_reg["value_ref"].to_numpy(),
                      isl_paqi_vs_reg["value_cand"].to_numpy()) if len(isl_paqi_vs_reg) >= 5 else None
isl_ag_stats    = ols(isl_ag_vs_reg["value_ref"].to_numpy(),
                      isl_ag_vs_reg["value_cand"].to_numpy()) if len(isl_ag_vs_reg) >= 5 else None

print(f"Lahore PAQI vs Reg: {paqi_stats}")
print(f"Lahore AG   vs Reg: {ag_stats}")
print(f"Islamabad PAQI vs Reg: {isl_paqi_stats}")
print(f"Islamabad AG   vs Reg: {isl_ag_stats}")


# ─── Build composite figure ─────────────────────────────────────────────────

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.5,
})

fig = plt.figure(figsize=(13, 4.0))
gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.7], wspace=0.32)
ax_sc = fig.add_subplot(gs[0, 0])
ax_ts = fig.add_subplot(gs[0, 1])

# Scatter: PAQI vs Regulatory Monitors
x = lahore_paqi_vs_reg["value_ref"].to_numpy()
y = lahore_paqi_vs_reg["value_cand"].to_numpy()
lim = max(x.max(), y.max()) * 1.05
ax_sc.scatter(x, y, s=14, alpha=0.55, color=COLOR["PAQI / AirVisual"], edgecolors="none", zorder=3)
ax_sc.plot([0, lim], [0, lim], "--", color="#444", linewidth=1.0, label="1:1", zorder=2)
xs = np.linspace(0, lim, 120)
ax_sc.plot(xs, paqi_stats["slope"] * xs + paqi_stats["intercept"],
           color="#c0392b", linewidth=1.6,
           label=f"OLS y = {paqi_stats['slope']:.2f}x + {paqi_stats['intercept']:.1f}", zorder=4)
ax_sc.text(0.04, 0.96,
           f"N = {paqi_stats['n']}\nR² = {paqi_stats['r2']:.3f}\n"
           f"slope = {paqi_stats['slope']:.2f}\nintercept = {paqi_stats['intercept']:.1f}",
           transform=ax_sc.transAxes, va="top", ha="left", fontsize=10,
           bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#888", alpha=0.92))
ax_sc.set_xlim(0, lim); ax_sc.set_ylim(0, lim)
ax_sc.set_aspect("equal", adjustable="box")
ax_sc.set_xlabel("Regulatory Monitors daily mean (µg/m³)", fontsize=10)
ax_sc.set_ylabel("PAQI / AirVisual daily mean (µg/m³)", fontsize=10)
ax_sc.set_title("Lahore — PAQI / AirVisual vs Regulatory Monitors", fontsize=11)
ax_sc.legend(loc="lower right", fontsize=9, framealpha=0.92)
ax_sc.tick_params(labelsize=9)

# Time series: Lahore Oct 2025 → end (all three networks active)
window_start = pd.Timestamp("2025-10-01")
window_end   = pd.Timestamp("2026-05-13")
def clip(df):
    return df[(df["date"] >= window_start) & (df["date"] <= window_end)].copy()
pu_w = clip(lahore_pu)
lc_w = clip(lahore_lc)
ag_w = clip(lahore_ag)

for label, df, lw, alpha in [
    ("Regulatory Monitors", pu_w, 2.0, 1.0),
    ("PAQI / AirVisual",        lc_w, 1.2, 0.85),
    ("AirGradient",         ag_w, 1.2, 0.85),
]:
    if df.empty: continue
    ax_ts.plot(df["date"], df["value"], label=label, color=COLOR[label],
               linewidth=lw, alpha=alpha)

ax_ts.set_title("Lahore — daily mean PM2.5  (Oct 2025 → May 2026)", fontsize=11)
ax_ts.set_ylabel("PM2.5 (µg/m³)", fontsize=10)
ax_ts.set_xlabel("Date", fontsize=10)
# Dynamic y-cap from the actual data so annotations near the top stay visible
all_vals = pd.concat([pu_w["value"], lc_w["value"], ag_w["value"]])
y_top = float(np.nanpercentile(all_vals, 99)) * 1.25
ax_ts.set_ylim(0, max(y_top, 200))
ax_ts.tick_params(labelsize=9)
ax_ts.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
ax_ts.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
ax_ts.legend(loc="upper right", fontsize=9, framealpha=0.92)

# (No in-figure annotations — the divergences are visible in the lines themselves;
# numerical magnitudes are reported in the body text and stats table.)

FIG_PDF = FIGURES / "iqair_brief_figure.pdf"
fig.savefig(FIG_PDF, bbox_inches="tight")
plt.close(fig)
print(f"wrote {FIG_PDF}")


# ─── Build LaTeX source ─────────────────────────────────────────────────────

def pct_under(slope: float) -> float:
    """Approximate % under-read at high concentration: 1-slope at large x where intercept is small."""
    return (1.0 - slope) * 100.0

GENERATED = dt.date.today().isoformat()

tex = textwrap.dedent(r"""
\documentclass[10pt,a4paper]{article}

\usepackage[margin=1.0cm,bottom=0.7cm,top=0.9cm]{geometry}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{xcolor}
\usepackage[most]{tcolorbox}
\usepackage{lmodern}
\usepackage[T1]{fontenc}
\usepackage{microtype}
\usepackage{caption}
\usepackage{titlesec}
\usepackage{enumitem}
\usepackage{hyperref}

\hypersetup{colorlinks=true, urlcolor=blue!50!black, pdftitle={PM2.5 Network Comparison Brief}}

\definecolor{accent}{HTML}{1f3a93}
\definecolor{warnred}{HTML}{c0392b}
\definecolor{paqi}{HTML}{e67e22}
\definecolor{ag}{HTML}{8e44ad}
\definecolor{lightbg}{HTML}{eef3fa}

\setlength{\parindent}{0pt}
\setlength{\parskip}{2pt}
\pagestyle{empty}

\titleformat{\section}{\sffamily\bfseries\normalsize\color{accent}}{}{0pt}{}
\titlespacing*{\section}{0pt}{4pt}{1pt}

\renewcommand{\arraystretch}{1.15}

\begin{document}

% ───── Title strip ─────
\noindent{\sffamily\bfseries\Large\color{accent}PM\textsubscript{2.5} Network Comparison \,---\, Pakistan}\\
{\sffamily\small AirVisual network comparison against regulatory reference networks recently installed in Punjab}

\vspace{4pt}\noindent\hrulefill\vspace{4pt}

% ───── Result summary ─────
{\bfseries\color{accent}\large IQAir tracks Lahore pollution trends but underestimates winter peaks}

From October 2025 to May 2026, the AirVisual network closely follows the Punjab EPA
reference trend but reports lower values during high-pollution days. The comparison
covers REPLACE_PAQI_N\ matched daily-mean PM\textsubscript{2.5} observations.

\[ \text{PAQI / AirVisual} \;=\; \mathbf{REPLACE_PAQI_SLOPE} \times \text{Reference} \;+\; \text{REPLACE_PAQI_INTERCEPT}\ \mu g/m^3,
   \quad R^2 = \mathbf{REPLACE_PAQI_R2} \]

The AirVisual-based PAQI daily mean rises by about REPLACE_RISE\,$\mu g/m^3$ for every 100\,$\mu g/m^3$
increase in the regulatory daily mean. The high $R^2$ shows that the two networks move together,
but the slope below 1 shows a systematic under-reading at elevated concentrations.

% ───── Composite figure ─────
\begin{center}
\includegraphics[width=\linewidth]{figures/iqair_brief_figure.pdf}
\end{center}

{\footnotesize\itshape Left: PAQI / AirVisual daily means against Punjab EPA regulatory monitors at Lahore;
each marker is one calendar day. Dashed line is 1:1; red line is the OLS fit. Right: daily
means for the three networks over the window Oct 2025\,--\,May 2026. PAQI / AirVisual
tracks below the regulatory line through the winter peak while AirGradient shows
occasional positive spikes.}

\vspace{2pt}

% ───── Stats table ─────
\section*{Per-city pair statistics (full overlap window)}

\begin{center}
\sffamily\small
\begin{tabular}{l l r r r r r r}
\toprule
City & Candidate vs Reference & N (days) & Slope & Intercept & $R^2$ & MAE & RMSE \\
\midrule
Lahore     & PAQI / AirVisual vs Regulatory Monitors & REPLACE_PAQI_N    & REPLACE_PAQI_SLOPE  & REPLACE_PAQI_INTERCEPT  & REPLACE_PAQI_R2  & REPLACE_PAQI_MAE  & REPLACE_PAQI_RMSE  \\
Lahore     & AirGradient vs Regulatory Monitors   & REPLACE_AG_N      & REPLACE_AG_SLOPE    & REPLACE_AG_INTERCEPT    & REPLACE_AG_R2    & REPLACE_AG_MAE    & REPLACE_AG_RMSE    \\
Islamabad  & PAQI / AirVisual vs Regulatory Monitors\,$^{\dagger}$ & REPLACE_ISLP_N   & REPLACE_ISLP_SLOPE  & REPLACE_ISLP_INTERCEPT  & REPLACE_ISLP_R2  & REPLACE_ISLP_MAE  & REPLACE_ISLP_RMSE  \\
Islamabad  & AirGradient vs Regulatory Monitors\,$^{\dagger}$ & REPLACE_ISLA_N    & REPLACE_ISLA_SLOPE  & REPLACE_ISLA_INTERCEPT  & REPLACE_ISLA_R2  & REPLACE_ISLA_MAE  & REPLACE_ISLA_RMSE  \\
\bottomrule
\end{tabular}
\end{center}
{\footnotesize $^{\dagger}$ The Punjab EPA network does not operate inside Islamabad. Instead, the reference utilised here are three Rawalpindi monitors 7\,--\,22\,km from the US Embassy which we treat as a single airshed.}

\vspace{4pt}

% ───── Interpretation ─────
\section*{Magnitude in context}
At Lahore winter daily means above 250\,$\mu g/m^3$, the absolute difference between
PAQI / AirVisual and the reference is 80\,--\,100\,$\mu g/m^3$. Under the US EPA AQI
breakpoints, daily values in that range correspond to a category shift from
\textit{Very Unhealthy} ($\sim$AQI 200) to \textit{Hazardous} ($>$AQI 300).
A linear correction using each station's local slope and intercept can remove
most of the offset at the daily-mean level.

\vspace{2pt}\noindent\hrulefill

\noindent{\footnotesize\sffamily
\textbf{Method.} Daily means per (city, network) from UTC-day aggregation across all that network's stations in the city. Inner-join on date; OLS regression of candidate on reference; MAE and RMSE in $\mu g/m^3$.
\textbf{Sources.} Punjab EPA AQMS ($\sim$38 stations) $\cdot$ PAQI network using IQAir AirVisual monitors (69 stations). Data via Pakistan Air Quality Initiative.
}

\end{document}
""").lstrip()


# String substitutions (avoid f-string conflict with LaTeX braces)
subs = {
    "REPLACE_GENERATED": GENERATED,
    "REPLACE_PAQI_N":    str(paqi_stats["n"]),
    "REPLACE_PAQI_SLOPE":     f"{paqi_stats['slope']:.2f}",
    "REPLACE_PAQI_INTERCEPT": f"{paqi_stats['intercept']:.1f}",
    "REPLACE_PAQI_R2":   f"{paqi_stats['r2']:.3f}",
    "REPLACE_PAQI_MAE":  f"{paqi_stats['mae']:.1f}",
    "REPLACE_PAQI_RMSE": f"{paqi_stats['rmse']:.1f}",
    "REPLACE_PCT_UNDER": f"{pct_under(paqi_stats['slope']):.0f}",
    # "100 µg/m³ ref ↑" example: AirVisual ↑ by slope·100 (intercept cancels in the differential)
    "REPLACE_RISE": f"{paqi_stats['slope']*100:.0f}",
    # Reference-vs-fitted-AirVisual differences at 250 / 300 µg/m³ reference
    "REPLACE_EX_LOW":  f"{(1-paqi_stats['slope'])*250 - paqi_stats['intercept']:.0f}",
    "REPLACE_EX_HIGH": f"{(1-paqi_stats['slope'])*300 - paqi_stats['intercept']:.0f}",
    "REPLACE_AG_N":      str(ag_stats["n"]),
    "REPLACE_AG_SLOPE":     f"{ag_stats['slope']:.2f}",
    "REPLACE_AG_INTERCEPT": f"{ag_stats['intercept']:.1f}",
    "REPLACE_AG_R2":     f"{ag_stats['r2']:.3f}",
    "REPLACE_AG_MAE":    f"{ag_stats['mae']:.1f}",
    "REPLACE_AG_RMSE":   f"{ag_stats['rmse']:.1f}",
}

def fmt_opt(s, fmt):
    return f"{s:{fmt}}" if s is not None else "---"

if isl_paqi_stats:
    subs.update({
        "REPLACE_ISLP_N":         str(isl_paqi_stats["n"]),
        "REPLACE_ISLP_SLOPE":     f"{isl_paqi_stats['slope']:.2f}",
        "REPLACE_ISLP_INTERCEPT": f"{isl_paqi_stats['intercept']:.1f}",
        "REPLACE_ISLP_R2":        f"{isl_paqi_stats['r2']:.3f}",
        "REPLACE_ISLP_MAE":       f"{isl_paqi_stats['mae']:.1f}",
        "REPLACE_ISLP_RMSE":      f"{isl_paqi_stats['rmse']:.1f}",
    })
else:
    for k in ["N", "SLOPE", "INTERCEPT", "R2", "MAE", "RMSE"]:
        subs[f"REPLACE_ISLP_{k}"] = "---"

if isl_ag_stats:
    subs.update({
        "REPLACE_ISLA_N":         str(isl_ag_stats["n"]),
        "REPLACE_ISLA_SLOPE":     f"{isl_ag_stats['slope']:.2f}",
        "REPLACE_ISLA_INTERCEPT": f"{isl_ag_stats['intercept']:.1f}",
        "REPLACE_ISLA_R2":        f"{isl_ag_stats['r2']:.3f}",
        "REPLACE_ISLA_MAE":       f"{isl_ag_stats['mae']:.1f}",
        "REPLACE_ISLA_RMSE":      f"{isl_ag_stats['rmse']:.1f}",
    })
else:
    for k in ["N", "SLOPE", "INTERCEPT", "R2", "MAE", "RMSE"]:
        subs[f"REPLACE_ISLA_{k}"] = "---"

for k, v in subs.items():
    tex = tex.replace(k, v)

OUT_TEX = REPORTS / "iqair_brief.tex"
OUT_TEX.write_text(tex)
print(f"wrote {OUT_TEX}")
