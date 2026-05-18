"""
07_v2_spot_charts.py
====================
Human-readable SVG charts summarising the Phase 3 spot-signal discovery
(script 06_v2_spot_signals.py).

Charts produced
---------------
  07_feature_auc.svg      — Feature AUC bar chart (train + test), coloured by sig.
  07_conditions.svg       — Combination conditions: mag_win rate + fires/wk bubble
  07_bucket_heatmap.svg   — Decile win-rate heatmap for all 6 validated features
  07_dow_session.svg      — Day-of-week & hour-of-day win-rate bar charts

All files saved to the same directory as this script.
"""

from pathlib import Path
import re
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np


def _parse_lower(bucket_str):
    """Extract lower bound float from '(lo, hi]' or '[lo, hi)' bucket string."""
    m = re.search(r'[\[(]\s*(-?[\d.]+)', str(bucket_str))
    return float(m.group(1)) if m else np.nan

# ── paths ─────────────────────────────────────────────────────────────────────
HERE   = Path(__file__).parent
AUC_F  = HERE / "06_feature_auc.csv"
VAL_F  = HERE / "06_train_test_validation.csv"
BKT_F  = HERE / "06_bucket_winrates.csv"
COND_F = HERE / "06_conditions.csv"

# ── helpers ───────────────────────────────────────────────────────────────────
GREY_BG   = "#1c1c1e"
GREY_CARD = "#2c2c2e"
C_PASS    = "#34c759"   # green
C_FAIL    = "#636366"   # mid-grey
C_ACCENT  = "#0a84ff"   # blue
C_AMBER   = "#ff9f0a"
C_RED     = "#ff453a"
WHITE     = "#ffffff"
LIGHT     = "#aeaeb2"

def _fig(w, h):
    fig = plt.figure(figsize=(w, h), facecolor=GREY_BG)
    return fig

def _save(fig, name):
    out = HERE / name
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=GREY_BG)
    plt.close(fig)
    print(f"  → saved {name}")

FEATURE_LABELS = {
    "rv_24h":        "rv_24h (24h realised vol)",
    "bb_width":      "bb_width (Bollinger width)",
    "rv_rank":       "rv_rank (vol percentile)",
    "vol_z":         "vol_z (volume z-score)",
    "range_ratio":   "range_ratio (bar range / avg)",
    "close_vs_ema168": "ema168_dev (price vs 7-d EMA)",
    "rv_trend":      "rv_trend (vol direction)",
    "ret_1h":        "ret_1h",
    "ret_4h":        "ret_4h",
    "ret_1d":        "ret_1d",
    "accel_1h":      "accel_1h",
    "close_vs_ema24": "ema24_dev (price vs 1-d EMA)",
}

# ══════════════════════════════════════════════════════════════════════════════
#  CHART 1 — Feature AUC  (train & test,  mag_win @ 2.5%)
# ══════════════════════════════════════════════════════════════════════════════
def chart_feature_auc():
    auc  = pd.read_csv(AUC_F)
    val  = pd.read_csv(VAL_F)

    # keep mag_win only
    mag_auc = auc[auc.target == "mag_win"].set_index("feature")
    mag_val = val[val.target == "mag_win"].set_index("feature")

    # sort by train AUC descending (fold around 0.5 for display)
    features = mag_auc.sort_values("auc", ascending=False).index.tolist()

    train_auc = [mag_auc.loc[f, "auc"] for f in features]
    test_auc  = [mag_val.loc[f, "test_auc"] for f in features]
    sig       = [mag_auc.loc[f, "significant"] for f in features]
    labels    = [FEATURE_LABELS.get(f, f) for f in features]

    y   = np.arange(len(features))
    fig = _fig(11, 7)
    ax  = fig.add_subplot(111, facecolor=GREY_CARD)

    # Bars: train AUC as signed distance from 0.5
    for i, (ta, te, s) in enumerate(zip(train_auc, test_auc, sig)):
        col = C_PASS if s else C_FAIL
        ax.barh(i, ta, left=0, height=0.55, color=col, alpha=0.85, zorder=2)
        ax.plot(te, i, marker="D", ms=7, color=WHITE, zorder=4,
                markeredgecolor=GREY_BG, markeredgewidth=0.8)
        ax.text(max(ta, 0.505) + 0.003, i, f"{ta:.3f}", va="center",
                ha="left", fontsize=8, color=col if s else LIGHT)

    ax.axvline(0.5, color=WHITE, lw=1.2, ls="--", alpha=0.5, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9, color=WHITE)
    ax.set_xlim(0.38, 0.72)
    ax.set_xlabel("Mann-Whitney AUC  (train bar, ◆ = test)", color=LIGHT, fontsize=10)
    ax.tick_params(axis="x", colors=LIGHT)
    ax.tick_params(axis="y", length=0)
    for sp in ax.spines.values():
        sp.set_edgecolor(GREY_BG)

    # legend
    p1 = mpatches.Patch(color=C_PASS, label="Bonferroni-significant (p<0.005)")
    p2 = mpatches.Patch(color=C_FAIL, label="Not significant")
    p3 = plt.Line2D([0], [0], marker="D", color="w", ms=7,
                    markeredgecolor=GREY_BG, label="Test AUC")
    ax.legend(handles=[p1, p2, p3], loc="lower right", framealpha=0.3,
              fontsize=8, labelcolor=WHITE, facecolor=GREY_BG)

    ax.set_title(
        "Feature discriminability — mag_win ≥ 2.5% in next 24 h  (BTCUSDT 1h, 2025)",
        color=WHITE, fontsize=12, pad=12)

    fig.text(0.01, 0.02,
             "AUC > 0.5 → feature value predicts big move.  AUC < 0.5 → inverse (extreme/crash bars predict big move).",
             fontsize=7.5, color=LIGHT)

    _save(fig, "07_feature_auc.svg")


