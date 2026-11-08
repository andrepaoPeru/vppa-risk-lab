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


# --- shape risk -------------------------------------------------------------
def test_hourly_match_cannot_shift_excess_between_hours():
    # 4 hours, 100 MW load. Output 200, 200, 0, 0 -> annual volume 100%,
    # but only the first two hours are covered -> hourly match 50%.
    t = _hours(4)
    m = risk.hourly_match(pd.Series([200.0, 200.0, 0.0, 0.0], t), load_mw=100).loc[2024]
    assert m["annual_volume_match"] == 1.0
    assert m["hourly_match"] == 0.5
    assert m["hours_fully_covered"] == 0.5
    assert m["excess_share"] == 0.5          # 200 of the 400 MWh exceeded load


def test_flat_output_equal_to_load_is_a_perfect_match():
    t = _hours(24)
    m = risk.hourly_match(pd.Series(100.0, t), load_mw=100).loc[2024]
    assert m["hourly_match"] == 1.0 and m["excess_share"] == 0.0


def test_shape_cost_is_zero_for_flat_output_and_positive_for_cheap_hours():
    t = _hours(2)
    price = pd.Series([10.0, 50.0], t)                      # hub average $30
    flat = risk.shape_cost(price, pd.Series([5.0, 5.0], t)).loc[2024]
    cheap = risk.shape_cost(price, pd.Series([10.0, 0.0], t)).loc[2024]
    assert flat["shape_cost"] == 0.0
    assert cheap["capture_price"] == 10.0
    assert cheap["shape_cost"] == 200.0                     # ($30 - $10) x 10 MWh


# --- volume risk ------------------------------------------------------------
def _two_januaries(mw_2023, mw_2024):
    """Flat output for all of Jan 2023 and Jan 2024."""
    t23 = pd.date_range("2023-01-01", "2023-02-01", freq="h", tz="US/Central", inclusive="left")
    t24 = pd.date_range("2024-01-01", "2024-02-01", freq="h", tz="US/Central", inclusive="left")
    return pd.concat([pd.Series(mw_2023, t23), pd.Series(mw_2024, t24)])


def test_low_resource_scales_each_month_to_worst_observed():
    gen = _two_januaries(80.0, 60.0)                 # CF 40% and 30% on 200 MW
    low = risk.low_resource_profile(gen, nameplate_mw=200)
    # pytest.approx allows for tiny floating-point rounding (60.0000000001)
    assert low[low.index.year == 2023].tolist() == pytest.approx([60.0] * 744)  # 80 x (30/40)
    assert low[low.index.year == 2024].tolist() == pytest.approx([60.0] * 744)  # already the worst


def test_low_resource_never_increases_output():
    gen = _two_januaries(80.0, 60.0)
    assert (risk.low_resource_profile(gen, 200) <= gen).all()


def test_volume_scenarios_report_lower_energy_in_low_case():
    gen = _two_januaries(80.0, 60.0)
    price = pd.Series(50.0, gen.index)
    v = risk.volume_scenarios(price, gen, nameplate_mw=200, strike=35, load_mw=100)
    assert v.loc["low_resource", "annual_mwh"] < v.loc["base", "annual_mwh"]
    # Price is always $15 above strike, so less energy = smaller payment to buyer
    assert v.loc["low_resource", "annual_settlement"] < v.loc["base", "annual_settlement"]


# --- hedge effectiveness ----------------------------------------------------
def test_flat_generation_equal_to_load_is_a_perfect_hedge():
    # If the project makes exactly the load every hour, the buyer's net cost
    # is load x strike no matter what the price does.
    annual = pd.DataFrame({
        "load_cost": [100 * 20.0, 100 * 50.0, 100 * 80.0],             # prices 20, 50, 80
        "flat_settlement": [100 * (20 - 35.0), 100 * (50 - 35.0), 100 * (80 - 35.0)],
    })
    h = risk.hedge_effectiveness(annual)
    assert risk.net_costs(annual)["flat"].tolist() == [3500.0, 3500.0, 3500.0]
    assert h.loc["flat", "std_reduction"] == pytest.approx(1.0)
    assert h.loc["flat", "hedge_premium"] == pytest.approx(3500.0 - 5000.0)
    assert h.loc["no_vppa", "std_reduction"] == 0.0


def test_payout_lowers_net_cost():
    annual = pd.DataFrame({"load_cost": [1000.0], "x_settlement": [300.0]})
    assert risk.net_costs(annual).loc[0, "x"] == 700.0


def test_annual_costs_matches_hand_calculation():
    t = _hours(2)
    price = pd.Series([10.0, 50.0], t)
    gen = pd.DataFrame({"wind_mw": [100.0, 0.0]}, t)
    a = risk.annual_costs(price, gen, strike=35, load_mw=100).loc[2024]
    assert a["load_cost"] == 100 * 10 + 100 * 50
    assert a["wind_settlement"] == (10 - 35) * 100
