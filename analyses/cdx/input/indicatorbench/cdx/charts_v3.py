"""
charts_v3.py — Supplementary charts for the CDX NA IG report.
Outputs:
  cdx_strategy_bars.svg  — Sharpe / Calmar / MaxDD comparison, all 11 strategies
  cdx_trade_logs.svg     — Per-trade return dot-plots for B, J, K
  cdx_regime_hist.svg    — Regime distribution + spread histogram
"""
from __future__ import annotations
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib.patches import Patch

# ── palette ───────────────────────────────────────────────────────────────────
DARK  = "#0e1117"; GRID = "#2a2d35"
BLUE  = "#4c9be8"; AMBER= "#f0a500"
RED   = "#e05252"; GREEN= "#52b788"
TEAL  = "#2dd4bf"; PINK = "#f472b6"
GREY  = "#6b7280"; LITE = "#c8cdd6"

def style_ax(ax, title="", xlabel="", ylabel="", ts=False):
    ax.set_facecolor(DARK)
    ax.tick_params(colors=LITE, labelsize=8)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color(GRID)
    ax.grid(axis="x" if not ts else "y", color=GRID, lw=0.5, ls="--", alpha=0.7)
    if title:   ax.set_title(title,   color=LITE, fontsize=9.5, pad=6)
    if xlabel:  ax.set_xlabel(xlabel, color=LITE, fontsize=8.5)
    if ylabel:  ax.set_ylabel(ylabel, color=LITE, fontsize=8.5)
    if ts:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_major_locator(mdates.YearLocator())

# ─────────────────────────────────────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────────────────────────────────────

best = pd.read_csv("results/best_per_family.csv")
b_trades = pd.read_csv("results/spike_onset_trades.csv", parse_dates=["entry_date"])
j_trades = pd.read_csv("results/tail_hold_trades.csv",   parse_dates=["entry_date"])
k_trades = pd.read_csv("results/crisis_ride_trades.csv", parse_dates=["entry_date"])

df = pd.read_csv("cdx_na_ig_clean.csv", parse_dates=["date"])
df = df.sort_values("date").reset_index(drop=True)
s  = df.set_index("date")["cdx_na_ig"]


# ══════════════════════════════════════════════════════════════════════════════
# CHART 1 — Strategy comparison bars
# ══════════════════════════════════════════════════════════════════════════════

best_s = best.sort_values("sharpe", ascending=True).copy()
names  = best_s["name"].str.replace("_", " ").values
sharpe = best_s["sharpe"].values
calmar = best_s["calmar"].values
maxdd  = best_s["max_dd%"].abs().values
cagr   = best_s["cagr%"].values

# colour bars by maxdd bucket
def dd_color(dd):
    if dd < 25:  return GREEN
    if dd < 40:  return AMBER
    if dd < 60:  return "#f97316"
    return RED

bar_colors = [dd_color(d) for d in maxdd]

fig1, axes = plt.subplots(1, 3, figsize=(20, 7), facecolor=DARK,
                          gridspec_kw={"wspace": 0.38})
fig1.suptitle("CDX NA IG — Strategy Family Comparison (best grid-search params)",
              fontsize=13, color="white", fontweight="bold", y=1.01)

y = np.arange(len(names))

