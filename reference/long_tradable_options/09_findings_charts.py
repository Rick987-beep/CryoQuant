"""09_findings_charts.py — Phase 3 findings summary charts.

Four dark-theme SVG charts:
  09_named_conditions.svg  — mag_win@2.5% bar chart for all named conditions
  09_threshold_curves.svg  — win-rate gradient 1.5%→3.5% for top conditions
  09_call_put_map.svg      — call vs put win rates scatter (straddle vs directional)
  09_regime_context.svg    — historical vs recent-3wk comparison

Usage:
    python3 research/long_tradable_options/09_findings_charts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# ── Palette ──────────────────────────────────────────────────────────────────
BG       = "#1c1c1e"
CARD     = "#2c2c2e"
FG       = "#f2f2f7"
SUBTLE   = "#8e8e93"
GREEN    = "#30d158"
YELLOW   = "#ffd60a"
ORANGE   = "#ff9f0a"
RED      = "#ff453a"
BLUE     = "#0a84ff"
TEAL     = "#5ac8fa"
PURPLE   = "#bf5af2"
PINK     = "#ff375f"

def _fig(w: float, h: float):
    fig, ax = plt.subplots(figsize=(w, h), facecolor=BG)
    ax.set_facecolor(CARD)
    for spine in ax.spines.values():
        spine.set_edgecolor(SUBTLE)
    ax.tick_params(colors=FG, labelsize=9)
    return fig, ax

def _save(fig, name: str) -> None:
    path = HERE / name
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved {name}")

# ── Named conditions data ─────────────────────────────────────────────────────
#
# All from 06_conditions.csv (full analysis window 2025-01-01 → 2026-05-15).
# "Named" conditions only — subset chosen for the plan document.

CONDITIONS = [
    # (short_name, label, fw_wk, mag_1p5, mag_2p0, mag_2p5, mag_3p0, mag_3p5, call_2p5, put_2p5, signal_type)
    ("baseline",     "Baseline (no Sat)",          144.1, .79, .63, .48, .36, .27, .24, .27, "straddle"),
    ("vol_regime",   "vol_regime\n(rv_rank≥0.60, no Sat)", 58.0, .83, .69, .56, .44, .34, .26, .34, "puts"),
    ("vol_burst",    "vol_burst\n(vol_z≥1.5 + rv≥0.60)",   6.3,  .87, .73, .61, .47, .36, .35, .33, "straddle"),
    ("vol_surge",    "vol_surge\n(vol_z≥2.0 + rv≥0.60)",   4.2,  .87, .74, .63, .49, .38, .35, .35, "straddle"),
    ("bb_extreme",   "bb_extreme\n(BB-width ≥ 90th pct)",   16.8, .91, .81, .71, .58, .49, .37, .41, "straddle"),
    ("bear_burst",   "bear_burst\n(4h<-0.5% + vol_z≥1.5 + rv≥0.60)", 2.2, .90, .82, .73, .62, .50, .40, .44, "straddle"),
    ("pullback",     "pullback\n(EITHER MTF + rv≥0.60)",   3.4,  .94, .82, .73, .63, .52, .44, .39, "straddle"),
    ("bull_pullback","bull_pullback\n(4h≥+1% + 1h≤-0.5% + rv≥0.60)", 1.5, .95, .79, .68, .59, .46, .39, .34, "straddle"),
    ("bear_pullback","bear_pullback\n(4h≤-1% + 1h≥+0.5% + rv≥0.60)", 1.9, .94, .84, .76, .66, .57, .47, .43, "straddle"),
    ("bb_squeeze",   "bb_squeeze\n(BB-width ≤ 25th pct,  reference)", 42.0, .59, .43, .30, .22, .15, .15, .16, "straddle"),
]

NAMES      = [c[0] for c in CONDITIONS]
LABELS     = [c[1] for c in CONDITIONS]
FPW        = [c[2] for c in CONDITIONS]
MAG_15     = [c[3] for c in CONDITIONS]
MAG_20     = [c[4] for c in CONDITIONS]
MAG_25     = [c[5] for c in CONDITIONS]
MAG_30     = [c[6] for c in CONDITIONS]
MAG_35     = [c[7] for c in CONDITIONS]
CALL_25    = [c[8] for c in CONDITIONS]
PUT_25     = [c[9] for c in CONDITIONS]
STYPES     = [c[10] for c in CONDITIONS]

# ── Recent-3wk data (from 08_recent_check output) ────────────────────────────
RECENT = {
    "baseline":     .20,
    "vol_regime":   .21,
    "vol_burst":    .21,
    "vol_surge":    .33,
    "bb_extreme":   .26,
    "bear_burst":   .43,
    "pullback":     .50,
    "bull_pullback": None,  # 0 fires
    "bear_pullback": .50,
    "bb_squeeze":   .22,
}

# ─────────────────────────────────────────────────────────────────────────────
# Chart 1: Named conditions — mag_win@2.5% horizontal bar chart
# ─────────────────────────────────────────────────────────────────────────────
def chart_conditions() -> None:
    n = len(CONDITIONS)
    fig, ax = _fig(11, 8)

    y = np.arange(n)
    bar_h = 0.6

    baseline_wr = .48   # BASELINE (no Sat) at 2.5%

    # Color bars by frequency bucket
    colors = []
    for fpw_val, name in zip(FPW, NAMES):
        if name == "baseline":
            colors.append(SUBTLE)
        elif name == "bb_squeeze":
            colors.append(RED)
        elif 2.0 <= fpw_val <= 10.0:
            colors.append(GREEN)    # sweet-spot frequency
        elif fpw_val < 2.0:
            colors.append(TEAL)     # too rare
        else:
            colors.append(ORANGE)   # too frequent (use as filter)

    bars = ax.barh(y, MAG_25, height=bar_h, color=colors, alpha=0.85, zorder=3)

    # Baseline reference line
    ax.axvline(baseline_wr, color=SUBTLE, linewidth=1.0, linestyle="--", zorder=2)
    ax.text(baseline_wr + 0.005, n - 0.3, "baseline\n48%", color=SUBTLE, fontsize=7.5, va="top")

    # Value labels on bars
    for i, (val, fpw_val) in enumerate(zip(MAG_25, FPW)):
        ax.text(val + 0.007, y[i], f"{val:.0%}  ({fpw_val:.1f}/wk)",
                va="center", ha="left", color=FG, fontsize=8.5)

    ax.set_yticks(y)
    ax.set_yticklabels(LABELS, fontsize=8.5, color=FG)
    ax.set_xlim(0, 1.18)
    ax.set_xlabel("mag_win @ 2.5% threshold", color=FG, fontsize=10)
    ax.set_title("Named Conditions — Win Rate (mag_win @ 2.5%)\nfull analysis window  2025-01-01 → 2026-05-15",
                 color=FG, fontsize=11, pad=14)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="x", color=SUBTLE, alpha=0.25, zorder=1)

    # Legend
    legend_items = [
        mpatches.Patch(color=GREEN,  label="sweet-spot freq  (2–10/wk)"),
        mpatches.Patch(color=TEAL,   label="low freq  (<2/wk)"),
        mpatches.Patch(color=ORANGE, label="high freq — use as filter"),
        mpatches.Patch(color=RED,    label="reference (squeeze)"),
    ]
    ax.legend(handles=legend_items, loc="lower right", framealpha=0.2,
              labelcolor=FG, fontsize=8, facecolor=CARD, edgecolor=SUBTLE)

    fig.tight_layout()
    _save(fig, "09_named_conditions.svg")


# ─────────────────────────────────────────────────────────────────────────────
# Chart 2: Threshold curves  (win rate 1.5% → 3.5% for top conditions)
# ─────────────────────────────────────────────────────────────────────────────
def chart_threshold_curves() -> None:
    fig, ax = _fig(10, 6)

    thresholds = [1.5, 2.0, 2.5, 3.0, 3.5]

    selected = [
        ("pullback",     MAG_15[6], MAG_20[6], MAG_25[6], MAG_30[6], MAG_35[6], GREEN,  "-",  "o"),
        ("bear_pullback",MAG_15[8], MAG_20[8], MAG_25[8], MAG_30[8], MAG_35[8], TEAL,   "-",  "s"),
        ("vol_burst",    MAG_15[2], MAG_20[2], MAG_25[2], MAG_30[2], MAG_35[2], YELLOW, "-",  "^"),
        ("bear_burst",   MAG_15[5], MAG_20[5], MAG_25[5], MAG_30[5], MAG_35[5], ORANGE, "-",  "D"),
        ("bb_extreme",   MAG_15[4], MAG_20[4], MAG_25[4], MAG_30[4], MAG_35[4], PURPLE, "--", "x"),
        ("vol_regime",   MAG_15[1], MAG_20[1], MAG_25[1], MAG_30[1], MAG_35[1], BLUE,   ":",  "v"),
        ("baseline",     MAG_15[0], MAG_20[0], MAG_25[0], MAG_30[0], MAG_35[0], SUBTLE, "--", "+"),
        ("bb_squeeze",   MAG_15[9], MAG_20[9], MAG_25[9], MAG_30[9], MAG_35[9], RED,    ":",  "P"),
    ]

    for name, w15, w20, w25, w30, w35, col, ls, mk in selected:
        ys = [w15, w20, w25, w30, w35]
        ax.plot(thresholds, ys, color=col, linestyle=ls, marker=mk,
                markersize=6, linewidth=1.8, label=name, zorder=3)
        # Annotate the 2.5% point
        ax.text(2.5 + 0.04, w25 + 0.005, f"{w25:.0%}", color=col, fontsize=7.5)

    ax.set_xlabel("Price-move threshold (%)", color=FG, fontsize=10)
    ax.set_ylabel("mag_win rate", color=FG, fontsize=10)
    ax.set_title("Win-Rate vs Threshold  (1.5% → 3.5%)\n"
                 "full analysis window  2025-01-01 → 2026-05-15",
                 color=FG, fontsize=11, pad=14)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlim(1.3, 3.7)
    ax.set_xticks(thresholds)
    ax.set_xticklabels([f"{t}%" for t in thresholds])
    ax.grid(color=SUBTLE, alpha=0.25, zorder=1)
    ax.legend(loc="upper right", framealpha=0.2, labelcolor=FG,
              fontsize=8.5, facecolor=CARD, edgecolor=SUBTLE)

    # Strike-selection guidance box
    ax.axvspan(1.8, 2.2, alpha=0.07, color=GREEN, zorder=0)
    ax.text(2.0, 0.02, "← primary\n   strike zone", ha="center", color=GREEN,
            fontsize=7.5, style="italic")

    fig.tight_layout()
    _save(fig, "09_threshold_curves.svg")


# ─────────────────────────────────────────────────────────────────────────────
# Chart 3: Call vs Put scatter  (straddle vs directional map)
# ─────────────────────────────────────────────────────────────────────────────
def chart_call_put_map() -> None:
    fig, ax = _fig(9, 7)

    for i, (name, label, fpw_val, c, p, stype) in enumerate(
            zip(NAMES, LABELS, FPW, CALL_25, PUT_25, STYPES)):

        short_label = label.split("\n")[0]
        color = {
            "calls":    BLUE,
            "puts":     ORANGE,
            "straddle": GREEN,
        }.get(stype, SUBTLE)

        size = max(30, min(fpw_val * 10, 300))
        ax.scatter(c, p, s=size, color=color, alpha=0.75, zorder=3,
                   edgecolors=FG, linewidths=0.5)
        ax.annotate(short_label, (c, p),
                    textcoords="offset points", xytext=(6, 4),
                    color=FG, fontsize=7.5, zorder=4)

    # Diagonal = equal call & put
    lo, hi = 0.05, 0.60
    ax.plot([lo, hi], [lo, hi], color=SUBTLE, linewidth=1.0, linestyle="--", zorder=2)
    ax.text(0.43, 0.45, "equal  →  straddle", color=SUBTLE, fontsize=7.5,
            rotation=43, style="italic")

    # Region labels
    ax.text(0.42, 0.14, "call-biased zone", color=BLUE, fontsize=8, style="italic", alpha=0.7)
    ax.text(0.09, 0.44, "put-biased zone",  color=ORANGE, fontsize=8, style="italic", alpha=0.7, rotation=90)

    ax.set_xlabel("call_win @ 2.5%", color=FG, fontsize=10)
    ax.set_ylabel("put_win @ 2.5%", color=FG, fontsize=10)
    ax.set_title("Call vs Put Win Rates @ 2.5%\n"
                 "bubble size = fires/week  |  colour = signal_type",
                 color=FG, fontsize=11, pad=14)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlim(0.05, 0.60)
    ax.set_ylim(0.05, 0.60)
    ax.grid(color=SUBTLE, alpha=0.25, zorder=1)

    legend_items = [
        mpatches.Patch(color=GREEN,  label="straddle"),
        mpatches.Patch(color=BLUE,   label="calls-biased"),
        mpatches.Patch(color=ORANGE, label="puts-biased"),
    ]
    ax.legend(handles=legend_items, loc="upper left", framealpha=0.2,
              labelcolor=FG, fontsize=8.5, facecolor=CARD, edgecolor=SUBTLE)

    fig.tight_layout()
    _save(fig, "09_call_put_map.svg")


# ─────────────────────────────────────────────────────────────────────────────
# Chart 4: Historical vs recent-3wk regime comparison
# ─────────────────────────────────────────────────────────────────────────────
def chart_regime_context() -> None:
    # Only show conditions with both historical and recent data
    show = [c for c in CONDITIONS if RECENT.get(c[0]) is not None and c[0] != "bb_squeeze"]
    names_s     = [c[0] for c in show]
    labels_s    = [c[1].split("\n")[0] for c in show]
    hist_wr     = [c[5] for c in show]
    recent_wr   = [RECENT[n] for n in names_s]
    fpw_s       = [c[2] for c in show]

    n = len(show)
    fig, ax = _fig(11, 6.5)

    x   = np.arange(n)
    w   = 0.36

    bars_h = ax.bar(x - w/2, hist_wr,   width=w, color=GREEN,  alpha=0.80, label="Historical  (16 months)",   zorder=3)
    bars_r = ax.bar(x + w/2, recent_wr, width=w, color=ORANGE, alpha=0.80, label="Recent  (last 3 weeks)",  zorder=3)

    # Value labels
    for bar_h_obj, val in zip(bars_h, hist_wr):
        ax.text(bar_h_obj.get_x() + bar_h_obj.get_width()/2, val + 0.008,
                f"{val:.0%}", ha="center", va="bottom", color=FG, fontsize=8)
    for bar_r_obj, val in zip(bars_r, recent_wr):
        ax.text(bar_r_obj.get_x() + bar_r_obj.get_width()/2, val + 0.008,
                f"{val:.0%}", ha="center", va="bottom", color=FG, fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(labels_s, fontsize=8.5, color=FG, rotation=18, ha="right")
    ax.set_ylabel("mag_win @ 2.5%", color=FG, fontsize=10)
    ax.set_title("Regime Context — Historical vs Recent 3 Weeks\n"
                 "mag_win @ 2.5%  |  recent = 2026-04-26 → 2026-05-15",
                 color=FG, fontsize=11, pad=14)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_ylim(0, 1.0)
    ax.grid(axis="y", color=SUBTLE, alpha=0.25, zorder=1)

    # Regime annotation
    ax.text(0.97, 0.95,
            "Recent regime: low vol (rv_rank 0.25–0.60)\n"
            "BTC calm uptrend — strategy correctly quiet",
            transform=ax.transAxes, ha="right", va="top",
            color=SUBTLE, fontsize=8, style="italic",
            bbox=dict(boxstyle="round,pad=0.4", facecolor=CARD, edgecolor=SUBTLE, alpha=0.8))

    ax.legend(loc="upper left", framealpha=0.2, labelcolor=FG,
              fontsize=9, facecolor=CARD, edgecolor=SUBTLE)

    fig.tight_layout()
    _save(fig, "09_regime_context.svg")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("Generating Phase 3 findings charts …")
    chart_conditions()
    chart_threshold_curves()
    chart_call_put_map()
    chart_regime_context()
    print("Done.")


if __name__ == "__main__":
    main()
