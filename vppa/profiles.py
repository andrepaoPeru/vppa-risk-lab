"""
Phase 2: hypothetical 200 MW solar and 200 MW wind generation profiles.

PROXY, NOT A REAL PROJECT. We take ERCOT's system-wide solar and wind
output and scale it down to a 200 MW project:

    capacity factor (hour) = ERCOT-wide output (MW) / ERCOT installed capacity (MW)
    project output (hour)  = capacity factor x 200 MW

Dividing by installed capacity first matters: ERCOT solar capacity more
than doubled from 2022 to 2025. Without that step, 2023 would look like
a very cloudy year when really there were just fewer panels.
"""
import numpy as np
import pandas as pd

from vppa import config

# ERCOT installed (operational) capacity in MW at each year end.
# Source: ERCOT "Capacity Changes by Fuel Type Charts" (September 2026
# edition), column "Cumulative MW Operational", Wind Chart / Solar Chart
# sheets. Listed under https://www.ercot.com/gridinfo/resource
INSTALLED_MW_YEAR_END = {
    "solar": {2022: 14818.22, 2023: 22153.33, 2024: 29344.07, 2025: 37442.74},
    "wind":  {2022: 36947.92, 2023: 38730.81, 2024: 39491.03, 2025: 40738.65},
}


def installed_capacity(index: pd.DatetimeIndex, fuel: str) -> pd.Series:
    """
    ERCOT installed capacity (MW) for every hour in `index`.

    We only know capacity at each year end, so we draw a straight line
    between year ends (linear interpolation). New plants actually come
    online in steps, so this is an approximation.
    """
    year_end = INSTALLED_MW_YEAR_END[fuel]
    known_times = [pd.Timestamp(f"{y}-12-31 23:00", tz=config.TIMEZONE) for y in year_end]
    known_mw = list(year_end.values())

    # np.interp needs plain numbers, so convert timestamps to nanoseconds.
    x = index.asi8
    xp = pd.DatetimeIndex(known_times).asi8
    return pd.Series(np.interp(x, xp, known_mw), index=index, name=f"{fuel}_capacity_mw")


def capacity_factor(output_mw: pd.Series, capacity_mw: pd.Series) -> pd.Series:
    """
    Share of nameplate capacity actually produced in each hour (0 to 1).

    Clipped to [0, 1]: rounding and timing quirks in the data can push the
    ratio a hair outside that range, which is physically impossible.
    """
    return (output_mw / capacity_mw).clip(lower=0.0, upper=1.0)


def build_profiles(system_gen: pd.DataFrame,
                   solar_mw: float = config.SOLAR_MW,
                   wind_mw: float = config.WIND_MW) -> pd.DataFrame:
    """
    Hourly output (MW, which equals MWh per hour) of the two proxy projects.

    Input: hourly ERCOT-wide output with columns solar_mw, wind_mw
    (from vppa.data.load_system_generation).
    """
    idx = system_gen.index
    solar_cf = capacity_factor(system_gen["solar_mw"], installed_capacity(idx, "solar"))
    wind_cf = capacity_factor(system_gen["wind_mw"], installed_capacity(idx, "wind"))
    return pd.DataFrame({"solar_mw": solar_cf * solar_mw,
                         "wind_mw": wind_cf * wind_mw}, index=idx)


def summarize(profiles: pd.DataFrame,
              nameplate: dict | None = None) -> pd.DataFrame:
    """Annual energy (MWh) and capacity factor for each project."""
    nameplate = nameplate or {"solar_mw": config.SOLAR_MW, "wind_mw": config.WIND_MW}
    by_year = profiles.groupby(profiles.index.year)
    energy = by_year.sum()                      # MW summed over hours = MWh
    hours = by_year.size()
    rows = {}
    for col, mw in nameplate.items():
        name = col.replace("_mw", "")
        rows[f"{name}_mwh"] = energy[col]
        rows[f"{name}_cf"] = energy[col] / (mw * hours)
    out = pd.DataFrame(rows)
    out.index.name = "year"
    return out
