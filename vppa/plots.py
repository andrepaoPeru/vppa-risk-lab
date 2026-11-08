"""
One function per chart. Every chart is saved to figures/ for the README.

Colors are fixed per entity across the whole project so a reader never
has to re-learn them: solar = orange, wind = blue, data center load = gray.
"""
import matplotlib
import numpy as np

matplotlib.use("Agg")            # draw to files, no screen needed
import matplotlib.pyplot as plt

# Treat "$" as a normal character (dollar amounts), not as math markup.
plt.rcParams["text.parse_math"] = False

from vppa import config

COLORS = {"solar": "#eb6834", "wind": "#2a78d6", "blend": "#1baf7a",
          "solar_battery": "#e87ba4",
          "load": "#52514e", "grid": "#e4e3df", "text": "#0b0b0b",
          "muted": "#52514e"}


def _style(ax, title, ylabel, xlabel=None):
    """Shared look: light grid, no top/right box lines, plain titles."""
    ax.set_title(title, loc="left", fontsize=12, color=COLORS["text"])
    ax.set_ylabel(ylabel, color=COLORS["muted"])
    if xlabel:
        ax.set_xlabel(xlabel, color=COLORS["muted"])
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLORS["grid"])
    ax.tick_params(colors=COLORS["muted"])


def _save(fig, name):
    config.FIGURES_DIR.mkdir(exist_ok=True)
    path = config.FIGURES_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def plot_average_day(profiles, load_mw=config.LOAD_MW):
    """
    Average output by hour of day vs. the flat data center load.
    This is the first look at SHAPE: when each project produces power.
    """
    by_hour = profiles.groupby(profiles.index.hour).mean()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for col, name in (("solar_mw", "solar"), ("wind_mw", "wind")):
        ax.plot(by_hour.index, by_hour[col], color=COLORS[name], linewidth=2,
                label=f"{name.title()} {config.SOLAR_MW if name == 'solar' else config.WIND_MW:.0f} MW (proxy)")
    ax.axhline(load_mw, color=COLORS["load"], linewidth=2, linestyle="--",
               label=f"Data center load {load_mw:.0f} MW")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlim(0, 23)
    ax.set_ylim(bottom=0)
    _style(ax, "Average output by hour of day, 2023-2025", "MW", "Hour of day (Central time)")
    ax.legend(frameon=False, loc="upper left")
    return _save(fig, "02_average_day")


def plot_monthly_capacity_factor(profiles):
    """Monthly capacity factor of each proxy project: seasons and year-to-year swings."""
    monthly = profiles.resample("MS").mean()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for col, name, mw in (("solar_mw", "solar", config.SOLAR_MW),
                          ("wind_mw", "wind", config.WIND_MW)):
        cf = monthly[col] / mw * 100
        ax.plot(cf.index, cf, color=COLORS[name], linewidth=2, marker="o",
                markersize=4, label=name.title())
    ax.set_ylim(0, None)
    _style(ax, "Monthly capacity factor of the proxy projects", "Capacity factor (%)")
    ax.legend(frameon=False, loc="lower left", ncol=2)
    return _save(fig, "02_monthly_capacity_factor")


