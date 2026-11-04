"""
Phase 1: download public ERCOT data and cache it locally as parquet.

Each fetch function follows the same pattern:
  1. If the parquet file already exists in data/, read it (fast, offline).
  2. Otherwise download it with gridstatus, clean it, and save it.

So the internet is only needed the first time.
"""
import pandas as pd
import gridstatus

from vppa import config


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _cache_path(name: str):
    """Where a cached dataset lives, e.g. data/hub_prices_HB_WEST_2023.parquet"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / f"{name}.parquet"


def to_hourly(df: pd.DataFrame, time_col: str = "Interval Start",
              value_col: str = "SPP") -> pd.Series:
    """
    Average 15-minute ERCOT prices into hourly prices.

    ERCOT's real-time market settles every 15 minutes, so each hour has
    4 prices. We take their simple average to get one price per hour.
    Simplification: a real VPPA usually settles each 15-minute interval
    against the generation in that interval. With hourly generation data
    only, an hourly average price is the closest match.

    Daylight saving time: the clock repeats 1:00-2:00 AM in November.
    To avoid mixing those two different hours together, we group in UTC
    (which has no daylight saving), then convert back to Central time.
    """
    times_utc = pd.to_datetime(df[time_col]).dt.tz_convert("UTC")
    hour_utc = times_utc.dt.floor("h")                 # start of each hour
    hourly = df[value_col].groupby(hour_utc.values).mean()
    hourly.index = pd.DatetimeIndex(hourly.index).tz_localize("UTC")
    hourly.index = hourly.index.tz_convert(config.TIMEZONE)
    hourly.index.name = "hour_start"
    return hourly


# ---------------------------------------------------------------------------
# Hub prices
# ---------------------------------------------------------------------------
def fetch_hub_prices(year: int, hub: str = config.HUB) -> pd.Series:
    """
    Hourly real-time settlement point prices ($/MWh) for one hub and year.

    Source: ERCOT report NP6-785-ER "Historical RTM Load Zone and Hub
    Prices" - one public Excel file per year, no login needed.
    Returns a pandas Series indexed by hour (Central time).
    """
    path = _cache_path(f"hub_prices_{hub}_{year}")
    if path.exists():
        return pd.read_parquet(path)["price"]

    print(f"Downloading ERCOT real-time hub/zone prices for {year}...")
    raw = gridstatus.Ercot().get_rtm_spp(year)        # all hubs + load zones, 15-min
    raw = raw[raw["Location"] == hub]
    if raw.empty:
        raise ValueError(f"No rows for {hub} in {year}. Check the hub name.")

    hourly = to_hourly(raw).rename("price")
    hourly.to_frame().to_parquet(path)
    return hourly


def load_hub_prices(years=config.YEARS, hub: str = config.HUB) -> pd.Series:
    """All years stacked into one hourly price series."""
    return pd.concat([fetch_hub_prices(y, hub) for y in years]).sort_index()
