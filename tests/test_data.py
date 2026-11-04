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
