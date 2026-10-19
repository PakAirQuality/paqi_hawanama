"""Pull Punjab AQMS + LCS + US Consulate PM2.5 readings for the last 24 months
and render per-city time-series overlay + LCS-vs-reference scatter plots.

Sources
  - Punjab AQMS  : providers.code = 'punjab'           (regulatory, ~24 stations)
  - LCS          : providers.display_name = 'Airvisual/PAQI'  (IQAir AirVisual, ~267 stations)
  - US Consulate : AirNow API (Pakistan bbox), filtered to consulate SiteNames

Outputs (gitignored CSVs; PNGs are committed)
  data/punjab_aqms_24m.csv
  data/lcs_24m.csv
  data/us_consulate_24m.csv
  data/cache/airnow_YYYYMMDD.csv   (per-week response cache)
  plots/timeseries_<city>.png
  plots/scatter_<city>_lcs_vs_punjab.png
  plots/scatter_<city>_lcs_vs_consulate.png
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg2
import requests
from psycopg2.extras import RealDictCursor

REPO = Path("/Users/rehanahmad/Desktop/hawanama-main")
DATA = REPO / "data"
CACHE = DATA / "cache"
PLOTS = REPO / "plots"
DATA.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True, parents=True)
PLOTS.mkdir(exist_ok=True)

END = dt.datetime(2026, 5, 13, 0, 0, tzinfo=dt.timezone.utc)
START = END - dt.timedelta(days=730)   # exactly 24 months

AIRNOW_API_KEY = os.environ["AIRNOW_API_KEY"]  # never commit the key; export it in the shell
CONSULATE_SITES = {"Lahore", "Karachi", "Islamabad", "Peshawar"}

COLOR = {
    "Punjab AQMS":   "#1f3a93",   # dark blue
    "LCS":           "#e67e22",   # orange
    "US Consulate":  "#16a085",   # green
}


# ---------------------------------------------------------------------- DB ---

def load_env(p: Path) -> dict:
    env = {}
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def db_conn():
    e = load_env(REPO / ".env")
    return psycopg2.connect(
        host=e["POSTGRES_SERVER"], port=int(e["POSTGRES_PORT"]),
        user=e["POSTGRES_USER"], password=e["POSTGRES_PASSWORD"],
        dbname=e["POSTGRES_DB"], sslmode="require",
    )


def dump_db_source(out_path: Path, where_clause: str) -> int:
    """Stream a long-format CSV from Postgres via COPY. Returns row count."""
    sql = f"""
    COPY (
      SELECT
        s.station_id      AS location_id,
        s.name            AS location,
        c.name            AS city,
        s.lat,
        s.lon,
        to_char(r.ts_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS datetime_utc,
        r.pm25            AS value
      FROM readings r
      JOIN stations s   ON r.scope_type = 'station' AND r.scope_key = s.station_id
      JOIN providers p  ON s.provider_id = p.id
      LEFT JOIN cities c ON c.id = s.city_id
      WHERE {where_clause}
        AND r.pm25 IS NOT NULL
        AND r.pm25 > 0 AND r.pm25 < 1000
        AND r.ts_utc >= '{START.strftime('%Y-%m-%dT%H:%M:%SZ')}'
        AND r.ts_utc <  '{END.strftime('%Y-%m-%dT%H:%M:%SZ')}'
      ORDER BY s.station_id, r.ts_utc
    ) TO STDOUT WITH CSV HEADER
    """
    t0 = time.time()
    conn = db_conn()
    conn.set_session(readonly=True)
    try:
        with open(out_path, "w") as f, conn.cursor() as cur:
            cur.copy_expert(sql, f)
    finally:
        conn.close()
    with open(out_path) as f:
        n = sum(1 for _ in f) - 1
    print(f"  {out_path.name}: {n:,} rows  ({(time.time() - t0):.1f}s)")
    return n


# ------------------------------------------------------------------ AirNow ---

def airnow_chunk(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    """Fetch one week's worth of Pakistan PM2.5 observations from AirNow.
    Cache responses keyed by start-date to avoid re-querying.
    """
    cache_path = CACHE / f"airnow_{start.strftime('%Y%m%d')}.csv"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return pd.read_csv(cache_path)

    params = {
        "startDate": start.strftime("%Y-%m-%dT%H"),
        "endDate":   end.strftime("%Y-%m-%dT%H"),
        "parameters": "PM25",
        "BBOX":      "60.0,23.0,77.0,37.0",
        "dataType":  "B",
        "format":    "text/csv",
        "monitorType": "0",
        "verbose":   "1",
        "API_KEY":   AIRNOW_API_KEY,
    }
    url = "https://www.airnowapi.org/aq/data/"
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=60)
            r.raise_for_status()
            break
        except Exception as e:
            if attempt == 2:
                print(f"  airnow {start.date()}: FAILED after 3 attempts: {e}")
                cache_path.write_text("")
                return pd.DataFrame()
            time.sleep(2 ** attempt)

    text = r.text or ""
    # Header per AirNow docs (with verbose=1): Latitude,Longitude,UTC,Parameter,Concentration,Unit,RawConcentration,AQI,Category,SiteName,SiteAgencyName,AQSID,FullAQSID
    cols = ["Latitude", "Longitude", "UTC", "Parameter", "Concentration", "Unit",
            "RawConcentration", "AQI", "Category", "SiteName", "SiteAgencyName",
            "AQSID", "FullAQSID"]
    if not text.strip():
        cache_path.write_text(",".join(cols) + "\n")
        return pd.DataFrame(columns=cols)

    # AirNow returns CSV without a header → write it out with our header for sanity
    with open(cache_path, "w") as f:
        f.write(",".join(cols) + "\n")
        f.write(text)
    try:
        return pd.read_csv(cache_path)
    except Exception:
        return pd.DataFrame(columns=cols)


def pull_us_consulate(out_path: Path) -> int:
    """Walk 24 months in 7-day chunks; concat, filter to consulate sites."""
    chunks = []
    cur = START
    week = dt.timedelta(days=7)
    n_calls = 0
    while cur < END:
        nxt = min(cur + week, END)
        df = airnow_chunk(cur, nxt)
        if not df.empty:
            chunks.append(df)
        n_calls += 1
        cur = nxt

    if not chunks:
        out_path.write_text("location_id,location,city,lat,lon,datetime_utc,value\n")
        return 0

    all_df = pd.concat(chunks, ignore_index=True)
    # Pakistan US consulate/embassy SiteName format:
    #   "U.S. Department of State Pakistan - Islamabad"  →  city = "Islamabad"
    sn = all_df["SiteName"].astype(str).str.strip()
    keep = all_df[sn.str.contains("Pakistan", case=False, na=False)].copy()
    keep["city"] = keep["SiteName"].astype(str).str.split(" - ").str[-1].str.strip()
    # Drop anything whose extracted city isn't one of the four we expect
    keep = keep[keep["city"].isin(CONSULATE_SITES)]

    # Normalize to our shape
    keep["datetime_utc"] = keep["UTC"].astype(str).str[:13] + ":00:00Z"
    keep["value"] = pd.to_numeric(keep["Concentration"], errors="coerce")
    keep = keep[keep["value"].notna() & (keep["value"] > 0) & (keep["value"] < 1000)]
    keep["location_id"] = "usconsulate_" + keep["city"].str.lower()
    keep["location"] = "US Consulate " + keep["city"]

    out = keep[["location_id", "location", "city", "Latitude", "Longitude", "datetime_utc", "value"]].rename(
        columns={"Latitude": "lat", "Longitude": "lon"}
    )
    out.to_csv(out_path, index=False)
    print(f"  airnow chunks fetched: {n_calls}  rows-after-filter: {len(out):,}")
    print(f"  distinct consulate sites: {sorted(out['city'].unique().tolist())}")
    return len(out)


# ------------------------------------------------------------------- plots ---

def daily_means_by_city(csv_path: Path) -> pd.DataFrame:
    """Read a long CSV, return (city, date) → mean PM2.5."""
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return pd.DataFrame(columns=["city", "date", "value"])
    df = pd.read_csv(csv_path)
    if df.empty:
        return pd.DataFrame(columns=["city", "date", "value"])
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], errors="coerce", utc=True)
    df = df[df["datetime_utc"].notna()]
    df["city"] = df["city"].astype(str).str.strip()
    df = df[df["city"].astype(bool) & (df["city"].str.lower() != "nan")]
    if df.empty:
        return pd.DataFrame(columns=["city", "date", "value"])
    df["date"] = df["datetime_utc"].dt.tz_convert(None).dt.floor("D")
    out = df.groupby(["city", "date"], as_index=False)["value"].mean()
    return out


def ols_fit(x: np.ndarray, y: np.ndarray):
    n = len(x)
    if n < 5:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return slope, intercept, r2, n


def plot_city_timeseries(city: str, series: dict, out_path: Path):
    """series: { 'Punjab AQMS': df[date,value], 'LCS': ..., 'US Consulate': ... }"""
    fig, ax = plt.subplots(figsize=(12, 6))
    for label, df in series.items():
        if df is None or df.empty:
            continue
        ax.plot(df["date"], df["value"], label=label, color=COLOR[label], linewidth=1.2, alpha=0.9)
    ax.set_title(f"PM2.5 daily mean — {city}  (2024-05-13 → 2026-05-13)")
    ax.set_ylabel("PM2.5 (µg/m³)")
    ax.set_xlabel("Date")
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", framealpha=0.9)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"  wrote {out_path}")


def plot_scatter(city: str, ref_label: str, ref_df: pd.DataFrame, lcs_df: pd.DataFrame, out_path: Path):
    merged = ref_df.merge(lcs_df, on="date", suffixes=("_ref", "_lcs")).dropna()
    if len(merged) < 5:
        print(f"  scatter {city} vs {ref_label}: only {len(merged)} pairs — skipping")
        return None
    x = merged["value_ref"].to_numpy()
    y = merged["value_lcs"].to_numpy()
    fit = ols_fit(x, y)
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(x, y, s=10, alpha=0.45, color=COLOR["LCS"], edgecolors="none")
    lim = max(x.max(), y.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", alpha=0.5, label="1:1")
    if fit is not None:
        slope, intercept, r2, n = fit
        xs = np.linspace(0, lim, 100)
        ax.plot(xs, slope * xs + intercept, color="#c0392b", label=f"OLS  y = {slope:.2f}x + {intercept:.1f}")
        ax.text(0.04, 0.96,
                f"N = {n}\nR² = {r2:.3f}\nslope = {slope:.2f}\nintercept = {intercept:.1f}",
                transform=ax.transAxes, va="top", ha="left",
                fontsize=10, bbox=dict(boxstyle="round", fc="white", ec="#888", alpha=0.85))
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel(f"{ref_label} daily mean (µg/m³)")
    ax.set_ylabel("LCS daily mean (µg/m³)")
    ax.set_title(f"LCS vs {ref_label} — {city} (daily means)")
    ax.grid(alpha=0.25)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"  wrote {out_path}")


# --------------------------------------------------------------------- main --

def main():
    print(f"Window: {START.date()} → {END.date()}\n")

    print("--- Step 1/5: pull Punjab AQMS ---")
    dump_db_source(DATA / "punjab_aqms_24m.csv", "p.code = 'punjab'")

    print("--- Step 2/5: pull LCS (PAQI / IQAir) ---")
    dump_db_source(DATA / "lcs_24m.csv", "p.display_name = 'Airvisual/PAQI'")

    print("--- Step 3/5: pull AirGradient ---")
    # AirGradient is tagged by stations.monitor_type, not by a separate provider row.
    # Earliest data is 2025-02; the 24-month window starts earlier — rows simply
    # don't exist before AG was deployed, which is fine.
    dump_db_source(DATA / "airgradient_24m.csv", "s.monitor_type = 'AirGradient'")

    print("--- Step 4/5: pull US Consulate from AirNow ---")
    pull_us_consulate(DATA / "us_consulate_24m.csv")

    print("\n--- Step 5/5: render plots ---")
    daily_punjab = daily_means_by_city(DATA / "punjab_aqms_24m.csv")
    daily_lcs    = daily_means_by_city(DATA / "lcs_24m.csv")
    daily_cons   = daily_means_by_city(DATA / "us_consulate_24m.csv")

    print(f"  daily means — punjab_aqms: {len(daily_punjab):,}  lcs: {len(daily_lcs):,}  us_consulate: {len(daily_cons):,}")
    print(f"  cities with punjab_aqms: {sorted(daily_punjab['city'].unique().tolist())}")
    print(f"  cities with us_consulate: {sorted(daily_cons['city'].unique().tolist())}")

    # Cities to plot: union of all cities where any reference network has data, OR LCS only
    # We focus on the 4 consulate cities + any other Punjab city the user might find interesting
    plot_cities = set(daily_cons["city"].unique())
    plot_cities |= set(daily_punjab["city"].unique())
    # Filter out junk strings
    plot_cities = sorted({c for c in plot_cities if c and str(c).lower() not in {"nan", "none", ""}})
    print(f"  cities to plot: {plot_cities}\n")

    for city in plot_cities:
        pu = daily_punjab[daily_punjab["city"].str.lower() == city.lower()][["date", "value"]]
        lc = daily_lcs[daily_lcs["city"].str.lower() == city.lower()][["date", "value"]]
        co = daily_cons[daily_cons["city"].str.lower() == city.lower()][["date", "value"]]

        if pu.empty and lc.empty and co.empty:
            continue

        safe = city.lower().replace(" ", "_")
        plot_city_timeseries(
            city,
            {"Punjab AQMS": pu, "LCS": lc, "US Consulate": co},
            PLOTS / f"timeseries_{safe}.png",
        )
        if not pu.empty and not lc.empty:
            plot_scatter(city, "Punjab AQMS", pu, lc, PLOTS / f"scatter_{safe}_lcs_vs_punjab.png")
        if not co.empty and not lc.empty:
            plot_scatter(city, "US Consulate", co, lc, PLOTS / f"scatter_{safe}_lcs_vs_consulate.png")


if __name__ == "__main__":
    main()
