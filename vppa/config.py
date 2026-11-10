"""
All project assumptions in one place.

Change a number here and every module, test and chart picks it up.
Everything below is a HYPOTHETICAL assumption for a learning project,
not a real contract or a real company's data.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Market and time window
# ---------------------------------------------------------------------------
# ERCOT publishes prices at "settlement points": hubs, load zones and
# resource nodes. HB_WEST is the West Texas trading hub, an average of
# many West Texas nodes, and the usual reference price for wind/solar PPAs there.
HUB = "HB_WEST"

# The resource node where our hypothetical projects inject power.
# Pending: needs the ERCOT Public API (Step 2). None = not available yet.
NODE = None

# The load zone where the data center buys its power. A West Texas load
# pays the LZ_WEST price, while the VPPA settles at HB_WEST: that gap is
# the buyer's side of basis risk.
LOAD_ZONE = "LZ_WEST"

# Three full calendar years of history.
YEARS = [2023, 2024, 2025]

# ERCOT reports in Central Prevailing Time (includes daylight saving).
TIMEZONE = "US/Central"

# ---------------------------------------------------------------------------
# Hypothetical projects and buyer
# ---------------------------------------------------------------------------
SOLAR_MW = 200.0   # nameplate capacity of the proxy solar project
WIND_MW = 200.0    # nameplate capacity of the proxy wind project
LOAD_MW = 100.0    # flat 24/7 data center load

# VPPA strike price in $/MWh. Settlement each hour = (price - strike) x MWh.
STRIKE = 35.0

# ---------------------------------------------------------------------------
# File locations
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"          # parquet cache (git-ignored)
FIGURES_DIR = ROOT / "figures"    # charts used in the README

# ---------------------------------------------------------------------------
# Hypothetical battery paired with the solar project (Step 11)
# ---------------------------------------------------------------------------
BATTERY_MW = 100.0          # maximum charge / discharge rate
BATTERY_MWH = 400.0         # storage size: 4 hours at full power
BATTERY_EFFICIENCY = 0.85   # round trip: 100 MWh in -> 85 MWh back out
