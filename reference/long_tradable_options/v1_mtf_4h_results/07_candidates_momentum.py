"""07_candidates_momentum.py — Phase 0: Does prior spot momentum predict tradeability?

Enriches candidates_summary with:
  spread_pct          — (ask−bid)/mark × 100 at entry (for tight-spread filter)
  spot_30m_chg_pct    — spot % change 30 min before entry
  spot_1h_chg_pct     — spot % change 1h before entry
  spot_4h_chg_pct     — spot % change 4h before entry
  spot_24h_chg_pct    — spot % change 24h before entry

Analyses IN THE TIGHT-SPREAD SUBSET ONLY (spread_pct ≤ 10%):
  1. Base rate by 4h prior spot momentum — calls and puts separately
  2. Base rate by 1h prior spot momentum — calls and puts separately
  3. Base rate by 30m prior spot momentum — calls and puts separately
  4. Combined filter table: spread ≤ 10% AND aligned 4h momentum ≥ threshold
     → base rate + entry windows per day (the key frequency metric)

Decision gate:
  ≥ 68% base rate AND ≥ 1 qualifying entry window/day → strategy kernel exists.
  Flat base rate across all momentum buckets → move to Phase 1 (visual characterisation).

Outputs:
  candidates_enriched.parquet       — all candidates + spread + momentum (used by Phase 1+)
  phase0_by_4h_momentum.csv         — base rate by 4h bucket, calls and puts
  phase0_by_1h_momentum.csv         — base rate by 1h bucket, calls and puts
  phase0_combined_filter.csv        — combined filter: base rate + daily frequency
  phase0_overview.svg               — summary chart (2×3 panels)
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
# Config
# ---------------------------------------------------------------------------
SPREAD_THRESHOLD = 10.0   # % of mark — tight-spread filter

MOMENTUM_BINS   = [-np.inf, -3, -1.5, -0.5, 0.5, 1.5, 3, np.inf]
MOMENTUM_LABELS = ["<-3%", "-3–-1.5%", "-1.5–-0.5%", "±0.5%",
                   "+0.5–+1.5%", "+1.5–+3%", ">+3%"]

ALIGNED_THRESHOLDS = [0.3, 0.5, 1.0, 1.5, 2.0, 3.0]   # for combined filter table


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
# Spread computation — vectorised within each (date, entry_ts) batch
# ---------------------------------------------------------------------------

def _compute_spread(df: pd.DataFrame) -> pd.Series:
    """Return spread_pct = (ask−bid)/mark × 100 for each candidate row."""
    print("Computing spread_pct ...")
    spread = pd.Series(np.nan, index=df.index, dtype=float)
    dates  = sorted(df["entry_date"].unique())

    for di, date_str in enumerate(dates, 1):
        df_opts = _load_opts_cached(date_str)
        if df_opts is None:
            continue

        df_opts = df_opts.copy()
        valid = df_opts["mark_price"] > 0
        df_opts.loc[valid, "spread_pct"] = (
            (df_opts.loc[valid, "ask_price"] - df_opts.loc[valid, "bid_price"])
            / df_opts.loc[valid, "mark_price"] * 100
        )
        df_opts["strike_int"]  = df_opts["strike"].round(0).astype(int)
        unique_ts_arr          = df_opts["timestamp"].unique()

        for ts_str, grp in df[df["entry_date"] == date_str].groupby("entry_ts"):
            ts_us   = _str_to_us(ts_str)
            snap_ts = int(unique_ts_arr[np.abs(unique_ts_arr - ts_us).argmin()])
            snap    = df_opts[df_opts["timestamp"] == snap_ts][
                ["expiry", "is_call", "strike_int", "spread_pct"]
            ]
            if snap.empty:
                continue
            grp_m              = grp.copy()
            grp_m["strike_int"] = grp_m["strike"].round(0).astype(int)
            merged              = grp_m.merge(snap, on=["expiry", "is_call", "strike_int"], how="left")
            spread.loc[grp.index] = merged["spread_pct"].values

        if di % 25 == 0 or di == len(dates):
            print(f"  spread: {di}/{len(dates)} dates")

    return spread


# ---------------------------------------------------------------------------
# Spot momentum — batched over unique entry timestamps
# ---------------------------------------------------------------------------

def _spot_at_us(ts_us: int) -> float | None:
    date_str = datetime.fromtimestamp(ts_us / 1e6, tz=timezone.utc).date().isoformat()
    df_spot  = _load_spot_cached(date_str)
    if df_spot is None:
        return None
    idx = int(np.abs(df_spot["timestamp"].values - ts_us).argmin())
    return float(df_spot.iloc[idx]["close"])


def _compute_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """Add spot_Nh_chg_pct columns. Batches by unique entry_ts_us (~683 lookups)."""
    unique_ts = df["entry_ts_us"].unique()
    print(f"Computing spot momentum for {len(unique_ts)} unique timestamps ...")

    lookbacks_sec = {"30m": 1800, "1h": 3600, "4h": 14400, "24h": 86400}
    rows: list[dict] = []

    for i, ts_us in enumerate(unique_ts):
        spot_now = _spot_at_us(int(ts_us))
        row: dict = {"entry_ts_us": int(ts_us)}
        for name, secs in lookbacks_sec.items():
            prior_us   = int(ts_us) - secs * 1_000_000
            spot_prior = _spot_at_us(prior_us)
            if spot_now and spot_prior and spot_prior > 0:
                row[f"spot_{name}_chg_pct"] = (spot_now / spot_prior - 1) * 100
            else:
                row[f"spot_{name}_chg_pct"] = np.nan
        rows.append(row)
        if (i + 1) % 100 == 0 or (i + 1) == len(unique_ts):
            print(f"  momentum: {i+1}/{len(unique_ts)}")

    mom_df = pd.DataFrame(rows)
    return df.merge(mom_df, on="entry_ts_us", how="left")


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def _base_rate_by_bucket(df_sub: pd.DataFrame, col: str) -> pd.DataFrame:
    df_sub = df_sub.copy()
    df_sub["_bucket"] = pd.cut(df_sub[col], bins=MOMENTUM_BINS, labels=MOMENTUM_LABELS)
    return (
        df_sub.groupby("_bucket", observed=True)
        .agg(n_candidates=("tradeable", "count"), n_tradeable=("tradeable", "sum"))
        .assign(base_rate_pct=lambda x: (x["n_tradeable"] / x["n_candidates"] * 100).round(1))
        .reset_index()
        .rename(columns={"_bucket": "bucket"})
    )


def _combined_filter_table(df_calls: pd.DataFrame, df_puts: pd.DataFrame,
                            thresholds: list[float], n_days: int) -> pd.DataFrame:
    """For each aligned momentum threshold, compute base rate and entry windows/day."""
    rows = []
    for thr in thresholds:
        calls_aln = df_calls[df_calls["spot_4h_chg_pct"] >=  thr]
        puts_aln  = df_puts[ df_puts["spot_4h_chg_pct"]  <= -thr]
        combined  = pd.concat([calls_aln, puts_aln])

        n_opt   = len(combined)
        n_tr    = int(combined["tradeable"].sum())
        n_win   = combined["entry_ts"].nunique()   # unique (date,hour) windows

        rows.append({
            "aligned_4h_thr": f"≥{thr:.1f}%",
            "n_options":       n_opt,
            "n_tradeable":     n_tr,
            "base_rate_pct":   round(n_tr / n_opt * 100, 1) if n_opt > 0 else np.nan,
            "entry_windows":   n_win,
            "windows_per_day": round(n_win / n_days, 2),
            "options_per_day": round(n_opt / n_days, 1),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _momentum_bars(ax, tbl: pd.DataFrame, title: str, overall_br: float,
                   color: str, xlabel: str) -> None:
    x    = np.arange(len(tbl))
    bars = ax.bar(x, tbl["base_rate_pct"], color=color, alpha=0.85, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(tbl["bucket"], fontsize=7.5)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel("Base Rate (%)", fontsize=9)
    ax.set_title(title, fontsize=9.5)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2,
               label=f"Avg {overall_br:.1f}%", zorder=2)
    ax.set_ylim(30, 90)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.legend(fontsize=8)
    for bar, n in zip(bars, tbl["n_candidates"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.6,
                f"n={n:,}", ha="center", va="bottom", fontsize=6.5)


def _combined_filter_chart(ax, df_combined: pd.DataFrame, overall_br: float) -> None:
    x   = np.arange(len(df_combined))
    ax2 = ax.twinx()
    bars = ax.bar(x, df_combined["base_rate_pct"], color="#59a14f", alpha=0.85, zorder=3)
    ax2.plot(x, df_combined["windows_per_day"], "o-",
             color="#f28e2b", lw=2, zorder=4, label="Windows/day")
    ax.set_xticks(x)
    ax.set_xticklabels(df_combined["aligned_4h_thr"], fontsize=8)
    ax.set_xlabel("Aligned 4h momentum threshold (call or put)", fontsize=9)
    ax.set_ylabel("Base Rate (%)", fontsize=9)
    ax2.set_ylabel("Entry windows per day", fontsize=9, color="#f28e2b")
    ax2.tick_params(axis="y", colors="#f28e2b")
    ax.set_title("Combined filter: spread ≤ 10% + aligned 4h momentum\n"
                 "Base rate (green bars) | Entry windows per day (orange line)", fontsize=9)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2,
               label=f"Tight-spread avg {overall_br:.1f}%", zorder=2)
    ax.set_ylim(30, 90)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.legend(fontsize=8, loc="upper left")
    ax2.legend(fontsize=8, loc="upper right")
    for bar, n in zip(bars, df_combined["n_options"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.6,
                f"n={n:,}", ha="center", va="bottom", fontsize=7)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = pd.read_parquet(HERE / "candidates_summary.parquet")
    print(f"Loaded {len(df):,} candidates")

    df["entry_ts_us"] = df["entry_ts"].apply(_str_to_us)
    df["entry_date"]  = df["entry_ts"].str[:10]
    n_days            = df["entry_date"].nunique()
    print(f"Dataset spans {n_days} trading days")

    # --- Enrich ---
    df["spread_pct"] = _compute_spread(df)
    df = _compute_momentum(df)

    # Save enriched candidates for Phase 1+
    out_parquet = HERE / "candidates_enriched.parquet"
    df.to_parquet(out_parquet, index=False)
    print(f"\nSaved {out_parquet}  ({len(df):,} rows, {len(df.columns)} cols)")

    # ===== ANALYSIS: tight-spread subset only =====
    df_tight = df[df["spread_pct"] <= SPREAD_THRESHOLD].copy()
    n_tight  = len(df_tight)
    overall_br = df_tight["tradeable"].mean() * 100
    print(f"\nTight-spread subset (spread ≤ {SPREAD_THRESHOLD}%): {n_tight:,} / {len(df):,} candidates")
    print(f"Tight-spread overall base rate: {overall_br:.1f}%")

    df_calls = df_tight[df_tight["is_call"] == True].copy()   # noqa: E712
    df_puts  = df_tight[df_tight["is_call"] == False].copy()  # noqa: E712

    # --- 4h momentum ---
    tbl_4h_calls = _base_rate_by_bucket(df_calls, "spot_4h_chg_pct")
    tbl_4h_puts  = _base_rate_by_bucket(df_puts,  "spot_4h_chg_pct")
    tbl_4h_calls["side"] = "calls"
    tbl_4h_puts["side"]  = "puts"
    tbl_4h = pd.concat([tbl_4h_calls, tbl_4h_puts])
    tbl_4h.to_csv(HERE / "phase0_by_4h_momentum.csv", index=False)

    print("\n4h prior momentum — CALLS (tight-spread):")
    print(tbl_4h_calls[["bucket","n_candidates","n_tradeable","base_rate_pct"]].to_string(index=False))
    print("\n4h prior momentum — PUTS (tight-spread):")
    print(tbl_4h_puts[["bucket","n_candidates","n_tradeable","base_rate_pct"]].to_string(index=False))

    # --- 1h momentum ---
    tbl_1h_calls = _base_rate_by_bucket(df_calls, "spot_1h_chg_pct")
    tbl_1h_puts  = _base_rate_by_bucket(df_puts,  "spot_1h_chg_pct")
    tbl_1h_calls["side"] = "calls"
    tbl_1h_puts["side"]  = "puts"
    pd.concat([tbl_1h_calls, tbl_1h_puts]).to_csv(HERE / "phase0_by_1h_momentum.csv", index=False)

    print("\n1h prior momentum — CALLS (tight-spread):")
    print(tbl_1h_calls[["bucket","n_candidates","n_tradeable","base_rate_pct"]].to_string(index=False))
    print("\n1h prior momentum — PUTS (tight-spread):")
    print(tbl_1h_puts[["bucket","n_candidates","n_tradeable","base_rate_pct"]].to_string(index=False))

    # --- Combined filter table ---
    df_combined = _combined_filter_table(df_calls, df_puts, ALIGNED_THRESHOLDS, n_days)
    df_combined.to_csv(HERE / "phase0_combined_filter.csv", index=False)

    print("\nCombined filter — spread ≤ 10% AND aligned 4h momentum:")
    print(df_combined.to_string(index=False))

    # --- Decision gate summary ---
    best = df_combined[df_combined["windows_per_day"] >= 1.0]
    if not best.empty:
        top = best.iloc[0]
        print(f"\n>>> DECISION GATE: at threshold {top['aligned_4h_thr']}: "
              f"{top['base_rate_pct']:.1f}% base rate, "
              f"{top['windows_per_day']:.2f} windows/day")
        if top["base_rate_pct"] >= 68.0:
            print(">>> ✓ Strategy kernel found: spread filter + aligned momentum")
        else:
            print(">>> base rate < 68% at viable frequency — proceed to Phase 1")
    else:
        print(">>> All qualifying thresholds fire < 1 window/day — proceed to Phase 1")

    # ===== CHARTS =====
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    fig.suptitle(
        f"Phase 0 — Prior spot momentum vs base rate  "
        f"(tight-spread ≤ {SPREAD_THRESHOLD}%, n={n_tight:,})",
        fontsize=13, fontweight="bold"
    )

    # Row 0: 4h momentum (calls, puts, combined filter)
    _momentum_bars(axes[0][0], tbl_4h_calls, "4h prior momentum — Calls",
                   overall_br, "#4e79a7", "Spot Δ 4h before entry")
    _momentum_bars(axes[0][1], tbl_4h_puts,  "4h prior momentum — Puts",
                   overall_br, "#e15759", "Spot Δ 4h before entry")
    _combined_filter_chart(axes[0][2], df_combined, overall_br)

    # Row 1: 1h momentum (calls, puts) + 30m calls-vs-puts split
    _momentum_bars(axes[1][0], tbl_1h_calls, "1h prior momentum — Calls",
                   overall_br, "#4e79a7", "Spot Δ 1h before entry")
    _momentum_bars(axes[1][1], tbl_1h_puts,  "1h prior momentum — Puts",
                   overall_br, "#e15759", "Spot Δ 1h before entry")

    # 30m: calls vs puts side-by-side
    tbl_30m_calls = _base_rate_by_bucket(df_calls, "spot_30m_chg_pct")
    tbl_30m_puts  = _base_rate_by_bucket(df_puts,  "spot_30m_chg_pct")
    ax = axes[1][2]
    buckets = tbl_30m_calls["bucket"].tolist()
    xc = np.arange(len(buckets))
    w  = 0.38
    ax.bar(xc - w/2, tbl_30m_calls["base_rate_pct"], width=w,
           label="Calls", color="#4e79a7", alpha=0.85, zorder=3)
    ax.bar(xc + w/2, tbl_30m_puts["base_rate_pct"],  width=w,
           label="Puts",  color="#e15759", alpha=0.85, zorder=3)
    ax.set_xticks(xc)
    ax.set_xticklabels(buckets, fontsize=7.5)
    ax.set_xlabel("Spot Δ 30min before entry", fontsize=9)
    ax.set_ylabel("Base Rate (%)", fontsize=9)
    ax.set_title("30-min momentum: calls vs puts", fontsize=9.5)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2,
               label=f"Avg {overall_br:.1f}%", zorder=2)
    ax.set_ylim(30, 90)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.legend(fontsize=8)

    plt.tight_layout()
    out_svg = HERE / "phase0_overview.svg"
    plt.savefig(out_svg, bbox_inches="tight")
    print(f"\nSaved {out_svg}")
    print("Done.")


if __name__ == "__main__":
    main()
