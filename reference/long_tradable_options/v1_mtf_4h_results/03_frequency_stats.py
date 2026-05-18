"""03_frequency_stats.py — Base rates and breakdowns for tradeable long options.

Loads tradeable_longs_enriched.parquet + candidates_summary.parquet.

Outputs:
  freq_by_dte.csv          — base rate, count, hold stats by DTE
  freq_by_delta.csv        — same by delta bucket
  freq_by_side.csv         — calls vs puts
  freq_momentum.csv        — base rate by prior spot move bucket (4h)
  freq_overview.svg        — 2×2 summary chart
  freq_momentum.svg        — spot momentum vs base rate (calls/puts)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "intraday_options"))

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_t = pd.read_parquet(HERE / "tradeable_longs_enriched.parquet")
    df_c = pd.read_parquet(HERE / "candidates_summary.parquet")

    # Parse entry_hour and entry_day from candidates_summary (string timestamps)
    entry_dts = pd.to_datetime(df_c["entry_ts"].str.replace(" UTC", ""), utc=True)
    df_c["entry_hour_utc"]    = entry_dts.dt.hour.astype(int)
    df_c["entry_day_of_week"] = entry_dts.dt.dayofweek.astype(int)

    return df_t, df_c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_rate_table(df_c: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Compute base rate per group from candidates_summary."""
    grp = df_c.groupby(group_col)["tradeable"]
    total     = grp.count().rename("n_candidates")
    tradeable = grp.sum().rename("n_tradeable")
    br = (tradeable / total * 100).round(1).rename("base_rate_pct")
    return pd.concat([total, tradeable, br], axis=1).reset_index()


