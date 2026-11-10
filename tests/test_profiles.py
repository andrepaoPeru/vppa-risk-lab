"""Tests for the proxy generation profiles (no internet needed)."""
import pandas as pd
import pytest

from vppa.profiles import (INSTALLED_MW_YEAR_END, build_profiles,
                           capacity_factor, installed_capacity, summarize)


def test_capacity_matches_known_year_end_value():
    t = pd.DatetimeIndex([pd.Timestamp("2023-12-31 23:00", tz="US/Central")])
    assert installed_capacity(t, "solar").iloc[0] == pytest.approx(
        INSTALLED_MW_YEAR_END["solar"][2023])


def test_capacity_is_halfway_at_midyear():
    # Linear interpolation: about halfway between the two year-end values.
    t = pd.DatetimeIndex([pd.Timestamp("2024-07-01 23:00", tz="US/Central")])
    lo, hi = INSTALLED_MW_YEAR_END["wind"][2023], INSTALLED_MW_YEAR_END["wind"][2024]
    assert installed_capacity(t, "wind").iloc[0] == pytest.approx((lo + hi) / 2, rel=1e-3)


def test_capacity_factor_is_clipped_to_0_1():
    cf = capacity_factor(pd.Series([-5.0, 50.0, 150.0]), pd.Series([100.0] * 3))
    assert cf.tolist() == [0.0, 0.5, 1.0]


def test_profile_is_capacity_factor_times_nameplate():
    t = pd.DatetimeIndex([pd.Timestamp("2023-12-31 23:00", tz="US/Central")])
    cap = INSTALLED_MW_YEAR_END
    # System running at exactly 25% (solar) and 40% (wind) of installed capacity
    gen = pd.DataFrame({"solar_mw": [0.25 * cap["solar"][2023]],
                        "wind_mw": [0.40 * cap["wind"][2023]]}, index=t)
    prof = build_profiles(gen, solar_mw=200, wind_mw=200)
    assert prof["solar_mw"].iloc[0] == pytest.approx(50.0)
    assert prof["wind_mw"].iloc[0] == pytest.approx(80.0)


def test_summary_energy_and_capacity_factor():
    # 100 MW flat for 10 hours from a 200 MW project -> 1,000 MWh, 50% CF
    t = pd.date_range("2024-01-01", periods=10, freq="h", tz="US/Central")
    prof = pd.DataFrame({"solar_mw": 100.0, "wind_mw": 50.0}, index=t)
    s = summarize(prof, nameplate={"solar_mw": 200, "wind_mw": 200})
    assert s.loc[2024, "solar_mwh"] == 1000.0
    assert s.loc[2024, "solar_cf"] == pytest.approx(0.5)
    assert s.loc[2024, "wind_cf"] == pytest.approx(0.25)
