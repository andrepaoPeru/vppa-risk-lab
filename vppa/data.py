"""
Phase 1: download public ERCOT data and cache it locally as parquet.

Each fetch function follows the same pattern:
  1. If the parquet file already exists in data/, read it (fast, offline).
  2. Otherwise download it with gridstatus, clean it, and save it.

So the internet is only needed the first time.
"""
import time

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


def with_retries(fetch, attempts: int = 4, wait_seconds: float = 5.0):
    """
    Call fetch(); if it fails, wait and try again (5s, 10s, 20s...).

    ERCOT's public website sometimes rejects or truncates a download
    (HTTP 403, broken zip file) and then works a few seconds later.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fetch()
        except Exception as err:
            if attempt == attempts:
                raise
            print(f"  attempt {attempt} failed ({type(err).__name__}), retrying...")
            time.sleep(wait_seconds * 2 ** (attempt - 1))


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
    raw = with_retries(lambda: gridstatus.Ercot().get_rtm_spp(year))  # all hubs + zones, 15-min
    raw = raw[raw["Location"] == hub]
    if raw.empty:
        raise ValueError(f"No rows for {hub} in {year}. Check the hub name.")

    hourly = to_hourly(raw).rename("price")
    hourly.to_frame().to_parquet(path)
    return hourly


def load_hub_prices(years=config.YEARS, hub: str = config.HUB) -> pd.Series:
    """All years stacked into one hourly price series."""
    return pd.concat([fetch_hub_prices(y, hub) for y in years]).sort_index()


# ---------------------------------------------------------------------------
# System-wide solar and wind generation
# ---------------------------------------------------------------------------
# ERCOT "Interval Generation by Fuel" report: one public Excel file per
# year, one sheet per month, one row per (day, fuel), and one column per
# 15-minute interval holding the MWh generated in that interval.
# Listed on https://www.ercot.com/gridinfo/generation
FUEL_MIX_URLS = {
    2023: "https://www.ercot.com/files/docs/2023/02/07/IntGenbyFuel2023.xlsx",
    2024: "https://www.ercot.com/files/docs/2024/02/08/IntGenbyFuel2024.xlsx",
    2025: "https://www.ercot.com/files/docs/2025/02/07/IntGenbyFuel2025.xlsx",
}
MONTH_SHEETS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_fuel_mix(df: pd.DataFrame, fuels=("Solar", "Wind")) -> pd.DataFrame:
    """
    Turn ERCOT's wide fuel-mix table into hourly MW, one column per fuel.

    Column labels are the END of each 15-minute interval:
      "0:15" = 00:00-00:15, ..., "0:00" = 23:45-24:00 (end of day).
    On the November "fall back" day there are 4 extra columns such as
    "01:15 (DST)". We treat those as the second, repeated 1 AM hour
    (after clocks go back). On the March "spring forward" day, the
    2 AM columns are empty because that hour does not exist.
    """
    df = df[df["Fuel"].isin(fuels)]
    interval_cols = [c for c in df.columns if ":" in str(c)]

    # Wide -> long: one row per (day, fuel, interval).
    long = df.melt(id_vars=["Date", "Fuel"], value_vars=interval_cols,
                   var_name="label", value_name="mwh").dropna(subset=["mwh"])

    # "13:45" -> interval ends 825 minutes after midnight -> starts at 810.
    label = long["label"].astype(str)
    is_repeat_hour = label.str.contains("DST")
    hh_mm = label.str.replace(" (DST)", "", regex=False).str.split(":", expand=True)
    end_min = hh_mm[0].astype(int) * 60 + hh_mm[1].astype(int)
    end_min = end_min.where(end_min > 0, 24 * 60)            # "0:00" means midnight at day end
    start_local = (pd.to_datetime(long["Date"]).dt.normalize()
                   + pd.to_timedelta(end_min - 15, unit="min"))

    # Attach the Central time zone. ambiguous=True means "the first
    # (daylight time) 1 AM hour"; the DST-labelled columns are the second.
    long["interval_start"] = start_local.dt.tz_localize(
        config.TIMEZONE, ambiguous=~is_repeat_hour.to_numpy(), nonexistent="NaT")
    long = long.dropna(subset=["interval_start"])

    # Four 15-minute MWh values summed = MWh in that hour = average MW.
    hour_utc = long["interval_start"].dt.tz_convert("UTC").dt.floor("h")
    hourly = long.groupby([hour_utc, "Fuel"])["mwh"].sum().unstack("Fuel")
    hourly.index = hourly.index.tz_convert(config.TIMEZONE)
    hourly.index.name = "hour_start"
    hourly.columns = [f"{c.lower()}_mw" for c in hourly.columns]   # solar_mw, wind_mw
    hourly.columns.name = None
    return hourly


def fetch_system_generation(year: int) -> pd.DataFrame:
    """Hourly ERCOT-wide solar and wind output (MW) for one year."""
    path = _cache_path(f"system_generation_{year}")
    if path.exists():
        return pd.read_parquet(path)

    print(f"Downloading ERCOT generation by fuel for {year}...")
    url = FUEL_MIX_URLS[year]
    sheets = with_retries(lambda: pd.read_excel(url, sheet_name=MONTH_SHEETS))
    raw = pd.concat(sheets.values(), ignore_index=True)

    gen = parse_fuel_mix(raw)
    gen.to_parquet(path)
    return gen


def load_system_generation(years=config.YEARS) -> pd.DataFrame:
    """All years of hourly system solar and wind output stacked together."""
    return pd.concat([fetch_system_generation(y) for y in years]).sort_index()