def _hold_stats(df_t: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Median hold hours and net PnL per group from tradeable trades."""
    return (
        df_t.groupby(group_col)
        .agg(
            median_hold_h   =("hold_hours",   "median"),
            median_net_pnl  =("net_pnl_usd",  "median"),
            median_gross_pct=("gross_gain_pct","median"),
        )
        .round(2)
        .reset_index()
    )


def _delta_bucket(delta_abs: pd.Series) -> pd.Series:
    bins   = [0.09, 0.125, 0.175, 0.225, 0.275, 0.325, 0.375, 0.45]
    labels = ["0.10", "0.15", "0.20", "0.25", "0.30", "0.35", "0.40"]
    return pd.cut(delta_abs, bins=bins, labels=labels)


def _momentum_bucket(chg_pct: pd.Series) -> pd.Series:
    bins   = [-np.inf, -3, -1.5, -0.5, 0.5, 1.5, 3, np.inf]
    labels = ["<-3%", "-3–-1.5%", "-1.5–-0.5%", "-0.5–+0.5%",
              "+0.5–+1.5%", "+1.5–+3%", ">+3%"]
    return pd.cut(chg_pct, bins=bins, labels=labels)


# ---------------------------------------------------------------------------
# Analysis tables
# ---------------------------------------------------------------------------

def by_dte(df_t: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    br = _base_rate_table(df_c[df_c["skip_reason"] != "ask_too_low"], "dte_at_entry")
    hs = _hold_stats(df_t, "dte_at_entry")
    return br.merge(hs, on="dte_at_entry", how="left")


def by_delta(df_t: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    df_c2 = df_c[df_c["skip_reason"] != "ask_too_low"].copy()
    df_c2["delta_bucket"] = _delta_bucket(df_c2["delta_at_entry"].abs())
    df_t2 = df_t.copy()
    df_t2["delta_bucket"] = _delta_bucket(df_t2["delta_at_entry"].abs())

    br = _base_rate_table(df_c2.dropna(subset=["delta_bucket"]), "delta_bucket")
    hs = _hold_stats(df_t2.dropna(subset=["delta_bucket"]), "delta_bucket")
    return br.merge(hs, on="delta_bucket", how="left")


def by_side(df_t: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    df_c2 = df_c[df_c["skip_reason"] != "ask_too_low"].copy()
    df_c2["side"] = df_c2["is_call"].map({True: "Call", False: "Put"})
    df_t2 = df_t.copy()
    df_t2["side"] = df_t2["is_call"].map({True: "Call", False: "Put"})

    br = _base_rate_table(df_c2, "side")
    hs = _hold_stats(df_t2, "side")
    return br.merge(hs, on="side", how="left")


def by_momentum(df_t: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    """Base rate by prior 4h spot move, separate for calls and puts."""
    rows = []
    for side, is_call in [("Call", True), ("Put", False)]:
        sub_c = df_c[
            (df_c["is_call"] == is_call) &
            (df_c["skip_reason"] != "ask_too_low")
        ].copy()
        sub_t = df_t[df_t["is_call"] == is_call].copy()

        # Need spot_4h_chg_pct in candidates_summary — not there, but in tradeable
        # Approximate by using only the tradeable trades' momentum distribution
        # and the total candidates per bucket
        # Better: join tradeable to candidates to get prior moves for all candidates
        # Since candidates_summary doesn't have spot context, we use tradeable trades
        # and note this is the distribution OF SUCCESSFUL trades, not base rate by momentum.
        sub_t["mom_bucket"] = _momentum_bucket(sub_t["spot_4h_chg_pct"])
        grp = (sub_t.groupby("mom_bucket", observed=True)
               .agg(n=("net_pnl_usd", "count"),
                    median_hold=("hold_hours", "median"),
                    pct_direction_correct=("direction_correct", "mean"))
               .reset_index())
        grp["side"] = side
        rows.append(grp)
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

BLUE  = "#2196F3"
GREEN = "#4CAF50"
RED   = "#F44336"
AMBER = "#FFC107"


def plot_overview(dte_df: pd.DataFrame, delta_df: pd.DataFrame,
                  side_df: pd.DataFrame, df_t: pd.DataFrame,
                  out_path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Tradeable Long Options — Frequency & Base Rate Overview", fontsize=14)

    # --- Panel 1: base rate by DTE ---
    ax = axes[0, 0]
    ax.bar(dte_df["dte_at_entry"].astype(str), dte_df["base_rate_pct"], color=BLUE, width=0.6)
    ax.set_xlabel("DTE at entry")
    ax.set_ylabel("Base rate (%)")
    ax.set_title("Base Rate by DTE")
    for i, (x, v, n) in enumerate(zip(dte_df["dte_at_entry"], dte_df["base_rate_pct"], dte_df["n_tradeable"])):
        ax.text(i, v + 0.5, f"{v:.0f}%\n(n={n})", ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, dte_df["base_rate_pct"].max() * 1.3)

    # --- Panel 2: base rate by delta bucket ---
    ax = axes[0, 1]
    dbuckets = delta_df["delta_bucket"].astype(str)
    ax.bar(dbuckets, delta_df["base_rate_pct"], color=GREEN, width=0.6)
    ax.set_xlabel("Delta bucket")
    ax.set_ylabel("Base rate (%)")
    ax.set_title("Base Rate by |Delta|")
    for i, (v, n) in enumerate(zip(delta_df["base_rate_pct"], delta_df["n_tradeable"])):
        ax.text(i, v + 0.5, f"{v:.0f}%\nn={n}", ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, delta_df["base_rate_pct"].max() * 1.3)

    # --- Panel 3: calls vs puts ---
    ax = axes[1, 0]
    sides = side_df["side"].tolist()
    colors = [BLUE, RED]
    ax.bar(sides, side_df["base_rate_pct"], color=colors, width=0.5)
    ax.set_ylabel("Base rate (%)")
    ax.set_title("Base Rate: Calls vs Puts")
    for i, (v, n) in enumerate(zip(side_df["base_rate_pct"], side_df["n_tradeable"])):
        ax.text(i, v + 0.3, f"{v:.1f}%\nn={n:,}", ha="center", va="bottom", fontsize=10)
    ax.set_ylim(0, side_df["base_rate_pct"].max() * 1.3)

    # --- Panel 4: hold hours distribution ---
    ax = axes[1, 1]
    bins_h = [0, 1, 2, 4, 8, 12, 24, 48, 72, 96, 200]
    ax.hist(df_t["hold_hours"], bins=bins_h, color=AMBER, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Hold hours (entry → first 20% exit)")
    ax.set_ylabel("Count")
    ax.set_title("Hold Period Distribution")
    ax.axvline(df_t["hold_hours"].median(), color="black", linestyle="--", linewidth=1.2,
               label=f"median = {df_t['hold_hours'].median():.1f}h")
    ax.legend(fontsize=9)
    ax.set_xscale("symlog", linthresh=1)
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter())

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out_path.name}")


def plot_momentum(mom_df: pd.DataFrame, out_path: Path) -> None:
    calls = mom_df[mom_df["side"] == "Call"]
    puts  = mom_df[mom_df["side"] == "Put"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Tradeable Long Options — Distribution by Prior 4h Spot Move", fontsize=13)

    for ax, grp, side, color in [
        (axes[0], calls, "Calls", BLUE),
        (axes[1], puts,  "Puts",  RED),
    ]:
        labels = grp["mom_bucket"].astype(str)
        x = np.arange(len(labels))
        bars = ax.bar(x, grp["n"], color=color, width=0.6, alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.set_title(f"{side}: trades by prior 4h spot move")
        ax.set_ylabel("Number of tradeable trades")
        ax.set_xlabel("4h spot move at entry")
        for bar, val in zip(bars, grp["n"]):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    str(int(val)), ha="center", va="bottom", fontsize=8)

        ax2 = ax.twinx()
        ax2.plot(x, grp["median_hold"] * 60, color="black", marker="o",
                 linewidth=1.5, markersize=4, label="median hold (min)")
        ax2.set_ylabel("Median hold hours", color="black")
        ax2.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v/60:.0f}h")
        )

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
    dte_df   = by_dte(df_t, df_c)
    delta_df = by_delta(df_t, df_c)
    side_df  = by_side(df_t, df_c)
    mom_df   = by_momentum(df_t, df_c)

    # Save CSVs
    dte_df.to_csv(HERE / "freq_by_dte.csv",   index=False)
    delta_df.to_csv(HERE / "freq_by_delta.csv", index=False)
    side_df.to_csv(HERE / "freq_by_side.csv",  index=False)
    mom_df.to_csv(HERE / "freq_momentum.csv",  index=False)

    # Plots
    print("Generating charts...")
    plot_overview(dte_df, delta_df, side_df, df_t, HERE / "freq_overview.svg")
    plot_momentum(mom_df, HERE / "freq_momentum.svg")

    # Print tables
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", 20)

    print("\n=== By DTE ===")
    print(dte_df.to_string(index=False))

    print("\n=== By |Delta| ===")
    print(delta_df.to_string(index=False))

    print("\n=== Calls vs Puts ===")
    print(side_df.to_string(index=False))

    print("\n=== Tradeable trades by prior 4h spot move ===")
    print(mom_df.to_string(index=False))

    print("\nSkip reason breakdown:")
    skip = (df_c[~df_c["tradeable"]]
            .groupby("skip_reason").size()
            .sort_values(ascending=False)
            .rename("count"))
    print(skip.to_string())


if __name__ == "__main__":
    main()
