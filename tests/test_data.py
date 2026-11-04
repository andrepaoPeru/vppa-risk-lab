"""Offline tests for the data-cleaning logic (no internet needed)."""
import pandas as pd

from vppa.data import to_hourly


def _fifteen_min_frame(start, end, price_fn):
    """Build a fake ERCOT-style 15-minute price table."""
    times = pd.date_range(start, end, freq="15min", tz="US/Central", inclusive="left")
    return pd.DataFrame({"Interval Start": times,
                         "SPP": [price_fn(i) for i in range(len(times))]})


def test_four_intervals_average_to_one_hour():
    # Prices 10, 20, 30, 40 in the first hour -> hourly average 25
    df = _fifteen_min_frame("2024-07-01 00:00", "2024-07-01 02:00",
                            lambda i: [10, 20, 30, 40][i % 4])
    hourly = to_hourly(df)
    assert len(hourly) == 2
    assert hourly.iloc[0] == 25.0


def test_daylight_saving_fall_back_day_has_25_hours():
    # 3 Nov 2024: clocks go back, so the 1 AM hour happens twice.
    df = _fifteen_min_frame("2024-11-03 00:00", "2024-11-04 00:00", lambda i: 1.0)
    assert len(to_hourly(df)) == 25


def test_spring_forward_day_has_23_hours():
    # 10 Mar 2024: clocks jump ahead, the 2 AM hour does not exist.
    df = _fifteen_min_frame("2024-03-10 00:00", "2024-03-11 00:00", lambda i: 1.0)
    assert len(to_hourly(df)) == 23


# ---------------------------------------------------------------------------
# Fuel-mix parser
# ---------------------------------------------------------------------------
from vppa.data import parse_fuel_mix


def _labels():
    """ERCOT's interval-ending column labels: 0:15 ... 23:45, 0:00."""
    labels = [f"{m // 60}:{m % 60:02d}" for m in range(15, 24 * 60, 15)]
    return labels + ["0:00"]


def _fuel_mix_day(date, solar_mwh, wind_mwh):
    """One fake day of ERCOT fuel-mix data with constant 15-min MWh."""
    cols = {lab: [solar_mwh, wind_mwh, 999.0] for lab in _labels()}
    return pd.DataFrame({"Date": [pd.Timestamp(date)] * 3,
                         "Fuel": ["Solar", "Wind", "Coal"], **cols})


def test_fuel_mix_sums_four_intervals_to_hourly_mw():
    # 250 MWh every 15 minutes = 1,000 MWh per hour = 1,000 MW average.
    hourly = parse_fuel_mix(_fuel_mix_day("2024-07-01", 250.0, 100.0))
    assert len(hourly) == 24
    assert list(hourly.columns) == ["solar_mw", "wind_mw"]   # coal dropped
    assert (hourly["solar_mw"] == 1000.0).all()
    assert (hourly["wind_mw"] == 400.0).all()
    # "0:15" is the interval that STARTS at midnight.
    assert hourly.index[0] == pd.Timestamp("2024-07-01 00:00", tz="US/Central")


def test_fuel_mix_fall_back_day_uses_dst_columns():
    day = _fuel_mix_day("2024-11-03", 10.0, 10.0)
    for lab in ["01:15 (DST)", "01:30 (DST)", "01:45 (DST)", "02:00 (DST)"]:
        day[lab] = 10.0
    hourly = parse_fuel_mix(day)
    assert len(hourly) == 25
    assert (hourly["solar_mw"] == 40.0).all()


def test_fuel_mix_spring_forward_day_skips_missing_hour():
    day = _fuel_mix_day("2024-03-10", 10.0, 10.0)
    for lab in ["2:15", "2:30", "2:45", "3:00"]:
        day[lab] = float("nan")            # ERCOT leaves the 2 AM hour blank
    assert len(parse_fuel_mix(day)) == 23
