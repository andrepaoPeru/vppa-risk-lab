"""Monte Carlo mechanics checked on tiny, fully predictable inputs."""
import numpy as np
import pandas as pd
import pytest

from vppa import montecarlo as mc


def _year_of_days(price_fn, gen_fn, year=2023):
    """Hourly price and generation for one non-leap year, constant within each day."""
    t = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h",
                      tz="US/Central", inclusive="left")
    day_num = t.dayofyear.to_numpy()
    price = pd.Series([price_fn(d) for d in day_num], t)
    gen = pd.DataFrame({"wind_mw": [gen_fn(d) for d in day_num]}, t)
    return price, gen


def test_daily_table_sums_hours_and_drops_dst_days():
    price, gen = _year_of_days(lambda d: 45.0, lambda d: 10.0)
    daily = mc.daily_table(price, gen, strike=35, load_mw=100)
    assert len(daily) == 365 - 2                      # March and November clock changes
    assert daily["wind_settlement"].iloc[0] == (45 - 35) * 10 * 24
    assert daily["wind_matched"].iloc[0] == 10 * 24


def test_identical_days_give_identical_years():
    # Every day is the same, so every simulated year must be 365 x that day.
    price, gen = _year_of_days(lambda d: 45.0, lambda d: 10.0)
    sims = mc.simulate_years(mc.daily_table(price, gen, strike=35), n_years=50)
    assert np.allclose(sims["annual"]["wind_settlement"], 365 * 2400.0)


def test_price_and_generation_stay_paired():
    # Odd days: windy and cheap (price 0, 10 MW). Even days: calm and pricey (100, 0 MW).
    # Paired draws can only ever settle at (0-35)*10*24 = -8,400 or 0 per day,
    # so a year is always a multiple of -8,400 and never positive.
    price, gen = _year_of_days(lambda d: 0.0 if d % 2 else 100.0,
                               lambda d: 10.0 if d % 2 else 0.0)
    annual = mc.simulate_years(mc.daily_table(price, gen, strike=35), n_years=200)["annual"]
    s = annual["wind_settlement"]
    assert (s <= 0).all()
    assert np.allclose(s % 8400, 0)


def test_same_seed_same_answer():
    price, gen = _year_of_days(lambda d: float(d % 7) * 10, lambda d: float(d % 5))
    daily = mc.daily_table(price, gen, strike=35)
    a = mc.simulate_years(daily, n_years=100, seed=7)["annual"]
    b = mc.simulate_years(daily, n_years=100, seed=7)["annual"]
    pd.testing.assert_frame_equal(a, b)


def test_risk_metrics_on_known_numbers():
    years = np.arange(1, 101, dtype=float)            # 1, 2, ..., 100
    m = mc.risk_metrics(years, monthly_settlement=years)
    assert m["expected_value"] == 50.5
    assert m["p5_annual"] == pytest.approx(5.95)       # numpy's linear interpolation
    assert m["cfar_95"] == pytest.approx(50.5 - 5.95)
    assert m["expected_shortfall"] == pytest.approx(3.0)   # mean of 1..5
    assert m["prob_net_payment"] == 0.0
    assert m["var_95_1m"] == pytest.approx(50.5 - 5.95)


def test_each_simulated_month_comes_from_a_single_historical_year():
    # 2023 days settle at +240/day, 2024 days at -240/day (constant within a year).
    # If months mixed years, a 31-day month could total anything in between;
    # with the regime step it must be exactly +/- 31 x 240.
    p23, g23 = _year_of_days(lambda d: 36.0, lambda d: 10.0, year=2023)
    p24, g24 = _year_of_days(lambda d: 34.0, lambda d: 10.0, year=2024)
    daily = mc.daily_table(pd.concat([p23, p24]), pd.concat([g23, g24]), strike=35)
    monthly = mc.simulate_years(daily, n_years=200)["monthly"]
    jan = monthly.loc[monthly["month"] == 1, "wind_settlement"]
    assert set(np.round(jan, 6)) <= {31 * 240.0, -31 * 240.0}
    assert len(set(np.round(jan, 6))) == 2       # both regimes do get drawn