def plot_monthly_settlement(results: dict, strike: float = config.STRIKE):
    """
    Monthly VPPA settlement for each project, one panel each, same y-axis.
    Above zero: the project paid the buyer. Below zero: the buyer paid.
    """
    from vppa.settlement import summarize_settlement

    names = list(results)
    fig, axes = plt.subplots(len(names), 1, figsize=(9, 2.8 * len(names)),
                             sharex=True, sharey=True)
    for ax, name in zip(axes, names):
        monthly = summarize_settlement(results[name], "MS")["settlement"] / 1e6
        ax.bar(monthly.index, monthly, width=24, color=COLORS[name])
        ax.axhline(0, color=COLORS["muted"], linewidth=0.8)
        _style(ax, f"{name.title()} 200 MW", "$ million")
    axes[0].figure.suptitle(
        f"Monthly VPPA settlement at {config.HUB}, strike ${strike:.0f}/MWh "
        "(positive = project pays buyer)", x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    return _save(fig, "03_monthly_settlement")


def plot_negative_price_hours(price):
    """How many hours had a negative hub price, by hour of day, per year."""
    neg = price[price < 0]
    counts = neg.groupby([neg.index.year, neg.index.hour]).size().unstack(0).reindex(range(24)).fillna(0)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    shades = ["#9ec5f4", "#5598e7", "#1c5cab"]            # one hue, light -> dark = older -> newer
    for color, year in zip(shades, counts.columns):
        ax.plot(counts.index, counts[year], color=color, linewidth=2, marker="o",
                markersize=4, label=str(year))
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlim(0, 23)
    ax.set_ylim(bottom=0)
    _style(ax, f"Hours with a negative {config.HUB} price, by hour of day",
           "Number of hours", "Hour of day (Central time)")
    ax.legend(frameon=False, loc="upper left", ncol=3)
    return _save(fig, "03_negative_price_hours")


def plot_price_sensitivity(price, profiles, strike=config.STRIKE):
    """Average annual settlement vs. a parallel shift in every hourly price."""
    from vppa.risk import price_sensitivity

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for col in profiles.columns:
        name = col.replace("_mw", "")
        sens = price_sensitivity(price, profiles[col], strike)
        y = sens["annual_settlement"] / 1e6
        ax.plot(sens.index, y, color=COLORS[name], linewidth=2, marker="o",
                markersize=5, label=name.title())
        slope_k = sens["dollars_per_1_shift"].iloc[0] / 1e3
        ax.annotate(f"{name.title()}: ${slope_k:,.0f}k per $1/MWh",
                    xy=(sens.index[-1], y.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center",
                    fontsize=9, color=COLORS["text"])
    ax.axhline(0, color=COLORS["muted"], linewidth=0.8)
    ax.axvline(0, color=COLORS["grid"], linewidth=0.8)
    _style(ax, f"Price risk: average annual settlement vs. price shift (strike ${strike:.0f})",
           "$ million per year (+ = project pays buyer)",
           f"Change applied to every hourly {config.HUB} price ($/MWh)")
    ax.legend(frameon=False, loc="upper left")
    ax.set_xlim(right=ax.get_xlim()[1] + 12)          # room for the labels
    return _save(fig, "04_price_sensitivity")


def plot_hourly_match_heatmap(profiles, load_mw=config.LOAD_MW):
    """
    Shape risk: share of the flat data center load each project covers,
    by month (rows) and hour of day (columns). Dark = load fully covered.
    """
    from matplotlib.colors import LinearSegmentedColormap
    from vppa.risk import match_by_month_hour

    # One hue, light -> dark (sequential): more coverage = darker blue.
    blues = LinearSegmentedColormap.from_list(
        "blues", ["#f0efec", "#9ec5f4", "#3987e5", "#1c5cab", "#0d366b"])
    names = [c.replace("_mw", "") for c in profiles.columns]
    fig, axes = plt.subplots(1, len(names), figsize=(5.2 * len(names), 4.2), sharey=True)
    for ax, col, name in zip(axes, profiles.columns, names):
        grid = match_by_month_hour(profiles[col], load_mw) * 100
        im = ax.imshow(grid.values, cmap=blues, vmin=0, vmax=100, aspect="auto")
        ax.set_title(f"{name.title()} 200 MW", loc="left", fontsize=11)
        ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (Central time)", color=COLORS["muted"])
        for side in ax.spines.values():
            side.set_visible(False)
        ax.tick_params(colors=COLORS["muted"], length=0)
    axes[0].set_yticks(range(12))
    axes[0].set_yticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    cbar = fig.colorbar(im, ax=axes, shrink=0.85, pad=0.02)
    cbar.set_label(f"% of {load_mw:.0f} MW load covered (2023-2025 avg)", color=COLORS["muted"])
    cbar.outline.set_visible(False)
    fig.suptitle("Shape risk: when does each project cover a flat 24/7 load?",
                 x=0.01, y=1.03, ha="left", fontsize=13)
    return _save(fig, "05_hourly_match_heatmap")


def plot_volume_risk(price, profiles, strike=config.STRIKE):
    """Base history vs. the low-resource year: energy, settlement, hourly match."""
    from vppa.risk import volume_scenarios

    names = [c.replace("_mw", "") for c in profiles.columns]
    nameplate = {"solar": config.SOLAR_MW, "wind": config.WIND_MW}
    res = {n: volume_scenarios(price, profiles[f"{n}_mw"], nameplate[n], strike) for n in names}
    panels = [("annual_mwh", "Energy (GWh per year)", 1e-3),
              ("annual_settlement", "Settlement ($M per year)", 1e-6),
              ("hourly_match", "Hourly match (% of load)", 100)]

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    width = 0.38
    for ax, (col, title, scale) in zip(axes, panels):
        for i, n in enumerate(names):
            base = res[n].loc["base", col] * scale
            low = res[n].loc["low_resource", col] * scale
            # Same hue per project: light = base history, full = low-resource year
            ax.bar(i - width / 2 - 0.01, base, width, color=COLORS[n], alpha=0.4)
            ax.bar(i + width / 2 + 0.01, low, width, color=COLORS[n])
            for x, v in ((i - width / 2, base), (i + width / 2, low)):
                ax.annotate(f"{v:,.1f}", (x, v), xytext=(0, 3 if v >= 0 else -11),
                            textcoords="offset points", ha="center", fontsize=8,
                            color=COLORS["text"])
        ax.axhline(0, color=COLORS["muted"], linewidth=0.8)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels([n.title() for n in names])
        _style(ax, title, "")
    # Neutral legend swatches: the shade (light/full) is what the legend explains.
    from matplotlib.patches import Patch
    axes[0].legend(handles=[Patch(color=COLORS["muted"], alpha=0.4, label="Base history"),
                            Patch(color=COLORS["muted"], label="Low-resource year")],
                   frameon=False, loc="upper left", fontsize=9)
    fig.suptitle("Volume risk: actual 2023-2025 vs. a year built from the worst month of each kind",
                 x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    return _save(fig, "06_volume_risk")


def plot_monte_carlo(annual, summary, actual_by_year=None, strike=config.STRIKE):
    """
    Distribution of simulated annual settlement, one panel per project.
    Marks the expected value, the 5th percentile (cash flow at risk) and,
    if given, the real 2023-2025 results for comparison.
    """
    names = list(summary.index)
    fig, axes = plt.subplots(len(names), 1, figsize=(9, 3.2 * len(names)),
                             sharex=True)
    all_vals = annual[[f"{n}_settlement" for n in names]] / 1e6
    bins = np.linspace(all_vals.min().min(), all_vals.max().max(), 70)
    for ax, n in zip(axes, names):
        vals = all_vals[f"{n}_settlement"]
        ax.hist(vals, bins=bins, color=COLORS[n], alpha=0.85, edgecolor="white", linewidth=0.5)
        ev = summary.loc[n, "expected_value"] / 1e6
        p5 = summary.loc[n, "p5_annual"] / 1e6
        top = ax.get_ylim()[1]
        ax.axvline(ev, color=COLORS["text"], linewidth=1.5)
        ax.annotate(f"Expected {ev:+.1f}M", (ev, top * 0.92), xytext=(4, 0),
                    textcoords="offset points", fontsize=9)
        ax.axvline(p5, color=COLORS["text"], linewidth=1.5, linestyle="--")
        ax.annotate(f"5th pct {p5:+.1f}M\nCFaR {ev - p5:.1f}M", (p5, top * 0.72),
                    xytext=(-4, 0), textcoords="offset points", ha="right", fontsize=9)
        if actual_by_year is not None:
            last_x, level = None, 0
            for year, v in sorted(actual_by_year[n].items(), key=lambda kv: kv[1]):
                x = v / 1e6
                # Stack labels upward when two real years are close together.
                level = level + 1 if last_x is not None and x - last_x < 1.5 else 0
                last_x = x
                ax.plot(x, top * 0.05, marker="v", markersize=9,
                        color=COLORS["text"], markeredgecolor="white")
                ax.annotate(str(year), (x, top * (0.12 + 0.09 * level)),
                            ha="center", fontsize=8)
        ax.axvline(0, color=COLORS["muted"], linewidth=0.8, alpha=0.6)
        _style(ax, f"{n.title()} 200 MW", "Simulated years")
    axes[-1].set_xlabel("Annual settlement, $ million (+ = project pays buyer)",
                        color=COLORS["muted"])
    fig.suptitle(f"Monte Carlo: {len(annual):,} simulated years, strike ${strike:.0f}/MWh "
                 "(triangles = actual 2023-2025)", x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    return _save(fig, "07_monte_carlo")


LABELS = {"solar": "Solar", "wind": "Wind", "blend": "Solar + wind",
          "solar_battery": "Solar + battery"}


def plot_portfolio_comparison(table, sizes=None, title_note=""):
    """
    Four panels, one bar per option: expected settlement, cash flow at
    risk, hourly match and breakeven strike (capture price).
    """
    names = list(table.index)
    panels = [("expected_value", "Expected settlement ($M/yr, + = paid to buyer)", 1e-6, "{:+.1f}"),
              ("cfar_95", "Cash flow at risk, 95% ($M/yr)", 1e-6, "{:.1f}"),
              ("hourly_match", "Hourly match of 100 MW load (%)", 100, "{:.0f}%"),
              ("capture_price", "Breakeven strike = capture price ($/MWh)", 1, "${:.1f}")]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, (col, title, scale, fmt) in zip(axes.flat, panels):
        vals = table[col] * scale
        bars = ax.bar(range(len(names)), vals, color=[COLORS[n] for n in names], width=0.65)
        for b, v in zip(bars, vals):
            ax.annotate(fmt.format(v), (b.get_x() + b.get_width() / 2, v),
                        xytext=(0, 3 if v >= 0 else -12), textcoords="offset points",
                        ha="center", fontsize=9, color=COLORS["text"])
        ax.axhline(0, color=COLORS["muted"], linewidth=0.8)
        ax.margins(y=0.15)                       # room for the value labels
        ax.set_xticks(range(len(names)))
        labels = [LABELS[n] if not sizes else f"{LABELS[n]}\n{sizes[n]:.0f} MW" for n in names]
        ax.set_xticklabels(labels, fontsize=9)
        _style(ax, title, "")
        if col == "capture_price":
            ax.axhline(config.STRIKE, color=COLORS["text"], linestyle="--", linewidth=1)
            ax.annotate(f"Contract strike ${config.STRIKE:.0f}", (1, config.STRIKE),
                        xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8)
    fig.suptitle(f"Which portfolio for a 24/7 data center? {title_note}",
                 x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    return _save(fig, "08_portfolio_comparison")


def plot_battery_day(solar_mw, battery, load_mw=config.LOAD_MW):
    """
    Average day in summer (Jun-Aug 2025): solar alone vs. solar + battery,
    and the battery's charging (midday) and discharging (evening).
    """
    sel = (solar_mw.index.year == 2025) & solar_mw.index.month.isin([6, 7, 8])
    hour = solar_mw.index[sel].hour
    solo = solar_mw[sel].groupby(hour).mean()
    b = battery[sel].groupby(hour).mean()
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.fill_between(b.index, 0, b["discharge_mw"], color=COLORS["solar_battery"], alpha=0.35,
                    label="Battery discharging")
    ax.fill_between(b.index, 0, -b["charge_mw"], color=COLORS["muted"], alpha=0.25,
                    label="Battery charging (shown below zero)")
    ax.plot(solo.index, solo, color=COLORS["solar"], linewidth=2, label="Solar alone")
    ax.plot(b.index, b["delivered_mw"], color=COLORS["solar_battery"], linewidth=2.5,
            label="Solar + battery delivered")
    ax.axhline(load_mw, color=COLORS["text"], linestyle="--", linewidth=1.3,
               label=f"Data center load {load_mw:.0f} MW")
    ax.axhline(0, color=COLORS["muted"], linewidth=0.8)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlim(0, 23)
    _style(ax, "How the battery reshapes solar: average summer day, 2025 (200 MW solar)",
           "MW", "Hour of day (Central time)")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17),
              ncol=3, fontsize=8)
    return _save(fig, "08_battery_day")


def plot_example_week(profiles, start="2025-08-04", end="2025-08-10",
                      load_mw=config.LOAD_MW):
    """
    Shape risk in one real week: each project's hourly output vs. the flat
    load. Gray = shortfall bought from the grid; tint = excess sold back.
    """
    week = profiles.loc[start:end]
    cols = [c for c in ("solar_mw", "wind_mw") if c in week]
    fig, axes = plt.subplots(len(cols), 1, figsize=(11, 3 * len(cols)), sharex=True, sharey=True)
    for ax, col in zip(np.atleast_1d(axes), cols):
        name = col.replace("_mw", "")
        g = week[col]
        ax.fill_between(g.index, g, load_mw, where=g < load_mw, color="#c3c2b7", alpha=0.6,
                        step="post", label="Shortfall: bought from the grid")
        ax.fill_between(g.index, g, load_mw, where=g > load_mw, color=COLORS[name], alpha=0.25,
                        step="post", label="Excess: sold to the grid")
        ax.step(g.index, g, where="post", color=COLORS[name], linewidth=1.8,
                label=f"{name.title()} 200 MW output")
        ax.axhline(load_mw, color=COLORS["text"], linewidth=1.5, linestyle="--",
                   label=f"Data center load {load_mw:.0f} MW")
        ax.set_ylim(0, 200)
        _style(ax, f"{name.title()}: {start} to {end}", "MW")
        ax.legend(frameon=False, loc="upper right", fontsize=8, ncol=4)
    fig.suptitle("Shape risk in one real week: gray gaps are hours the project cannot cover",
                 x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    return _save(fig, "05_example_week")
