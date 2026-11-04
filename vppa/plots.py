"""
One function per chart. Every chart is saved to figures/ for the README.

Colors are fixed per entity across the whole project so a reader never
has to re-learn them: solar = orange, wind = blue, data center load = gray.
"""
import matplotlib

matplotlib.use("Agg")            # draw to files, no screen needed
import matplotlib.pyplot as plt

# Treat "$" as a normal character (dollar amounts), not as math markup.
plt.rcParams["text.parse_math"] = False

from vppa import config

COLORS = {"solar": "#eb6834", "wind": "#2a78d6", "blend": "#1baf7a",
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
