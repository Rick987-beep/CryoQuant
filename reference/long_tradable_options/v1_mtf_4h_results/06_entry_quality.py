"""06_entry_quality.py — Entry quality: spread efficiency and spot acceleration.

For each candidate entry, computes:
  spread_pct    — (ask − bid) / mark × 100 at entry snapshot (option level)
                  measures how much of fair value is eaten by the bid-ask spread
  accel_30m_pct — % spot change in the 30 minutes before entry
                  positive = spot rising into entry, negative = falling

Splits base rate (% tradeable) by:
  • spread_pct quartile  (do tighter-spread entries actually win less often?)
  • accel_30m_pct bucket (momentum at the moment of entry)

Also shows call/put split for the acceleration analysis to check directional
alignment (calls benefit from positive acceleration; puts from negative).

Outputs:
  quality_by_spread.csv   — base rate by spread quartile
  quality_by_accel.csv    — base rate by acceleration bucket (calls + puts combined)
  quality_by_accel_cp.csv — same, calls and puts separately
  entry_quality.svg       — 3-panel summary chart
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "intraday_options"))
import option_utils as ou  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str_to_us(ts_str: str) -> int:
    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


@lru_cache(maxsize=14)
def _load_opts_cached(date_str: str) -> pd.DataFrame | None:
    try:
        return ou.load_day(date_str)
    except FileNotFoundError:
        return None


@lru_cache(maxsize=10)
def _load_spot_cached(date_str: str) -> pd.DataFrame | None:
    try:
        return ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# Spread lookup — vectorised within each (date, entry_ts) group
# ---------------------------------------------------------------------------

def _spread_for_date(date_str: str, cands: pd.DataFrame) -> pd.Series:
    """Return spread_pct = (ask−bid)/mark×100 for each candidate on date_str.

    Batches all candidates by entry timestamp (up to 6 snapshots per date),
    then does a merge-based lookup — no per-row Python loops.
    """
    df_opts = _load_opts_cached(date_str)
    results = pd.Series(np.nan, index=cands.index, dtype=float)
    if df_opts is None:
        return results

    # Pre-compute spread_pct on the full day's options data
    df_opts = df_opts.copy()
    mask_valid = df_opts["mark_price"] > 0
    df_opts.loc[mask_valid, "spread_pct"] = (
        (df_opts.loc[mask_valid, "ask_price"] - df_opts.loc[mask_valid, "bid_price"])
        / df_opts.loc[mask_valid, "mark_price"] * 100
    )
    df_opts["strike_int"] = df_opts["strike"].round(0).astype(int)

    unique_ts_arr = df_opts["timestamp"].unique()

    for ts_str, grp in cands.groupby("entry_ts"):
        ts_us   = _str_to_us(ts_str)
        snap_ts = int(unique_ts_arr[np.abs(unique_ts_arr - ts_us).argmin()])
        snap    = df_opts[df_opts["timestamp"] == snap_ts][
            ["expiry", "is_call", "strike_int", "spread_pct"]
        ]
        if snap.empty:
            continue

        # Build merge key in the candidates group
        grp_m = grp.copy()
        grp_m["strike_int"] = grp_m["strike"].round(0).astype(int)

        merged = grp_m.merge(
            snap,
            on=["expiry", "is_call", "strike_int"],
            how="left",
        )
        results.loc[grp.index] = merged["spread_pct"].values

    return results


# ---------------------------------------------------------------------------
# 30-min spot acceleration — batched over unique timestamps
# ---------------------------------------------------------------------------

def _spot_at_us(ts_us: int) -> float | None:
    """Spot close nearest to ts_us (from 1-min data)."""
    date_str = datetime.fromtimestamp(ts_us / 1e6, tz=timezone.utc).date().isoformat()
    df_spot  = _load_spot_cached(date_str)
    if df_spot is None:
        return None
    idx = int(np.abs(df_spot["timestamp"].values - ts_us).argmin())
    return float(df_spot.iloc[idx]["close"])


def _compute_accels(unique_ts: np.ndarray) -> dict[int, float]:
    """% spot change in 30 min before each entry timestamp."""
    accel: dict[int, float] = {}
    for ts_us in unique_ts:
        prior_us  = int(ts_us) - 30 * 60 * 1_000_000
        spot_now   = _spot_at_us(int(ts_us))
        spot_prior = _spot_at_us(prior_us)
        if spot_now is None or spot_prior is None or spot_prior == 0:
            accel[int(ts_us)] = np.nan
        else:
            accel[int(ts_us)] = (spot_now / spot_prior - 1) * 100
    return accel


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = pd.read_parquet(HERE / "candidates_summary.parquet")
    print(f"Loaded {len(df):,} candidates")

    df["entry_ts_us"] = df["entry_ts"].apply(_str_to_us)
    df["entry_date"]  = df["entry_ts"].str[:10]

    # --- Spread: batch by date ---
    print("Computing spread_pct …")
    spread_parts: list[pd.Series] = []
    dates = sorted(df["entry_date"].unique())
    for di, date_str in enumerate(dates, 1):
        grp = df[df["entry_date"] == date_str]
        spread_parts.append(_spread_for_date(date_str, grp))
        if di % 25 == 0 or di == len(dates):
            print(f"  {di}/{len(dates)} dates")

    df["spread_pct"] = pd.concat(spread_parts)
    n_spread = df["spread_pct"].notna().sum()
    print(f"  spread_pct: {n_spread:,} non-null ({n_spread/len(df)*100:.1f}%)")

    # --- Acceleration: unique timestamps ---
    unique_ts = df["entry_ts_us"].unique()
    print(f"Computing 30-min acceleration for {len(unique_ts)} timestamps …")
    accel_map = _compute_accels(unique_ts)
    df["accel_30m_pct"] = df["entry_ts_us"].map(accel_map)
    n_accel = df["accel_30m_pct"].notna().sum()
    print(f"  accel_30m_pct: {n_accel:,} non-null")

    overall_br = df["tradeable"].mean() * 100

    # -----------------------------------------------------------------------
    # Analysis 1: base rate by spread quartile
    # -----------------------------------------------------------------------
    df_s = df.dropna(subset=["spread_pct"]).copy()
    df_s["spread_q"] = pd.qcut(
        df_s["spread_pct"], q=4,
        labels=["Q1\n(tightest)", "Q2", "Q3", "Q4\n(widest)"]
    )
    by_spread = (
        df_s.groupby("spread_q", observed=True)
        .agg(
            n_candidates =("tradeable", "count"),
            n_tradeable  =("tradeable", "sum"),
            spread_min   =("spread_pct", "min"),
            spread_max   =("spread_pct", "max"),
            spread_median=("spread_pct", "median"),
        )
        .assign(base_rate_pct=lambda x: (x["n_tradeable"] / x["n_candidates"] * 100).round(1))
        .reset_index()
    )
    print("\nBase rate by spread quartile:")
    print(by_spread[["spread_q","spread_median","spread_min","spread_max","n_candidates","base_rate_pct"]].to_string(index=False))
    by_spread.to_csv(HERE / "quality_by_spread.csv", index=False)

    # -----------------------------------------------------------------------
    # Analysis 2: base rate by 30-min acceleration (calls + puts combined)
    # -----------------------------------------------------------------------
    df_a = df.dropna(subset=["accel_30m_pct"]).copy()
    bins   = [-np.inf, -2, -1, -0.3, 0.3, 1, 2, np.inf]
    labels = ["<-2%", "-2–-1%", "-1–-0.3%", "±0.3%", "+0.3–+1%", "+1–+2%", ">+2%"]
    df_a["accel_bucket"] = pd.cut(df_a["accel_30m_pct"], bins=bins, labels=labels)

    by_accel = (
        df_a.groupby("accel_bucket", observed=True)
        .agg(
            n_candidates=("tradeable", "count"),
            n_tradeable =("tradeable", "sum"),
            accel_median=("accel_30m_pct", "median"),
        )
        .assign(base_rate_pct=lambda x: (x["n_tradeable"] / x["n_candidates"] * 100).round(1))
        .reset_index()
    )
    print("\nBase rate by 30-min spot acceleration (calls+puts combined):")
    print(by_accel[["accel_bucket","accel_median","n_candidates","base_rate_pct"]].to_string(index=False))
    by_accel.to_csv(HERE / "quality_by_accel.csv", index=False)

    # -----------------------------------------------------------------------
    # Analysis 3: same, calls and puts separately (directional alignment)
    # -----------------------------------------------------------------------
    by_accel_cp = (
        df_a.groupby(["accel_bucket", "is_call"], observed=True)
        .agg(
            n_candidates=("tradeable", "count"),
            n_tradeable =("tradeable", "sum"),
        )
        .assign(base_rate_pct=lambda x: (x["n_tradeable"] / x["n_candidates"] * 100).round(1))
        .reset_index()
    )
    print("\nBase rate by 30-min acceleration × calls/puts:")
    print(by_accel_cp.to_string(index=False))
    by_accel_cp.to_csv(HERE / "quality_by_accel_cp.csv", index=False)

    # -----------------------------------------------------------------------
    # Charts
    # -----------------------------------------------------------------------
    fig = plt.figure(figsize=(16, 5))
    fig.suptitle("Entry Quality vs Base Rate (long options, BTC)", fontsize=13, fontweight="bold")

    gs = fig.add_gridspec(1, 3, wspace=0.35)
    axes = [fig.add_subplot(gs[i]) for i in range(3)]

    # --- Panel 1: spread quartile ---
    ax = axes[0]
    x    = np.arange(len(by_spread))
    bars = ax.bar(x, by_spread["base_rate_pct"], color="#59a14f", alpha=0.85, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(by_spread["spread_q"], fontsize=8.5)
    ax.set_xlabel("Bid-Ask / Mark Spread (quartile)", fontsize=10)
    ax.set_ylabel("Base Rate (%)", fontsize=10)
    ax.set_title("Wider spread = harder to profit?", fontsize=10)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2, label=f"Overall {overall_br:.1f}%", zorder=2)
    ax.set_ylim(45, 80)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    for bar, med, n in zip(bars, by_spread["spread_median"], by_spread["n_candidates"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.4,
                f"med={med:.0f}%\nn={n:,}", ha="center", va="bottom", fontsize=7)
    ax.legend(fontsize=8)

    # --- Panel 2: acceleration (combined) ---
    ax = axes[1]
    x    = np.arange(len(by_accel))
    bars = ax.bar(x, by_accel["base_rate_pct"], color="#f28e2b", alpha=0.85, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(by_accel["accel_bucket"], fontsize=7.5)
    ax.set_xlabel("Spot change in 30 min before entry", fontsize=10)
    ax.set_ylabel("Base Rate (%)", fontsize=10)
    ax.set_title("30-min momentum at entry\n(calls + puts combined)", fontsize=10)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2, label=f"Overall {overall_br:.1f}%", zorder=2)
    ax.set_ylim(45, 80)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    for bar, n in zip(bars, by_accel["n_candidates"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.4,
                f"n={n:,}", ha="center", va="bottom", fontsize=7)
    ax.legend(fontsize=8)

    # --- Panel 3: acceleration calls vs puts ---
    ax = axes[2]
    calls_data = by_accel_cp[by_accel_cp["is_call"] == True]   # noqa: E712
    puts_data  = by_accel_cp[by_accel_cp["is_call"] == False]  # noqa: E712
    buckets    = by_accel["accel_bucket"].tolist()
    n_buckets  = len(buckets)
    w          = 0.38
    x          = np.arange(n_buckets)

    # Align to bucket order
    calls_rates = [float(calls_data.loc[calls_data["accel_bucket"] == b, "base_rate_pct"].values[0])
                   if len(calls_data.loc[calls_data["accel_bucket"] == b]) > 0 else np.nan
                   for b in buckets]
    puts_rates  = [float(puts_data.loc[puts_data["accel_bucket"]  == b, "base_rate_pct"].values[0])
                   if len(puts_data.loc[puts_data["accel_bucket"]  == b]) > 0 else np.nan
                   for b in buckets]

    ax.bar(x - w/2, calls_rates, width=w, label="Calls", color="#4e79a7", alpha=0.85, zorder=3)
    ax.bar(x + w/2, puts_rates,  width=w, label="Puts",  color="#e15759", alpha=0.85, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(buckets, fontsize=7.5)
    ax.set_xlabel("Spot change in 30 min before entry", fontsize=10)
    ax.set_ylabel("Base Rate (%)", fontsize=10)
    ax.set_title("Directional momentum at entry\n(calls vs puts)", fontsize=10)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2, label=f"Overall {overall_br:.1f}%", zorder=2)
    ax.set_ylim(45, 80)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.legend(fontsize=8)

    plt.tight_layout()
    outfile = HERE / "entry_quality.svg"
    plt.savefig(outfile, bbox_inches="tight")
    print(f"\nSaved {outfile}")
    print("Done.")


if __name__ == "__main__":
    main()