# ══════════════════════════════════════════════════════════════════════════════
#  CHART 2 — Combination conditions  (bubble chart: lift vs fires/wk)
# ══════════════════════════════════════════════════════════════════════════════
def chart_conditions():
    cond = pd.read_csv(COND_F)
    baseline_mask = cond["filter"] == "BASELINE  (all bars)"
    baseline_mag  = cond.loc[baseline_mask, "wr_mag_2p5"].values[0]

    # drop baseline row for plotting
    df = cond[~baseline_mask].copy()
    df["lift"] = df["wr_mag_2p5"] / baseline_mag

    # group colours
    def _group(f):
        if "4h" in f:         return "MTF momentum"
        if "rv_rank" in f and "vol_z" in f: return "Vol + spike combo"
        if "rv_rank" in f:    return "Vol regime"
        if "bb_width" in f:   return "BB width"
        if "vol_z" in f:      return "Volume spike"
        if "range_ratio" in f: return "Range expansion"
        if "US open" in f or "Asia" in f: return "Session"
        return "Other"

    GROUP_COLORS = {
        "MTF momentum":     C_ACCENT,
        "Vol + spike combo": C_PASS,
        "Vol regime":       C_AMBER,
        "BB width":         C_RED,
        "Volume spike":     "#bf5af2",
        "Range expansion":  "#64d2ff",
        "Session":          LIGHT,
        "Other":            C_FAIL,
    }

    df["group"] = df["filter"].apply(_group)

    fig = _fig(13, 8)
    ax  = fig.add_subplot(111, facecolor=GREY_CARD)

    seen_groups = set()
    for _, row in df.iterrows():
        g   = row["group"]
        col = GROUP_COLORS[g]
        sz  = max(30, row["fires_per_week"] * 12)
        label = g if g not in seen_groups else None
        seen_groups.add(g)
        ax.scatter(row["fires_per_week"], row["wr_mag_2p5"], s=sz, c=col,
                   alpha=0.80, edgecolors=GREY_BG, linewidths=0.8,
                   label=label, zorder=3)

    # annotate a few key points
    interesting = {
        "4h <= -1%  +  1h >= +0.5%  (puts pullback)": "Puts pullback\n76.3%",
        "rv_rank>=0.75  +  4h>=+1%  +  1h<=-0.5%":   "rv75+MTF\n74.0%",
        "rv_rank>=0.60  +  vol_z>=1.5  +  range_ratio>=1.5": "rv60+spike+range\n62.6%",
        "vol_z >= 1.5  +  rv_rank >= 0.60":            "rv60+volSpike\n60.9%",
        "rv_rank >= 0.75":                              "rv_rank≥0.75\n56.5%",
        "bb_width <= 25th pct  (squeeze)":              "BB squeeze\n30.3%",
    }
    for _, row in df.iterrows():
        note = interesting.get(row["filter"])
        if note:
            ax.annotate(note,
                        xy=(row["fires_per_week"], row["wr_mag_2p5"]),
                        xytext=(8, 6), textcoords="offset points",
                        fontsize=7.5, color=WHITE, alpha=0.9,
                        arrowprops=dict(arrowstyle="-", color=LIGHT, lw=0.6))

    ax.axhline(baseline_mag, color=WHITE, lw=1.2, ls="--", alpha=0.5)
    ax.text(df["fires_per_week"].max() * 0.75, baseline_mag + 0.005,
            f"Baseline {baseline_mag:.1%}", color=LIGHT, fontsize=8)

    ax.set_xlabel("Fires per week (trading frequency)", color=LIGHT, fontsize=10)
    ax.set_ylabel("mag_win rate @ 2.5% (≥2.5% in 24h)", color=LIGHT, fontsize=10)
    ax.tick_params(colors=LIGHT)
    for sp in ax.spines.values():
        sp.set_edgecolor(GREY_BG)

    ax.legend(fontsize=8, labelcolor=WHITE, facecolor=GREY_BG,
              framealpha=0.4, loc="lower right", title="Condition type",
              title_fontsize=8)

    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_title(
        "Entry conditions — magnitude win rate vs trading frequency  (2025–2026)",
        color=WHITE, fontsize=12, pad=12)
    fig.text(0.01, 0.02,
             "Bubble size ∝ fires/week.  Dashed line = baseline 44.0%.  "
             "Seek top-right (high win rate + reasonable frequency).",
             fontsize=7.5, color=LIGHT)

    _save(fig, "07_conditions.svg")


