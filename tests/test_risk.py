"""Risk math checked against small hand-calculated examples."""
import pandas as pd
import pytest

from vppa import risk


def _hours(n, start="2024-06-01"):
    return pd.date_range(start, periods=n, freq="h", tz="US/Central")


# --- price risk -------------------------------------------------------------
def test_price_shift_moves_settlement_by_shift_times_mwh():
    t = _hours(2)
    price, gen = pd.Series([30.0, 40.0], t), pd.Series([10.0, 20.0], t)
    sens = risk.price_sensitivity(price, gen, strike=35, shifts=[0, 10])
    # base: (30-35)*10 + (40-35)*20 = 50; +$10 on 30 MWh adds 300
    assert sens.loc[0, "annual_settlement"] == 50.0
    assert sens.loc[10, "annual_settlement"] == 350.0
    assert sens.loc[0, "dollars_per_1_shift"] == 30.0


def test_breakeven_shift_is_strike_minus_capture_price():
    t = _hours(2)
    price, gen = pd.Series([20.0, 60.0], t), pd.Series([10.0, 30.0], t)
    # capture price = (20*10 + 60*30) / 40 = 50, strike 35 -> prices could fall $15
    assert risk.breakeven_price_shift(price, gen, strike=35) == pytest.approx(-15.0)


def test_tail_concentration_splits_top_hours():
    t = _hours(4)
    price = pd.Series([10.0, 20.0, 30.0, 1000.0], t)
    gen = pd.Series([1.0, 1.0, 1.0, 1.0], t)
    tail = risk.tail_concentration(price, gen, strike=35, top_share=0.25)
    assert tail["hours"] == 1
    assert tail["settlement_in_top_hours"] == 965.0
    assert tail["settlement_in_other_hours"] == -45.0
