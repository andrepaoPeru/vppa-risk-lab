"""
Phase 4: risk decomposition. One function (plus one chart in plots.py)
for each risk the VPPA buyer carries:

    price risk  - the market price level moves
    shape risk  - generation does not line up hour by hour with the load
    basis risk  - the project's local price differs from the hub price
    volume risk - the project produces more or less energy than expected

All settlement figures use the buyer's view from settlement.py:
positive = project pays buyer, negative = buyer pays project.
"""
import numpy as np
import pandas as pd

from vppa import config
from vppa.settlement import settle_hourly


def _n_years(index: pd.DatetimeIndex) -> int:
    return index.year.nunique()


# ---------------------------------------------------------------------------
# 1. PRICE RISK
# ---------------------------------------------------------------------------
def price_sensitivity(price: pd.Series, generation_mw: pd.Series,
                      strike: float = config.STRIKE,
                      shifts=range(-20, 21, 5)) -> pd.DataFrame:
    """
    Average annual settlement if every hourly price were $X/MWh higher or lower.

    Because settlement = (price - strike) x MWh, adding $X to every price
    adds exactly $X x (annual MWh) to annual settlement. So the buyer is
    "long" its contract volume: price risk per $1/MWh = annual MWh.
    """
    years = _n_years(price.index)
    rows = []
    for shift in shifts:
        hourly = settle_hourly(price + shift, generation_mw, strike)
        rows.append({"price_shift": shift,
                     "annual_settlement": hourly["settlement"].sum() / years})
    out = pd.DataFrame(rows).set_index("price_shift")
    out["dollars_per_1_shift"] = generation_mw.sum() / years   # the slope
    return out


def breakeven_price_shift(price: pd.Series, generation_mw: pd.Series,
                          strike: float = config.STRIKE) -> float:
    """
    How far ($/MWh) all prices would have to move for the contract to net
    to zero over the period. Equivalently: strike minus capture price.
    """
    hourly = settle_hourly(price, generation_mw, strike)
    return -hourly["settlement"].sum() / hourly["mwh"].sum()


def tail_concentration(price: pd.Series, generation_mw: pd.Series,
                       strike: float = config.STRIKE,
                       top_share: float = 0.01) -> dict:
    """
    How much of the total settlement came from the top 1% highest-price hours.
    A big number means price risk lives in rare scarcity events, which a
    simple "average price" view will miss.
    """
    hourly = settle_hourly(price, generation_mw, strike)
    cutoff = hourly["price"].quantile(1 - top_share)
    top = hourly["price"] >= cutoff
    return {"price_cutoff": cutoff,
            "hours": int(top.sum()),
            "settlement_in_top_hours": hourly.loc[top, "settlement"].sum(),
            "settlement_in_other_hours": hourly.loc[~top, "settlement"].sum()}


# ---------------------------------------------------------------------------
# 2. SHAPE RISK
# ---------------------------------------------------------------------------
def hourly_match(generation_mw: pd.Series,
                 load_mw: float = config.LOAD_MW) -> pd.DataFrame:
    """
    How well the project's output lines up with a flat 24/7 load, per year.

    annual_volume_match : total MWh generated / total MWh consumed.
                          100% is what "100% renewable" usually means
                          today (annual matching).
    hourly_match        : MWh of load actually covered hour by hour /
                          total load. Output above the load in one hour
                          cannot cover a shortfall in another hour.
                          This is the 24/7 carbon-free energy view.
    hours_fully_covered : share of hours where output >= load.
    excess_share        : share of generated MWh that exceeded the load
                          in its hour (sold back to the grid, not "used").
    """
    load = pd.Series(load_mw, index=generation_mw.index)
    matched = np.minimum(generation_mw, load)
    excess = (generation_mw - load).clip(lower=0)
    by_year = generation_mw.index.year
    out = pd.DataFrame({
        "annual_volume_match": generation_mw.groupby(by_year).sum() / load.groupby(by_year).sum(),
        "hourly_match": matched.groupby(by_year).sum() / load.groupby(by_year).sum(),
        "hours_fully_covered": (generation_mw >= load).groupby(by_year).mean(),
        "excess_share": excess.groupby(by_year).sum() / generation_mw.groupby(by_year).sum(),
    })
    out.index.name = "year"
    return out


def match_by_month_hour(generation_mw: pd.Series,
                        load_mw: float = config.LOAD_MW) -> pd.DataFrame:
    """Average share of load covered, as a 12 (months) x 24 (hours) table."""
    covered = np.minimum(generation_mw, load_mw) / load_mw
    return covered.groupby([covered.index.month, covered.index.hour]).mean().unstack()


def shape_cost(price: pd.Series, generation_mw: pd.Series) -> pd.DataFrame:
    """
    The dollar cost of WHEN the project generates, per year.

    shape_cost = (hub average price - capture price) x MWh

    It compares the project's energy with the same MWh delivered as a
    flat block in every hour. Positive = the project's timing is worth
    less than flat power (it generates mostly in cheap hours).
    """
    df = pd.concat({"price": price, "mwh": generation_mw}, axis=1, join="inner")
    g = df.groupby(df.index.year)
    hub_avg = g["price"].mean()
    mwh = g["mwh"].sum()
    capture = (df["price"] * df["mwh"]).groupby(df.index.year).sum() / mwh
    out = pd.DataFrame({"hub_avg_price": hub_avg, "capture_price": capture,
                        "shape_discount_per_mwh": hub_avg - capture,
                        "shape_cost": (hub_avg - capture) * mwh})
    out.index.name = "year"
    return out
