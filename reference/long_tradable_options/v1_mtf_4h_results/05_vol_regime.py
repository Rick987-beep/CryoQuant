"""05_vol_regime.py — Volatility regime at entry: HV vs IV.

For each candidate entry, computes at-entry:
  hv24_pct     — 24h realised vol (annualised %) from 5-min spot log-returns
  atm_iv_pct   — ATM call IV at entry (nearest-to-spot call, DTE=1,2,3 in order)
  hv_iv_ratio  — hv24_pct / atm_iv_pct  (>1 = IV cheap relative to recent realised)
  iv_pct_30d   — rolling 30-day percentile of daily ATM IV (0=cheapest, 100=most expensive)

Uses ATM IV (not the specific option's own IV) so the ratio is delta-neutral
and not contaminated by skew.

Outputs:
  vol_by_hv_iv.csv      — base rate by HV/IV quintile
  vol_by_iv_pct.csv     — base rate by IV percentile decile
  vol_regime.svg        — 2-panel summary chart
  vol_regime_candidates.parquet  — candidates + vol features (for use in 07)
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


@lru_cache(maxsize=10)
def _load_spot_cached(date_str: str) -> pd.DataFrame | None:
    try:
        return ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None


@lru_cache(maxsize=14)
def _load_opts_cached(date_str: str) -> pd.DataFrame | None:
    try:
        return ou.load_day(date_str)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# 24h realised vol
# ---------------------------------------------------------------------------

def _compute_hv24(entry_ts_us: int) -> float:
    """24h annualised realised vol (%) from 5-min spot log-returns."""
    start_ts = entry_ts_us - 24 * 3_600 * 1_000_000
    start_dt = datetime.fromtimestamp(start_ts / 1e6, tz=timezone.utc)
    end_dt   = datetime.fromtimestamp(entry_ts_us / 1e6, tz=timezone.utc)

    frames: list[pd.DataFrame] = []
    cur = start_dt.date()
    while cur <= end_dt.date():
        df = _load_spot_cached(cur.isoformat())
        if df is not None:
            mask = (df["timestamp"] >= start_ts) & (df["timestamp"] <= entry_ts_us)
            frames.append(df[mask][["timestamp", "close"]])
        cur += timedelta(days=1)

    if not frames:
        return np.nan

    df_w = pd.concat(frames).sort_values("timestamp").drop_duplicates("timestamp")
    closes = df_w["close"].values.astype(float)
    if len(closes) < 10:
        return np.nan

    log_ret = np.diff(np.log(closes))
    # BTC trades 24/7 → 365-day year; 5-min bars → 288 bars/day
    return float(np.std(log_ret, ddof=1) * np.sqrt(365 * 288) * 100)


# ---------------------------------------------------------------------------
# ATM IV lookup (market-level, delta-neutral)
# ---------------------------------------------------------------------------

def _compute_atm_iv(date_str: str, entry_ts_us: int, spot_usd: float) -> float | None:
    """Return ATM call IV at the entry snapshot. Tries DTE=1, 2, 3 in order."""
    df = _load_opts_cached(date_str)
    if df is None:
        return None

    # Snap to nearest 5-min bar in the file
    unique_ts = df["timestamp"].unique()
    snap_ts   = int(unique_ts[np.abs(unique_ts - entry_ts_us).argmin()])
    snap      = df[
        (df["timestamp"] == snap_ts) &
        (df["is_call"]   == True) &     # noqa: E712
        (df["mark_iv"]   >  0) &
        (df["mark_price"] > 0)
    ].copy()

    if snap.empty:
        return None

    # Pre-compute DTE for each row (fast: uses vectorised date arithmetic)
    snap_date = datetime.fromtimestamp(snap_ts / 1e6, tz=timezone.utc).date()
    exp_dates = {c: ou.parse_expiry(c).date() for c in snap["expiry"].unique()}
    snap["dte"] = snap["expiry"].map(exp_dates).apply(
        lambda ed: (ed - snap_date).days
    )

    for dte_try in [1, 2, 3]:
        sub = snap[snap["dte"] == dte_try]
        if sub.empty:
            continue
        nearest = int((sub["strike"] - spot_usd).abs().values.argmin())
        return float(sub.iloc[nearest]["mark_iv"])

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = pd.read_parquet(HERE / "candidates_summary.parquet")
    print(f"Loaded {len(df):,} candidates")

    df["entry_ts_us"] = df["entry_ts"].apply(_str_to_us)
    df["entry_date"]  = df["entry_ts"].str[:10]

    # --- Build per-timestamp features (batch: ~780 unique timestamps) ---
    unique_ts_rows = (
        df[["entry_ts_us", "entry_date", "entry_spot_usd"]]
        .drop_duplicates("entry_ts_us")
        .reset_index(drop=True)
    )
    print(f"Computing HV24 + ATM IV for {len(unique_ts_rows)} unique timestamps …")

    hv24_map:   dict[int, float]       = {}
    atm_iv_map: dict[int, float | None] = {}

    for i, row in unique_ts_rows.iterrows():
        ts_us      = int(row["entry_ts_us"])
        hv24_map[ts_us]   = _compute_hv24(ts_us)
        atm_iv_map[ts_us] = _compute_atm_iv(
            str(row["entry_date"]), ts_us, float(row["entry_spot_usd"])
        )
        if (int(i) + 1) % 100 == 0 or int(i) + 1 == len(unique_ts_rows):
            print(f"  {int(i)+1}/{len(unique_ts_rows)}")

    df["hv24_pct"]  = df["entry_ts_us"].map(hv24_map)
    df["atm_iv_pct"] = df["entry_ts_us"].map(atm_iv_map)

    n_before = len(df)
    df_valid = df.dropna(subset=["hv24_pct", "atm_iv_pct"]).copy()
    print(f"\nValid rows (HV24 + ATM IV present): {len(df_valid):,} / {n_before:,}")

    df_valid["hv_iv_ratio"] = df_valid["hv24_pct"] / df_valid["atm_iv_pct"]

    # --- Rolling 30-day ATM IV percentile ---
    # Use daily median ATM IV as the market-level IV signal
    daily_iv = (
        df_valid.groupby("entry_date")["atm_iv_pct"]
        .median()
        .sort_index()
        .reset_index()
        .rename(columns={"atm_iv_pct": "daily_atm_iv"})
    )
    daily_iv["date_dt"] = pd.to_datetime(daily_iv["entry_date"])

    iv_pct_map: dict[str, float] = {}
    for _, drow in daily_iv.iterrows():
        d_dt   = drow["date_dt"]
        window = daily_iv[
            (daily_iv["date_dt"] >= d_dt - pd.Timedelta(days=30)) &
            (daily_iv["date_dt"] <  d_dt)
        ]["daily_atm_iv"].values
        if len(window) < 5:
            iv_pct_map[str(drow["entry_date"])] = np.nan
        else:
            today_iv = float(drow["daily_atm_iv"])
            iv_pct_map[str(drow["entry_date"])] = float(np.mean(window <= today_iv) * 100)

    df_valid["iv_pct_30d"] = df_valid["entry_date"].map(iv_pct_map)
    df_clean = df_valid.dropna(subset=["hv_iv_ratio", "iv_pct_30d"]).copy()
    print(f"After dropping NaN percentile: {len(df_clean):,} rows")

    overall_br = df_clean["tradeable"].mean() * 100

    # --- Analysis 1: base rate by HV/IV quintile ---
    df_clean["hv_iv_q"] = pd.qcut(
        df_clean["hv_iv_ratio"], q=5,
        labels=["Q1\n(vol cheap)", "Q2", "Q3", "Q4", "Q5\n(vol expensive)"]
    )
    by_hv_iv = (
        df_clean.groupby("hv_iv_q", observed=True)
        .agg(
            n_candidates =("tradeable", "count"),
            n_tradeable  =("tradeable", "sum"),
            hv24_med     =("hv24_pct",  "median"),
            atm_iv_med   =("atm_iv_pct","median"),
            hv_iv_med    =("hv_iv_ratio","median"),
        )
        .assign(base_rate_pct=lambda x: (x["n_tradeable"] / x["n_candidates"] * 100).round(1))
        .reset_index()
    )
    print("\nBase rate by HV24/ATM_IV quintile:")
    print(by_hv_iv[["hv_iv_q","hv_iv_med","hv24_med","atm_iv_med","n_candidates","base_rate_pct"]].to_string(index=False))
    by_hv_iv.to_csv(HERE / "vol_by_hv_iv.csv", index=False)

    # --- Analysis 2: base rate by IV percentile decile ---
    df_clean["iv_decile"] = pd.qcut(
        df_clean["iv_pct_30d"], q=10,
        labels=[f"D{i}" for i in range(1, 11)],
        duplicates="drop"
    )
    by_iv_pct = (
        df_clean.groupby("iv_decile", observed=True)
        .agg(
            n_candidates  =("tradeable", "count"),
            n_tradeable   =("tradeable", "sum"),
            iv_pct_median =("iv_pct_30d","median"),
            atm_iv_median =("atm_iv_pct","median"),
        )
        .assign(base_rate_pct=lambda x: (x["n_tradeable"] / x["n_candidates"] * 100).round(1))
        .reset_index()
    )
    print("\nBase rate by ATM IV 30-day percentile decile:")
    print(by_iv_pct[["iv_decile","iv_pct_median","atm_iv_median","n_candidates","base_rate_pct"]].to_string(index=False))
    by_iv_pct.to_csv(HERE / "vol_by_iv_pct.csv", index=False)

    # --- Charts ---
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Vol Regime at Entry vs Base Rate (long options, BTC)", fontsize=13, fontweight="bold")

    # Panel 1: HV/IV quintile
    ax = axes[0]
    x    = np.arange(len(by_hv_iv))
    bars = ax.bar(x, by_hv_iv["base_rate_pct"], color="#4e79a7", alpha=0.85, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(by_hv_iv["hv_iv_q"], fontsize=8.5)
    ax.set_xlabel("HV24 / ATM IV Quintile", fontsize=10)
    ax.set_ylabel("Base Rate (%)", fontsize=10)
    ax.set_title("Is cheap IV more tradeable?\n(HV/IV > 1 → IV cheap vs recent realised)", fontsize=10)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2, label=f"Overall {overall_br:.1f}%", zorder=2)
    ax.set_ylim(45, 80)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    for bar, hv_iv, n in zip(bars, by_hv_iv["hv_iv_med"], by_hv_iv["n_candidates"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f"r={hv_iv:.2f}\nn={n:,}", ha="center", va="bottom", fontsize=7.5)
    ax.legend(fontsize=9)

    # Panel 2: IV percentile decile
    ax = axes[1]
    x    = np.arange(len(by_iv_pct))
    bars = ax.bar(x, by_iv_pct["base_rate_pct"], color="#e15759", alpha=0.85, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(by_iv_pct["iv_decile"], fontsize=8.5)
    ax.set_xlabel("ATM IV 30-day Rolling Percentile Decile", fontsize=10)
    ax.set_ylabel("Base Rate (%)", fontsize=10)
    ax.set_title("Cheap IV (low percentile) = better?\n(D1 = cheapest IV in past 30 days)", fontsize=10)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2, label=f"Overall {overall_br:.1f}%", zorder=2)
    ax.set_ylim(45, 80)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    for bar, iv_pct, n in zip(bars, by_iv_pct["iv_pct_median"], by_iv_pct["n_candidates"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f"p={iv_pct:.0f}\nn={n:,}", ha="center", va="bottom", fontsize=7.5)
    ax.legend(fontsize=9)

    plt.tight_layout()
    outfile = HERE / "vol_regime.svg"
    plt.savefig(outfile, bbox_inches="tight")
    print(f"\nSaved {outfile}")

    # Save enriched candidates for downstream use
    out_parquet = HERE / "vol_regime_candidates.parquet"
    df_valid.to_parquet(out_parquet, index=False)
    print(f"Saved {out_parquet}")
    print("Done.")


if __name__ == "__main__":
    main()
