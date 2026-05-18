"""05_v2_charts.py — Generate SVG charts summarising V2 signal discovery findings.

Reads CSV outputs from 03_v2_signal_discovery.py and 04_v2_kernel.py.

Charts produced
---------------
  v2_vol_regime.svg       — Vol regime: iv_rank + hv_1d quintile bars
  v2_dte_price.svg        — Universe: DTE breakdown + price tier + cross-tab heatmap
  v2_feature_auc.svg      — Feature AUC ranking (all features)
  v2_top_combos.svg       — Top filter combinations (combined 03 + 04)
  v2_momentum.svg         — Calls vs puts 4h-momentum + MTF pullback pattern
  v2_mtf_heatmap.svg      — MTF heatmap for calls (4h × 1h momentum win rates)
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.colors as mcolors
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# ── Palette (matches V1 style) ───────────────────────────────────────────────
BLUE    = "#2196F3"
GREEN   = "#4CAF50"
RED     = "#F44336"
AMBER   = "#FFC107"
TEAL    = "#009688"
PURPLE  = "#9C27B0"
GRAY    = "#90A4AE"
DKGRAY  = "#546E7A"
BASE_RATE_DTE15 = 0.232   # DTE 1-5, no price floor

plt.rcParams.update({
    "font.family"        : "DejaVu Sans",
    "axes.spines.top"    : False,
    "axes.spines.right"  : False,
    "axes.grid"          : True,
    "axes.grid.axis"     : "y",
    "grid.alpha"         : 0.35,
    "grid.linewidth"     : 0.6,
    "svg.fonttype"       : "none",   # keep text as text in SVG
})

# ── Shared helpers ────────────────────────────────────────────────────────────

def _findings_box(fig: plt.Figure, bullets: list[str],
                  y: float = 0.03, fontsize: float = 8.5) -> None:
    """Add a grey findings box at the bottom of the figure."""
    # Escape $ so matplotlib doesn't treat them as math delimiters
    safe = [b.replace("$", r"\$") for b in bullets]
    text = "Findings:\n" + "\n".join(f"  \u2022 {b}" for b in safe)
    fig.text(
        0.015, y, text,
        transform=fig.transFigure,
        fontsize=fontsize, va="bottom", ha="left",
        linespacing=1.55,
        color="#1a1a1a",
        bbox=dict(
            boxstyle="round,pad=0.5",
            facecolor="#F3F4F6",
            edgecolor="#CBD5E1",
            linewidth=0.8,
            alpha=0.95,
        ),
    )


def _bar_colors(values: list[float], base: float,
                hi_col: str = GREEN, lo_col: str = RED,
                mid_col: str = GRAY) -> list[str]:
    """Color bars: green if well above base rate, red if below, gray otherwise."""
    cols = []
    for v in values:
        if np.isnan(v):
            cols.append(GRAY)
        elif v >= base + 0.04:
            cols.append(hi_col)
        elif v < base - 0.02:
            cols.append(lo_col)
        else:
            cols.append(mid_col)
    return cols


def _save(fig: plt.Figure, name: str) -> None:
    path = HERE / name
    fig.savefig(path, format="svg", bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  saved → {name}")


# =============================================================================
# Chart 1: Vol Regime (iv_rank quintiles + hv_1d quintiles)
# =============================================================================

def chart_vol_regime() -> None:
    iv   = pd.read_csv(HERE / "03_vol_regime_iv_rank.csv")
    hv1d = pd.read_csv(HERE / "03_vol_regime_hv1d.csv")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Vol Regime at Entry  —  Win Rate by Quintile\n"
                 "Universe: DTE 1–5, no price floor  |  Base rate = 23.2%",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.subplots_adjust(bottom=0.28, wspace=0.35)

    # Panel 1: iv_30d_pct_rank
    ax = axes[0]
    labels = [f"Q{i+1}" for i in range(len(iv))]
    wr     = iv["win_rate"].tolist()
    cols   = _bar_colors(wr, BASE_RATE_DTE15)
    bars   = ax.bar(labels, wr, color=cols, width=0.55, edgecolor="white", linewidth=0.5)
    ax.axhline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.2, label="base rate")
    for bar, v, n in zip(bars, wr, iv["n"].tolist()):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.004,
                f"{v:.1%}", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, 0.005,
                f"n={n//1000:.0f}k", ha="center", va="bottom", fontsize=7, color="#666")
    ax.set_title("IV Rank — 30d Percentile", fontsize=11)
    ax.set_xlabel("Quintile (Q1=lowest, Q5=highest)", fontsize=9)
    ax.set_ylabel("Win rate (2× in 24h)", fontsize=9)
    ax.set_ylim(0, max(wr) * 1.22)
    ax.legend(fontsize=8)
    # Add quintile edge labels
    for i, row in iv.iterrows():
        qstr = str(row["quintile"])
        m = re.search(r'\(([\d.]+),\s*([\d.]+)\]', qstr)
        lbl = f"{float(m.group(1)):.2f}→{float(m.group(2)):.2f}" if m else qstr
        ax.text(i, -0.018, lbl, ha="center", va="top", fontsize=6, color="#888", rotation=25)

    # Panel 2: hv_1d
    ax = axes[1]
    wr2   = hv1d["win_rate"].tolist()
    cols2 = _bar_colors(wr2, BASE_RATE_DTE15)
    bars2 = ax.bar(labels, wr2, color=cols2, width=0.55, edgecolor="white", linewidth=0.5)
    ax.axhline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.2, label="base rate")
    for bar, v, n in zip(bars2, wr2, hv1d["n"].tolist()):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.004,
                f"{v:.1%}", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, 0.005,
                f"n={n//1000:.0f}k", ha="center", va="bottom", fontsize=7, color="#666")
    ax.set_title("Realised Volatility (HV 1d)", fontsize=11)
    ax.set_xlabel("Quintile (Q1=lowest HV, Q5=highest)", fontsize=9)
    ax.set_ylabel("Win rate (2× in 24h)", fontsize=9)
    ax.set_ylim(0, max(wr2) * 1.22)
    ax.legend(fontsize=8)
    for i, row in hv1d.iterrows():
        qstr = str(row["quintile"])
        m = re.search(r'\(([\d.]+),\s*([\d.]+)\]', qstr)
        lbl = f"{float(m.group(1)):.1f}→{float(m.group(2)):.1f}" if m else qstr
        ax.text(i, -0.018, lbl, ha="center", va="top", fontsize=6, color="#888", rotation=25)

    _findings_box(fig, [
        "iv_30d_pct_rank is the primary signal: win rate climbs monotonically Q1→Q5 (16.9% → 31.1%), a 1.84× lift.",
        "hv_1d Q5 (>55% ann. HV) matches: 30.5% win rate. Q2 dips below Q1 — signal is 'high HV', not 'rising HV'.",
        "Combining iv_rank≥Q5 + hv≥median yields 33% win rate; the two features are complementary, not redundant.",
        "iv_hv_ratio is noise (AUC 0.506, Q1–Q5 spread only 4pp) — confirmed, drop from all kernels.",
        "Average winner multiple rises in Q5 too (2.16× for iv_rank, 2.29× for hv_1d) — not just more winners but larger.",
    ], y=0.01)
    _save(fig, "v2_vol_regime.svg")


# =============================================================================
# Chart 2: DTE + Price tier overview
# =============================================================================

def chart_dte_price() -> None:
    dte_df   = pd.read_csv(HERE / "03_universe_dte.csv")
    price_df = pd.read_csv(HERE / "03_universe_price.csv")
    cross_df = pd.read_csv(HERE / "03_universe_cross.csv")

    fig = plt.figure(figsize=(16, 8))
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.55, wspace=0.40,
                            top=0.88, bottom=0.28)
    fig.suptitle("Universe Breakdown: DTE Tier  ×  Entry Price\n"
                 "Win Rate = fraction reaching 2× ask within 24h",
                 fontsize=13, fontweight="bold")

    # Panel A: win rate by DTE
    ax_dte = fig.add_subplot(gs[0, :2])
    dte_rows = dte_df[dte_df["filter"].str.startswith("DTE")]
    dtes  = [int(r.split()[-1]) for r in dte_rows["filter"]]
    wr_d  = dte_rows["win_rate"].tolist()
    mult  = dte_rows["avg_multiple"].tolist()
    cols  = _bar_colors(wr_d, BASE_RATE_DTE15)
    bars  = ax_dte.bar([str(d) for d in dtes], wr_d, color=cols, width=0.55,
                       edgecolor="white")
    ax_dte.axhline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.2, label="base rate")
    for bar, v, m, n in zip(bars, wr_d, mult, dte_rows["n_options"].tolist()):
        ax_dte.text(bar.get_x() + bar.get_width() / 2, v + 0.004,
                    f"{v:.1%}\n×{m:.2f}", ha="center", va="bottom", fontsize=8.5)
        ax_dte.text(bar.get_x() + bar.get_width() / 2, 0.003,
                    f"n={n//1000:.0f}k", ha="center", va="bottom", fontsize=7, color="#666")
    ax_dte.set_title("Win Rate by DTE  (DTE 6-7 excluded as <10% win rate)", fontsize=10)
    ax_dte.set_xlabel("Days to Expiry at entry", fontsize=9)
    ax_dte.set_ylabel("Win rate", fontsize=9)
    ax_dte.set_ylim(0, max(wr_d) * 1.25)
    ax_dte.legend(fontsize=8)

    # Panel B: win rate by price tier
    ax_p = fig.add_subplot(gs[0, 2])
    price_rows = price_df[price_df["filter"].str.contains(r"\$")]
    wr_p  = price_rows["win_rate"].fillna(0).tolist()
    labs  = price_rows["filter"].tolist()
    cols2 = _bar_colors(wr_p, BASE_RATE_DTE15)
    bars2 = ax_p.barh(labs, wr_p, color=cols2, height=0.55, edgecolor="white")
    ax_p.axvline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.2)
    for bar, v in zip(bars2, wr_p):
        if v > 0.01:
            ax_p.text(v + 0.003, bar.get_y() + bar.get_height() / 2,
                      f"{v:.1%}", va="center", fontsize=8)
    ax_p.set_title("Win Rate by\nEntry Price Tier", fontsize=10)
    ax_p.set_xlabel("Win rate", fontsize=8)
    ax_p.set_xlim(0, max(wr_p) * 1.3)

    # Panel C: DTE × price heatmap
    ax_h = fig.add_subplot(gs[1, :])
    price_cols = [c for c in cross_df.columns if c != "dte_at_entry"]
    hm_data    = cross_df.set_index("dte_at_entry")[price_cols].values.astype(float)
    dtes_hm    = cross_df["dte_at_entry"].tolist()

    cmap = plt.cm.RdYlGn
    cmap.set_bad(color="#E0E0E0")
    im = ax_h.imshow(hm_data, aspect="auto", cmap=cmap,
                     vmin=0.0, vmax=0.42, interpolation="nearest")
    ax_h.set_xticks(range(len(price_cols)))
    ax_h.set_xticklabels(price_cols, fontsize=8)
    ax_h.set_yticks(range(len(dtes_hm)))
    ax_h.set_yticklabels([f"DTE {d}" for d in dtes_hm], fontsize=9)
    ax_h.set_title("Win Rate Heatmap: DTE × Entry Price Tier", fontsize=10)
    ax_h.grid(False)
    # Annotate cells
    for i in range(len(dtes_hm)):
        for j in range(len(price_cols)):
            v = hm_data[i, j]
            if not np.isnan(v) and v > 0:
                fg = "white" if v > 0.30 else "black"
                ax_h.text(j, i, f"{v:.0%}", ha="center", va="center",
                          fontsize=8.5, color=fg, fontweight="bold")
    plt.colorbar(im, ax=ax_h, shrink=0.7, pad=0.02, label="Win rate")

    _findings_box(fig, [
        "DTE 1 and 2 have highest win rates (28.1%, 27.3%) AND avg multiples (2.51×, 2.14×). Short-dated = better.",
        "DTE 4-5 drop to 17–18%; drop is structural, not just price — keep as supplementary, not primary.",
        "Price <$50: 0% winners — fee drag + wide spreads kill profitability. Soft floor at $100+ recommended.",
        "DTE 1 + $250-500: 34.3% win rate — the sweet spot; high gamma, affordable but not too cheap.",
        "DTE 3 in vol regime is still viable (21%); pair with iv_rank≥0.75 to lift to ~33%.",
    ], y=0.01)
    _save(fig, "v2_dte_price.svg")


# =============================================================================
# Chart 3: Feature AUC Ranking
# =============================================================================

def chart_feature_auc() -> None:
    auc = pd.read_csv(HERE / "03_feature_auc.csv").sort_values("auc_all")
    labels = auc["feature"].tolist()
    vals   = auc["auc_all"].tolist()
    calls_ = auc["auc_calls"].tolist()
    puts_  = auc["auc_puts"].tolist()

    # Highlight top-3
    cols = []
    for i, v in enumerate(vals):
        rank = len(vals) - i  # rank from top
        if rank <= 3:
            cols.append(BLUE)
        elif v < 0.50:
            cols.append(RED)
        else:
            cols.append(GRAY)

    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    fig.suptitle("Feature Predictive Power — Mann-Whitney AUC\n"
                 "AUC=0.5 is random; higher = better separator of winners vs non-winners",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.subplots_adjust(bottom=0.28, wspace=0.55)

    # Panel 1: overall AUC
    ax = axes[0]
    bars = ax.barh(labels, vals, color=cols, height=0.65, edgecolor="white")
    ax.axvline(0.5, color=DKGRAY, linestyle="--", linewidth=1.2, label="random (0.5)")
    ax.axvline(0.55, color=AMBER, linestyle=":", linewidth=1.0, alpha=0.7, label="weak threshold (0.55)")
    for bar, v in zip(bars, vals):
        ax.text(v + 0.001, bar.get_y() + bar.get_height() / 2,
                f"{v:.3f}", va="center", fontsize=8.5,
                color=BLUE if v >= sorted(vals)[-3] else "#333")
    ax.set_title("Overall AUC", fontsize=11)
    ax.set_xlabel("AUC", fontsize=9)
    ax.set_xlim(0.39, 0.65)
    ax.legend(fontsize=8, loc="lower right")

    # Panel 2: calls vs puts AUC for top features
    top_feats  = auc.nlargest(8, "auc_all")
    x          = np.arange(len(top_feats))
    w          = 0.35
    ax2        = axes[1]
    ax2.barh(x + w/2, top_feats["auc_calls"].tolist(), w, color=BLUE,
             label="Calls", edgecolor="white")
    ax2.barh(x - w/2, top_feats["auc_puts"].tolist(), w, color=RED,
             label="Puts", edgecolor="white")
    ax2.axvline(0.5, color=DKGRAY, linestyle="--", linewidth=1.2)
    ax2.set_yticks(x)
    ax2.set_yticklabels(top_feats["feature"].tolist(), fontsize=9)
    ax2.set_title("Top 8 Features: Calls vs Puts AUC", fontsize=11)
    ax2.set_xlabel("AUC", fontsize=9)
    ax2.set_xlim(0.46, 0.68)
    ax2.legend(fontsize=9)
    for i, (vc, vp) in enumerate(zip(top_feats["auc_calls"], top_feats["auc_puts"])):
        ax2.text(vc + 0.001, i + w/2, f"{vc:.3f}", va="center", fontsize=7.5, color=BLUE)
        ax2.text(vp + 0.001, i - w/2, f"{vp:.3f}", va="center", fontsize=7.5, color=RED)

    _findings_box(fig, [
        "atm_iv_at_entry (AUC 0.587) and iv_30d_pct_rank (0.579) are co-primary signals — absolute + relative IV both matter.",
        "hv_1d (0.564) is the third signal; combined with iv_rank it adds non-redundant information.",
        "aligned_4h momentum (0.516) is real but weak solo; it matters as a confirmatory condition, not primary.",
        "dte_at_entry AUC=0.435 (<0.5) means lower DTE predicts winners — structural edge of short-dated options confirmed.",
        "Spread, iv_hv_ratio, spot_vs_24h_ema, accel ≈ noise (0.48–0.51). Do NOT build primary conditions on these.",
        "Calls have consistently higher AUC than puts on vol features: vol regime favours calls more than puts.",
    ], y=0.01)
    _save(fig, "v2_feature_auc.svg")


# =============================================================================
# Chart 4: Top Combinations
# =============================================================================

def chart_top_combos() -> None:
    c03 = pd.read_csv(HERE / "03_combinations.csv")
    c04 = pd.read_csv(HERE / "04_kernel_combos.csv")

    # Merge, deduplicate keeping best win_rate per filter name
    combined = (pd.concat([c03, c04], ignore_index=True)
                .sort_values("win_rate", ascending=False)
                .drop_duplicates(subset="filter", keep="first"))

    # Show top 20 by win_rate where fires_per_week >= 2
    top = (combined[combined["fires_per_week"] >= 2.0]
           .nlargest(20, "win_rate")
           .iloc[::-1])   # reverse for horizontal bars (best at top)

    fig, ax = plt.subplots(figsize=(14, 9))
    fig.suptitle("Top 20 Filter Combinations  (≥2 fires/week)\n"
                 "Sorted by win rate  |  Base rate = 23.2%  |  DTE 1–5",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.subplots_adjust(left=0.42, bottom=0.25, right=0.95)

    wr      = top["win_rate"].tolist()
    mult    = top["avg_multiple"].tolist()
    fpw     = top["fires_per_week"].tolist()
    labels  = top["filter"].tolist()
    y_pos   = np.arange(len(labels))

    # Color by fires_per_week
    norm    = mcolors.Normalize(vmin=2, vmax=40)
    cmap    = plt.cm.YlGn
    cols    = [cmap(norm(f)) for f in fpw]

    bars = ax.barh(y_pos, wr, color=cols, height=0.65, edgecolor="white", linewidth=0.4)
    ax.axvline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.3, label="base rate 23.2%")

    for bar, v, m, f in zip(bars, wr, mult, fpw):
        ax.text(v + 0.002, bar.get_y() + bar.get_height() / 2,
                f"{v:.1%}  ×{m:.2f}  {f:.0f}/wk",
                va="center", fontsize=8)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.set_xlabel("Win rate (2× peak in 24h)", fontsize=10)
    ax.set_xlim(0.18, 0.55)
    ax.legend(fontsize=9, loc="lower right")

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    plt.colorbar(sm, ax=ax, label="Fires / week", pad=0.01, shrink=0.7)

    _findings_box(fig, [
        "Best combo: CALLS + DTE 1-2 + iv_rank≥0.75 + hv≥med + aligned_4h>0 → 43.0% win rate, 2.45× avg, 9.2/week.",
        "Undifferentiated DTE 1-2 + iv_rank≥0.75 + hv≥med + aligned_4h>0 → 39.6%, 2.82×, 23.2/week — best high-frequency kernel.",
        "Crash-entry calls (4h≤-3%) hit 39.7%+ but only fire 1.7/week — use as supplementary overlay, not primary signal.",
        "DTE restriction to 1-2 adds +4-7pp win rate vs DTE 1-5 for the same vol conditions; avg multiple lifts to 2.5-2.8×.",
        "MTF pullback (4h=+1:+3%, 1h≤-0.5%) is 66% but fires 0.6/week — exceptional quality but too rare to trade alone.",
    ], y=0.01)
    _save(fig, "v2_top_combos.svg")


# =============================================================================
# Chart 5: Calls vs Puts 4h Momentum
# =============================================================================

def chart_momentum() -> None:
    calls4h = pd.read_csv(HERE / "03_mtf_calls_4h.csv")
    puts4h  = pd.read_csv(HERE / "03_mtf_puts_4h.csv")

    # Also load kernel combos for MTF pullback
    k04 = pd.read_csv(HERE / "04_kernel_combos.csv")
    mtf = k04[k04["section"] == "C"].copy()

    fig, axes = plt.subplots(1, 3, figsize=(17, 7))
    fig.suptitle("Directional Momentum at Entry  —  4h Bucket Win Rates\n"
                 "Calls: raw spot 4h change  |  Puts: sign-inverted (positive = aligned fall)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.subplots_adjust(bottom=0.28, wspace=0.45)

    bucks = calls4h["bucket"].tolist()
    x     = np.arange(len(bucks))
    w     = 0.36

    # Panel 1: Calls
    ax = axes[0]
    wr_c = calls4h["win_rate"].tolist()
    cols_c = _bar_colors(wr_c, BASE_RATE_DTE15, hi_col=BLUE, lo_col=RED)
    bars_c = ax.bar(x, wr_c, color=cols_c, width=0.62, edgecolor="white")
    ax.axhline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.2, label="base rate")
    for bar, v in zip(bars_c, wr_c):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.004,
                f"{v:.1%}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(bucks, rotation=35, ha="right", fontsize=8)
    ax.set_title("CALLS — 4h spot momentum", fontsize=11)
    ax.set_ylabel("Win rate", fontsize=9)
    ax.set_ylim(0, max(wr_c) * 1.3)
    ax.legend(fontsize=8)

    # Panel 2: Puts (inverted)
    ax2   = axes[1]
    wr_p  = puts4h["win_rate"].tolist()
    cols_p = _bar_colors(wr_p, BASE_RATE_DTE15, hi_col=RED, lo_col=GRAY)
    bars_p = ax2.bar(x, wr_p, color=cols_p, width=0.62, edgecolor="white")
    ax2.axhline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.2, label="base rate")
    for bar, v in zip(bars_p, wr_p):
        ax2.text(bar.get_x() + bar.get_width() / 2, v + 0.004,
                 f"{v:.1%}", ha="center", va="bottom", fontsize=8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(bucks, rotation=35, ha="right", fontsize=8)
    ax2.set_title("PUTS — aligned 4h momentum\n(positive = spot fell)", fontsize=11)
    ax2.set_ylabel("Win rate", fontsize=9)
    ax2.set_ylim(0, max(wr_p) * 1.3)
    ax2.legend(fontsize=8)

    # Panel 3: MTF pullback combos
    ax3    = axes[2]
    mtf_s  = mtf.nlargest(8, "win_rate").iloc[::-1]
    labels = [r.replace("CALLS  +  ", "").replace("  +  ", " + ")
              for r in mtf_s["filter"].tolist()]
    wr_m   = mtf_s["win_rate"].tolist()
    fpw_m  = mtf_s["fires_per_week"].tolist()
    y_pos  = np.arange(len(labels))
    norm   = mcolors.Normalize(vmin=2, vmax=35)
    cmap   = plt.cm.Blues
    cols_m = [cmap(norm(f)) for f in fpw_m]
    ax3.barh(y_pos, wr_m, color=cols_m, height=0.6, edgecolor="white")
    ax3.axvline(BASE_RATE_DTE15, color=DKGRAY, linestyle="--", linewidth=1.2)
    for i, (v, f) in enumerate(zip(wr_m, fpw_m)):
        ax3.text(v + 0.003, i, f"{v:.1%}  {f:.0f}/wk", va="center", fontsize=8)
    ax3.set_yticks(y_pos)
    ax3.set_yticklabels(labels, fontsize=7.5)
    ax3.set_title("MTF Pullback Combos (Calls)\n4h uptrend + 1h pullback", fontsize=11)
    ax3.set_xlabel("Win rate", fontsize=9)
    ax3.set_xlim(0.18, 0.50)

    _findings_box(fig, [
        "Calls after 4h crash (≤-3%): 37.6% win rate, avg 2.66× — IV expansion + recovery. Puts in same scenario: 22.6% only.",
        "Calls after strong 4h rally (≥+3%): 38.1% — continuation works too. Both extremes outperform directionless entries.",
        "Puts are less responsive to 4h momentum (max 32.2% at extreme); calls are the primary vehicle in vol regimes.",
        "MTF pullback (4h=+1:+3%, 1h=-1.5:-.5%) fires 0.6/week at 66.2% — too rare to trade alone, but pair with vol signal.",
        "'Any pullback' (4h≥+1%, 1h<0) broadens to 4.6/week at 30.9% — practical but weaker; add vol filter to lift to 34%+.",
    ], y=0.01)
    _save(fig, "v2_momentum.svg")


# =============================================================================
# Chart 6: MTF Heatmap — Calls (4h × 1h)
# =============================================================================

def chart_mtf_heatmap() -> None:
    mtf_wide = pd.read_csv(HERE / "03_mtf_calls.csv")
    row_labs  = mtf_wide["b4h"].tolist()
    col_labs  = [c for c in mtf_wide.columns if c != "b4h"]
    data      = mtf_wide[col_labs].values.astype(float)

    # Load counts (from the 03 script stdout — we regenerate from kernel combos isn't easy,
    # so we embed the count data from the last run as a reference overlay)
    COUNT_DATA = np.array([
        [260,  183,   42,   38,   24,   92,   18],
        [289, 2092, 1564,  942,  682,  283,   18],
        [ 30, 1515, 3759, 3987, 1802,  366,    0],
        [ 39,  678, 4414, 9838, 3796, 1010,   32],
        [  0,  493, 1435, 4259, 3450, 1224,   43],
        [  0,  198,  673, 1004, 1348, 1842,  320],
        [  0,   34,   31,   19,   20,  204,  135],
    ], dtype=float)
    COUNT_DATA[COUNT_DATA == 0] = np.nan

    fig, axes = plt.subplots(1, 2, figsize=(17, 7))
    fig.suptitle("MTF Heatmap — CALLS ONLY\n"
                 "Rows = 4h spot momentum bucket  |  Cols = 1h spot momentum bucket",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.subplots_adjust(bottom=0.28, wspace=0.35)

    cmap = plt.cm.RdYlGn
    cmap.set_bad(color="#E0E0E0")

    for ax, matrix, title, fmt in [
        (axes[0], np.where(np.isnan(data), np.nan, data), "Win Rate", ".0%"),
        (axes[1], COUNT_DATA,                              "Sample Count (n)", ".0f"),
    ]:
        masked = np.ma.array(matrix, mask=np.isnan(matrix))
        if "Win" in title:
            im = ax.imshow(masked, aspect="auto", cmap=cmap,
                           vmin=0.10, vmax=0.70, interpolation="nearest")
        else:
            log_m = np.log10(np.where(np.isnan(matrix), np.nan, matrix + 1))
            im = ax.imshow(np.ma.array(log_m, mask=np.isnan(log_m)),
                           aspect="auto", cmap=plt.cm.Blues,
                           vmin=0, vmax=4, interpolation="nearest")

        ax.set_xticks(range(len(col_labs)))
        ax.set_xticklabels(col_labs, rotation=35, ha="right", fontsize=8)
        ax.set_yticks(range(len(row_labs)))
        ax.set_yticklabels(row_labs, fontsize=9)
        ax.set_xlabel("1h spot momentum", fontsize=9)
        ax.set_ylabel("4h spot momentum", fontsize=9)
        ax.set_title(title, fontsize=11)
        ax.grid(False)
        plt.colorbar(im, ax=ax, shrink=0.85, pad=0.02)

        for i in range(len(row_labs)):
            for j in range(len(col_labs)):
                v = matrix[i, j]
                if not np.isnan(v) and v > 0:
                    if "Win" in title:
                        fg = "white" if v > 0.50 else "black"
                        ax.text(j, i, f"{v:.0%}", ha="center", va="center",
                                fontsize=8, color=fg, fontweight="bold")
                    else:
                        fg = "white" if v > 500 else "black"
                        ax.text(j, i, f"{int(v)}", ha="center", va="center",
                                fontsize=7, color=fg)

    # Highlight the key cell: 4h row=5 "+1:+3%", 1h col=1 "-1.5:-.5%"
    axes[0].add_patch(plt.Rectangle((0.5, 4.5), 1, 1,
                                    fill=False, edgecolor="gold", linewidth=2.5,
                                    label="66% pullback cell (n=198)"))
    axes[0].legend(fontsize=8, loc="upper right")

    _findings_box(fig, [
        "Key pullback cell (gold box): 4h=+1:+3% + 1h=-1.5:-.5% → 66.2% win rate (n=198). 'Buy the dip in uptrend' confirmed.",
        "Crash recovery (4h=<-3%): 38–93% win rates but tiny n — IV spike + mean-reversion. Opportunistic overlay only.",
        "Centre zone (4h≈0, 1h≈0) is the dead zone: 19–22%. Directionless entries are structurally weak.",
        "The pullback pattern requires real 4h momentum (+1:+3%) — wider to +0.3% dilutes win rate significantly.",
        "Combining with iv_rank≥0.60 adds +8pp on the pullback cell (75%) but fires only 0.3/week — extreme quality/frequency trade-off.",
    ], y=0.01)
    _save(fig, "v2_mtf_heatmap.svg")


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    print("Generating V2 charts...")
    chart_vol_regime()
    chart_dte_price()
    chart_feature_auc()
    chart_top_combos()
    chart_momentum()
    chart_mtf_heatmap()
    print("Done. All SVGs written to", HERE)


if __name__ == "__main__":
    main()
