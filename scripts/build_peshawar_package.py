#!/usr/bin/env python3
"""
Build the Peshawar data deliverable package.

Pulls all Peshawar station readings from the production TimescaleDB (read-only),
applies batch QA/QC (rules mirrored from apps/api/app/routers/exports_publish.py
_apply_hourly_qc, flag-don't-drop), and writes:

    peshawar/
    ├── peshawar_hourly_readings.csv   station-hour records with QC columns
    ├── peshawar_stations.csv          station metadata + PM2.5-specific counts
    ├── qc_summary.csv                 long-format flag summary (station x rule)
    ├── peshawar_report.pdf            PAQI-style analysis + QA/QC report
    ├── peshawar_map.html              interactive station map (needs internet)
    ├── peshawar_map_static.png/.pdf   static station map for slides/print
    └── plots/                         PNGs used in the report

Definitions (used consistently in report, CSVs, and figures):
  station-hour record  — one row in the hourly CSV (PM2.5 may be missing)
  raw PM2.5 observation — station-hour with a non-null pm25 value
  QC-passed observation — non-null pm25_qc (raw minus invalid/suspect hours)

Daily-mean rule: a station-day mean is computed only when >= 18 valid hourly
pm25_qc values exist in that Pakistan Standard Time (UTC+5) day; a site-day is
the mean of its feeds' valid station-days (duplicate feeds at one location are
not double-counted); a city-day is the mean of valid site-days. Annual means
are reported only when >= 75% of the year's days have a city-day value.

Usage:
    python3 scripts/build_peshawar_package.py            # fetch fresh from DB
    python3 scripts/build_peshawar_package.py --cached   # reuse existing CSV
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import folium
import matplotlib.dates as mdates
import matplotlib.patheffects
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg2
from matplotlib.colors import Normalize
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from PIL import Image as PILImage

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "peshawar"
PLOTS = OUT / "plots"
LOGO = REPO / "logo-cropped.png"
LOGO_FULL = REPO / "logo-paqi-full.png"  # calligraphy + org-name lockup
DISTRICTS_GEOJSON = (
    REPO / "apps/dashboard-frontend/public/pakistan_districts.geojson"
)

LOCAL_UTC_OFFSET_H = 5  # Pakistan Standard Time

# ── QC thresholds (mirrored from exports_publish.py / bam_service.py) ──
PM25_ABS_MAX = 1000.0
PM25_SENTINELS = {999.0, 1000.0, -1.0}
PM25_MAX_DELTA_1H = 250.0
PM25_SPIKE_RETURN_TOL = 1.0
PM25_FLATLINE_HOURS = 18
AQI_US_MIN, AQI_US_MAX = 0, 500
PM10_ABS_MAX = 2000.0
CITY_OUTLIER_RATIO = 3.0
CITY_OUTLIER_MIN_STATIONS = 3
CITY_OUTLIER_MIN_PM25 = 50.0

# ── Aggregation rules (documented in the report methodology) ──
MIN_HOURS_PER_DAY = 18          # valid pm25_qc hours for a station-day mean
ANNUAL_MIN_DAY_COVERAGE = 0.75  # share of days needed for an annual mean

FLAG_SEVERITY = {
    "pm25_sentinel": "invalid",
    "pm25_oor": "invalid",
    "pm25_spike": "suspect",
    "pm25_flatline": "suspect",
    "city_outlier": "suspect",
    "pm10_oor": "info",
    "aqi_oor": "info",
    "humidity_oor": "info",
    "temp_oor": "info",
}
FLAG_ORDER = list(FLAG_SEVERITY)
PM25_INVALID_FLAGS = ["pm25_sentinel", "pm25_oor"]
PM25_SUSPECT_FLAGS = ["pm25_spike", "pm25_flatline", "city_outlier"]

# Station display-name corrections (typos / stray whitespace in source feeds)
NAME_FIXES = {
    "Haytabad-Phase5": "Hayatabad Phase 5",
    "BoK Industrial Estate Hayatabat": "BoK Industrial Estate Hayatabad",
    "IMSciences Institute Peshwar": "IMSciences Institute Peshawar",
    "Small industrial development board(SIDB": "Small Industrial Development Board (SIDB)",
    "Small industrial development board(SIDB)": "Small Industrial Development Board (SIDB)",
    "Hayatabad phase 7": "Hayatabad Phase 7",
}

# ── PAQI palette (per scripts/build_report.py / build_iqair_brief.py) ──
ACCENT = "#1f3a93"
ORANGE = "#e67e22"
WARNRED = "#c0392b"
MODERATE = "#f0c20c"
TEAL = "#16a085"
GRAY = "#666666"
GRID = "#cccccc"
SEVERITY_COLOR = {"invalid": WARNRED, "suspect": MODERATE, "info": "#9aa0a6"}

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#999999",
        "axes.labelcolor": "#333333",
        "axes.titlecolor": "#222222",
        "xtick.color": "#555555",
        "ytick.color": "#555555",
        "axes.grid": True,
        "grid.color": GRID,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.6,
    }
)


def load_db_config() -> dict:
    cfg = {}
    for line in (REPO / ".env").read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.startswith("POSTGRES_"):
            cfg[k] = v.strip()
    return cfg


def fetch_data() -> pd.DataFrame:
    cfg = load_db_config()
    conn = psycopg2.connect(
        host=cfg["POSTGRES_SERVER"],
        port=cfg["POSTGRES_PORT"],
        user=cfg["POSTGRES_USER"],
        password=cfg["POSTGRES_PASSWORD"],
        dbname=cfg["POSTGRES_DB"],
    )
    query = """
        SELECT s.station_id, s.name AS station_name, p.display_name AS provider,
               s.lat, s.lon, r.ts_utc, r.aqi_us,
               r.pm25, r.pm10, r.o3, r.no2, r.so2, r.co,
               r.temp_c, r.humidity, r.pressure_hpa,
               r.wind_speed_ms, r.wind_dir_deg, r.source
        FROM readings r
        JOIN stations s ON r.scope_key = s.station_id AND r.scope_type = 'station'
        JOIN cities c ON s.city_id = c.id
        JOIN providers p ON s.provider_id = p.id
        WHERE c.name ILIKE '%%peshaw%%'
        ORDER BY s.station_id, r.ts_utc
    """
    df = pd.read_sql(query, conn)
    conn.close()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    return df


def load_cached() -> pd.DataFrame:
    """Reload the previously exported CSV so PDF iterations skip the DB."""
    path = OUT / "peshawar_hourly_readings.csv"
    df = pd.read_csv(path, low_memory=False)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    derived = ["pm25_qc", "qc_state", "pm25_qc_state", "qc_severity_max",
               "qc_flags", "ts_local", "site_id"]
    return df.drop(columns=derived, errors="ignore")


def clean_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Fix station-name typos/whitespace and derive site_id + ts_local.

    site_id groups duplicate/replacement feeds at one physical location
    (identical coordinates to ~10 m); it is the station_id of the group's
    longest-running feed.
    """
    df = df.copy()
    df["station_name"] = (
        df["station_name"].str.strip().replace(NAME_FIXES)
    )
    df["ts_local"] = (
        df["ts_utc"].dt.tz_localize(None) + pd.Timedelta(hours=LOCAL_UTC_OFFSET_H)
    )

    coord_key = df["lat"].round(4).astype(str) + "," + df["lon"].round(4).astype(str)
    counts = df.groupby(["station_id"]).size()
    site_map = {}
    for _, grp in df[["station_id"]].assign(key=coord_key).drop_duplicates().groupby("key"):
        ids = grp["station_id"].tolist()
        site = max(ids, key=lambda i: counts.get(i, 0))
        for i in ids:
            site_map[i] = site
    df["site_id"] = df["station_id"].map(site_map)
    return df