# ══════════════════════════════════════════════════════════════════════════════
#  CHART 3 — Decile bucket heatmap  (6 validated features, mag_win @ 2.5%)
# ══════════════════════════════════════════════════════════════════════════════
def chart_bucket_heatmap():
    bkt = pd.read_csv(BKT_F)

    validated = ["bb_width", "rv_24h", "rv_rank", "vol_z", "range_ratio", "close_vs_ema168"]
    mag_bkt   = bkt[(bkt.target == "mag_win_2p5") &
                    (bkt.feature.isin(validated))].copy()
    mag_bkt["lower_bound"] = mag_bkt["bucket"].apply(_parse_lower)

    # build heatmap matrix: rows = feature, cols = decile rank 0 (lowest) → 9 (highest)
    # each feature is already sorted by value; assign rank 0..9 per feature
    mat   = np.full((len(validated), 10), np.nan)
    fnames = []

    for fi, feat in enumerate(validated):
        sub = mag_bkt[mag_bkt.feature == feat].copy()
        # sort by decile label to get ascending value order
        sub = sub.sort_values("lower_bound").reset_index(drop=True)
        for di in range(min(10, len(sub))):
            mat[fi, di] = sub.loc[di, "win_rate"]
        fnames.append(FEATURE_LABELS.get(feat, feat))

    fig = _fig(13, 5)
    ax  = fig.add_subplot(111, facecolor=GREY_CARD)

    baseline = 0.384   # train base rate
    # center colormap at baseline
    vmin, vmax = 0.15, 0.85
    im = ax.imshow(mat, aspect="auto", cmap="RdYlGn",
                   vmin=vmin, vmax=vmax, interpolation="nearest")

    for fi in range(len(validated)):
        for di in range(10):
            v = mat[fi, di]
            if not np.isnan(v):
                txt_col = "black" if 0.35 < v < 0.65 else "white"
                ax.text(di, fi, f"{v:.0%}", ha="center", va="center",
                        fontsize=7.5, color=txt_col, fontweight="bold")

    ax.set_yticks(range(len(validated)))
    ax.set_yticklabels(fnames, fontsize=9, color=WHITE)
    ax.set_xticks(range(10))
    ax.set_xticklabels([f"D{i+1}" for i in range(10)], fontsize=8, color=LIGHT)
    ax.set_xlabel("Decile  (D1 = lowest feature value → D10 = highest)", color=LIGHT, fontsize=9)
    for sp in ax.spines.values():
        sp.set_edgecolor(GREY_BG)
    ax.tick_params(length=0)

    cb = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cb.ax.tick_params(colors=LIGHT)
    cb.set_label("mag_win rate", color=LIGHT, fontsize=8)
    cb.ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))

    ax.set_title(
        "Decile win-rates for validated features  (train set, mag_win ≥ 2.5%, 24h)",
        color=WHITE, fontsize=12, pad=12)
    fig.text(0.01, 0.02,
             "Green = above-baseline win rate.  Red = below baseline.  "
             "D10 = extreme high value of the feature.",
             fontsize=7.5, color=LIGHT)

    _save(fig, "07_bucket_heatmap.svg")


