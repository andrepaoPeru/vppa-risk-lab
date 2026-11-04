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
