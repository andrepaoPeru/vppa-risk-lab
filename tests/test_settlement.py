"""Settlement math checked against small hand-calculated examples."""
import pandas as pd
import pytest

from vppa.settlement import negative_price_summary, settle_hourly, summarize_settlement


def _hours(n, start="2024-06-01"):
    return pd.date_range(start, periods=n, freq="h", tz="US/Central")


def test_project_pays_buyer_when_price_above_strike():
    t = _hours(1)
    s = settle_hourly(pd.Series([50.0], t), pd.Series([10.0], t), strike=35)
    assert s["settlement"].iloc[0] == 150.0           # (50 - 35) x 10 MWh


def test_buyer_pays_project_when_price_below_strike():
    t = _hours(1)
    s = settle_hourly(pd.Series([20.0], t), pd.Series([10.0], t), strike=35)
    assert s["settlement"].iloc[0] == -150.0          # (20 - 35) x 10 MWh


def test_negative_price_costs_more_than_the_strike():
    t = _hours(1)
    s = settle_hourly(pd.Series([-10.0], t), pd.Series([5.0], t), strike=35)
    assert s["settlement"].iloc[0] == -225.0          # (-10 - 35) x 5 MWh


def test_zero_generation_means_zero_settlement_even_at_extreme_prices():
    t = _hours(1)
    s = settle_hourly(pd.Series([5000.0], t), pd.Series([0.0], t), strike=35)
    assert s["settlement"].iloc[0] == 0.0


def test_missing_hours_are_dropped_not_zero_filled():
    s = settle_hourly(pd.Series([50.0, 60.0], _hours(2)),
                      pd.Series([10.0], _hours(1)), strike=35)
    assert len(s) == 1


def test_capture_price_is_generation_weighted():
    # 10 MWh at $20 and 30 MWh at $60: simple average $40, capture price $50
    t = _hours(2)
    hourly = settle_hourly(pd.Series([20.0, 60.0], t), pd.Series([10.0, 30.0], t), strike=35)
    y = summarize_settlement(hourly, "YS").iloc[0]
    assert y["hub_avg_price"] == 40.0
    assert y["capture_price"] == 50.0
    assert y["mwh"] == 40.0
    assert y["settlement"] == pytest.approx((20 - 35) * 10 + (60 - 35) * 30)


def test_negative_price_summary_counts_and_costs():
    t = _hours(3)
    hourly = settle_hourly(pd.Series([-5.0, -1.0, 40.0], t),
                           pd.Series([10.0, 0.0, 10.0], t), strike=35)
    n = negative_price_summary(hourly).loc[2024]
    assert n["negative_hours"] == 2                   # hours count even with zero output
    assert n["mwh_in_negative_hours"] == 10.0
    assert n["settlement_in_negative_hours"] == -400.0  # (-5 - 35) x 10
    assert n["share_of_mwh"] == 0.5
