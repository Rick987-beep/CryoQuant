"""09_winner_magnitude.py — How high do winning options actually peak?

Two-part analysis:
  Part A — Quick (no rescan): uses existing exit_bid_btc from tradeable_longs_enriched.
            gross_gain_pct = gain at the FIRST detected 1.2× bid crossover (5-min resolution).
            This is the "exit at first signal" scenario.

  Part B — Full rescan: scans ALL options snapshots from entry to expiry-1h for each
            tradeable trade, finding the maximum bid/entry_ask ratio (peak_multiple).
            This is the ceiling — what you could get with a perfect oracle exit.

Together: shows the true distribution of winner magnitude and computes expected value (EV)
at different take-profit (TP) levels.

EV formula:
  EV(TP) = base_rate × P(peak ≥ TP | tradeable) × (TP - 1) − (1 − base_rate × P(peak ≥ TP)) × 1.0
          = base_rate × f(TP) × TP − 1
  where f(TP) = fraction of tradeable trades whose peak_multiple ≥ TP.

Outputs:
  winner_peaks.parquet            — tradeable trades + peak_multiple (from rescan)
  magnitude_distribution.csv      — % of winners reaching each TP level
  ev_table.csv                    — EV at each TP × base_rate combination
  magnitude_overview.svg          — distribution + EV chart
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
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

TP_LEVELS   = [1.2, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0]
BASE_RATES  = [0.582, 0.672, 0.746, 0.806, 0.872]   # overall, spread-only, 4h≥1%, MTF, MTF-high


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str_to_us(ts_str: str) -> int:
    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def _expiry_cutoff_us(expiry_date_str: str) -> int:
    """07:00 UTC on expiry date (1h before Deribit 08:00 UTC expiry)."""
    parts = expiry_date_str.split("-")
    dt    = datetime(int(parts[0]), int(parts[1]), int(parts[2]),
                     7, 0, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


@lru_cache(maxsize=20)
def _load_opts(date_str: str) -> pd.DataFrame | None:
    try:
        return ou.load_day(date_str)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# Part B: full peak rescan
# ---------------------------------------------------------------------------

def _rescan_peaks(df: pd.DataFrame) -> pd.Series:
    """
    For each row in df (tradeable trades), scan all options snapshots from
    entry_ts to expiry-1h and return peak_multiple = max(bid) / entry_ask_btc.
    Vectorised: batch by calendar date, single merge per date.
    """
    print("Rescanning for peak multiples (batch by date) ...")

    # Parse expiry dates from Deribit codes (e.g. "15MAY26" → "2026-05-15")
    df   = df.copy()
    df["expiry_date"]     = df["expiry"].apply(
        lambda x: datetime.strptime(x, "%d%b%y").date().isoformat()
    )
    df["entry_ts_us"]     = df["entry_ts"].apply(_str_to_us)
    df["strike_int"]      = df["strike"].round(0).astype(int)
    df["expiry_cutoff_us"] = df["expiry_date"].apply(_expiry_cutoff_us)
    df["entry_date"]      = df["entry_ts"].str[:10]

    peak_map: dict[int, float] = {}   # orig_index → peak_multiple

    all_dates = sorted(ou.available_dates())
    for di, date_str in enumerate(all_dates, 1):
        # Trades active on this date: entered on or before, expiring on or after
        active = df[(df["entry_date"] <= date_str) & (df["expiry_date"] >= date_str)]
        if active.empty:
            continue

        df_opts = _load_opts(date_str)
        if df_opts is None:
            continue

        df_opts   = df_opts.copy()
        df_opts["strike_int"] = df_opts["strike"].round(0).astype(int)

        snap = df_opts.loc[
            df_opts["bid_price"] > 0,
            ["timestamp", "expiry", "is_call", "strike_int", "bid_price"]
        ]

        # Preserve original index as _orig_idx
        active_m = active[
            ["entry_ts_us", "expiry_cutoff_us", "entry_ask_btc",
             "expiry", "is_call", "strike_int"]
        ].copy()
        active_m["_orig_idx"] = active_m.index

        merged = snap.merge(active_m, on=["expiry", "is_call", "strike_int"], how="inner")
        if merged.empty:
            continue

        merged = merged[
            (merged["timestamp"] >= merged["entry_ts_us"]) &
            (merged["timestamp"] <  merged["expiry_cutoff_us"])
        ]
        if merged.empty:
            continue

        merged["multiple"] = merged["bid_price"] / merged["entry_ask_btc"]

        best = merged.groupby("_orig_idx")["multiple"].max()
        for orig_idx, peak in best.items():
            if peak > peak_map.get(orig_idx, 0.0):
                peak_map[orig_idx] = peak

        if di % 20 == 0 or di == len(all_dates):
            print(f"  {di}/{len(all_dates)} dates  ({len(peak_map)} trades tracked)")

    return pd.Series(peak_map, name="peak_multiple")


# ---------------------------------------------------------------------------
# Part A: quick analysis from existing gross_gain_pct
# ---------------------------------------------------------------------------

def _quick_analysis(df: pd.DataFrame) -> None:
    print("\n=== PART A: First-crossover analysis (existing data) ===")
    print(f"n_tradeable = {len(df):,}")
    desc = df["gross_gain_pct"].describe()
    print(f"gross_gain_pct: mean={desc['mean']:.1f}%  median={desc['50%']:.1f}%  "
          f"p75={desc['75%']:.1f}%  p90={df['gross_gain_pct'].quantile(0.90):.1f}%  "
          f"p99={df['gross_gain_pct'].quantile(0.99):.1f}%  max={desc['max']:.1f}%")

    # Net gain (fee-adjusted)
    df   = df.copy()
    df["net_gain_pct"] = df["net_pnl_usd"] / df["entry_ask_usd"] * 100
    ng   = df["net_gain_pct"]
    print(f"net_gain_pct:   mean={ng.mean():.1f}%  median={ng.median():.1f}%  "
          f"p75={ng.quantile(0.75):.1f}%  p90={ng.quantile(0.90):.1f}%")

    # EV at first-crossover exit, using different base rates
    mean_net = ng.mean() / 100    # fractional
    print("\nEV at first-crossover exit (p × mean_net_win − (1-p) × 1.0):")
    br_labels = ["all candidates (58.2%)", "spread≤10% (67.2%)",
                 "MTF kernel 80.6%",       "MTF high 87.2%"]
    for p, lbl in zip([0.582, 0.672, 0.806, 0.872], br_labels):
        ev = p * mean_net - (1 - p) * 1.0
        print(f"  p={p:.3f} ({lbl}): EV = {ev*100:+.1f}% per trade")


# ---------------------------------------------------------------------------
# EV table
# ---------------------------------------------------------------------------

def _ev_table(peak_series: pd.Series) -> pd.DataFrame:
    rows = []
    for tp in TP_LEVELS:
        f_tp = (peak_series >= tp).mean()     # P(peak ≥ TP | tradeable)
        for p in BASE_RATES:
            ev = p * f_tp * tp - 1            # EV formula
            rows.append({
                "tp_multiple":   tp,
                "base_rate":     p,
                "frac_reaching": round(f_tp, 3),
                "eff_hit_rate":  round(p * f_tp, 3),
                "ev_pct":        round(ev * 100, 1),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _draw_charts(df: pd.DataFrame, ev_df: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle("Winner Magnitude Analysis — how high do winning options peak?",
                 fontsize=13, fontweight="bold")

    # --- [0,0] Peak multiple distribution histogram ---
    ax = axes[0][0]
    clipped = df["peak_multiple"].clip(upper=6)
    ax.hist(clipped, bins=60, color="#4e79a7", alpha=0.80, edgecolor="white", lw=0.3)
    for tp, c in [(1.5, "orange"), (2.0, "red"), (3.0, "darkred")]:
        ax.axvline(tp, color=c, ls="--", lw=1.5, label=f"{tp}×")
    ax.set_xlabel("Peak multiple (bid / entry_ask_btc)", fontsize=9)
    ax.set_ylabel("Count", fontsize=9)
    ax.set_title("Distribution of peak multiples\n(capped at 6× for display)", fontsize=9.5)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # --- [0,1] CDF: % of winners reaching each multiple ---
    ax = axes[0][1]
    pm = df["peak_multiple"].sort_values().values
    cdf = np.arange(1, len(pm) + 1) / len(pm)
    ax.plot(pm[pm <= 10], 1 - cdf[pm <= 10], color="#59a14f", lw=2.5)
    for tp, c in [(1.2, "navy"), (1.5, "orange"), (2.0, "red"), (3.0, "darkred")]:
        frac = (df["peak_multiple"] >= tp).mean()
        ax.axvline(tp, color=c, ls="--", lw=1.2, label=f"{tp}× → {frac*100:.0f}%")
    ax.set_xlabel("TP level (×)", fontsize=9)
    ax.set_ylabel("Fraction of winners reaching TP", fontsize=9)
    ax.set_title("% of tradeable winners reaching each TP level\n(survival function)", fontsize=9.5)
    ax.legend(fontsize=8)
    ax.set_xlim(1, 8)
    ax.grid(alpha=0.3)

    # --- [0,2] EV vs TP at kernel base rates ---
    ax = axes[0][2]
    for p, lbl, clr in zip(
        [0.582, 0.672, 0.806, 0.872],
        ["all 58.2%", "spread 67.2%", "MTF 80.6%", "MTF-high 87.2%"],
        ["#bab0ac", "#76b7b2", "#59a14f", "#4e79a7"]
    ):
        sub = ev_df[ev_df["base_rate"] == p].sort_values("tp_multiple")
        ax.plot(sub["tp_multiple"], sub["ev_pct"], "o-", color=clr, lw=2, label=lbl)
    ax.axhline(0, color="black", lw=1.2)
    ax.set_xlabel("Take-profit multiple (×)", fontsize=9)
    ax.set_ylabel("EV per trade (%)", fontsize=9)
    ax.set_title("Expected value per trade vs TP level\n(assuming 100% loss if TP not hit)",
                 fontsize=9.5)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    ax.set_xlim(1, 6)

    # --- [1,0] Peak by DTE ---
    ax = axes[1][0]
    for dte, c in [(3, "#bab0ac"), (4, "#76b7b2"), (5, "#59a14f"), (7, "#4e79a7")]:
        sub = df[df["dte_at_entry"] == dte]["peak_multiple"]
        if len(sub) < 10:
            continue
        sub_c = sub.clip(upper=8)
        ax.hist(sub_c, bins=40, alpha=0.55, label=f"DTE {dte} (n={len(sub):,})", color=c)
    ax.set_xlabel("Peak multiple", fontsize=9)
    ax.set_ylabel("Count", fontsize=9)
    ax.set_title("Peak multiple distribution by DTE", fontsize=9.5)
    ax.legend(fontsize=8)
    ax.set_xlim(1, 8)
    ax.grid(alpha=0.3)

    # --- [1,1] Peak by side (calls vs puts) ---
    ax = axes[1][1]
    for is_call, lbl, c in [(True, "Calls", "#4e79a7"), (False, "Puts", "#e15759")]:
        sub = df[df["is_call"] == is_call]["peak_multiple"]
        ax.hist(sub.clip(upper=8), bins=40, alpha=0.6, label=f"{lbl} (n={len(sub):,})",
                color=c)
    ax.set_xlabel("Peak multiple", fontsize=9)
    ax.set_ylabel("Count", fontsize=9)
    ax.set_title("Peak multiple: calls vs puts", fontsize=9.5)
    ax.legend(fontsize=8)
    ax.set_xlim(1, 8)
    ax.grid(alpha=0.3)

    # --- [1,2] EV table at MTF kernel (p=0.806) ---
    ax = axes[1][2]
    sub = ev_df[ev_df["base_rate"] == 0.806].copy()
    x   = np.arange(len(sub))
    colors = ["#59a14f" if v >= 0 else "#e15759" for v in sub["ev_pct"]]
    bars = ax.bar(x, sub["ev_pct"], color=colors, alpha=0.85, zorder=3)
    ax.axhline(0, color="black", lw=1.2, zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t:.2g}×\nf={r:.0%}" for t, r in
                        zip(sub["tp_multiple"], sub["frac_reaching"])], fontsize=7.5)
    ax.set_xlabel("TP level  (f = fraction of winners reaching it)", fontsize=9)
    ax.set_ylabel("EV per trade (%)", fontsize=9)
    ax.set_title("EV breakdown at MTF kernel base rate (80.6%)\n"
                 "Bar color: green=positive, red=negative", fontsize=9.5)
    ax.grid(axis="y", alpha=0.3)
    for bar, v in zip(bars, sub["ev_pct"]):
        ax.text(bar.get_x() + bar.get_width()/2,
                bar.get_height() + (0.5 if v >= 0 else -1.5),
                f"{v:+.0f}%", ha="center", va="bottom", fontsize=7.5)

    plt.tight_layout()
    plt.savefig(out_path, bbox_inches="tight")
    print(f"\nSaved {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = pd.read_parquet(HERE / "tradeable_longs_enriched.parquet")
    print(f"Loaded {len(df):,} tradeable trades")

    # Part A: quick first-crossover analysis
    _quick_analysis(df)

    # Part B: rescan for peak multiples
    peaks = _rescan_peaks(df)
    df["peak_multiple"] = peaks.reindex(df.index).fillna(
        df["gross_gain_pct"] / 100 + 1   # fallback: use first-crossover value
    )

    # Save enriched
    out_parq = HERE / "winner_peaks.parquet"
    df.to_parquet(out_parq, index=False)
    print(f"\nSaved {out_parq}")

    # Distribution summary
    pm = df["peak_multiple"]
    print("\n=== PART B: Peak multiple distribution ===")
    print(f"mean={pm.mean():.2f}×  median={pm.median():.2f}×  "
          f"p75={pm.quantile(0.75):.2f}×  p90={pm.quantile(0.90):.2f}×  "
          f"p99={pm.quantile(0.99):.2f}×  max={pm.max():.2f}×")

    # Fraction reaching each TP
    print("\nFraction of tradeable winners reaching each TP level:")
    dist_rows = []
    for tp in TP_LEVELS:
        frac = (pm >= tp).mean()
        dist_rows.append({"tp_multiple": tp, "pct_winners_reaching": round(frac * 100, 1)})
        print(f"  TP={tp:.2f}×:  {frac*100:.1f}% of winners")
    pd.DataFrame(dist_rows).to_csv(HERE / "magnitude_distribution.csv", index=False)

    # EV table
    ev_df = _ev_table(pm)
    ev_df.to_csv(HERE / "ev_table.csv", index=False)

    print("\nEV table at MTF kernel base rate (80.6%):")
    print(ev_df[ev_df["base_rate"] == 0.806][
        ["tp_multiple", "frac_reaching", "eff_hit_rate", "ev_pct"]
    ].to_string(index=False))

    print("\nEV table at MTF-high base rate (87.2%):")
    print(ev_df[ev_df["base_rate"] == 0.872][
        ["tp_multiple", "frac_reaching", "eff_hit_rate", "ev_pct"]
    ].to_string(index=False))

    # Hold time to peak
    print(f"\nHold hours (to first 1.2× crossover): "
          f"median={df['hold_hours'].median():.1f}h  "
          f"p75={df['hold_hours'].quantile(0.75):.1f}h  "
          f"p90={df['hold_hours'].quantile(0.90):.1f}h")

    # Charts
    _draw_charts(df, ev_df, HERE / "magnitude_overview.svg")
    print("Done.")


if __name__ == "__main__":
    main()