# ────────────────────────────── QA/QC ──────────────────────────────


def apply_qc(df: pd.DataFrame) -> pd.DataFrame:
    """Flag-don't-drop QC.

    Adds pm25_qc_state (missing|ok|suspect|invalid), qc_severity_max
    (none|info|suspect|invalid), qc_flags, pm25_qc.
    """
    n_dup = int(df.duplicated(["station_id", "ts_utc"]).sum())
    assert n_dup == 0, f"{n_dup} duplicate (station_id, ts_utc) rows"

    df = df.sort_values(["station_id", "ts_utc"]).reset_index(drop=True)
    flags: dict[str, pd.Series] = {}
    pm = pd.to_numeric(df["pm25"], errors="coerce")

    flags["pm25_sentinel"] = pm.isin(PM25_SENTINELS)
    flags["pm25_oor"] = ~flags["pm25_sentinel"] & ((pm < 0) | (pm > PM25_ABS_MAX))
    invalid = flags["pm25_sentinel"] | flags["pm25_oor"]

    clean = pm.where(~invalid)
    sid = df["station_id"]
    grp = clean.groupby(sid)
    prev_pm, next_pm, prev2_pm = grp.shift(1), grp.shift(-1), grp.shift(2)

    spike_1h = (
        clean.notna()
        & prev_pm.notna()
        & next_pm.notna()
        & ((clean - prev_pm).abs() > PM25_MAX_DELTA_1H)
        & ((next_pm - prev_pm).abs() <= PM25_SPIKE_RETURN_TOL)
    )
    spike_2h = (
        clean.notna()
        & prev_pm.notna()
        & prev2_pm.notna()
        & next_pm.notna()
        & ((prev_pm - prev2_pm).abs() > PM25_MAX_DELTA_1H)
        & ((clean - prev2_pm).abs() > PM25_MAX_DELTA_1H)
        & ((next_pm - prev2_pm).abs() <= PM25_SPIKE_RETURN_TOL)
    )
    spike_2h_prev = spike_2h.groupby(sid).shift(-1).fillna(False)
    flags["pm25_spike"] = spike_1h | spike_2h | spike_2h_prev

    new_seg = (
        (sid != sid.shift(1))
        | clean.isna()
        | clean.shift(1).isna()
        | (clean != clean.shift(1))
    )
    seg_len = clean.groupby(new_seg.cumsum()).transform("size")
    flags["pm25_flatline"] = clean.notna() & (seg_len >= PM25_FLATLINE_HOURS)

    day = df["ts_local"].dt.floor("D")
    daily = clean.groupby([sid, day]).mean()
    city = daily.groupby(level=1).agg(["median", "size"])
    daily_df = daily.rename("st_mean").reset_index()
    daily_df.columns = ["station_id", "day", "st_mean"]
    daily_df = daily_df.merge(
        city.rename(columns={"median": "city_med", "size": "n_st"}),
        left_on="day",
        right_index=True,
    )
    out_days = daily_df[
        (daily_df["n_st"] >= CITY_OUTLIER_MIN_STATIONS)
        & (daily_df["st_mean"] > CITY_OUTLIER_MIN_PM25)
        & (daily_df["st_mean"] > CITY_OUTLIER_RATIO * daily_df["city_med"])
    ]
    out_keys = set(zip(out_days["station_id"], out_days["day"]))
    row_keys = pd.Series(list(zip(sid, day)), index=df.index)
    flags["city_outlier"] = clean.notna() & row_keys.isin(out_keys)

    pm10 = pd.to_numeric(df["pm10"], errors="coerce")
    aqi = pd.to_numeric(df["aqi_us"], errors="coerce")
    hum = pd.to_numeric(df["humidity"], errors="coerce")
    temp = pd.to_numeric(df["temp_c"], errors="coerce")
    flags["pm10_oor"] = (pm10 < 0) | (pm10 > PM10_ABS_MAX)
    flags["aqi_oor"] = (aqi < AQI_US_MIN) | (aqi > AQI_US_MAX)
    flags["humidity_oor"] = (hum < 0) | (hum > 100)
    flags["temp_oor"] = (temp < -60) | (temp > 80)

    suspect = flags["pm25_spike"] | flags["pm25_flatline"] | flags["city_outlier"]

    df["pm25_qc_state"] = np.select(
        [pm.isna(), invalid, suspect],
        ["missing", "invalid", "suspect"],
        default="ok",
    )
    info = pd.Series(False, index=df.index)
    for f, sev in FLAG_SEVERITY.items():
        if sev == "info":
            info |= flags[f].fillna(False)
    df["qc_severity_max"] = np.select(
        [invalid, suspect, info],
        ["invalid", "suspect", "info"],
        default="none",
    )

    flag_df = pd.DataFrame(flags).fillna(False)
    names = np.array(flag_df.columns)
    df["qc_flags"] = [
        ";".join(names[row]) for row in flag_df.to_numpy(dtype=bool)
    ]
    df["pm25_qc"] = clean.where(~suspect)

    for name, s in flags.items():
        df[f"_flag_{name}"] = s.fillna(False)
    return df


# ────────────────────────────── aggregation ──────────────────────────────


def compute_daily(df: pd.DataFrame):
    """City daily-mean series under the documented rule (PKT days).

    Returns (city_day: Series indexed by local day,
             sites_per_day: Series of valid sites per day,
             site_day: Series indexed by (site_id, day)).
    """
    v = df.dropna(subset=["pm25_qc"]).copy()
    v["day"] = v["ts_local"].dt.floor("D")
    st_day = v.groupby(["station_id", "site_id", "day"])["pm25_qc"].agg(
        ["mean", "size"]
    )
    st_day = st_day[st_day["size"] >= MIN_HOURS_PER_DAY]
    site_day = st_day.groupby(["site_id", "day"])["mean"].mean()
    city_day = site_day.groupby("day").mean()
    sites_per_day = site_day.groupby("day").size()
    return city_day, sites_per_day, site_day


def yearly_summary(df: pd.DataFrame, city_day: pd.Series,
                   site_day: pd.Series) -> pd.DataFrame:
    """Yearly table: mean/max of city days, day coverage, sites, PM2.5 obs."""
    last_day = df["ts_local"].max().floor("D")
    years = sorted(city_day.index.year.unique())
    rows = []
    obs_by_year = df.dropna(subset=["pm25"]).groupby(
        df["ts_local"].dt.year
    ).size()
    site_years = site_day.reset_index()
    site_years["year"] = site_years["day"].dt.year
    sites_by_year = site_years.groupby("year")["site_id"].nunique()
    for y in years:
        days = city_day[city_day.index.year == y]
        if y == last_day.year:
            days_in_year = (last_day - pd.Timestamp(f"{y}-01-01")).days + 1
        else:
            days_in_year = pd.Timestamp(f"{y}-12-31").dayofyear
        coverage = len(days) / days_in_year
        rows.append({
            "year": y,
            "mean": days.mean(),
            "max": days.max(),
            "coverage": 100 * coverage,
            "complete": coverage >= ANNUAL_MIN_DAY_COVERAGE,
            "ytd": y == last_day.year,
            "sites": int(sites_by_year.get(y, 0)),
            "n_obs": int(obs_by_year.get(y, 0)),
        })
    return pd.DataFrame(rows).set_index("year")