# ══════════════════════════════════════════════════════════════════════════════
#  CHART 4 — Day-of-week & hour effects
# ══════════════════════════════════════════════════════════════════════════════
def chart_session():
    """Session effects: DOW and hour data embedded from script 06 output."""

    # Day-of-week data (from Section C output, mag_win @ 2.5%, full analysis window)
    dow_data = {
        "Thu": 0.521,
        "Sun": 0.473,
        "Mon": 0.456,
        "Wed": 0.427,
        "Tue": 0.425,
        "Fri": 0.263,
        "Sat": 0.124,
    }
    dow_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # Hour data (from Section C output, mag_win @ 2.5%, full analysis window)
    # hours 0–23, win rates from the printed table
    hour_wr_map = {
        0: 0.392, 1: 0.382, 2: 0.408, 3: 0.426, 4: 0.397, 5: 0.382,
        6: 0.364, 7: 0.375, 8: 0.379, 9: 0.368, 10: 0.349, 11: 0.346,
        12: 0.371, 13: 0.401, 14: 0.371, 15: 0.393, 16: 0.371, 17: 0.375,
        18: 0.386, 19: 0.408, 20: 0.408, 21: 0.401, 22: 0.393, 23: 0.371,
    }
    hours = list(range(24))
    hr_wr = [hour_wr_map[h] for h in hours]

    baseline = 0.440

    fig = _fig(14, 5.5)
    gs  = gridspec.GridSpec(1, 2, figure=fig, wspace=0.15, left=0.07, right=0.97)

    # ── left: DOW ─────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0], facecolor=GREY_CARD)
    vals  = [dow_data[d] for d in dow_order]
    cols  = [C_PASS if v >= baseline else C_RED for v in vals]
    bars = ax1.bar(dow_order, vals, color=cols, alpha=0.85, zorder=2)
    for bar, v in zip(bars, vals):
        ax1.text(bar.get_x() + bar.get_width()/2, v + 0.007,
                 f"{v:.0%}", ha="center", va="bottom", fontsize=9, color=WHITE)
    ax1.axhline(baseline, color=WHITE, lw=1.2, ls="--", alpha=0.5)
    ax1.text(0.01, baseline + 0.012, f"Baseline {baseline:.0%}",
             transform=ax1.get_yaxis_transform(), fontsize=8, color=LIGHT)
    ax1.set_ylim(0, 0.65)
    ax1.set_ylabel("mag_win rate (≥2.5%)", color=LIGHT, fontsize=9)
    ax1.set_title("Day of Week", color=WHITE, fontsize=11, pad=8)
    ax1.tick_params(colors=LIGHT)
    for sp in ax1.spines.values():
        sp.set_edgecolor(GREY_BG)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))

    # ── right: hour ───────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1], facecolor=GREY_CARD)
    cols_hr = [C_PASS if v >= baseline else C_RED for v in hr_wr]
    ax2.bar(hours, hr_wr, color=cols_hr, alpha=0.85, zorder=2, width=0.8)
    ax2.axhline(baseline, color=WHITE, lw=1.2, ls="--", alpha=0.5)
    ax2.set_xlim(-0.5, 23.5)
    ax2.set_ylim(0, 0.65)
    ax2.set_xlabel("Hour (UTC)", color=LIGHT, fontsize=9)
    ax2.set_title("Hour of Day (UTC)", color=WHITE, fontsize=11, pad=8)
    ax2.tick_params(colors=LIGHT)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    for sp in ax2.spines.values():
        sp.set_edgecolor(GREY_BG)
    # shade US open
    ax2.axvspan(13, 17, alpha=0.12, color=C_ACCENT, label="US open (13–17 UTC)")
    ax2.legend(fontsize=7.5, labelcolor=WHITE, facecolor=GREY_BG, framealpha=0.4)

    fig.suptitle(
        "Session effects on magnitude win rate  (mag_win ≥ 2.5%, 2025–2026)",
        color=WHITE, fontsize=12, y=1.01)
    fig.text(0.01, -0.04,
             "Bars below baseline shown in red.  Thursday is the most active day.  "
             "Saturday is a dead zone (12%).  Hourly effects are weak (+/- 5 pp).",
             fontsize=7.5, color=LIGHT)

    _save(fig, "07_dow_session.svg")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Generating spot-signal discovery charts …")
    chart_feature_auc()
    chart_conditions()
    chart_bucket_heatmap()
    chart_session()
    print("Done.")
