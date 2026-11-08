"""
Phase 5: Monte Carlo simulation of annual VPPA settlement.

METHOD: two-step ("nested") bootstrap, one block = one whole day.

  1. Cut 2023-2025 into days. Each day keeps its 24 hourly prices AND
     its 24 hourly solar/wind outputs together.
  2. A simulated year is built month by month. For each month:
       a. pick which historical year's version of that month to use
          (e.g. August 2023, 2024 or 2025) - this keeps the month's
          "regime": a heat wave, a gas price level, a windy spell;
       b. fill the month's days by drawing (with replacement) real days
          from that one historical month.
  3. Sum the year's settlement. Repeat 10,000 times.

Why step (a) matters: drawing every day independently from all three
years mixes regimes, so every simulated year ends up close to average.
In testing that made the actual 2024 results fall OUTSIDE the simulated
range and roughly halved cash flow at risk. Keeping each month's regime
fixes that while step (b) still adds day-to-day variety.

Why whole days, drawn together:
  - price and generation stay paired, so their real relationship
    (windy hours -> cheap power; sunset -> price spike) is kept for free;
  - the hours inside a day stay in a realistic order (sunrise, peak, sunset);
  - drawing within the month keeps the seasons (August heat, windy spring).

What it cannot do:
  - produce a day worse than anything seen in 2023-2025;
  - link regimes ACROSS months (a hot July followed by a hot August is
    no more likely than a mild one), and only 3 historical versions of
    each month exist, so the tails are still probably understated.

Speed trick: settlement is additive, so we compute each historical day's
settlement once. A simulated year is then just the sum of 365 drawn
numbers, which makes 10,000 years take well under a second.
"""
import numpy as np
import pandas as pd

from vppa import config

DAYS_PER_YEAR = 365
# Days in each month of a non-leap year: the template for a simulated year.
DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def daily_table(price: pd.Series, generation: pd.DataFrame,
                strike: float = config.STRIKE,
                load_mw: float = config.LOAD_MW) -> pd.DataFrame:
    """
    One row per historical day with that day's totals, for each project:
      <project>_settlement : sum over 24 hours of (price - strike) x MWh
      <project>_mwh        : energy generated
      <project>_matched    : MWh of the flat load covered hour by hour
    plus, once per day:
      load_cost            : cost of buying the flat load at the hub price
                             (what the data center pays with no VPPA)
    Days with 23 or 25 hours (daylight-saving changes) are left out.
    """
    df = generation.join(price.rename("price"), how="inner")
    day = df.index.date
    rows = {}
    for col in generation.columns:
        name = col.replace("_mw", "")
        gen = df[col]
        rows[f"{name}_settlement"] = ((df["price"] - strike) * gen).groupby(day).sum()
        rows[f"{name}_mwh"] = gen.groupby(day).sum()
        rows[f"{name}_matched"] = np.minimum(gen, load_mw).groupby(day).sum()
    rows["load_cost"] = (df["price"] * load_mw).groupby(day).sum()
    out = pd.DataFrame(rows)
    hours = df.groupby(day).size()
    out = out[hours == 24]
    out.index = pd.to_datetime(out.index)
    out["month"] = out.index.month
    return out


def simulate_years(daily: pd.DataFrame, n_years: int = 10_000,
                   seed: int = 42) -> dict:
    """
    Draw n_years simulated years from the daily table.

    Returns {"annual": DataFrame (one row per simulated year),
             "monthly": DataFrame (one row per simulated month)}
    with the summed settlement, MWh and matched MWh of each project.
    A fixed seed makes the results identical on every run.
    """
    rng = np.random.default_rng(seed)
    value_cols = [c for c in daily.columns if c != "month"]
    values = daily[value_cols].to_numpy()
    hist_year = daily.index.year.to_numpy()
    hist_month = daily["month"].to_numpy()

    monthly_parts = []
    for month, n_days in enumerate(DAYS_IN_MONTH, start=1):
        years_available = np.unique(hist_year[hist_month == month])
        # Step a: each simulated year picks one historical year for this month.
        chosen = rng.choice(years_available, size=n_years)
        picks = np.empty((n_years, n_days), dtype=int)
        for y in years_available:
            sims = np.flatnonzero(chosen == y)
            pool = np.flatnonzero((hist_month == month) & (hist_year == y))
            # Step b: fill that month with random days from that historical month.
            picks[sims] = rng.choice(pool, size=(len(sims), n_days), replace=True)
        monthly_parts.append(values[picks].sum(axis=1))             # (n_years, n_cols)

    monthly = np.stack(monthly_parts, axis=1)                       # (n_years, 12, n_cols)
    annual = pd.DataFrame(monthly.sum(axis=1), columns=value_cols)
    annual.index.name = "sim_year"
    monthly_df = pd.DataFrame(monthly.reshape(-1, len(value_cols)), columns=value_cols)
    monthly_df["month"] = np.tile(np.arange(1, 13), n_years)
    return {"annual": annual, "monthly": monthly_df}


def risk_metrics(annual_settlement, monthly_settlement=None,
                 confidence: float = 0.95) -> dict:
    """
    Summary risk numbers for one project (all in $, buyer's view).

    expected_value     : average simulated annual settlement.
    p5_annual          : 5th percentile annual settlement - in 1 year out
                         of 20 the result is this bad or worse.
    cfar_95            : Cash Flow at Risk = expected_value - p5_annual.
                         How far below budget a bad (1-in-20) year lands.
    expected_shortfall : average of the worst 5% of years (how bad the bad
                         years are, on average).
    prob_net_payment   : share of years in which the buyer pays overall.
    var_95_1m          : 1-month Value at Risk = average month minus the
                         5th percentile month (pooled across all months).
                         A short-horizon number, like a trading desk uses.
    """
    a = np.asarray(annual_settlement, dtype=float)
    tail = 1 - confidence
    p5 = np.quantile(a, tail)
    out = {
        "expected_value": a.mean(),
        "p5_annual": p5,
        "cfar_95": a.mean() - p5,
        "expected_shortfall": a[a <= p5].mean(),
        "p95_annual": np.quantile(a, confidence),
        "prob_net_payment": (a < 0).mean(),
    }
    if monthly_settlement is not None:
        m = np.asarray(monthly_settlement, dtype=float)
        out["var_95_1m"] = m.mean() - np.quantile(m, tail)
    return out


def run(price: pd.Series, generation: pd.DataFrame,
        strike: float = config.STRIKE, n_years: int = 10_000,
        seed: int = 42, load_mw: float = config.LOAD_MW) -> tuple:
    """
    Full Monte Carlo for every project column.
    Returns (summary table, simulated annual results).
    """
    daily = daily_table(price, generation, strike, load_mw)
    sims = simulate_years(daily, n_years, seed)
    annual, monthly = sims["annual"], sims["monthly"]
    rows = {}
    for col in generation.columns:
        name = col.replace("_mw", "")
        m = risk_metrics(annual[f"{name}_settlement"], monthly[f"{name}_settlement"])
        m["annual_mwh"] = annual[f"{name}_mwh"].mean()
        m["hourly_match"] = (annual[f"{name}_matched"] / (load_mw * 24 * DAYS_PER_YEAR)).mean()
        rows[name] = m
    return pd.DataFrame(rows).T, annual