# ────────────────────────────── tables ──────────────────────────────

CSV_COLS = [
    "station_id", "site_id", "station_name", "provider", "lat", "lon",
    "ts_utc", "ts_local", "aqi_us", "pm25", "pm25_qc",
    "pm10", "o3", "no2", "so2", "co",
    "temp_c", "humidity", "pressure_hpa", "wind_speed_ms", "wind_dir_deg",
    "source", "pm25_qc_state", "qc_severity_max", "qc_flags",
]


def station_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(
        ["station_id", "site_id", "station_name", "provider", "lat", "lon"]
    )
    st = g.agg(
        first_reading=("ts_utc", "min"),
        last_reading=("ts_utc", "max"),
        n_station_hours=("ts_utc", "size"),
        n_pm25_raw=("pm25", "count"),
        n_pm25_qc=("pm25_qc", "count"),
        mean_pm25_qc=("pm25_qc", "mean"),
    ).reset_index()
    st["pm25_coverage_pct"] = (
        100 * st["n_pm25_raw"] / st["n_station_hours"]
    ).round(1)
    st["pm25_qc_pass_pct"] = (
        100 * st["n_pm25_qc"] / st["n_pm25_raw"].replace(0, np.nan)
    ).round(1)
    st["mean_pm25_qc"] = st["mean_pm25_qc"].round(1)
    return st.sort_values("first_reading").reset_index(drop=True)


def qc_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """Long format: one row per (station, rule) with >= 1 hit."""
    rows = []
    for (station_id, name), g in df.groupby(["station_id", "station_name"]):
        n_pm25 = int(g["pm25"].notna().sum())
        for rule in FLAG_ORDER:
            hit = g[g[f"_flag_{rule}"]]
            if not len(hit):
                continue
            rows.append({
                "station_id": station_id,
                "station_name": name,
                "rule": rule,
                "severity": FLAG_SEVERITY[rule],
                "n_flags": len(hit),
                "first_flag": hit["ts_utc"].min(),
                "last_flag": hit["ts_utc"].max(),
                "pct_of_pm25_observations": (
                    round(100 * len(hit) / n_pm25, 2) if n_pm25 else np.nan
                ),
            })
    return (
        pd.DataFrame(rows)
        .sort_values(["severity", "n_flags"], ascending=[True, False])
        .reset_index(drop=True)
    )


# ────────────────────────────── figures ──────────────────────────────


def load_district_shapes():
    gj = json.loads(DISTRICTS_GEOJSON.read_text())
    peshawar, neighbours = None, []
    for f in gj["features"]:
        if f["properties"].get("division") == "Peshawar Division":
            if f["properties"]["ds"] == "PESHAWAR DISTRICT":
                peshawar = f["geometry"]
            else:
                neighbours.append(f["geometry"])
    return peshawar, neighbours


