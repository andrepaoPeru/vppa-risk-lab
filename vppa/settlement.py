"""
Phase 3: historical backtest of the VPPA settlement.

SIGN CONVENTION (buyer's view, used everywhere in this project):
    settlement ($) = (market price - strike) x MWh generated
    positive -> the project pays the buyer (market price was above strike)
    negative -> the buyer pays the project (market price was below strike)

The buyer never receives the electrons; this is a purely financial swap.
"""
import pandas as pd

from vppa import config


def settle_hourly(price: pd.Series, generation_mw: pd.Series,
                  strike: float = config.STRIKE) -> pd.DataFrame:
    """
    One row per hour: price, MWh, settlement.

    generation_mw is average MW in the hour, which equals MWh in that hour.
    Hours missing from either input are dropped (inner join), so a data
    gap can never be silently treated as zero output or a zero price.
    """
    df = pd.concat({"price": price, "mwh": generation_mw}, axis=1, join="inner")
    df["settlement"] = (df["price"] - strike) * df["mwh"]
    return df


def summarize_settlement(hourly: pd.DataFrame, freq: str = "YS") -> pd.DataFrame:
    """
    Roll hourly settlement up to months (freq="MS") or years (freq="YS").

    capture_price = generation-weighted average price: what the project's
    MWh were actually worth at the hub. Compare it with hub_avg_price, the
    simple average over all hours. A capture price below the hub average
    means the project tends to generate when power is cheap.
    """
    g = hourly.resample(freq)
    out = pd.DataFrame({
        "mwh": g["mwh"].sum(),
        "settlement": g["settlement"].sum(),
        "hub_avg_price": g["price"].mean(),
    })
    value = (hourly["price"] * hourly["mwh"]).resample(freq).sum()
    out["capture_price"] = value / out["mwh"]
    out["settlement_per_mwh"] = out["settlement"] / out["mwh"]
    return out


def negative_price_summary(hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Per year: how often prices were negative, and what those hours cost.

    In a negative-price hour the buyer pays (strike - price), i.e. MORE
    than the full strike, for every MWh the project generates.
    """
    neg = hourly[hourly["price"] < 0]
    by_year = hourly.index.year
    out = pd.DataFrame({
        "negative_hours": (hourly["price"] < 0).groupby(by_year).sum(),
        "mwh_in_negative_hours": neg["mwh"].groupby(neg.index.year).sum(),
        "settlement_in_negative_hours": neg["settlement"].groupby(neg.index.year).sum(),
    }).fillna(0.0)
    out["share_of_mwh"] = out["mwh_in_negative_hours"] / hourly["mwh"].groupby(by_year).sum()
    out.index.name = "year"
    return out


def backtest(price: pd.Series, profiles: pd.DataFrame,
             strike: float = config.STRIKE) -> dict:
    """Run the hourly settlement for every project column (solar_mw, wind_mw, ...)."""
    return {col.replace("_mw", ""): settle_hourly(price, profiles[col], strike)
            for col in profiles.columns}
