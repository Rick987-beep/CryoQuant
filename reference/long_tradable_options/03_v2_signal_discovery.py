"""03_v2_signal_discovery.py — Signal discovery for 2× option winners.

Universe: full scan universe (DTE 1–7, no price floor beyond scan minimum).
Section 0 breaks down stats by DTE and price tier for comparison.
Source:   candidates_1h_enriched.parquet

Sections
--------
  A  Vol regime    : iv_30d_pct_rank, hv_1d, iv_hv_ratio
  B  Spot state    : spot_vs_24h_ema, spot_1h_accel, MTF momentum grid
  C  Spread        : win rate + option count at each spread threshold
  D  AUC + combos  : per-feature AUC, top filter combinations, fire frequency

Key metric beyond win_rate: avg_peak_multiple — do filters select bigger winners?

Outputs (CSV alongside this script)
------------------------------------
  03_vol_regime.csv
  03_spot_state.csv
  03_mtf_calls.csv, 03_mtf_puts.csv
  03_spread.csv
  03_feature_auc.csv
  03_combinations.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DTE_MIN        = 1          # include 1DTE — Section 0 shows breakdown
DTE_MAX        = 5          # 6-7DTE have <10% win rate — excluded
MIN_PRICE_USD  = 0.0        # no price floor — Section 0 shows breakdown
PERIOD_DAYS    = 132
PERIOD_WEEKS   = PERIOD_DAYS / 7.0

# Spot-move bucket edges (%)
BINS_4H   = [-np.inf, -3.0, -1.0, -0.3, 0.3, 1.0, 3.0, np.inf]
LABS_4H   = ["<-3%", "-3:-1%", "-1:-0.3%", "±0.3%", "+0.3:+1%", "+1:+3%", ">+3%"]

BINS_1H   = [-np.inf, -1.5, -0.5, -0.15, 0.15, 0.5, 1.5, np.inf]
LABS_1H   = ["<-1.5%", "-1.5:-.5%", "-.5:-.15%", "±0.15%", "+.15:+.5%", "+.5:+1.5%", ">+1.5%"]

BINS_EMA  = [-np.inf, -2.0, -0.75, 0.75, 2.0, np.inf]
LABS_EMA  = ["<-2%", "-2:-0.75%", "±0.75%", "+0.75:+2%", ">+2%"]

BINS_ACC  = [-np.inf, -1.0, -0.3, 0.3, 1.0, np.inf]
LABS_ACC  = ["<-1%", "-1:-0.3%", "±0.3%", "+0.3:+1%", ">+1%"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auc(df: pd.DataFrame, col: str) -> float:
    """Mann-Whitney AUC of `col` predicting tradeable=1 vs 0."""
    valid = df[[col, "tradeable"]].dropna()
    if len(valid) < 50 or valid["tradeable"].nunique() < 2:
        return float("nan")
    pos = valid.loc[valid["tradeable"] == 1, col].values
    neg = valid.loc[valid["tradeable"] == 0, col].values
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    u, _ = mannwhitneyu(pos, neg, alternative="greater")
    return round(float(u) / (len(pos) * len(neg)), 3)


def _bucket_stats(df: pd.DataFrame, col: str, bins, labels) -> pd.DataFrame:
    tmp = df.copy()
    tmp["_b"] = pd.cut(tmp[col], bins=bins, labels=labels)
    grp = tmp.groupby("_b", observed=True)
    out = pd.DataFrame({
        "bucket"        : labels,
        "n"             : grp["tradeable"].count().reindex(labels).values,
        "win_rate"      : grp["tradeable"].mean().reindex(labels).round(3).values,
        "avg_multiple"  : grp["peak_multiple_24h"].mean().reindex(labels).round(3).values,
        "fires_per_day" : (grp["tradeable"].count().reindex(labels) / PERIOD_DAYS).round(2).values,
    })
    return out


def _quintile_stats(df: pd.DataFrame, col: str) -> pd.DataFrame:
    tmp = df[[col, "tradeable", "peak_multiple_24h"]].dropna(subset=[col]).copy()
    tmp["_q"] = pd.qcut(tmp[col], q=5, labels=False, duplicates="drop")
    # Get bin edges for display
    cuts = pd.qcut(tmp[col], q=5, duplicates="drop")
    label_map = {i: f"Q{i+1} {iv}" for i, iv in enumerate(cuts.cat.categories)}
    tmp["_ql"] = tmp["_q"].map(label_map)
    grp = tmp.groupby("_ql", observed=True)
    out = (
        grp[["tradeable", "peak_multiple_24h"]]
        .agg(n=("tradeable", "count"), win_rate=("tradeable", "mean"),
             avg_multiple=("peak_multiple_24h", "mean"))
        .round(3)
        .reset_index()
        .rename(columns={"_ql": "quintile"})
    )
    out["fires_per_day"]  = (out["n"] / PERIOD_DAYS).round(2)
    out["fires_per_week"] = (out["n"] / PERIOD_WEEKS).round(1)
    return out


def _signal_stats(df: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    """Stats for a filter mask — counts unique signal hours, not just rows."""
    sub = df[mask]
    if len(sub) == 0:
        return {"filter": label, "n_options": 0, "n_signal_hours": 0,
                "options_per_signal": 0, "win_rate": float("nan"),
                "avg_multiple": float("nan"), "fires_per_day": 0, "fires_per_week": 0}
    sig_hours = int(sub["entry_ts_us"].nunique())
    n_opts    = len(sub)
    return {
        "filter"             : label,
        "n_options"          : n_opts,
        "n_signal_hours"     : sig_hours,
        "opts_per_signal"    : round(n_opts / max(sig_hours, 1), 1),
        "win_rate"           : round(float(sub["tradeable"].mean()), 3),
        "avg_multiple"       : round(float(sub["peak_multiple_24h"].mean()), 3),
        "fires_per_day"      : round(sig_hours / PERIOD_DAYS, 2),
        "fires_per_week"     : round(sig_hours / PERIOD_WEEKS, 1),
    }


def _hdr(title: str) -> None:
    print(f"\n{'='*72}\n  {title}\n{'='*72}")


def _sub(title: str) -> None:
    print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    enriched = pd.read_parquet(HERE / "candidates_1h_enriched.parquet")

    # ── Universe filter ───────────────────────────────────────────────────
    df = enriched[
        (enriched["dte_at_entry"]  >= DTE_MIN) &
        (enriched["dte_at_entry"]  <= DTE_MAX) &
        (enriched["entry_ask_usd"] >= MIN_PRICE_USD)
    ].copy().reset_index(drop=True)

    base_rate  = float(df["tradeable"].mean())
    n_sig_hrs  = int(df["entry_ts_us"].nunique())

    print(f"\nUniverse  : {len(df):,} options | DTE {DTE_MIN}–{DTE_MAX} | ask ≥ ${MIN_PRICE_USD:.0f}")
    print(f"Base rate : {base_rate:.3f}  ({df['tradeable'].sum():,} winners / {len(df):,})")
    print(f"Period    : {PERIOD_DAYS} days = {PERIOD_WEEKS:.1f} weeks")
    print(f"Signal hrs: {n_sig_hrs:,}  →  {n_sig_hrs / PERIOD_DAYS:.1f}/day  "
          f"({n_sig_hrs / PERIOD_WEEKS:.1f}/week)")
    print(f"Opts/hr   : {len(df) / n_sig_hrs:.1f}  (option selection breadth per entry hour)")

    # =========================================================================
    # SECTION 0 — UNIVERSE BREAKDOWN (DTE tier × price tier)
    # =========================================================================
    _hdr("0 — UNIVERSE BREAKDOWN  (before any signal filter)")

    _sub("0A: by DTE")
    dte_rows = []
    for dte in sorted(df["dte_at_entry"].unique()):
        m = df["dte_at_entry"] == dte
        dte_rows.append(_signal_stats(df, m, f"DTE {dte}"))
    dte_df = pd.DataFrame(dte_rows)
    print(dte_df[["filter", "n_options", "n_signal_hours", "opts_per_signal",
                  "win_rate", "avg_multiple", "fires_per_week"]].to_string(index=False))
    dte_df.to_csv(HERE / "03_universe_dte.csv", index=False)

    _sub("0B: by entry_ask_usd price tier")
    price_bins  = [0, 50, 100, 150, 250, 500, np.inf]
    price_labs  = ["<$50", "$50–100", "$100–150", "$150–250", "$250–500", ">$500"]
    price_rows  = []
    for lab, lo, hi in zip(price_labs, price_bins[:-1], price_bins[1:]):
        m = (df["entry_ask_usd"] >= lo) & (df["entry_ask_usd"] < hi)
        price_rows.append(_signal_stats(df, m, lab))
    price_df = pd.DataFrame(price_rows)
    print(price_df[["filter", "n_options", "n_signal_hours", "opts_per_signal",
                    "win_rate", "avg_multiple", "fires_per_week"]].to_string(index=False))
    price_df.to_csv(HERE / "03_universe_price.csv", index=False)

    _sub("0C: DTE × price tier cross-tab (win_rate)")
    df["_price_tier"] = pd.cut(df["entry_ask_usd"], bins=price_bins,
                               labels=price_labs, right=False)
    cross_rate = (df.groupby(["dte_at_entry", "_price_tier"], observed=True)["tradeable"]
                  .mean().round(3).unstack("_price_tier"))
    cross_n    = (df.groupby(["dte_at_entry", "_price_tier"], observed=True)["tradeable"]
                  .count().unstack("_price_tier"))
    print("Win rates:")
    print(cross_rate.to_string())
    print("Counts:")
    print(cross_n.to_string())
    df.drop(columns=["_price_tier"], inplace=True)
    cross_rate.reset_index().to_csv(HERE / "03_universe_cross.csv", index=False)

    base_rate  = float(df["tradeable"].mean())
    n_sig_hrs  = int(df["entry_ts_us"].nunique())
    print(f"\nFull universe : {len(df):,} options | DTE {DTE_MIN}–{DTE_MAX} | no price floor")
    print(f"Base rate     : {base_rate:.3f}  ({df['tradeable'].sum():,} winners / {len(df):,})")
    print(f"Period        : {PERIOD_DAYS} days = {PERIOD_WEEKS:.1f} weeks")
    print(f"Signal hrs    : {n_sig_hrs:,}  →  {n_sig_hrs / PERIOD_DAYS:.1f}/day  "
          f"({n_sig_hrs / PERIOD_WEEKS:.1f}/week)")
    print(f"Opts/hr       : {len(df) / n_sig_hrs:.1f}  (option selection breadth per entry hour)")

    # Precompute call/put direction-aligned momentum
    sign = np.where(df["is_call"].values, 1.0, -1.0)
    df["aligned_4h"] = df["spot_4h_chg_pct"] * sign
    df["aligned_1h"] = df["spot_1h_chg_pct"] * sign
    df["abs_delta"]  = df["delta_at_entry"].abs()

    calls = df[df["is_call"]].copy()
    puts  = df[~df["is_call"]].copy()
    puts["inv_4h"] = -puts["spot_4h_chg_pct"]
    puts["inv_1h"] = -puts["spot_1h_chg_pct"]

    all_section_csvs: dict[str, pd.DataFrame] = {}

    # =========================================================================
    # SECTION A — VOL REGIME
    # =========================================================================
    _hdr("A — VOL REGIME")

    _sub("A1: iv_30d_pct_rank (quintiles)")
    a1 = _quintile_stats(df, "iv_30d_pct_rank")
    auc_a1 = _auc(df, "iv_30d_pct_rank")
    print(a1.to_string(index=False))
    print(f"  AUC = {auc_a1}")
    all_section_csvs["03_vol_regime_iv_rank.csv"] = a1

    _sub("A2: hv_1d (quintiles)")
    a2 = _quintile_stats(df, "hv_1d")
    auc_a2 = _auc(df, "hv_1d")
    print(a2.to_string(index=False))
    print(f"  AUC = {auc_a2}")
    all_section_csvs["03_vol_regime_hv1d.csv"] = a2

    _sub("A3: iv_hv_ratio (quintiles)")
    a3 = _quintile_stats(df, "iv_hv_ratio")
    auc_a3 = _auc(df, "iv_hv_ratio")
    print(a3.to_string(index=False))
    print(f"  AUC = {auc_a3}")
    all_section_csvs["03_vol_regime_ivhv.csv"] = a3

    # =========================================================================
    # SECTION B — SPOT STATE
    # =========================================================================
    _hdr("B — SPOT STATE AT ENTRY")

    _sub("B1: spot_vs_24h_ema  (is spot compressed or extended?)")
    b1 = _bucket_stats(df, "spot_vs_24h_ema", BINS_EMA, LABS_EMA)
    auc_b1 = _auc(df, "spot_vs_24h_ema")
    print(b1.to_string(index=False))
    print(f"  AUC = {auc_b1}")

    _sub("B2: spot_1h_accel  (is momentum accelerating at entry?)")
    b2 = _bucket_stats(df, "spot_1h_accel", BINS_ACC, LABS_ACC)
    auc_b2 = _auc(df, "spot_1h_accel")
    print(b2.to_string(index=False))
    print(f"  AUC = {auc_b2}")

    pd.concat([
        b1.assign(feature="spot_vs_24h_ema"),
        b2.assign(feature="spot_1h_accel"),
    ]).to_csv(HERE / "03_spot_state.csv", index=False)

    # ── 4h momentum: calls (aligned = positive direction = spot rising) ──
    _sub("B3: 4h spot momentum — CALLS  (positive = rising spot = favorable)")
    b3c = _bucket_stats(calls, "spot_4h_chg_pct", BINS_4H, LABS_4H)
    print(b3c.to_string(index=False))
    b3c.to_csv(HERE / "03_mtf_calls_4h.csv", index=False)

    _sub("B4: 4h spot momentum — PUTS  (positive = falling spot = favorable, shown inverted)")
    b3p = _bucket_stats(puts, "inv_4h", BINS_4H, LABS_4H)
    print(b3p.to_string(index=False))
    b3p.to_csv(HERE / "03_mtf_puts_4h.csv", index=False)

    # ── MTF grid: 4h × 1h momentum (pivot heatmap) ───────────────────────
    _sub("B5: MTF heatmap — CALLS  (win_rate, rows=4h bucket, cols=1h bucket)")
    calls_tmp          = calls.copy()
    calls_tmp["b4h"]   = pd.cut(calls_tmp["spot_4h_chg_pct"], bins=BINS_4H, labels=LABS_4H)
    calls_tmp["b1h"]   = pd.cut(calls_tmp["spot_1h_chg_pct"], bins=BINS_1H, labels=LABS_1H)
    mtf_calls_rate     = (calls_tmp.groupby(["b4h", "b1h"], observed=True)["tradeable"]
                          .mean().round(3).unstack("b1h"))
    mtf_calls_n        = (calls_tmp.groupby(["b4h", "b1h"], observed=True)["tradeable"]
                          .count().unstack("b1h"))
    print("Win rates:")
    print(mtf_calls_rate.to_string())
    print("Counts:")
    print(mtf_calls_n.to_string())
    mtf_calls_rate.reset_index().to_csv(HERE / "03_mtf_calls.csv", index=False)

    _sub("B6: MTF heatmap — PUTS  (inverted momentum: positive = spot falling)")
    puts_tmp        = puts.copy()
    puts_tmp["b4h"] = pd.cut(puts_tmp["inv_4h"], bins=BINS_4H, labels=LABS_4H)
    puts_tmp["b1h"] = pd.cut(puts_tmp["inv_1h"], bins=BINS_1H, labels=LABS_1H)
    mtf_puts_rate   = (puts_tmp.groupby(["b4h", "b1h"], observed=True)["tradeable"]
                       .mean().round(3).unstack("b1h"))
    mtf_puts_n      = (puts_tmp.groupby(["b4h", "b1h"], observed=True)["tradeable"]
                       .count().unstack("b1h"))
    print("Win rates:")
    print(mtf_puts_rate.to_string())
    print("Counts:")
    print(mtf_puts_n.to_string())
    mtf_puts_rate.reset_index().to_csv(HERE / "03_mtf_puts.csv", index=False)

    # =========================================================================
    # SECTION C — SPREAD ANALYSIS (informational)
    # =========================================================================
    _hdr("C — SPREAD ANALYSIS  (option availability vs win rate trade-off)")

    spread_thresholds = [5, 10, 15, 20, 30, 50, None]
    spread_rows = []
    for thr in spread_thresholds:
        if thr is None:
            mask  = pd.Series(True, index=df.index)
            label = "no filter"
        else:
            mask  = df["spread_pct"] <= thr
            label = f"≤{thr}%"
        spread_rows.append(_signal_stats(df, mask, label))

    spread_df = pd.DataFrame(spread_rows)
    print(spread_df.to_string(index=False))
    spread_df.to_csv(HERE / "03_spread.csv", index=False)

    # =========================================================================
    # SECTION D — AUC + COMBINATIONS
    # =========================================================================
    _hdr("D — FEATURE AUC & FILTER COMBINATIONS")

    # ── D1: AUC per feature ─────────────────────────────────────────────
    _sub("D1: Per-feature AUC  (0.5 = random, higher = better separator)")
    feat_cols = [
        "iv_30d_pct_rank", "hv_1d", "iv_hv_ratio",
        "atm_iv_at_entry",
        "spot_vs_24h_ema", "spot_1h_accel",
        "spot_1h_chg_pct", "spot_4h_chg_pct",
        "aligned_4h", "aligned_1h",
        "spread_pct", "abs_delta", "dte_at_entry",
    ]
    auc_rows = []
    for col in feat_cols:
        if col not in df.columns:
            continue
        auc_rows.append({
            "feature"  : col,
            "auc_all"  : _auc(df,    col),
            "auc_calls": _auc(calls, col),
            "auc_puts" : _auc(puts,  col),
        })
    auc_df = (pd.DataFrame(auc_rows)
              .sort_values("auc_all", ascending=False)
              .reset_index(drop=True))
    print(auc_df.to_string(index=False))
    auc_df.to_csv(HERE / "03_feature_auc.csv", index=False)

    # ── D2: Combination filters ─────────────────────────────────────────
    _sub("D2: Filter combinations  (key metric: fires_per_week vs win_rate)")

    # Precompute useful thresholds from the data
    iv_rank  = df["iv_30d_pct_rank"]
    hv       = df["hv_1d"]
    ivhv     = df["iv_hv_ratio"]
    ema      = df["spot_vs_24h_ema"]
    acc      = df["spot_1h_accel"]
    a4h      = df["aligned_4h"]
    a1h      = df["aligned_1h"]

    hv_p50   = float(hv.median())
    hv_p75   = float(hv.quantile(0.75))

    combos: list[tuple[str, pd.Series]] = []

    # Baselines
    combos += [
        ("BASELINE",                    pd.Series(True, index=df.index)),
        ("DTE 2–3 only",               df["dte_at_entry"] <= 3),
        ("DTE 4–7 only",               df["dte_at_entry"] >= 4),
    ]

    # Single vol-regime filters
    combos += [
        ("iv_rank ≥ 0.40",             iv_rank >= 0.40),
        ("iv_rank ≥ 0.60",             iv_rank >= 0.60),
        ("iv_rank ≥ 0.75",             iv_rank >= 0.75),
        ("hv_1d ≥ median",             hv      >= hv_p50),
        ("hv_1d ≥ 75th pct",           hv      >= hv_p75),
        ("iv_hv_ratio ≥ 1.0",          ivhv    >= 1.0),
        ("iv_hv_ratio ≥ 1.2",          ivhv    >= 1.2),
    ]

    # Spot state filters
    combos += [
        ("spot near EMA (±0.75%)",     ema.abs() <= 0.75),
        ("spot extended >+1% (calls)", (ema > 1.0)  & df["is_call"]),
        ("spot extended <-1% (puts)",  (ema < -1.0) & ~df["is_call"]),
        ("aligned_4h > 0",             a4h > 0),
        ("aligned_4h > +1%",           a4h > 1.0),
        ("aligned_4h > +2%",           a4h > 2.0),
        ("accel > 0 (onset)",          acc > 0),
        ("accel > +0.3% (strong)",     acc > 0.3),
    ]

    # Two-feature vol combos
    combos += [
        ("iv_rank≥0.60 + hv≥med",
         (iv_rank >= 0.60) & (hv >= hv_p50)),
        ("iv_rank≥0.60 + iv_hv≥1.0",
         (iv_rank >= 0.60) & (ivhv >= 1.0)),
        ("iv_rank≥0.75 + hv≥med",
         (iv_rank >= 0.75) & (hv >= hv_p50)),
        ("iv_rank≥0.60 + near EMA",
         (iv_rank >= 0.60) & (ema.abs() <= 0.75)),
        ("hv≥med + iv_hv≥1.0",
         (hv >= hv_p50) & (ivhv >= 1.0)),
    ]

    # Vol + momentum combos
    combos += [
        ("iv_rank≥0.60 + aligned_4h>0",
         (iv_rank >= 0.60) & (a4h > 0)),
        ("iv_rank≥0.60 + aligned_4h>+1%",
         (iv_rank >= 0.60) & (a4h > 1.0)),
        ("iv_rank≥0.75 + aligned_4h>0",
         (iv_rank >= 0.75) & (a4h > 0)),
        ("iv_rank≥0.60 + accel>0",
         (iv_rank >= 0.60) & (acc > 0)),
    ]

    # Three-feature combos
    combos += [
        ("iv_rank≥0.60 + hv≥med + aligned_4h>0",
         (iv_rank >= 0.60) & (hv >= hv_p50) & (a4h > 0)),
        ("iv_rank≥0.60 + hv≥med + aligned_4h>+1%",
         (iv_rank >= 0.60) & (hv >= hv_p50) & (a4h > 1.0)),
        ("iv_rank≥0.60 + iv_hv≥1.0 + aligned_4h>0",
         (iv_rank >= 0.60) & (ivhv >= 1.0) & (a4h > 0)),
        ("iv_rank≥0.75 + aligned_4h>0 + accel>0",
         (iv_rank >= 0.75) & (a4h > 0) & (acc > 0)),
        ("iv_rank≥0.60 + near EMA + accel>0",
         (iv_rank >= 0.60) & (ema.abs() <= 0.75) & (acc > 0)),
        ("iv_rank≥0.60 + hv≥med + accel>0",
         (iv_rank >= 0.60) & (hv >= hv_p50) & (acc > 0)),
    ]

    combo_rows = [_signal_stats(df, m, lbl) for lbl, m in combos]
    combo_df   = pd.DataFrame(combo_rows)
    print(combo_df.to_string(index=False))
    combo_df.to_csv(HERE / "03_combinations.csv", index=False)

    # ── Save remaining CSVs ───────────────────────────────────────────────
    for fname, frame in all_section_csvs.items():
        frame.to_csv(HERE / fname, index=False)

    # =========================================================================
    # SUMMARY
    # =========================================================================
    _hdr("SUMMARY")
    print(f"Base rate (DTE {DTE_MIN}–{DTE_MAX}, ask≥${MIN_PRICE_USD:.0f}): {base_rate:.3f}")
    print(f"Best AUC feature: {auc_df.iloc[0]['feature']}  (AUC={auc_df.iloc[0]['auc_all']})")

    # Best combos by win_rate among those with ≥2 fires/week
    viable = combo_df[combo_df["fires_per_week"] >= 2.0].nlargest(5, "win_rate")
    print(f"\nTop 5 combos with ≥2 fires/week:")
    if len(viable):
        print(viable[["filter", "win_rate", "avg_multiple",
                       "fires_per_week", "opts_per_signal"]].to_string(index=False))
    else:
        print("  None with ≥2/week found.")

    # Best combos with ≥10 fires/week (more liquidity)
    frequent = combo_df[combo_df["fires_per_week"] >= 10.0].nlargest(5, "win_rate")
    print(f"\nTop 5 combos with ≥10 fires/week (high frequency):")
    if len(frequent):
        print(frequent[["filter", "win_rate", "avg_multiple",
                         "fires_per_week", "opts_per_signal"]].to_string(index=False))
    else:
        print("  None with ≥10/week found.")


if __name__ == "__main__":
    main()
