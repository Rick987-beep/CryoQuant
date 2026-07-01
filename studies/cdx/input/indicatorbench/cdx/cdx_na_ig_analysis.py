"""
CDX NA IG — Full historical analysis
Covers 2011-09-09 to 2026-03-15
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyArrowPatch
import warnings
warnings.filterwarnings("ignore")

# ── Load & sort ────────────────────────────────────────────────────────────────
df = pd.read_csv(
    "/Users/ulrikdeichsel/IndicatorBench/research/cdx_na_ig.csv",
    parse_dates=["date"],
)
df = df.sort_values("date").reset_index(drop=True)
s = df.set_index("date")["cdx_na_ig"]

# ── Rolling stats ──────────────────────────────────────────────────────────────
roll63  = s.rolling(63)     # ~3-month
roll252 = s.rolling(252)    # ~1-year
s_sma63  = roll63.mean()
s_sma252 = roll252.mean()
s_std63  = roll63.std()

# Z-score relative to trailing 63-day window
zscore = (s - s_sma63) / s_std63.replace(0, np.nan)

# ── Spike detection: |z| > 2.5 or single-day jump > 10% ─────────────────────
pct_chg     = s.pct_change() * 100
spike_z     = zscore[zscore.abs() > 2.5]
spike_jump  = pct_chg[pct_chg.abs() > 10]
spike_all   = spike_z.index.union(spike_jump.index)

# ── Percentile bands ──────────────────────────────────────────────────────────
p10, p25, p50, p75, p90 = np.percentile(s.dropna(), [10, 25, 50, 75, 90])

# ── Key named stress events (approximate peaks) ───────────────────────────────
events = {
    "EU Debt Crisis peak\n(Nov 2011)":   "2011-11-25",
    "China slowdown\n(Jan 2016)":        "2016-02-11",
    "COVID crash\n(Mar 2020)":           "2020-03-23",
    "Ukraine / Fed hikes\n(Oct 2022)":   "2022-10-13",
    "SVB / bank stress\n(Mar 2023)":     "2023-03-23",
    "Tariff shock\n(Mar 2026)":          "2026-03-15",
}

# ── Figure ─────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(
    4, 1,
    figsize=(18, 22),
    gridspec_kw={"height_ratios": [4, 1.5, 1.5, 1.5]},
    facecolor="#0e1117",
)
fig.suptitle("CDX NA IG — Credit Stress Index  (2011 – 2026)", fontsize=16,
             color="white", fontweight="bold", y=0.985)

DARK  = "#0e1117"
GRID  = "#2a2d35"
BLUE  = "#4c9be8"
AMBER = "#f0a500"
RED   = "#e05252"
GREEN = "#52b788"
GREY  = "#6b7280"

for ax in axes:
    ax.set_facecolor(DARK)
    ax.tick_params(colors="white", labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.grid(axis="y", color=GRID, linewidth=0.5, linestyle="--")
    ax.grid(axis="x", color=GRID, linewidth=0.3, linestyle=":")

# ── Panel 1: full history with bands ─────────────────────────────────────────
ax = axes[0]
ax.fill_between(s.index, p75, p90, color=RED,   alpha=0.12, label=f"75–90th pct ({p75:.0f}–{p90:.0f})")
ax.fill_between(s.index, p25, p75, color=AMBER, alpha=0.10, label=f"25–75th pct ({p25:.0f}–{p75:.0f})")
ax.fill_between(s.index, p10, p25, color=GREEN, alpha=0.12, label=f"10–25th pct ({p10:.0f}–{p25:.0f})")
ax.plot(s.index, s.values,      color=BLUE,  linewidth=0.9, alpha=0.95, label="CDX NA IG spread")
ax.plot(s_sma63.index,  s_sma63.values,  color=AMBER, linewidth=1.3, linestyle="--", alpha=0.8, label="63-day SMA")
ax.plot(s_sma252.index, s_sma252.values, color=GREEN, linewidth=1.5, linestyle="--", alpha=0.8, label="252-day SMA")

# annotate named events
for label, d in events.items():
    dt = pd.Timestamp(d)
    # snap to nearest date in index
    idx = s.index.get_indexer([dt], method="nearest")[0]
    dt_actual = s.index[idx]
    val = s.iloc[idx]
    ax.axvline(dt_actual, color=RED, linewidth=0.6, alpha=0.4)
    ax.annotate(
        label, xy=(dt_actual, val),
        xytext=(0, 22), textcoords="offset points",
        fontsize=6.5, color=RED, ha="center",
        arrowprops=dict(arrowstyle="-", color=RED, lw=0.5),
    )

ax.set_ylabel("Spread (bps)", color="white", fontsize=9)
ax.set_ylim(bottom=0)
leg = ax.legend(loc="upper right", fontsize=7.5, facecolor="#1a1d26",
                labelcolor="white", edgecolor=GRID, framealpha=0.8)
ax.set_title("Full History with Percentile Bands", color="white", fontsize=10, pad=6)

# ── Panel 2: daily % change ───────────────────────────────────────────────────
ax2 = axes[1]
colors_bar = [RED if v > 0 else GREEN for v in pct_chg.values]
ax2.bar(pct_chg.index, pct_chg.values, color=colors_bar, width=1.5, alpha=0.8)
ax2.axhline(0, color=GREY, linewidth=0.5)
ax2.axhline(10,  color=RED,   linewidth=0.6, linestyle="--", alpha=0.6, label="+10% spike")
ax2.axhline(-10, color=GREEN, linewidth=0.6, linestyle="--", alpha=0.6, label="-10% spike")
ax2.set_ylabel("Daily Δ (%)", color="white", fontsize=9)
ax2.set_title("Daily % Change — Spike Detection (±10% threshold)", color="white", fontsize=10, pad=6)
leg2 = ax2.legend(loc="upper right", fontsize=7.5, facecolor="#1a1d26",
                  labelcolor="white", edgecolor=GRID, framealpha=0.8)

# ── Panel 3: rolling 63-day z-score ──────────────────────────────────────────
ax3 = axes[2]
ax3.fill_between(zscore.index, zscore.values, 0,
                 where=zscore > 0, color=RED,   alpha=0.45, interpolate=True)
ax3.fill_between(zscore.index, zscore.values, 0,
                 where=zscore < 0, color=GREEN, alpha=0.35, interpolate=True)
ax3.plot(zscore.index, zscore.values, color=BLUE, linewidth=0.6, alpha=0.7)
ax3.axhline( 2.5, color=RED,   linewidth=0.8, linestyle="--", alpha=0.7, label="±2.5σ")
ax3.axhline(-2.5, color=RED,   linewidth=0.8, linestyle="--", alpha=0.7)
ax3.axhline(0,    color=GREY,  linewidth=0.5)
ax3.set_ylabel("Z-score (63d)", color="white", fontsize=9)
ax3.set_title("Rolling 63-day Z-score", color="white", fontsize=10, pad=6)
leg3 = ax3.legend(loc="upper right", fontsize=7.5, facecolor="#1a1d26",
                  labelcolor="white", edgecolor=GRID, framealpha=0.8)

# ── Panel 4: rolling 252-day percentile rank ─────────────────────────────────
pctrank = s.rolling(252).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100)
ax4 = axes[3]
ax4.fill_between(pctrank.index, pctrank.values, color=BLUE, alpha=0.3)
ax4.plot(pctrank.index, pctrank.values, color=BLUE, linewidth=0.8)
ax4.axhline(80, color=RED,   linewidth=0.7, linestyle="--", alpha=0.7, label="80th pct (elevated)")
ax4.axhline(20, color=GREEN, linewidth=0.7, linestyle="--", alpha=0.7, label="20th pct (calm)")
ax4.set_ylabel("1-yr pct rank", color="white", fontsize=9)
ax4.set_title("1-Year Rolling Percentile Rank", color="white", fontsize=10, pad=6)
ax4.set_ylim(0, 100)
leg4 = ax4.legend(loc="upper right", fontsize=7.5, facecolor="#1a1d26",
                  labelcolor="white", edgecolor=GRID, framealpha=0.8)
ax4.set_xlabel("Year", color="white", fontsize=9)

plt.tight_layout(rect=[0, 0, 1, 0.983])
out_chart = "/Users/ulrikdeichsel/IndicatorBench/research/cdx_na_ig_chart.png"
fig.savefig(out_chart, dpi=150, bbox_inches="tight", facecolor=DARK)
print(f"Chart saved: {out_chart}")

# ── Text analytics ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("CDX NA IG — ANALYTICS SUMMARY")
print("="*60)
print(f"\nDate range : {s.index.min().date()} → {s.index.max().date()}  ({len(s):,} obs)")
print(f"Current    : {s.iloc[-1]:.2f} bps  ({s.index[-1].date()})")
print(f"\n--- Spread Distribution ---")
print(f"  Min    : {s.min():.2f} bps  ({s.idxmin().date()})")
print(f"  p10    : {np.percentile(s,10):.2f} bps")
print(f"  p25    : {np.percentile(s,25):.2f} bps")
print(f"  Median : {np.percentile(s,50):.2f} bps")
print(f"  Mean   : {s.mean():.2f} bps")
print(f"  p75    : {np.percentile(s,75):.2f} bps")
print(f"  p90    : {np.percentile(s,90):.2f} bps")
print(f"  Max    : {s.max():.2f} bps  ({s.idxmax().date()})")
print(f"  Skew   : {s.skew():.2f}  (>0 = fat right tail)")
print(f"  Kurt   : {s.kurt():.2f}  (>3 = excess kurtosis / fat tails)")

print(f"\n--- Current Level Context ---")
cur = s.iloc[-1]
cur_pct = (s <= cur).mean() * 100
print(f"  {cur:.1f} bps is at the {cur_pct:.0f}th percentile of the full history")
print(f"  Distance from median : {cur - np.percentile(s,50):+.1f} bps")
print(f"  Distance from 90th pct: {cur - np.percentile(s,90):+.1f} bps")

print(f"\n--- Spike Events (daily |Δ| > 10%) ---")
spikes = spike_jump.sort_values(key=abs, ascending=False)
print(f"  Total spikes: {len(spikes)}")
for dt, v in spikes.head(15).items():
    print(f"  {dt.date()}  {v:+.1f}%   spread={s.loc[dt]:.1f} bps")

print(f"\n--- Annual Max Spreads ---")
annual_max = s.groupby(s.index.year).max()
for yr, mx in annual_max.items():
    bar = "█" * int(mx / 10)
    print(f"  {yr}  {mx:6.1f} bps  {bar}")

print(f"\n--- Curve Shape Assessment ---")
from scipy.stats import skew, kurtosis
sk = skew(s.dropna())
ku = kurtosis(s.dropna())
print(f"  Skewness : {sk:.2f}")
print(f"  Excess kurtosis : {ku:.2f}")
if sk > 1.5:
    print("  → Distribution is strongly RIGHT-SKEWED: most of the time spreads")
    print("    are low, but rare stress events pull the tail far to the right.")
elif sk > 0.5:
    print("  → Moderately right-skewed: occasional stress spikes dominate the tail.")
print(f"\n  Regime summary by year bucket:")
print(f"  Tight  (<50 bps) : {(s<50).mean()*100:.0f}% of all observations")
print(f"  Normal (50-80)   : {((s>=50)&(s<80)).mean()*100:.0f}% of all observations")
print(f"  Elevated (80-120): {((s>=80)&(s<120)).mean()*100:.0f}% of all observations")
print(f"  Stress (>120 bps): {(s>=120).mean()*100:.0f}% of all observations")