def _iter_rings(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        yield np.asarray(poly[0])


def fig_station_map(st: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(8.4, 6.6))
    pad_x, pad_y = 0.03, 0.025
    ax.set_xlim(st["lon"].min() - pad_x, st["lon"].max() + pad_x)
    ax.set_ylim(st["lat"].min() - pad_y, st["lat"].max() + pad_y)

    basemap_ok = False
    try:
        import contextily as cx

        cx.add_basemap(ax, crs="EPSG:4326",
                       source=cx.providers.CartoDB.Positron,
                       attribution_size=5, zoom=12)
        basemap_ok = True
    except Exception:
        pass
    if not basemap_ok:  # offline fallback: district fills
        peshawar_geom, neighbours = load_district_shapes()
        for geom in neighbours:
            for ring in _iter_rings(geom):
                ax.fill(ring[:, 0], ring[:, 1], color="#f2f1ee", zorder=0)
        for ring in _iter_rings(peshawar_geom):
            ax.fill(ring[:, 0], ring[:, 1], color="#e8edf7", zorder=0)

    peshawar_geom, _ = load_district_shapes()
    for ring in _iter_rings(peshawar_geom):
        ax.plot(ring[:, 0], ring[:, 1], color=ACCENT, lw=1.2, ls=(0, (5, 3)),
                alpha=0.8, zorder=2)

    vals = st["mean_pm25_qc"].fillna(0)
    norm = Normalize(vmin=0, vmax=max(150, vals.max()))
    sc = ax.scatter(
        st["lon"], st["lat"], c=vals, cmap="Reds", norm=norm,
        s=40 + 90 * (st["n_pm25_qc"] / st["n_pm25_qc"].max()),
        edgecolors="white", linewidths=1.0, zorder=3,
    )
    # label the longest-running sites; alternate label side by latitude
    # rank so neighbouring labels do not collide
    landmarks = st.nlargest(6, "n_pm25_qc").sort_values("lat", ascending=False)
    for i, r in enumerate(landmarks.itertuples()):
        above = i % 2 == 0
        ax.annotate(
            r.station_name, (r.lon, r.lat),
            xytext=(0, 9 if above else -9), textcoords="offset points",
            fontsize=6.5, color="#222222", ha="center",
            va="bottom" if above else "top", zorder=4,
            path_effects=[
                matplotlib.patheffects.withStroke(linewidth=2.5,
                                                  foreground="white")
            ],
        )

    # 5 km scale bar, bottom left
    km_per_deg_lon = 111.32 * np.cos(np.radians(st["lat"].mean()))
    bar_deg = 5.0 / km_per_deg_lon
    x0 = ax.get_xlim()[0] + 0.012
    y0 = ax.get_ylim()[0] + 0.012
    ax.plot([x0, x0 + bar_deg], [y0, y0], color="#333333", lw=2.2,
            solid_capstyle="butt", zorder=5)
    ax.plot([x0, x0], [y0 - 0.0015, y0 + 0.0015], color="#333333", lw=1.4, zorder=5)
    ax.plot([x0 + bar_deg] * 2, [y0 - 0.0015, y0 + 0.0015], color="#333333",
            lw=1.4, zorder=5)
    ax.text(x0 + bar_deg / 2, y0 + 0.003, "5 km", ha="center", fontsize=7,
            color="#333333", zorder=5,
            path_effects=[matplotlib.patheffects.withStroke(
                linewidth=2, foreground="white")])

    # marker-size legend (number of QC-passed observations)
    max_n = st["n_pm25_qc"].max()
    handles = [
        plt.scatter([], [], s=40 + 90 * (n / max_n), facecolor="#bbbbbb",
                    edgecolor="white", linewidth=1.0, label=f"{n // 1000}k")
        for n in (2_000, 10_000, 25_000)
    ]
    ax.legend(handles=handles, title="QC-passed obs", loc="lower right",
              frameon=True, framealpha=0.9, edgecolor="#dddddd",
              fontsize=6.5, title_fontsize=7, borderpad=0.8,
              labelspacing=1.0)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_edgecolor("#cccccc")
    cb = plt.colorbar(sc, ax=ax, shrink=0.75, pad=0.02)
    cb.set_label("Mean PM2.5 (µg/m³, QC-passed)")
    cb.outline.set_visible(False)
    fig.tight_layout()
    path = PLOTS / "station_map.png"
    fig.savefig(path, dpi=300, bbox_inches="tight")
    # standalone static-map exports for slides / print (interactive HTML
    # map needs an internet connection)
    fig.savefig(OUT / "peshawar_map_static.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / "peshawar_map_static.pdf", bbox_inches="tight")
    plt.close(fig)
    return path


def fig_coverage(df: pd.DataFrame, st: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(11.0, 7.2))
    st_sorted = st.sort_values("first_reading", ascending=False).reset_index(drop=True)
    obs = df.dropna(subset=["pm25"])
    months = obs.assign(month=obs["ts_local"].dt.to_period("M"))
    present = months.groupby(["station_id", "month"]).size()
    for i, row in st_sorted.iterrows():
        if row["station_id"] not in present.index.get_level_values(0):
            continue
        mons = present.loc[row["station_id"]].index
        ax.broken_barh(
            [(mdates.date2num(m.to_timestamp()), 32) for m in mons],
            (i - 0.35, 0.7), color=ACCENT, linewidth=0,
        )
    ax.set_yticks(range(len(st_sorted)))
    labels = [
        f"{r.station_name[:40]}  ·  {r.n_pm25_raw:,}"
        for r in st_sorted.itertuples()
    ]
    ax.set_yticklabels(labels, fontsize=7)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(axis="y", visible=False)
    ax.margins(y=0.01)
    fig.tight_layout()
    path = PLOTS / "coverage.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_timeseries(city_day: pd.Series, sites_per_day: pd.Series) -> Path:
    fig, ax = plt.subplots(figsize=(11.0, 5.6))
    city_day = city_day.asfreq("D")  # NaN on gap days so lines break
    ax.plot(city_day.index, city_day.values, color=ACCENT, lw=0.6, alpha=0.55)
    roll = city_day.rolling(30, min_periods=10).mean()
    ax.plot(roll.index, roll.values, color=ORANGE, lw=1.9,
            label="30-day rolling mean")

    bbox = dict(facecolor="white", edgecolor="none", alpha=0.9, pad=1)
    ax.axhline(15, color=TEAL, lw=1.1, ls="--")
    ax.text(city_day.index[0], 13, "WHO 24-h guideline (15)", color=TEAL,
            fontsize=8, va="top", ha="left", bbox=bbox, zorder=5)
    ax.axhline(35, color=WARNRED, lw=1.1, ls="--")
    ax.text(city_day.index[0], 37, "Pak NEQS 24-h (35)", color=WARNRED,
            fontsize=8, va="bottom", ha="left", bbox=bbox, zorder=5)

    ax2 = ax.twinx()  # context strip only — no second data axis
    ax2.fill_between(sites_per_day.index, sites_per_day.values,
                     color="#bbbbbb", alpha=0.25, step="mid", zorder=0)
    ax2.set_ylim(0, sites_per_day.max() * 5)
    ax2.set_yticks([])
    ax2.grid(False)
    for s in ax2.spines.values():
        s.set_visible(False)
    ax.text(0.995, 0.03, "grey band: monitoring sites with a valid day (relative)",
            transform=ax.transAxes, ha="right", fontsize=7.5, color=GRAY)
    ax.set_ylabel("PM2.5 (µg/m³)")
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout()
    path = PLOTS / "timeseries.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_climatology(city_day: pd.Series) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    clim = city_day.groupby(city_day.index.month)
    med = clim.median()
    q1, q3 = clim.quantile(0.25), clim.quantile(0.75)
    ax.fill_between(med.index, q1, q3, color=ACCENT, alpha=0.15, linewidth=0)
    ax.plot(med.index, med.values, color=ACCENT, lw=2, marker="o", ms=4)
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], fontsize=8)
    ax.axhline(15, color=TEAL, lw=1, ls="--")
    ax.text(0.99, 16, "WHO 24-h guideline (15)", color=TEAL, fontsize=7.5,
            transform=ax.get_yaxis_transform(), ha="right", va="bottom")
    ax.set_ylabel("Daily PM2.5 (µg/m³)")
    fig.tight_layout()
    path = PLOTS / "climatology.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_qc_overview(df: pd.DataFrame, qc: pd.DataFrame) -> Path:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.2),
                                   gridspec_kw={"width_ratios": [1, 1.3]})
    counts = pd.Series({f: int(df[f"_flag_{f}"].sum()) for f in FLAG_ORDER})
    counts = counts[counts > 0].sort_values()
    bar_colors = [SEVERITY_COLOR[FLAG_SEVERITY[f]] for f in counts.index]
    ax1.barh(counts.index, counts.values, color=bar_colors, height=0.55)
    for i, v in enumerate(counts.values):
        ax1.text(v, i, f" {v:,}", va="center", fontsize=8, color="#333")
    ax1.set_title("Readings flagged, by rule", fontsize=10)
    ax1.grid(axis="y", visible=False)
    ax1.margins(x=0.18)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=SEVERITY_COLOR[s])
        for s in ("invalid", "suspect", "info")
    ]
    ax1.legend(handles, ["invalid", "suspect", "info only (pm25_qc kept)"],
               frameon=False, fontsize=7.5, loc="lower right")

    per_station = (
        qc[qc["severity"] != "info"]
        .pivot_table(index=["station_id", "station_name"], columns="severity",
                     values="n_flags", aggfunc="sum", fill_value=0)
        .reindex(columns=["invalid", "suspect"], fill_value=0)
        .reset_index()
    )
    per_station["flagged"] = per_station["invalid"] + per_station["suspect"]
    worst = per_station.nlargest(10, "flagged").iloc[::-1]
    ax2.barh(worst["station_name"].str.slice(0, 32), worst["invalid"],
             color=WARNRED, height=0.55, label="invalid")
    ax2.barh(worst["station_name"].str.slice(0, 32), worst["suspect"],
             left=worst["invalid"], color=MODERATE, height=0.55,
             label="suspect")
    ax2.set_title("Most-flagged stations (PM2.5-affecting rules)", fontsize=10)
    ax2.legend(frameon=False, fontsize=8, loc="lower right")
    ax2.grid(axis="y", visible=False)
    ax2.tick_params(labelsize=7.5)
    fig.tight_layout()
    path = PLOTS / "qc_overview.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_anomaly_example(df: pd.DataFrame, qc: pd.DataFrame):
    """Raw vs QC'd overlay for the most-flagged station, worst 60 days."""
    per_station = (
        qc[qc["severity"] != "info"]
        .groupby("station_id")["n_flags"].sum().sort_values()
    )
    if not len(per_station):
        return None
    ex_id = per_station.index[-1]
    ex = df[df["station_id"] == ex_id].set_index("ts_local")
    bad = ex[ex["pm25_qc_state"].isin(["suspect", "invalid"])]
    if not len(bad):
        return None
    center = bad.index[len(bad) // 2]
    lo, hi = center - pd.Timedelta("30D"), center + pd.Timedelta("30D")
    win = ex.loc[lo:hi]
    # reindex to hourly so lines break at gaps instead of bridging them
    win = win[~win.index.duplicated()].resample("h").asfreq()

    fig, ax = plt.subplots(figsize=(11.0, 4.0))
    ax.plot(win.index, win["pm25"], color=WARNRED, lw=0.8, alpha=0.65,
            label="raw pm25")
    ax.plot(win.index, win["pm25_qc"], color=ACCENT, lw=1.3,
            label="pm25_qc (QC-passed)")
    flagged = win[win["pm25_qc_state"].isin(["suspect", "invalid"])]
    ax.scatter(flagged.index, flagged["pm25"], s=14, color=WARNRED,
               zorder=3, label="flagged readings")
    ax.set_ylabel("PM2.5 (µg/m³)")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    path = PLOTS / "anomaly_example.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path, ex.iloc[0]["station_name"], win.index.min(), win.index.max()


# ────────────────────────────── PDF report ──────────────────────────────

PAGE_W_P, PAGE_H_P = A4
PAGE_W_L, PAGE_H_L = landscape(A4)
MARGIN = 1.5 * cm

_styles = getSampleStyleSheet()
title_style = ParagraphStyle("Title", parent=_styles["Title"], fontSize=24,
                             leading=28, alignment=1)
subtitle_style = ParagraphStyle("Subtitle", parent=_styles["Heading2"],
                                fontSize=14, leading=18, alignment=1,
                                textColor=colors.HexColor("#555555"))
h1_style = ParagraphStyle("H1", parent=_styles["Heading1"], fontSize=18,
                          leading=22, spaceAfter=8,
                          textColor=colors.HexColor(ACCENT))
h2_style = ParagraphStyle("H2", parent=_styles["Heading2"], fontSize=13,
                          leading=17, spaceAfter=6,
                          textColor=colors.HexColor("#222222"))
body_style = ParagraphStyle("Body", parent=_styles["BodyText"], fontSize=10,
                            leading=14, spaceAfter=6, alignment=4)
caption_style = ParagraphStyle("Caption", parent=_styles["BodyText"],
                               fontSize=8.5, leading=11,
                               textColor=colors.HexColor("#666666"),
                               alignment=1, spaceBefore=2)
caption_right_style = ParagraphStyle("CaptionRight", parent=caption_style,
                                     alignment=2)

TABLE_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(ACCENT)),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
    ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
    ("ROWBACKGROUNDS", (1, 1), (-1, -1),
     [colors.white, colors.HexColor("#f6f8fb")]),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
])


