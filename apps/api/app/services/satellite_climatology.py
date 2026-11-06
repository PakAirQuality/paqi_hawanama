"""Day-of-year climatology and z-anomalies for a daily region series (port of atminvest.baseline.climatology).

The baseline for a day is every value within ±HALF_WINDOW_D days of the same day of year in the
other July–June seasons (the target season left out), so an anomalous season does not shrink its
own anomaly. A table row is (season_out, doy): the statistics of the window with that season left
out; season_out = ALL_SEASONS keeps every season and scores dates outside the climatology period.
"""

from __future__ import annotations

import warnings
from typing import Iterable

import numpy as np
import pandas as pd

HALF_WINDOW_D = 15
MIN_N = 10
ALL_SEASONS = -1
CLIM_COLUMNS = ["season_out", "doy", "mean", "sd", "p10", "p50", "p90", "n"]


def season_year(t) -> np.ndarray:
    """July–June season label: the year the season started in."""
    t = pd.DatetimeIndex(pd.to_datetime(t, utc=True))
    return np.where(t.month >= 7, t.year, t.year - 1)


def circular_doy_distance(a, b, period: int = 366) -> np.ndarray:
    d = np.abs(np.asarray(a)[:, None] - np.asarray(b)[None, :]) % period
    return np.minimum(d, period - d)


def build_table(series: pd.Series) -> pd.DataFrame:
    """Climatology rows for a daily series (index: UTC days; NaN values ignored)."""
    s = series.dropna()
    idx = pd.DatetimeIndex(pd.to_datetime(s.index, utc=True))
    values = s.to_numpy(float)
    if len(values) == 0:
        return pd.DataFrame(columns=CLIM_COLUMNS)
    doy = idx.dayofyear.to_numpy()
    sy = season_year(idx)
    targets = np.arange(1, 367)
    near = circular_doy_distance(doy, targets) <= HALF_WINDOW_D          # (n_days, 366)
    seasons = sorted(set(sy.tolist()))
    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for s_out in [ALL_SEASONS, *seasons]:
            keep = sy != s_out
            for j, k in enumerate(targets):
                v = values[keep & near[:, j]]
                n = int(v.size)
                if n:
                    p10, p50, p90 = np.percentile(v, [10, 50, 90])
                    rows.append((s_out, int(k), float(v.mean()), float(v.std(ddof=1)) if n > 1 else np.nan,
                                 float(p10), float(p50), float(p90), n))
                else:
                    rows.append((s_out, int(k), np.nan, np.nan, np.nan, np.nan, np.nan, 0))
    return pd.DataFrame(rows, columns=CLIM_COLUMNS)


def expected(clim: pd.DataFrame, days: Iterable) -> pd.DataFrame:
    """Per day: the climatology mean, sd and n with that day's season left out (ALL_SEASONS if unknown)."""
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(list(days)), utc=True))
    if len(idx) == 0 or clim.empty:
        return pd.DataFrame({"mean": [], "sd": [], "n": []})
    known = set(clim["season_out"].unique()) - {ALL_SEASONS}
    keys = pd.DataFrame({"season_out": [s if s in known else ALL_SEASONS for s in season_year(idx)], "doy": idx.dayofyear})
    m = keys.merge(clim, on=["season_out", "doy"], how="left")
    return m[["mean", "sd", "n"]].reset_index(drop=True)


def zscores(clim: pd.DataFrame, days: Iterable, values) -> np.ndarray:
    """z-anomalies of daily values against the climatology; NaN where the baseline is thin (n < MIN_N) or flat."""
    v = np.asarray(list(values), dtype=float)
    if v.size == 0:
        return np.array([], dtype=float)
    e = expected(clim, days)
    if e.empty:
        return np.full(v.shape, np.nan)
    with np.errstate(all="ignore"):
        z = (v - e["mean"].to_numpy(float)) / e["sd"].to_numpy(float)
    bad = (e["n"].fillna(0).to_numpy() < MIN_N) | ~np.isfinite(z) | (e["sd"].to_numpy(float) == 0)
    z[bad] = np.nan
    return z
