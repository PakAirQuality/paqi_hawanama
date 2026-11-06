"""satellite_climatology: the leave-one-season-out day-of-year table and the z-scores."""

import numpy as np
import pandas as pd

from app.services import satellite_climatology as sc


def _series(years, value_of):
    days = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31", freq="D", tz="UTC")
    return pd.Series([value_of(d) for d in days], index=days)


def test_seasons_run_july_to_june_and_doy_distance_wraps():
    t = pd.to_datetime(["2022-06-30", "2022-07-01", "2023-01-15"], utc=True)
    assert sc.season_year(t).tolist() == [2021, 2022, 2022]
    assert sc.circular_doy_distance([1], [366]).tolist() == [[1]]
    assert sc.circular_doy_distance([10], [20, 5]).tolist() == [[10, 5]]


def test_table_statistics_leave_the_target_season_out():
    # value = year - 2019 on every day: 2020 -> 1, 2021 -> 2, 2022 -> 3; seasons 2019..2022 (Jan–Jun 2020 is season 2019)
    s = _series([2020, 2021, 2022], lambda d: float(d.year - 2019))
    table = sc.build_table(s)
    assert list(table.columns) == sc.CLIM_COLUMNS
    assert sorted(table["season_out"].unique()) == [sc.ALL_SEASONS, 2019, 2020, 2021, 2022]
    assert (table.groupby("season_out").size() == 366).all()
    # doy 60 (1 March): all seasons -> mean of 1,2,3 over 31-day windows = 2.0
    all_row = table[(table["season_out"] == sc.ALL_SEASONS) & (table["doy"] == 60)].iloc[0]
    assert abs(all_row["mean"] - 2.0) < 1e-9 and all_row["n"] == 3 * 31
    # with season 2021 left out (Jul 2021–Jun 2022), 1 March 2022 is gone: mean of 2020 (1) and 2021 (2) = 1.5
    row = table[(table["season_out"] == 2021) & (table["doy"] == 60)].iloc[0]
    assert abs(row["mean"] - 1.5) < 1e-9 and row["n"] == 2 * 31
    assert abs(row["sd"] - np.std([1] * 31 + [2] * 31, ddof=1)) < 1e-9


def test_zscores_use_the_right_season_and_mask_thin_or_flat_baselines():
    s = _series([2020, 2021, 2022], lambda d: float(d.year - 2019))
    table = sc.build_table(s)
    z = sc.zscores(table, ["2022-03-01"], [3.0])          # season 2021 left out: baseline mean 1.5
    row = table[(table["season_out"] == 2021) & (table["doy"] == 60)].iloc[0]
    assert abs(z[0] - (3.0 - 1.5) / row["sd"]) < 1e-9
    # a date outside the known seasons scores against ALL_SEASONS
    z2 = sc.zscores(table, ["2026-03-01"], [2.0])
    all_row = table[(table["season_out"] == sc.ALL_SEASONS) & (table["doy"] == 60)].iloc[0]
    assert abs(z2[0] - (2.0 - all_row["mean"]) / all_row["sd"]) < 1e-9
    # flat baseline -> NaN; thin baseline (n < MIN_N) -> NaN
    flat = sc.build_table(_series([2020, 2021], lambda d: 5.0))
    assert np.isnan(sc.zscores(flat, ["2021-03-01"], [6.0])[0])
    thin = sc.build_table(pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2020-03-01", "2021-03-01", "2022-03-01"], utc=True)))
    assert np.isnan(sc.zscores(thin, ["2023-03-01"], [2.0])[0])
    assert sc.zscores(table, [], []).size == 0
    e = sc.expected(table, ["2022-03-01"])
    assert abs(float(e["mean"][0]) - 1.5) < 1e-9
