"""Battery and portfolio math on tiny hand-checkable inputs."""
import pandas as pd
import pytest

from vppa import portfolio


def _hours(n):
    return pd.date_range("2024-06-01", periods=n, freq="h", tz="US/Central")


def test_battery_moves_surplus_into_shortfall_with_losses():
    # Hour 1: 150 MW solar vs 100 MW load -> 50 MWh surplus, 80% efficiency stores 40.
    # Hour 2: no solar -> battery releases its 40 MWh.
    solar = pd.Series([150.0, 0.0], _hours(2))
    b = portfolio.add_battery(solar, load_mw=100, power_mw=100, energy_mwh=400, efficiency=0.8)
    assert b["charge_mw"].tolist() == [50.0, 0.0]
    assert b["soc_mwh"].tolist() == [40.0, 0.0]
    assert b["delivered_mw"].tolist() == [100.0, 40.0]


def test_battery_respects_power_and_energy_limits():
    solar = pd.Series([400.0, 400.0, 0.0, 0.0], _hours(4))
    b = portfolio.add_battery(solar, load_mw=100, power_mw=50, energy_mwh=60, efficiency=1.0)
    assert b["charge_mw"].max() <= 50
    assert b["discharge_mw"].max() <= 50
    assert b["soc_mwh"].max() <= 60
    assert b["charge_mw"].tolist() == [50.0, 10.0, 0.0, 0.0]   # full after 60 MWh


def test_battery_never_creates_energy():
    solar = pd.Series([0, 50, 180, 220, 160, 40, 0, 0], _hours(8), dtype=float)
    b = portfolio.add_battery(solar, load_mw=100, power_mw=100, energy_mwh=400, efficiency=0.85)
    assert b["delivered_mw"].sum() <= solar.sum() + 1e-9
    assert (b["delivered_mw"] >= 0).all()


def test_blend_is_half_and_half():
    t = _hours(1)
    prof = pd.DataFrame({"solar_mw": [100.0], "wind_mw": [50.0]}, t)  # CF 0.50 and 0.25
    assert portfolio.make_option("blend", 200, prof).iloc[0] == pytest.approx(75.0)


def test_sizing_hits_the_annual_energy_target():
    t = pd.date_range("2024-01-01", periods=8760, freq="h", tz="US/Central")
    prof = pd.DataFrame({"solar_mw": 50.0, "wind_mw": 80.0}, t)       # CF 0.25 and 0.40
    sizes = portfolio.size_for_annual_match(prof, share=1.0, load_mw=100)
    assert sizes["solar"] == pytest.approx(400.0)                      # 100 MW / 0.25
    assert sizes["wind"] == pytest.approx(250.0)                       # 100 MW / 0.40
