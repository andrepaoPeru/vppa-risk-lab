"""
Build the local data cache in one command:

    python scripts/fetch_data.py

Safe to re-run: anything already in data/ is read from disk, not re-downloaded.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # find the vppa package

from vppa import config, data

prices = data.load_hub_prices()
print(f"{config.HUB}: {len(prices):,} hourly prices, "
      f"{prices.index.min()} to {prices.index.max()}")
print(prices.describe().round(2))

zone = data.load_load_zone_prices()
print(f"\n{config.LOAD_ZONE}: {len(zone):,} hourly prices")

gen = data.load_system_generation()
print(f"\nSystem generation: {len(gen):,} hours, "
      f"{gen.index.min()} to {gen.index.max()}")
print(gen.describe().round(0))

# Resource-node prices need a free ERCOT Public API account (see README).
import os
if all(os.environ.get(k) for k in ("ERCOT_API_USERNAME", "ERCOT_API_PASSWORD",
                                   "ERCOT_PUBLIC_API_SUBSCRIPTION_KEY")):
    node = data.load_node_prices()
    print(f"\n{config.NODE}: {len(node):,} hourly prices, mean ${node.mean():.2f}/MWh")
else:
    print("\nSkipping resource-node prices: ERCOT API credentials not set.")
