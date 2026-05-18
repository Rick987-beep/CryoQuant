"""11d_optimise.py — Exit rule grid search over 11c forward P&L curves.

For each (signal × DTE × delta_target × TP × time_stop × SL) combination:
  - Walk the 5-min forward P&L curve from 11c_pnl_curves.parquet
  - Apply exit rules in priority order: TP → SL → time-stop → hold to expiry
  - Record exit multiple (straddle_bid / entry_ask at exit) and exit reason
  - Aggregate: expected_value, expected_dollar_pnl, win_rate, hit_tp_pct

Grid
----
  TP:          [None, 1.3, 1.5, 2.0, 2.5]   (None = no TP, rely on time-stop/SL)
  time_stop_h: [4, 8, 12, 16, 20]
  SL:          [None, 0.3, 0.5]              (None = no stop-loss)
  → 75 combinations per (signal, DTE, delta_target)

Key metric: expected_dollar_pnl = (mean_exit_multiple - 1.0) × mean_entry_ask_usd
Secondary:  win_rate = fraction of fires exiting with multiple ≥ 1.0

Sections
--------
  A  Global top-20 combos by expected_dollar_pnl — pullback
  B  Global top-20 combos by expected_dollar_pnl — vol_burst
  C  Best configuration per (DTE, delta_target)
  D  Expected-value heatmap by (TP, time_stop) — best SL auto-selected
  E  Recommended final configuration summary

Outputs
-------
  11d_grid_results.csv   — full 75-combo × group grid (all stats)
  11d_best_per_group.csv — single best combo per (signal, DTE, delta_target)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# ── Grid ─────────────────────────────────────────────────────────────────────
TP_GRID         = [None, 1.3, 1.5, 2.0, 2.5]
TIME_STOP_GRID  = [4, 8, 12, 16, 20]
SL_GRID         = [None, 0.3, 0.5]

# Focus cells for compact output
FOCUS_DTE       = [1, 2, 3]
FOCUS_DELTA     = [0.15, 0.20, 0.25, 0.30, 0.35]
ALL_SIGNALS     = ["pullback", "vol_burst"]


# ── Exit simulation ───────────────────────────────────────────────────────────

def _apply_exit(
    bars_h: np.ndarray,
    multiples: np.ndarray,
    tp: float | None,
    time_stop_h: float,
    sl: float | None,
) -> tuple[float, str]:
    """Walk a fire's 5-min P&L curve and apply exit rules.

    Priority: TP → SL → time-stop → expiry (last bar).
    Returns (exit_multiple, exit_reason).
    """
    # Pre-compute first-crossing indices (n = out-of-bounds = never)
    n = len(multiples)
    tp_idx = n
    sl_idx = n
    ts_idx = n

    if tp is not None:
        hits = np.nonzero(multiples >= tp)[0]
        if len(hits):
            tp_idx = int(hits[0])

    if sl is not None:
        hits = np.nonzero(multiples <= sl)[0]
        if len(hits):
            sl_idx = int(hits[0])

    hits = np.nonzero(bars_h >= time_stop_h)[0]
    if len(hits):
        ts_idx = int(hits[0])

    # Exit at the earliest trigger, TP wins ties
    exit_i = min(tp_idx, sl_idx, ts_idx)
    if exit_i >= n:
        return float(multiples[-1]), "expiry"
    if exit_i == tp_idx:
        return float(multiples[exit_i]), "tp"
    if exit_i == sl_idx:
        return float(multiples[exit_i]), "sl"
    return float(multiples[exit_i]), "ts"


# ── Print helpers ─────────────────────────────────────────────────────────────

def _header(s: str) -> None:
    print(); print("=" * 76); print(f"  {s}"); print("=" * 76)

def _tp_label(tp: float | None) -> str:
    return "  —" if tp is None else f"{tp:.1f}×"

def _sl_label(sl: float | None) -> str:
    return " — " if sl is None else f"{sl:.1f}×"


def _print_top(df: pd.DataFrame, signal: str, n: int = 20) -> None:
    """Print top-N rows by expected_dollar_pnl for a signal tier."""
    sub = (df[df["signal"] == signal]
           .sort_values("expected_dollar_pnl", ascending=False)
           .head(n))
    if sub.empty:
        return
    print(f"\n  signal={signal}")
    print(f"  {'DTE':>3}  {'δ':>5}  {'TP':>5}  {'TS':>5}  {'SL':>5}  "
          f"{'N':>5}  {'E[×]':>6}  {'E[$]':>8}  {'win%':>6}  "
          f"{'%TP':>5}  {'%SL':>5}  {'%TS':>5}")
    print("  " + "-" * 78)
    for r in sub.itertuples(index=False):
        print(f"  {r.dte:>3}  {r.delta_target:>5.2f}  "
              f"{_tp_label(r.tp):>5}  {r.time_stop_h:>4.0f}h  {_sl_label(r.sl):>5}  "
              f"{r.n_fires:>5}  {r.mean_exit_multiple:>5.2f}×  "
              f"${r.expected_dollar_pnl:>7.0f}  {r.win_rate:>5.0%}  "
              f"{r.hit_tp_pct:>4.0%}  {r.hit_sl_pct:>4.0%}  {r.hit_ts_pct:>4.0%}")


def _print_best_per_group(df: pd.DataFrame, signal: str) -> None:
    """Best combo per (DTE, delta_target), sorted by DTE then delta."""
    sub = df[df["signal"] == signal]
    best = (sub.loc[sub.groupby(["dte", "delta_target"])["expected_dollar_pnl"].idxmax()]
            .sort_values(["dte", "delta_target"]))
    best = best[best["dte"].isin(FOCUS_DTE) & best["delta_target"].isin(FOCUS_DELTA)]
    if best.empty:
        return
    print(f"\n  signal={signal}")
    print(f"  {'DTE':>3}  {'δ':>5}  {'TP':>5}  {'TS':>5}  {'SL':>5}  "
          f"{'N':>5}  {'E[×]':>6}  {'E[$]':>8}  {'win%':>6}  {'%TP':>5}")
    print("  " + "-" * 68)
    for r in best.itertuples(index=False):
        print(f"  {r.dte:>3}  {r.delta_target:>5.2f}  "
              f"{_tp_label(r.tp):>5}  {r.time_stop_h:>4.0f}h  {_sl_label(r.sl):>5}  "
              f"{r.n_fires:>5}  {r.mean_exit_multiple:>5.2f}×  "
              f"${r.expected_dollar_pnl:>7.0f}  {r.win_rate:>5.0%}  "
              f"{r.hit_tp_pct:>4.0%}")


def _print_ev_heatmap(df: pd.DataFrame, signal: str, dte: int, delta: float) -> None:
    """Print E[$] heatmap: rows=TP, cols=time_stop.  Best SL auto-selected."""
    sub = (df[(df["signal"] == signal) &
              (df["dte"] == dte) &
              (df["delta_target"] == delta)]
           .groupby(["tp", "time_stop_h"], dropna=False)["expected_dollar_pnl"]
           .max()  # best SL auto-selected
           .reset_index())
    if sub.empty:
        return
    pivot = sub.pivot(index="tp", columns="time_stop_h", values="expected_dollar_pnl")
    # TP=None sorts last — reorder so None is first
    new_index = [None] + [t for t in TP_GRID if t is not None and t in pivot.index]
    pivot = pivot.reindex([r for r in new_index if r in pivot.index])

    col_hdr = "  ".join(f"TS{int(c):>2}h" for c in pivot.columns)
    print(f"\n  DTE={dte}  δ={delta:.2f}  (best SL auto-selected, E[$])")
    print(f"  {'TP':>5}  {col_hdr}")
    print("  " + "-" * (8 + 8 * len(pivot.columns)))
    for tp_val in pivot.index:
        row_vals = "  ".join(
            f"${pivot.loc[tp_val, c]:>5.0f}" if not np.isnan(pivot.loc[tp_val, c])
            else "    — "
            for c in pivot.columns
        )
        print(f"  {_tp_label(tp_val):>5}  {row_vals}")


# =============================================================================
# Main
# =============================================================================

def main() -> None:

    # ── Load curves ──────────────────────────────────────────────────────────
    print("Loading 11c_pnl_curves.parquet …")
    curves = pd.read_parquet(HERE / "11c_pnl_curves.parquet")
    print(f"  {len(curves):,} rows, {curves['fire_ts'].nunique():,} fires")

    # ── Grid application ─────────────────────────────────────────────────────
    print("Applying exit rule grid …")
    fire_results: list[dict] = []

    groups = list(curves.groupby(["signal", "fire_ts", "dte", "delta_target"],
                                 sort=False))
    n_groups = len(groups)

    for gi, (key, grp) in enumerate(groups):
        if (gi + 1) % 500 == 0:
            print(f"  [{gi+1}/{n_groups}] …")

        signal, fire_ts, dte, delta_target = key
        bars_h    = grp["bar_h"].values
        multiples = grp["multiple"].values
        entry_ask = float(grp["entry_ask"].iloc[0])

        for tp in TP_GRID:
            for ts in TIME_STOP_GRID:
                for sl in SL_GRID:
                    exit_m, reason = _apply_exit(bars_h, multiples, tp, ts, sl)
                    fire_results.append({
                        "signal":        signal,
                        "fire_ts":       fire_ts,
                        "dte":           dte,
                        "delta_target":  delta_target,
                        "tp":            tp,
                        "time_stop_h":   ts,
                        "sl":            sl,
                        "exit_multiple": exit_m,
                        "exit_reason":   reason,
                        "entry_ask_usd": entry_ask,
                    })

    print(f"  Done — {len(fire_results):,} exit simulations")

    # ── Aggregate ─────────────────────────────────────────────────────────────
    print("Aggregating …")
    raw = pd.DataFrame(fire_results)

    agg_rows: list[dict] = []
    for key, g in raw.groupby(
        ["signal", "dte", "delta_target", "tp", "time_stop_h", "sl"],
        dropna=False, sort=False
    ):
        signal, dte, delta_target, tp, time_stop_h, sl = key
        em  = g["exit_multiple"]
        ea  = g["entry_ask_usd"]
        dollar_pnl = (em - 1.0) * ea

        agg_rows.append({
            "signal":              signal,
            "dte":                 dte,
            "delta_target":        delta_target,
            "tp":                  tp,
            "time_stop_h":         time_stop_h,
            "sl":                  sl,
            "n_fires":             len(g),
            "mean_exit_multiple":  round(em.mean(), 4),
            "median_exit_multiple": round(em.median(), 4),
            "std_exit_multiple":   round(em.std(), 4),
            "win_rate":            round((em >= 1.0).mean(), 4),
            "hit_tp_pct":          round((g["exit_reason"] == "tp").mean(), 4),
            "hit_sl_pct":          round((g["exit_reason"] == "sl").mean(), 4),
            "hit_ts_pct":          round((g["exit_reason"] == "ts").mean(), 4),
            "hit_expiry_pct":      round((g["exit_reason"] == "expiry").mean(), 4),
            "mean_entry_ask_usd":  round(ea.mean(), 2),
            "expected_dollar_pnl": round(dollar_pnl.mean(), 2),
            "median_dollar_pnl":   round(dollar_pnl.median(), 2),
        })

    agg = pd.DataFrame(agg_rows)

    # =========================================================================
    # Section A/B — Global top-20 by expected_dollar_pnl
    # =========================================================================
    _header("A — TOP-20 CONFIGURATIONS  (pullback, sorted by E[$] per fire)")
    _print_top(agg, "pullback", n=20)

    _header("B — TOP-20 CONFIGURATIONS  (vol_burst, sorted by E[$] per fire)")
    _print_top(agg, "vol_burst", n=20)

    # =========================================================================
    # Section C — Best combo per (DTE, delta_target)
    # =========================================================================
    _header("C — BEST COMBO PER (DTE × δ)  (highest E[$] auto-selected)")
    for sig in ALL_SIGNALS:
        _print_best_per_group(agg, sig)

    # =========================================================================
    # Section D — E[$] heatmap (TP × time_stop) for key cells
    # =========================================================================
    _header("D — E[$] HEATMAP  (best SL auto-selected per cell)")
    for sig in ALL_SIGNALS:
        print(f"\n  === {sig} ===")
        for dte in [1, 2]:
            for dt in [0.20, 0.30]:
                _print_ev_heatmap(agg, sig, dte, dt)

    # =========================================================================
    # Section E — Recommended configuration
    # =========================================================================
    _header("E — RECOMMENDED FINAL CONFIGURATION")
    for sig in ALL_SIGNALS:
        sub = agg[agg["signal"] == sig]
        # Filter to DTE 1-3 and delta 0.15-0.35 for practical trades
        sub = sub[sub["dte"].isin(FOCUS_DTE) & sub["delta_target"].isin(FOCUS_DELTA)]
        best_row = sub.loc[sub["expected_dollar_pnl"].idxmax()]
        print(f"\n  {sig}:")
        print(f"    DTE={int(best_row.dte)}, δ={best_row.delta_target:.2f}, "
              f"TP={_tp_label(best_row.tp)}, "
              f"time_stop={int(best_row.time_stop_h)}h, "
              f"SL={_sl_label(best_row.sl)}")
        print(f"    E[exit multiple] = {best_row.mean_exit_multiple:.3f}×  "
              f"E[$] = ${best_row.expected_dollar_pnl:.0f} per fire  "
              f"win rate = {best_row.win_rate:.0%}")
        print(f"    TP hit: {best_row.hit_tp_pct:.0%}  "
              f"SL hit: {best_row.hit_sl_pct:.0%}  "
              f"time-stop: {best_row.hit_ts_pct:.0%}  "
              f"held to expiry: {best_row.hit_expiry_pct:.0%}")
        # Also show runner-up (2nd best, different (DTE,delta) to diversify)
        excl = (best_row.dte, best_row.delta_target)
        alt = sub[~((sub["dte"] == excl[0]) & (sub["delta_target"] == excl[1]))]
        if not alt.empty:
            alt_row = alt.loc[alt["expected_dollar_pnl"].idxmax()]
            print(f"    Runner-up: DTE={int(alt_row.dte)}, δ={alt_row.delta_target:.2f}, "
                  f"TP={_tp_label(alt_row.tp)}, TS={int(alt_row.time_stop_h)}h, "
                  f"SL={_sl_label(alt_row.sl)}  →  E[$]=${alt_row.expected_dollar_pnl:.0f}  "
                  f"win={alt_row.win_rate:.0%}")

    # =========================================================================
    # Save outputs
    # =========================================================================
    out_grid = HERE / "11d_grid_results.csv"
    agg.to_csv(out_grid, index=False)
    print(f"\n  → Saved {len(agg):,} rows to 11d_grid_results.csv")

    best_per = (agg.loc[agg.groupby(["signal", "dte", "delta_target"])
                         ["expected_dollar_pnl"].idxmax()]
                .sort_values(["signal", "dte", "delta_target"])
                .reset_index(drop=True))
    out_best = HERE / "11d_best_per_group.csv"
    best_per.to_csv(out_best, index=False)
    print(f"  → Saved {len(best_per):,} rows to 11d_best_per_group.csv")

    print("\nDone.")


if __name__ == "__main__":
    main()
