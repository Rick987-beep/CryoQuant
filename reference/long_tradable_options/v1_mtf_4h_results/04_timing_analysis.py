"""04_timing_analysis.py — Timing patterns for tradeable long options.

Analyses:
  1. Entry hour distribution + base rate by hour
  2. Day-of-week distribution + base rate
  3. Hold period vs DTE (how fast do options pay off by DTE?)
  4. Entry hour × DTE heatmap of base rate

Outputs:
  timing_by_hour.csv
  timing_by_dow.csv
  timing_hold_by_dte.csv
  timing_hour_dte_heatmap.csv
  timing_overview.svg
  timing_hold_by_dte.svg
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "intraday_options"))

BLUE  = "#2196F3"
GREEN = "#4CAF50"
RED   = "#F44336"
AMBER = "#FFC107"
GREY  = "#9E9E9E"

DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_t = pd.read_parquet(HERE / "tradeable_longs_enriched.parquet")
    df_c = pd.read_parquet(HERE / "candidates_summary.parquet")

    entry_dts = pd.to_datetime(df_c["entry_ts"].str.replace(" UTC", ""), utc=True)
    df_c["entry_hour_utc"]    = entry_dts.dt.hour.astype(int)
    df_c["entry_day_of_week"] = entry_dts.dt.dayofweek.astype(int)
    return df_t, df_c


# ---------------------------------------------------------------------------
# Analysis tables
# ---------------------------------------------------------------------------

def by_hour(df_t: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    """Base rate and hold stats per entry hour (0–23)."""
    df_c2 = df_c[df_c["skip_reason"] != "ask_too_low"]
    total     = df_c2.groupby("entry_hour_utc")["tradeable"].count().rename("n_candidates")
    tradeable = df_c2.groupby("entry_hour_utc")["tradeable"].sum().rename("n_tradeable")
    br        = (tradeable / total * 100).round(1).rename("base_rate_pct")

    hold_stats = (
        df_t.groupby("entry_hour_utc")
        .agg(
            median_hold_h   =("hold_hours",    "median"),
            median_net_pnl  =("net_pnl_usd",   "median"),
            median_gross_pct=("gross_gain_pct", "median"),
        )
        .round(2)
    )
    return (pd.concat([total, tradeable, br], axis=1)
            .join(hold_stats)
            .reset_index())


def by_dow(df_t: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    """Base rate and hold stats per day of week."""
    df_c2 = df_c[df_c["skip_reason"] != "ask_too_low"]
    total     = df_c2.groupby("entry_day_of_week")["tradeable"].count().rename("n_candidates")
    tradeable = df_c2.groupby("entry_day_of_week")["tradeable"].sum().rename("n_tradeable")
    br        = (tradeable / total * 100).round(1).rename("base_rate_pct")

    hold_stats = (
        df_t.groupby("entry_day_of_week")
        .agg(
            median_hold_h   =("hold_hours",    "median"),
            median_net_pnl  =("net_pnl_usd",   "median"),
        )
        .round(2)
    )
    out = (pd.concat([total, tradeable, br], axis=1)
           .join(hold_stats)
           .reset_index())
    out["day_name"] = out["entry_day_of_week"].apply(lambda d: DOW_LABELS[int(d)])
    return out


def hold_by_dte(df_t: pd.DataFrame) -> pd.DataFrame:
    """Percentile distribution of hold_hours by DTE at entry."""
    rows = []
    for dte, grp in df_t.groupby("dte_at_entry"):
        h = grp["hold_hours"]
        rows.append({
            "dte_at_entry":   int(dte),
            "n":              len(grp),
            "p10_hold_h":     h.quantile(0.10),
            "p25_hold_h":     h.quantile(0.25),
            "p50_hold_h":     h.quantile(0.50),
            "p75_hold_h":     h.quantile(0.75),
            "p90_hold_h":     h.quantile(0.90),
            "pct_under_4h":   (h <= 4).mean() * 100,
            "pct_under_12h":  (h <= 12).mean() * 100,
            "pct_under_24h":  (h <= 24).mean() * 100,
        })
    return pd.DataFrame(rows).round(2)


def hour_dte_heatmap(df_t: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    """Base rate matrix: entry hour (rows) × DTE (cols)."""
    df_c2 = df_c[df_c["skip_reason"] != "ask_too_low"]
    total     = df_c2.groupby(["entry_hour_utc", "dte_at_entry"]).size()
    tradeable = df_c2[df_c2["tradeable"]].groupby(["entry_hour_utc", "dte_at_entry"]).size()
    br = (tradeable / total * 100).unstack("dte_at_entry").round(1)
    return br


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_overview(hour_df: pd.DataFrame, dow_df: pd.DataFrame,
                  df_t: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("Tradeable Long Options — Timing Analysis", fontsize=14)

    # --- Panel 1: tradeable count + base rate by entry hour ---
    ax1 = axes[0, 0]
    x   = hour_df["entry_hour_utc"].values
    ax1.bar(x, hour_df["n_tradeable"], color=BLUE, alpha=0.8, width=0.8, label="# tradeable")
    ax1.set_xlabel("Entry hour (UTC)")
    ax1.set_ylabel("Tradeable trades", color=BLUE)
    ax1.set_xticks(range(0, 24, 2))
    ax1.tick_params(axis="y", labelcolor=BLUE)

    ax1r = ax1.twinx()
    ax1r.plot(x, hour_df["base_rate_pct"], color=AMBER, marker="o",
              linewidth=2, markersize=5, label="base rate %")
    ax1r.set_ylabel("Base rate (%)", color=AMBER)
    ax1r.tick_params(axis="y", labelcolor=AMBER)
    ax1r.set_ylim(0, 100)

    ax1.set_title("Entry Hour: Trade Count & Base Rate")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax1r.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")

    # --- Panel 2: median hold by entry hour ---
    ax2 = axes[0, 1]
    ax2.bar(x, hour_df["median_hold_h"], color=GREEN, alpha=0.8, width=0.8)
    ax2.set_xlabel("Entry hour (UTC)")
    ax2.set_ylabel("Median hold hours")
    ax2.set_xticks(range(0, 24, 2))
    ax2.set_title("Median Hold Period by Entry Hour")
    ax2.axhline(df_t["hold_hours"].median(), color="black", linestyle="--",
                linewidth=1, label=f"overall median: {df_t['hold_hours'].median():.1f}h")
    ax2.legend(fontsize=9)

    # --- Panel 3: tradeable count + base rate by day of week ---
    ax3 = axes[1, 0]
    dow_x = np.arange(len(dow_df))
    colors_dow = [GREEN if d < 5 else AMBER for d in dow_df["entry_day_of_week"]]
    ax3.bar(dow_x, dow_df["n_tradeable"], color=colors_dow, alpha=0.85, width=0.6)
    ax3.set_xticks(dow_x)
    ax3.set_xticklabels(dow_df["day_name"])
    ax3.set_ylabel("Tradeable trades")
    ax3.set_title("Day of Week: Trade Count & Base Rate")

    ax3r = ax3.twinx()
    ax3r.plot(dow_x, dow_df["base_rate_pct"], color=AMBER, marker="o",
              linewidth=2, markersize=6)
    ax3r.set_ylabel("Base rate (%)", color=AMBER)
    ax3r.tick_params(axis="y", labelcolor=AMBER)
    ax3r.set_ylim(0, 100)
    for xi, (v, n) in enumerate(zip(dow_df["base_rate_pct"], dow_df["n_tradeable"])):
        ax3.text(xi, n + 10, f"{v:.0f}%", ha="center", va="bottom", fontsize=9)

    # --- Panel 4: hold period CDF by DTE ---
    ax4 = axes[1, 1]
    dte_colors = plt.cm.viridis(np.linspace(0.1, 0.9, 7))
    for i, (dte, grp) in enumerate(df_t.groupby("dte_at_entry")):
        sorted_h = np.sort(grp["hold_hours"].values)
        cdf = np.arange(1, len(sorted_h) + 1) / len(sorted_h)
        ax4.plot(sorted_h, cdf * 100, color=dte_colors[i], linewidth=1.8,
                 label=f"DTE {int(dte)} (n={len(grp)})")
    ax4.axvline(24,  color="grey", linestyle=":", linewidth=1)
    ax4.axvline(48,  color="grey", linestyle=":", linewidth=1)
    ax4.axhline(50,  color="grey", linestyle="--", linewidth=0.8)
    ax4.axhline(80,  color="grey", linestyle="--", linewidth=0.8)
    ax4.set_xlabel("Hold hours to first 20% exit")
    ax4.set_ylabel("Cumulative % of trades")
    ax4.set_title("Hold Period CDF by DTE")
    ax4.set_xlim(0, 120)
    ax4.set_ylim(0, 100)
    ax4.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.name}")


def plot_hold_by_dte(hdt: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    dte_vals = hdt["dte_at_entry"].values
    x = np.arange(len(dte_vals))

    # Box-style: p25–p75 bar, p10–p90 whiskers, p50 line
    bar_h    = hdt["p75_hold_h"] - hdt["p25_hold_h"]
    ax.bar(x, bar_h, bottom=hdt["p25_hold_h"], color=BLUE, alpha=0.6,
           width=0.5, label="IQR (p25–p75)")
    ax.vlines(x, hdt["p10_hold_h"], hdt["p90_hold_h"],
              color=BLUE, linewidth=1.5, label="p10–p90")
    ax.scatter(x, hdt["p50_hold_h"], color="white", edgecolors=BLUE,
               s=60, zorder=5, label="median")

    for xi, row in hdt.iterrows():
        ax.text(xi, row["p90_hold_h"] + 1, f'n={int(row["n"])}',
                ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels([f"DTE {int(d)}" for d in dte_vals])
    ax.set_ylabel("Hold hours to first 20% exit")
    ax.set_title("Hold Period Distribution by DTE at Entry\n"
                 "(p10–p90 range, IQR shaded, median circle)")
    ax.legend(fontsize=9)

    ax2 = ax.twinx()
    for pct_col, color, lbl in [
        ("pct_under_4h",  RED,   "≤4h"),
        ("pct_under_24h", GREEN, "≤24h"),
    ]:
        ax2.plot(x, hdt[pct_col], color=color, marker="s",
                 linewidth=1.5, markersize=5, linestyle="--", label=f"% {lbl}")
    ax2.set_ylabel("% of trades exiting within threshold")
    ax2.set_ylim(0, 105)
    ax2.legend(fontsize=9, loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.name}")


def plot_heatmap(hm: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 7))
    data = hm.values
    im = ax.imshow(data, aspect="auto", cmap="RdYlGn",
                   vmin=0, vmax=100, interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax, fraction=0.03)
    cbar.set_label("Base rate (%)")

    ax.set_xticks(range(len(hm.columns)))
    ax.set_xticklabels([f"DTE {int(c)}" for c in hm.columns])
    ax.set_yticks(range(len(hm.index)))
    ax.set_yticklabels([f"{int(h):02d}:00" for h in hm.index])
    ax.set_xlabel("DTE at entry")
    ax.set_ylabel("Entry hour (UTC)")
    ax.set_title("Base Rate Heatmap: Entry Hour × DTE")

    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=7, color="black" if v > 30 else "white")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Loading data...")
    df_t, df_c = load_data()
    print(f"  Tradeable: {len(df_t):,}  |  All candidates: {len(df_c):,}")

    print("Computing tables...")
    hour_df = by_hour(df_t, df_c)
    dow_df  = by_dow(df_t, df_c)
    hdt     = hold_by_dte(df_t)
    hm      = hour_dte_heatmap(df_t, df_c)

    hour_df.to_csv(HERE / "timing_by_hour.csv",         index=False)
    dow_df.to_csv(HERE  / "timing_by_dow.csv",          index=False)
    hdt.to_csv(HERE     / "timing_hold_by_dte.csv",     index=False)
    hm.to_csv(HERE      / "timing_hour_dte_heatmap.csv")

    print("Generating charts...")
    plot_overview(hour_df, dow_df, df_t, HERE / "timing_overview.svg")
    plot_hold_by_dte(hdt, HERE / "timing_hold_by_dte.svg")
    plot_heatmap(hm, HERE / "timing_heatmap.svg")

    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.width", 160)

    print("\n=== By Entry Hour ===")
    print(hour_df.to_string(index=False))

    print("\n=== By Day of Week ===")
    print(dow_df[["day_name", "n_candidates", "n_tradeable",
                  "base_rate_pct", "median_hold_h"]].to_string(index=False))

    print("\n=== Hold Period by DTE ===")
    print(hdt.to_string(index=False))

    print("\n=== Hour × DTE Base Rate Heatmap ===")
    print(hm.to_string())


if __name__ == "__main__":
    main()