for ax, vals, xlabel, title, vline in [
    (axes[0], sharpe, "Sharpe Ratio",                    "Sharpe",  0.5),
    (axes[1], calmar, "Calmar (CAGR ÷ |Max Drawdown|)",  "Calmar",  0.3),
    (axes[2], cagr,   "CAGR %",                          "CAGR %",  None),
]:
    bars = ax.barh(y, vals, color=bar_colors, edgecolor="#1a1d26", linewidth=0.5, height=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels(names, color=LITE, fontsize=8.5)
    ax.axvline(0, color=GREY, lw=0.8)
    if vline is not None:
        ax.axvline(vline, color="#4b5563", lw=0.8, ls="--", alpha=0.6)
    # value labels
    for bar, v in zip(bars, vals):
        w = bar.get_width()
        ax.text(max(w + 0.005, 0.005), bar.get_y() + bar.get_height()/2,
                f"{v:.2f}", va="center", ha="left", color=LITE, fontsize=7.5)
    style_ax(ax, title=title, xlabel=xlabel)

# Legend
legend_elements = [
    Patch(color=GREEN,   label="MaxDD < 25%"),
    Patch(color=AMBER,   label="MaxDD 25–40%"),
    Patch(color="#f97316", label="MaxDD 40–60%"),
    Patch(color=RED,     label="MaxDD > 60%"),
]
axes[2].legend(handles=legend_elements, loc="lower right", fontsize=7.5,
               facecolor="#1a1d26", labelcolor=LITE, edgecolor=GRID, framealpha=0.9)

plt.tight_layout()
fig1.savefig("cdx_strategy_bars.svg", format="svg", bbox_inches="tight", facecolor=DARK)
print("Saved: cdx_strategy_bars.svg")


# ══════════════════════════════════════════════════════════════════════════════
# CHART 2 — Per-trade return dot plots: B, J, K
# ══════════════════════════════════════════════════════════════════════════════

fig2, axes2 = plt.subplots(1, 3, figsize=(20, 6), facecolor=DARK,
                            gridspec_kw={"wspace": 0.35})
fig2.suptitle("CDX NA IG — Per-Trade Return Distribution (B / J / K)",
              fontsize=13, color="white", fontweight="bold", y=1.01)

trade_sets = [
    (b_trades, "B — Spike Onset\n(move ≥10%, hold 3d)", AMBER),
    (j_trades, "J — Tail Hold\n(move ≥8%, trail 20%, max_level 70bps)", "#d4f542"),
    (k_trades, "K — Crisis Ride\n(move ≥10%, exit revert+20%)", "#94a3b8"),
]

for ax, (tlog, label, col) in zip(axes2, trade_sets):
    rets = tlog["trade_ret_%"].values
    wins = rets > 0
    years = pd.to_datetime(tlog["entry_date"]).dt.year.values

    # scatter: year on x, return on y
    ax.scatter(years[wins],  rets[wins],  color=GREEN, s=80,  zorder=5, label="Win",  edgecolors="#1a1d26", linewidth=0.5)
    ax.scatter(years[~wins], rets[~wins], color=RED,   s=80,  zorder=5, label="Loss", edgecolors="#1a1d26", linewidth=0.5)

    # label big ones
    for _, row in tlog.iterrows():
        if abs(row["trade_ret_%"]) > 5:
            yr = pd.to_datetime(row["entry_date"]).year
            ax.annotate(f"{row['trade_ret_%']:+.1f}%",
                        (yr, row["trade_ret_%"]),
                        textcoords="offset points", xytext=(6, 3),
                        color=LITE, fontsize=6.5, alpha=0.9)

    ax.axhline(0, color=GREY, lw=0.7, ls="--")
    wr  = wins.mean() * 100
    avg = rets.mean()
    med = np.median(rets)
    ax.set_title(f"{label}\nN={len(rets)}  WR={wr:.0f}%  Avg={avg:+.1f}%  Med={med:+.1f}%",
                 color=LITE, fontsize=8.5, pad=6)
    ax.legend(fontsize=7.5, facecolor="#1a1d26", labelcolor=LITE, edgecolor=GRID)
    style_ax(ax, xlabel="Year", ylabel="Trade Return %")

plt.tight_layout()
fig2.savefig("cdx_trade_logs.svg", format="svg", bbox_inches="tight", facecolor=DARK)
print("Saved: cdx_trade_logs.svg")


# ══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Spread distribution + regime overlay
# ══════════════════════════════════════════════════════════════════════════════

fig3, (ax_ts, ax_hist) = plt.subplots(2, 1, figsize=(20, 10), facecolor=DARK,
                                       gridspec_kw={"height_ratios": [2, 1], "hspace": 0.38})
fig3.suptitle("CDX NA IG — Spread Level & Distribution (2011–2026)",
              fontsize=13, color="white", fontweight="bold", y=1.01)

# ── time series with regime bands ──────────────────────────────────────────────
regimes = [
    (0,    50,  "#1e3a5f", "Tight  < 50bps"),
    (50,   80,  "#1a3a1a", "Normal 50–80bps"),
    (80,   120, "#3a2a0a", "Elevated 80–120bps"),
    (120,  200, "#3a1a1a", "Stress > 120bps"),
]
for lo, hi, col, _ in regimes:
    ax_ts.axhspan(lo, hi, facecolor=col, alpha=0.5)
ax_ts.plot(s.index, s.values, color=BLUE, lw=0.9, alpha=0.95)
ax_ts.plot(s.rolling(63).mean().index, s.rolling(63).mean(),
           color=AMBER, lw=1.3, ls="--", alpha=0.8, label="63d SMA")

# mark the B entry dates
for _, row in b_trades.iterrows():
    if row["trade_ret_%"] > 0:
        ax_ts.axvline(row["entry_date"], color=GREEN, lw=0.9, alpha=0.5)
    else:
        ax_ts.axvline(row["entry_date"], color=RED,   lw=0.7, alpha=0.4)

# percentile lines
for pct, val, lbl in [(25, s.quantile(0.25), "Q1"), (50, s.median(), "Median"),
                       (75, s.quantile(0.75), "Q3"), (95, s.quantile(0.95), "95th")]:
    ax_ts.axhline(val, color=GRID, lw=0.6, ls=":", alpha=0.8)
    ax_ts.text(s.index[-1], val + 0.5, lbl, color="#4b5563", fontsize=7, ha="right")

legend_patches = [Patch(color=col, alpha=0.7, label=lbl)
                  for _, _, col, lbl in regimes] + [
    Patch(color=BLUE, label="CDX NA IG"),
    Patch(color=AMBER, label="63d SMA"),
    Patch(color=GREEN, alpha=0.7, label="B entry (win)"),
    Patch(color=RED,   alpha=0.6, label="B entry (loss)"),
]
ax_ts.legend(handles=legend_patches, fontsize=7, facecolor="#1a1d26",
             labelcolor=LITE, edgecolor=GRID, framealpha=0.9, loc="upper right")
ax_ts.set_ylim(bottom=0)
style_ax(ax_ts, title="Spread Level with Regime Bands & Spike Onset Entries",
         ylabel="bps", ts=True)

# ── histogram by regime ────────────────────────────────────────────────────────
regime_colors  = ["#4c9be8","#52b788","#f0a500","#e05252"]
regime_labels  = ["Tight <50", "Normal 50–80", "Elevated 80–120", "Stress >120"]
regime_bounds  = [(0,50),(50,80),(80,120),(120,300)]
bins = np.linspace(40, 160, 50)

hist_vals, _ = np.histogram(s.values, bins=bins)
ax_hist.bar(bins[:-1], hist_vals, width=np.diff(bins), color=TEAL, alpha=0.6,
            edgecolor="#1a1d26", linewidth=0.3, label="All observations")

# overlay regime-colored histograms
for (lo, hi), col, lbl in zip(regime_bounds, regime_colors, regime_labels):
    mask = (s.values >= lo) & (s.values < hi)
    h, _ = np.histogram(s.values[mask], bins=bins)
    pct_days = mask.sum() / len(s) * 100
    ax_hist.bar(bins[:-1], h, width=np.diff(bins), color=col, alpha=0.55,
                edgecolor="#1a1d26", linewidth=0.3, label=f"{lbl}  ({pct_days:.1f}%)")

ax_hist.axvline(s.median(),       color=AMBER,  lw=1.3, ls="--", label=f"Median {s.median():.0f}bps")
ax_hist.axvline(s.values[-1],     color=PINK,   lw=1.5, ls="-",  label=f"Current {s.values[-1]:.0f}bps")
ax_hist.legend(fontsize=7.5, facecolor="#1a1d26", labelcolor=LITE, edgecolor=GRID,
               framealpha=0.9, ncol=2)
style_ax(ax_hist, title="Frequency Distribution of Spread Levels",
         xlabel="Spread (bps)", ylabel="Trading Days")

plt.tight_layout()
fig3.savefig("cdx_regime_hist.svg", format="svg", bbox_inches="tight", facecolor=DARK)
print("Saved: cdx_regime_hist.svg")

print("All charts generated.")
