"""
One function per chart. Every chart is saved to figures/ for the README.

Colors are fixed per entity across the whole project so a reader never
has to re-learn them: solar = orange, wind = blue, data center load = gray.
"""
import matplotlib

matplotlib.use("Agg")            # draw to files, no screen needed
import matplotlib.pyplot as plt

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
