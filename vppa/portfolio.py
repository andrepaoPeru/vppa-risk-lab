"""
Phase 6: which generation portfolio best serves a 24/7 data center?

Four hypothetical options, each built from the proxy profiles:
  solar          solar only
  wind           wind only
  blend          half solar, half wind (by MW)
  solar_battery  solar + a battery half its MW size, 4 hours long
                 (200 MW solar -> 100 MW / 400 MWh battery)

Two fair ways to size them:
  equal nameplate     200 MW of generation each
  equal annual energy each sized to produce 100% of the data center's
                      yearly use - the usual "100% renewable" claim.
Each option then runs through the same backtest and Monte Carlo.
"""
import numpy as np
import pandas as pd

from vppa import config


def add_battery(solar_mw: pd.Series,
                load_mw: float = config.LOAD_MW,
                power_mw: float = config.BATTERY_MW,
                energy_mwh: float = config.BATTERY_MWH,
                efficiency: float = config.BATTERY_EFFICIENCY) -> pd.DataFrame:
    """
    Simple rule-based battery that shifts surplus solar to later hours.

    Each hour, in time order:
      - if solar > load: charge with the surplus (limited by power rating
        and free space). Only (efficiency x charged MWh) is stored.
      - if solar < load: discharge to fill the gap (limited by power
        rating and what is stored).
    The battery never charges from the grid, so all delivered energy is
    still solar. It does NOT look at prices: it is built for hourly
    matching, not for trading. Starts empty.

    Returns hourly delivered output plus charge, discharge and state of charge.
    """
    solar = solar_mw.to_numpy()
    n = len(solar)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    soc = np.zeros(n)          # MWh stored at the END of each hour
    stored = 0.0
    for i in range(n):         # a loop, because each hour depends on the one before
        surplus = solar[i] - load_mw
        if surplus > 0:
            room = (energy_mwh - stored) / efficiency     # grid-side MWh that fit
            charge[i] = min(surplus, power_mw, room)
            stored += charge[i] * efficiency
        else:
            discharge[i] = min(-surplus, power_mw, stored)
            stored -= discharge[i]
        soc[i] = stored
    delivered = solar - charge + discharge
    return pd.DataFrame({"delivered_mw": delivered, "charge_mw": charge,
                         "discharge_mw": discharge, "soc_mwh": soc},
                        index=solar_mw.index)


OPTIONS = ["solar", "wind", "blend", "solar_battery"]
HOURS_PER_YEAR = 8760


def make_option(kind: str, size_mw: float, profiles: pd.DataFrame,
                load_mw: float = config.LOAD_MW) -> pd.Series:
    """
    Hourly output (MW) of one option with `size_mw` of generation.

    Built from per-MW capacity factors of the 200 MW proxy profiles, so
    any size can be made. For solar_battery the battery scales with the
    solar farm, keeping the config ratio (100 MW / 400 MWh per 200 MW).
    """
    solar_cf = profiles["solar_mw"] / config.SOLAR_MW
    wind_cf = profiles["wind_mw"] / config.WIND_MW
    if kind == "solar":
        return solar_cf * size_mw
    if kind == "wind":
        return wind_cf * size_mw
    if kind == "blend":                                   # half solar, half wind
        return (0.5 * solar_cf + 0.5 * wind_cf) * size_mw
    if kind == "solar_battery":
        ratio = size_mw / config.SOLAR_MW
        return add_battery(solar_cf * size_mw, load_mw,
                           power_mw=config.BATTERY_MW * ratio,
                           energy_mwh=config.BATTERY_MWH * ratio)["delivered_mw"]
    raise ValueError(f"Unknown option: {kind}")


def build_portfolios(profiles: pd.DataFrame, sizes: dict | None = None,
                     load_mw: float = config.LOAD_MW) -> pd.DataFrame:
    """
    Hourly output of every option, one column each (solar_mw, wind_mw, ...).
    Default sizes: 200 MW of generation each (equal nameplate).
    """
    sizes = sizes or {k: 200.0 for k in OPTIONS}
    return pd.DataFrame({f"{k}_mw": make_option(k, sizes[k], profiles, load_mw)
                         for k in OPTIONS})


def size_for_annual_match(profiles: pd.DataFrame, share: float = 1.0,
                          load_mw: float = config.LOAD_MW) -> dict:
    """
    Generation MW each option needs so that, on average, its annual energy
    equals `share` x the data center's annual use (1.0 = "100% renewable"
    on an annual basis, the usual corporate procurement target).

    Output is proportional to size for solar, wind and blend, so one
    division is enough. The battery's losses depend on size, so for
    solar_battery we repeat the division a few times until it settles.
    """
    target = share * load_mw * HOURS_PER_YEAR
    n_years = profiles.index.year.nunique()
    sizes = {}
    for kind in OPTIONS:
        size = 200.0
        for _ in range(5):
            annual = make_option(kind, size, profiles, load_mw).sum() / n_years
            size *= target / annual
        sizes[kind] = size
    return sizes


def compare(price: pd.Series, portfolios: pd.DataFrame,
            mc_summary: pd.DataFrame) -> pd.DataFrame:
    """
    One table with the numbers the buyer cares about, per option.

    capture_price: generation-weighted average hub price over 2023-2025.
                   It is also the strike at which the expected settlement
                   would have been zero (the "breakeven strike").
    """
    df = portfolios.join(price.rename("price"), how="inner")
    rows = {}
    for col in portfolios.columns:
        name = col.replace("_mw", "")
        mwh = df[col].sum()
        rows[name] = {
            "expected_value_per_mwh": mc_summary.loc[name, "expected_value"] / mc_summary.loc[name, "annual_mwh"],
            "expected_value": mc_summary.loc[name, "expected_value"],
            "cfar_95": mc_summary.loc[name, "cfar_95"],
            "p5_annual": mc_summary.loc[name, "p5_annual"],
            "prob_net_payment": mc_summary.loc[name, "prob_net_payment"],
            "annual_mwh": mc_summary.loc[name, "annual_mwh"],
            "hourly_match": mc_summary.loc[name, "hourly_match"],
            "capture_price": (df[col] * df["price"]).sum() / mwh,
        }
    return pd.DataFrame(rows).T