def _page_decorator(canvas, doc, page_w, page_h, header, generated):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    if doc.page > 1:
        canvas.drawString(MARGIN, page_h - 0.8 * cm, header)
        logo_size = 1.4 * cm
        canvas.drawImage(str(LOGO_FULL), page_w - MARGIN - logo_size,
                         page_h - 1.55 * cm, width=logo_size,
                         height=logo_size, mask="auto")
    canvas.drawRightString(page_w - MARGIN, 0.7 * cm, f"Page {doc.page}")
    canvas.restoreState()


def scaled_image(path, max_w_cm, max_h_cm=None) -> Image:
    with PILImage.open(path) as im:
        px_w, px_h = im.size
    aspect = px_h / px_w
    w = max_w_cm * cm
    h = w * aspect
    if max_h_cm is not None and h > max_h_cm * cm:
        h = max_h_cm * cm
        w = h / aspect
    return Image(str(path), width=w, height=h)


def P(text, style=body_style) -> Paragraph:
    return Paragraph(text, style)


def brand_table(rows, col_widths, extra_styles=()) -> Table:
    tbl = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    tbl.setStyle(TABLE_STYLE)
    if extra_styles:
        tbl.setStyle(TableStyle(list(extra_styles)))
    return tbl


def build_pdf(df, st, qc, figs, city_day, sites_per_day, ytbl) -> Path:
    n_hours = len(df)
    n_st = df["station_id"].nunique()
    n_sites = df["site_id"].nunique()
    n_pm25_raw = int(df["pm25"].notna().sum())
    n_pm25_qc = int(df["pm25_qc"].notna().sum())
    first, last = df["ts_utc"].min(), df["ts_utc"].max()
    last_local = df["ts_local"].max()
    span = f"{first:%d %B %Y} – {last:%d %B %Y}"

    n_inv = int((df["pm25_qc_state"] == "invalid").sum())
    n_sus = int((df["pm25_qc_state"] == "suspect").sum())
    n_pm25_flagged = n_inv + n_sus
    qc_pass_pct = 100 * n_pm25_qc / n_pm25_raw

    flag_counts = {f: int(df[f"_flag_{f}"].sum()) for f in FLAG_ORDER}
    per_station = (
        qc[qc["severity"] != "info"]
        .groupby("station_name")["n_flags"].sum().sort_values(ascending=False)
    )
    top_two = " and ".join(per_station.index[:2])
    pm25_max = df["pm25"].max()

    complete = ytbl[ytbl["complete"] & ~ytbl["ytd"]]
    ymin, ymax = int(complete["mean"].min()), int(complete["mean"].max())
    who_lo, who_hi = round(ymin / 5), round(ymax / 5)
    summer = city_day[city_day.index.month.isin([4, 5, 6, 7, 8])].mean()
    winter = city_day[city_day.index.month.isin([11, 12, 1, 2])]
    season = winter.index.year + (winter.index.month >= 10).astype(int)
    peaks = winter.groupby(season).max().tail(6)
    peak_lo, peak_hi = int(peaks.min() // 10 * 10), int(peaks.max())
    peak_years = f"{peaks.index.min()} through {peaks.index.max()}"

    generated = f"{pd.Timestamp.utcnow():%d %B %Y}"
    header = "Peshawar Air Quality — PM2.5 Monitoring Data and Quality Assessment"

    pdf_path = OUT / "peshawar_report.pdf"
    doc = BaseDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 0.6 * cm, bottomMargin=MARGIN,
        title="Peshawar Air Quality — PM2.5 Monitoring Data and Quality Assessment",
        author="Pakistan Air Quality Initiative",
    )
    p_frame = Frame(MARGIN, MARGIN, PAGE_W_P - 2 * MARGIN,
                    PAGE_H_P - 2 * MARGIN - 0.6 * cm, id="p")
    l_frame = Frame(MARGIN, MARGIN, PAGE_W_L - 2 * MARGIN,
                    PAGE_H_L - 2 * MARGIN - 0.6 * cm, id="l")
    doc.addPageTemplates([
        PageTemplate(id="portrait", frames=[p_frame], pagesize=A4,
                     onPage=lambda c, d: _page_decorator(
                         c, d, PAGE_W_P, PAGE_H_P, header, generated)),
        PageTemplate(id="landscape", frames=[l_frame], pagesize=landscape(A4),
                     onPage=lambda c, d: _page_decorator(
                         c, d, PAGE_W_L, PAGE_H_L, header, generated)),
    ])

    story = []

    # ── Cover ──
    story += [
        Spacer(1, 2.6 * cm),
        scaled_image(LOGO_FULL, 4.2),
        Spacer(1, 1.0 * cm),
        P("Peshawar Air Quality", title_style),
        Spacer(1, 0.4 * cm),
        P("PM2.5 Monitoring Data and Quality Assessment, 2017–2026",
          subtitle_style),
        Spacer(1, 0.5 * cm),
        P(f"{last:%B %Y}", caption_style),
        Spacer(1, 2.0 * cm),
        P(
            "The Pakistan Air Quality Initiative (PAQI) has been collecting, "
            "cleaning, and publishing air-quality data to support "
            "evidence-based work on clean air in Pakistan. This data package "
            "brings together the complete Peshawar station-hour record "
            "currently held on PAQI's Hawanama platform.",
            body_style,
        ),
        P(
            f"The archive begins on {first:%d %B %Y} and includes "
            f"{n_hours:,} station-hour records from {n_st} station feeds "
            f"across {n_sites} physical monitoring sites. Of these records, "
            f"{n_pm25_raw:,} contain raw PM2.5 observations, and "
            f"{n_pm25_qc:,} pass the quality-control process used for this "
            f"release. Values that appear anomalous are flagged rather than "
            f"removed, so the original record remains available for audit "
            f"and review.",
            body_style,
        ),
        P(
            "This report explains how the monitoring network developed, what "
            "the data shows about Peshawar's air quality, and how quality "
            "control was applied.",
            body_style,
        ),
        Spacer(1, 2.8 * cm),
        P("Pakistan Air Quality Initiative · hawanama.org",
          caption_right_style),
        P(
            "Contact: Rehan Ahmad — rehan@pakairquality.com · "
            "Abid Omar — abidomar@pakairquality.com",
            caption_right_style,
        ),
    ]

    # ── Executive summary ──
    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story += [
        P(
            "Peshawar now has more than nine years of air-quality "
            "observations, but the strength of the record varies considerably "
            "across time. From 2017 to mid-2022, monitoring depended on a "
            "small number of stations: initially the Peshawar Node, then the "
            "US Consulate monitor, and later a community sensor in Hayatabad. "
            "From mid-2022 onward, the network expanded substantially through "
            "the Peshawar Clean Air Alliance, Bank of Khyber sensors, "
            "universities, government offices, WWF, and community "
            "deployments. This expansion changed the dataset from a sparse "
            "single-city record into a much stronger city-scale monitoring "
            "network.",
            body_style,
        ),
        Spacer(1, 0.2 * cm),
        brand_table(
            [
                ["Period", "Active sites\n/ month", "Primary sources"],
                ["Jan 2017 – Apr 2019", "1", "Peshawar Node"],
                ["May 2019 – May 2022", "1–3",
                 "US Consulate (AirNow); Hayatabad community sensor from Dec 2020"],
                ["Jun 2022 – Dec 2023", "2–12",
                 "Peshawar Clean Air Alliance, Bank of Khyber, community sensors"],
                ["2024 – present", "6–18",
                 "PCAA, universities, government offices, WWF, community sensors"],
            ],
            [3.8 * cm, 2.1 * cm, 10.1 * cm],
        ),
        P("Table 1 — Data availability at a glance.", caption_style),
        Spacer(1, 0.3 * cm),
        P(
            f"The full package contains {n_hours:,} station-hour records "
            f"from {n_st} station feeds at {n_sites} physical sites. A total "
            f"of {n_pm25_raw:,} records contain PM2.5 values, of which "
            f"{n_pm25_qc:,} pass quality control. In practice, "
            f"{qc_pass_pct:.1f}% of PM2.5 observations remain "
            f"available in the cleaned <font face='Courier'>pm25_qc</font> "
            f"column, while failed observations are retained in the raw "
            f"<font face='Courier'>pm25</font> column for transparency.",
            body_style,
        ),
        P(
            f"The data shows that Peshawar's PM2.5 burden is severe. In "
            f"years with sufficient coverage, annual city means range from "
            f"{ymin} to {ymax} µg/m³, which is roughly {who_lo} to {who_hi} "
            f"times higher than the WHO annual guideline of 5 µg/m³. Winter "
            f"is the most polluted period. During December and January smog "
            f"episodes, daily city means regularly exceed 250 µg/m³, and "
            f"several winter peaks fall well inside the hazardous range. "
            f"Summer months, especially April to August, are cleaner by "
            f"comparison, but even then average concentrations remain around "
            f"{summer:.0f} µg/m³.",
            body_style,
        ),
        P(
            f"Quality-control failures are relatively rare but important. "
            f"Out of {n_pm25_raw:,} raw PM2.5 observations, "
            f"{n_pm25_flagged:,} fail a PM2.5-affecting check. Most of these "
            f"are suspect rather than invalid. The main issues are "
            f"cross-station outliers, stuck-sensor flatlines, and a small "
            f"number of physically implausible readings above 1,000 µg/m³. "
            f"These flagged values are blanked in "
            f"<font face='Courier'>pm25_qc</font> but preserved in "
            f"<font face='Courier'>pm25</font>.",
            body_style,
        ),
        P(
            "This dataset should be treated as an indicative low-cost sensor "
            "record, not as a reference-grade regulatory dataset. It is most "
            "useful for understanding city-wide patterns, seasonal "
            "behaviour, pollution episodes, and monitoring-network history. "
            "Users should rely on <font face='Courier'>pm25_qc</font> for "
            "analysis, average by site rather than station feed, and "
            "interpret pre-2022 city means with particular caution.",
            body_style,
        ),
    ]

    # ── 1. Monitoring network ──
    story.append(PageBreak())
    story += [
        P("1. The monitoring network", h1_style),
        P(
            "Understanding the history of the monitoring network is "
            "essential because the dataset is not equally dense across all "
            "years. The earliest part of the record is useful, but it "
            "reflects only a very small number of sites. The later period, "
            "especially after mid-2022, provides a much better picture of "
            "city-scale variation.",
            body_style,
        ),
        P(
            "Monitoring began in January 2017 with the Peshawar Node "
            "station. In May 2019, the US Consulate monitor, part of the US "
            "State Department's air-monitoring programme published through "
            "EPA's AirNow, added a second major source of observations. A "
            "PAQI community sensor in Hayatabad began contributing data in "
            "December 2020.",
            body_style,
        ),
        P(
            f"The network changed significantly in 2022. Peshawar Clean Air "
            f"Alliance stations came online from June 2022, followed by Bank "
            f"of Khyber branch sensors from November 2022. Additional "
            f"university, government, WWF, and community deployments "
            f"followed through 2025. Across the full period, {n_st} station "
            f"feeds from {n_sites} physical sites contributed data. Station "
            f"turnover is noticeable, and at any given point only part of "
            f"the historical network is active.",
            body_style,
        ),
        P(
            "Most stations are low-cost optical sensors reporting through "
            "the IQAir AirVisual network and aggregated on PAQI's Hawanama "
            "platform. In the data files, the "
            "<font face='Courier'>provider</font> column identifies the "
            "aggregation channel rather than necessarily identifying the "
            "institution operating the sensor.",
            body_style,
        ),
        P(
            "Some locations have hosted more than one feed over time, either "
            "because of replacement sensors or duplicate feeds at the same "
            "coordinates. For that reason, the "
            "<font face='Courier'>site_id</font> column is important. "
            "City-level averages in this report are calculated per site so "
            "that co-located feeds do not double-count a single location.",
            body_style,
        ),
        Spacer(1, 0.2 * cm),
        scaled_image(figs["map"], 15.5, 10.5),
        P(
            "Figure 1 — Monitoring stations. Colour shows mean QC-passed "
            "PM2.5; marker size shows the number of QC-passed observations. "
            "Dashed outline is Peshawar district.",
            caption_style,
        ),
    ]

    story.append(NextPageTemplate("landscape"))
    story.append(PageBreak())
    story += [
        scaled_image(figs["coverage"], 25.5, 15.5),
        P(
            "Figure 2 — Data availability by station feed (months with any "
            "PM2.5 observation), ordered by first record; the number after "
            "each name is raw PM2.5 observations.",
            caption_style,
        ),
    ]

    # ── 2. The data record ──
    story.append(PageBreak())
    story += [
        scaled_image(figs["timeseries"], 25.5, 13.5),
        P(
            "Figure 3 — City daily-mean PM2.5 (QC-passed data; station-days "
            "with ≥ 18 valid hours, averaged per site then across sites; "
            "Pakistan Standard Time days) with 30-day rolling mean. "
            "Reference lines are 24-hour values: WHO 24-hour guideline "
            "(15 µg/m³) and Pakistan NEQS 24-hour standard (35 µg/m³).",
            caption_style,
        ),
    ]

    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    y17 = ytbl.loc[2017]
    recent = ytbl.loc[[y for y in (2023, 2024, 2025) if y in ytbl.index]]
    story += [
        P("2. The data record", h1_style),
        P(
            "All daily, monthly, and annual summaries in this report are "
            "calculated in Pakistan Standard Time. A station-day mean is "
            "only calculated where at least 18 valid hourly "
            "<font face='Courier'>pm25_qc</font> values are available. "
            "Site-day means are calculated by averaging valid station-days "
            "at the same physical location, and city-day means are then "
            "calculated by averaging valid site-day means across the city.",
            body_style,
        ),
        P(
            "Annual means are only treated as reportable when at least 75% "
            "of the year's days have a valid city-day value. Years below "
            "this threshold are marked as incomplete. This distinction "
            "matters because early years can look precise in the table while "
            "still relying on limited monitoring coverage.",
            body_style,
        ),
        P(
            f"The clearest feature of the Peshawar record is its winter "
            f"cycle. PM2.5 rises sharply from October, usually peaks in "
            f"December or January, and then falls through February and "
            f"March. This pattern appears repeatedly across the record. Peak "
            f"daily city means reached between {peak_lo} and {peak_hi} µg/m³ "
            f"in the winters from {peaks.index.min()} to {peaks.index.max()}, "
            f"indicating severe winter pollution episodes.",
            body_style,
        ),
        P(
            "The years before 2022 should be read carefully. In several "
            "years, the city mean is effectively driven by one or two "
            "monitors, and day coverage is below the threshold used for "
            "annual reporting. From late 2022 onward, the network becomes "
            "much stronger, with more sites contributing on most days.",
            body_style,
        ),
        P(
            f"The yearly summary shows both the pollution burden and the "
            f"improvement in monitoring coverage. In 2017, the annual mean "
            f"was {y17['mean']:.0f} µg/m³ based on {int(y17['sites'])} site "
            f"and {y17['coverage']:.0f}% day coverage. Coverage then "
            f"remained incomplete for several years. By 2023, 2024, and "
            f"2025, coverage reached "
            f"{recent['coverage'].min():.0f}–{recent['coverage'].max():.0f}%, "
            f"with {int(recent['sites'].min())} to "
            f"{int(recent['sites'].max())} physical sites contributing valid "
            f"observations.",
            body_style,
        ),
        P(
            "Across sufficiently covered years, annual PM2.5 means remain "
            "far above health-based guidelines. Even the cleaner summer "
            "period remains polluted by international standards, while "
            "winter episodes reach levels that are hazardous for public "
            "health.",
            body_style,
        ),
    ]

    story.append(PageBreak())
    story += [
        P("Seasonality and yearly summary", h2_style),
        scaled_image(figs["climatology"], 14.0, 9.0),
        P(
            "Figure 4 — Monthly climatology of daily city-mean PM2.5: median "
            "and interquartile range, all years pooled.",
            caption_style,
        ),
        Spacer(1, 0.4 * cm),
    ]

    yr_rows = [["Year", "Mean PM2.5\n(µg/m³)", "Max daily\n(µg/m³)",
                "Day\ncoverage", "Sites", "PM2.5 obs"]]
    for y, r in ytbl.iterrows():
        label = f"{y} YTD (through {last_local:%d %b})" if r["ytd"] else f"{y}"
        mean_txt = f"{r['mean']:.0f}"
        if not r["complete"] and not r["ytd"]:
            mean_txt += " †"
        yr_rows.append([
            label, mean_txt, f"{r['max']:.0f}", f"{r['coverage']:.0f}%",
            f"{int(r['sites'])}", f"{int(r['n_obs']):,}",
        ])
    story += [
        brand_table(yr_rows, [4.2 * cm, 2.4 * cm, 2.2 * cm, 2.0 * cm,
                              1.7 * cm, 2.4 * cm],
                    extra_styles=[("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                                  ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                                  ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5)]),
        P(
            "Table 2 — Yearly summary (Pakistan Standard Time days). Mean "
            "PM2.5 is the annual mean of city-day means; Day coverage is the "
            "share of days with a valid city-day value; Sites is physical "
            "sites with at least one valid day; PM2.5 obs is raw "
            "observations. † Incomplete year (day coverage below 75%) — "
            "annual mean is indicative only.",
            caption_style,
        ),
    ]

    # ── 3. QA/QC ──
    story.append(PageBreak())
    story += [
        P("3. Quality assurance", h1_style),
        P(
            "The quality-control process used here follows a simple "
            "principle: flag values rather than delete them. The raw "
            "measurement remains in the <font face='Courier'>pm25</font> "
            "column, while values that fail PM2.5 quality control are "
            "blanked only in the derived <font face='Courier'>pm25_qc</font> "
            "column. This keeps the cleaned analysis field usable without "
            "destroying the original observation.",
            body_style,
        ),
        P(
            "Every reading was screened using automated rules developed for "
            "PAQI's Hawanama platform. These rules check for known error "
            "codes, physically implausible values, isolated spikes, long "
            "flatlines, and station-days that are extreme compared with the "
            "rest of the city network. Other fields, such as AQI, humidity, "
            "temperature, and PM10, are also checked where available, but "
            "these information-only flags do not affect "
            "<font face='Courier'>pm25_qc</font>.",
            body_style,
        ),
        Spacer(1, 0.2 * cm),
    ]

    rule_rows = [
        ["Rule", "Condition", "Severity"],
        ["pm25_sentinel", "PM2.5 equals a known error/cap code (999, 1000, −1)", "invalid"],
        ["pm25_oor", "PM2.5 outside 0–1,000 µg/m³", "invalid"],
        ["pm25_spike", "Isolated 1–2 h jump > 250 µg/m³ that reverts to baseline", "suspect"],
        ["pm25_flatline", "≥ 18 consecutive hours with an identical value", "suspect"],
        ["city_outlier", "Station day > 3× city median (≥ 3 stations, > 50 µg/m³)", "suspect"],
        ["pm10_oor / aqi_oor /\nhumidity_oor / temp_oor",
         "Range checks on PM10, AQI, and met fields\n(do not affect pm25_qc)",
         "info only"],
    ]
    story += [
        brand_table(rule_rows, [4.2 * cm, 9.6 * cm, 2.2 * cm],
                    extra_styles=[("FONT", (0, 1), (0, -1), "Courier", 8)]),
        P("Table 3 — QC rule set and severities.", caption_style),
        Spacer(1, 0.4 * cm),
        P(
            f"Out of {n_pm25_raw:,} raw PM2.5 observations, "
            f"{n_pm25_flagged:,} fail a PM2.5-affecting check. This "
            f"represents {100 * n_pm25_flagged / n_pm25_raw:.2f}% of the "
            f"PM2.5 record. Of these, {n_sus:,} are marked suspect and "
            f"{n_inv:,} are marked invalid.",
            body_style,
        ),
        P(
            f"The most common issue is cross-station outliers, with "
            f"{flag_counts['city_outlier']:,} observations flagged. These "
            f"are cases where a station reads much higher than the city "
            f"network on the same day. Stuck-sensor flatlines account for "
            f"another {flag_counts['pm25_flatline']:,} observations. There "
            f"are also {flag_counts['pm25_oor']:,} readings above "
            f"1,000 µg/m³, which are treated as physically implausible, and "
            f"{flag_counts['pm25_spike']:,} isolated spikes. No sentinel "
            f"error codes were found in this subset.",
            body_style,
        ),
        P(
            f"A separate group of {flag_counts['aqi_oor']:,} records carries "
            f"an information-only flag for reported AQI values above the US "
            f"AQI 500 ceiling. These occur during extreme winter pollution "
            f"episodes and are consistent with the underlying PM2.5 "
            f"concentrations. They do not blank "
            f"<font face='Courier'>pm25_qc</font> unless a PM2.5-specific "
            f"rule is also triggered.",
            body_style,
        ),
        P(
            f"The flags are not evenly distributed across the network. "
            f"{top_two} account for a large share of cross-station outliers. "
            f"On flagged days, these stations read persistently high "
            f"compared with the rest of the network. This could reflect "
            f"sensor drift, local siting conditions, or nearby emissions "
            f"sources. Until the instruments and siting conditions are "
            f"reviewed, flagged periods from these stations should be "
            f"excluded from quantitative analysis.",
            body_style,
        ),
        Spacer(1, 0.1 * cm),
        KeepTogether([
            scaled_image(figs["qc"], 17.5, 8.0),
            P(
                "Figure 5 — Left: readings flagged by rule, coloured by "
                "severity (grey rules are information-only and do not affect "
                "pm25_qc). Right: the ten most-flagged stations counting "
                "PM2.5-affecting rules only (red: invalid; yellow: suspect).",
                caption_style,
            ),
        ]),
    ]

    if figs.get("anomaly"):
        a_path, a_name, a_lo, a_hi = figs["anomaly"]
        story.append(NextPageTemplate("landscape"))
        story.append(PageBreak())
        story += [
            scaled_image(a_path, 25.5, 13.5),
            P(
                f"Figure 6 — Example of flagged anomalies at {a_name}, "
                f"{a_lo:%d %b %Y} – {a_hi:%d %b %Y} (Pakistan Standard "
                f"Time). Red points are readings flagged by PM2.5 rules; the "
                f"blue line is the QC-passed series that remains for "
                f"analysis.",
                caption_style,
            ),
        ]
        story.append(NextPageTemplate("portrait"))

    story += [
        Spacer(1, 0.8 * cm),
        P(
            "Prepared by the Pakistan Air Quality Initiative (PAQI) · "
            "hawanama.org",
            caption_style,
        ),
        P(
            "For questions about this dataset: Rehan Ahmad — "
            "rehan@pakairquality.com · Abid Omar — "
            "abidomar@pakairquality.com",
            caption_style,
        ),
    ]

    doc.build(story)
    return pdf_path


# ────────────────────────────── folium map ──────────────────────────────


def build_folium_map(st: pd.DataFrame):
    center = [st["lat"].mean(), st["lon"].mean()]
    m = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")

    peshawar, _ = load_district_shapes()
    folium.GeoJson(
        {"type": "Feature", "geometry": peshawar},
        style_function=lambda f: {
            "color": "#52514e", "weight": 1.5, "fill": False, "dashArray": "4"
        },
        name="Peshawar district",
    ).add_to(m)

    cmap = plt.get_cmap("Reds")
    norm = Normalize(vmin=0, vmax=max(150, st["mean_pm25_qc"].max()))
    for r in st.itertuples():
        val = r.mean_pm25_qc if pd.notna(r.mean_pm25_qc) else 0
        color = matplotlib.colors.to_hex(cmap(norm(val)))
        qc_pass = (
            f"{r.pm25_qc_pass_pct:.1f}%" if pd.notna(r.pm25_qc_pass_pct) else "n/a"
        )
        popup = folium.Popup(
            f"<b>{r.station_name}</b><br>"
            f"Provider: {r.provider}<br>"
            f"Records: {r.first_reading:%b %Y} – {r.last_reading:%b %Y}<br>"
            f"QC-passed PM2.5 obs: {r.n_pm25_qc:,}<br>"
            f"PM2.5 coverage: {r.pm25_coverage_pct:.1f}% of station-hours<br>"
            f"PM2.5 QC pass rate: {qc_pass}<br>"
            f"Mean PM2.5 (QC): {val:.0f} µg/m³",
            max_width=300,
        )
        folium.CircleMarker(
            location=[r.lat, r.lon], radius=7, color="#ffffff", weight=1.5,
            fill=True, fill_color=color, fill_opacity=0.95, popup=popup,
            tooltip=r.station_name,
        ).add_to(m)

    legend = """
    <div style="position: fixed; bottom: 24px; left: 24px; z-index: 1000;
                background: white; padding: 10px 14px; border-radius: 6px;
                box-shadow: 0 1px 4px rgba(0,0,0,.3); font: 12px sans-serif;">
      <b>Mean PM2.5 (µg/m³, QC-passed)</b><br>
      <span style="color:#fee5d9">&#9679;</span> 0 &nbsp;
      <span style="color:#fcae91">&#9679;</span> 40 &nbsp;
      <span style="color:#fb6a4a">&#9679;</span> 80 &nbsp;
      <span style="color:#de2d26">&#9679;</span> 120 &nbsp;
      <span style="color:#a50f15">&#9679;</span> 150+
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))
    path = OUT / "peshawar_map.html"
    m.save(str(path))
    return path


def main():
    OUT.mkdir(exist_ok=True)
    PLOTS.mkdir(exist_ok=True)
    cached = "--cached" in sys.argv

    if cached and (OUT / "peshawar_hourly_readings.csv").exists():
        print("Loading cached CSV (skipping DB)...")
        df = load_cached()
    else:
        print("Fetching data from production DB (read-only)...")
        df = fetch_data()

    print("Cleaning station metadata (names, site_id, local time)...")
    df = clean_metadata(df)
    n_sites = df["site_id"].nunique()
    print(f"  {len(df):,} station-hours, {df['station_id'].nunique()} feeds, "
          f"{n_sites} sites")

    print("Applying QA/QC...")
    df = apply_qc(df)
    print(f"  raw PM2.5 obs:      {df['pm25'].notna().sum():,}")
    print(f"  QC-passed obs:      {df['pm25_qc'].notna().sum():,}")
    for state, n in df["pm25_qc_state"].value_counts().items():
        print(f"  pm25_qc_state {state}: {n:,}")

    st = station_table(df)
    qc = qc_summary_table(df)

    print("Writing CSVs...")
    df[CSV_COLS].to_csv(OUT / "peshawar_hourly_readings.csv", index=False)
    st.to_csv(OUT / "peshawar_stations.csv", index=False)
    qc.to_csv(OUT / "qc_summary.csv", index=False)

    print("Computing daily/yearly summaries (PKT days, documented rule)...")
    city_day, sites_per_day, site_day = compute_daily(df)
    ytbl = yearly_summary(df, city_day, site_day)
    print(ytbl[["mean", "coverage", "complete", "sites"]].round(1).to_string())

    print("Building figures...")
    figs = {
        "map": fig_station_map(st),
        "coverage": fig_coverage(df, st),
        "timeseries": fig_timeseries(city_day, sites_per_day),
        "climatology": fig_climatology(city_day),
        "qc": fig_qc_overview(df, qc),
        "anomaly": fig_anomaly_example(df, qc),
    }

    print("Building PDF report...")
    pdf_path = build_pdf(df, st, qc, figs, city_day, sites_per_day, ytbl)
    print(f"  {pdf_path}")

    print("Building interactive map...")
    map_path = build_folium_map(st)
    print(f"  {map_path}")

    print("Done.")


if __name__ == "__main__":
    main()
