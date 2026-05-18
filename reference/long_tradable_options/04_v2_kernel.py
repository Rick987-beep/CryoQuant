"""04_v2_kernel.py — Deep kernel discovery.

Builds on 03_v2_signal_discovery.py findings.  Tests:
  A  DTE-filtered vol kernels   (DTE 1-2 / 1-3  ×  iv_rank / hv combos)
  B  Crash-entry signals        (calls after 4h ≤-3%; puts after strong aligned fall)
  C  MTF pullback for calls     (4h uptrend + 1h pullback — the 66% pattern)
  D  Direction-split vol kernels (calls-only vs puts-only for all top kernels)

Output: 04_kernel_combos.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE         = Path(__file__).resolve().parent
PERIOD_DAYS  = 132
PERIOD_WEEKS = PERIOD_DAYS / 7.0
DTE_MIN, DTE_MAX = 1, 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal_stats(df: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    sub = df[mask]
    if len(sub) == 0:
        return {"filter": label, "n_options": 0, "n_signal_hours": 0,
                "opts_per_signal": 0.0, "win_rate": float("nan"),
                "avg_multiple": float("nan"), "fires_per_day": 0.0,
                "fires_per_week": 0.0, "section": ""}
    sh = int(sub["entry_ts_us"].nunique())
    return {
        "filter"         : label,
        "n_options"      : len(sub),
        "n_signal_hours" : sh,
        "opts_per_signal": round(len(sub) / max(sh, 1), 1),
        "win_rate"       : round(float(sub["tradeable"].mean()), 3),
        "avg_multiple"   : round(float(sub["peak_multiple_24h"].mean()), 3),
        "fires_per_day"  : round(sh / PERIOD_DAYS, 2),
        "fires_per_week" : round(sh / PERIOD_WEEKS, 1),
        "section"        : "",
    }


def _hdr(t: str) -> None:
    print(f"\n{'='*72}\n  {t}\n{'='*72}")


def _row(r: dict) -> None:
    print(f"  {r['filter']:<55s}  wr={r['win_rate']:.3f}  "
          f"×{r['avg_multiple']:.2f}  {r['fires_per_week']:.1f}/wk  "
          f"n={r['n_options']:,}  opts/sig={r['opts_per_signal']:.1f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    enriched = pd.read_parquet(HERE / "candidates_1h_enriched.parquet")
    df = enriched[
        (enriched["dte_at_entry"] >= DTE_MIN) &
        (enriched["dte_at_entry"] <= DTE_MAX)
    ].copy().reset_index(drop=True)

    # Precompute
    sign            = np.where(df["is_call"].values, 1.0, -1.0)
    df["aligned_4h"] = df["spot_4h_chg_pct"] * sign
    df["aligned_1h"] = df["spot_1h_chg_pct"] * sign

    hv_med   = float(df["hv_1d"].median())
    iv_rank  = df["iv_30d_pct_rank"]
    hv       = df["hv_1d"]
    a4h      = df["aligned_4h"]
    acc      = df["spot_1h_accel"]
    spot4h   = df["spot_4h_chg_pct"]
    spot1h   = df["spot_1h_chg_pct"]
    calls    = df["is_call"]
    puts     = ~df["is_call"]
    dte12    = df["dte_at_entry"] <= 2
    dte13    = df["dte_at_entry"] <= 3

    rows: list[dict] = []

    def add(section: str, label: str, mask: pd.Series) -> None:
        r = _signal_stats(df, mask, label)
        r["section"] = section
        rows.append(r)
        _row(r)

    # =========================================================================
    # A — DTE-FILTERED VOL KERNELS
    # =========================================================================
    _hdr("A — DTE-FILTERED VOL KERNELS")
    add("A", "BASELINE (DTE 1–5)",              pd.Series(True, index=df.index))
    add("A", "DTE 1–2",                         dte12)
    add("A", "DTE 1–3",                         dte13)
    add("A", "DTE 1–2  +  iv_rank≥0.60",        dte12 & (iv_rank >= 0.60))
    add("A", "DTE 1–2  +  iv_rank≥0.75",        dte12 & (iv_rank >= 0.75))
    add("A", "DTE 1–2  +  hv≥median",           dte12 & (hv >= hv_med))
    add("A", "DTE 1–2  +  iv_rank≥0.60 + hv≥med",
        dte12 & (iv_rank >= 0.60) & (hv >= hv_med))
    add("A", "DTE 1–2  +  iv_rank≥0.75 + hv≥med",
        dte12 & (iv_rank >= 0.75) & (hv >= hv_med))
    add("A", "DTE 1–3  +  iv_rank≥0.60",        dte13 & (iv_rank >= 0.60))
    add("A", "DTE 1–3  +  iv_rank≥0.75",        dte13 & (iv_rank >= 0.75))
    add("A", "DTE 1–3  +  iv_rank≥0.60 + hv≥med",
        dte13 & (iv_rank >= 0.60) & (hv >= hv_med))
    add("A", "DTE 1–3  +  iv_rank≥0.75 + hv≥med",
        dte13 & (iv_rank >= 0.75) & (hv >= hv_med))
    add("A", "DTE 1–2  +  iv_rank≥0.75 + hv≥med + aligned_4h>0",
        dte12 & (iv_rank >= 0.75) & (hv >= hv_med) & (a4h > 0))
    add("A", "DTE 1–3  +  iv_rank≥0.75 + hv≥med + aligned_4h>0",
        dte13 & (iv_rank >= 0.75) & (hv >= hv_med) & (a4h > 0))

    # =========================================================================
    # B — CRASH-ENTRY & STRONG-MOVE SIGNALS
    # =========================================================================
    _hdr("B — CRASH-ENTRY & STRONG-MOVE SIGNALS")
    add("B", "CALLS  +  4h ≤ -3%  (crash recovery)",
        calls & (spot4h <= -3.0))
    add("B", "CALLS  +  4h ≤ -3%  +  iv_rank≥0.40",
        calls & (spot4h <= -3.0) & (iv_rank >= 0.40))
    add("B", "CALLS  +  4h ≤ -3%  +  iv_rank≥0.60",
        calls & (spot4h <= -3.0) & (iv_rank >= 0.60))
    add("B", "CALLS  +  4h ≤ -3%  +  hv≥median",
        calls & (spot4h <= -3.0) & (hv >= hv_med))
    add("B", "CALLS  +  4h ≤ -3%  +  DTE 1–2",
        calls & (spot4h <= -3.0) & dte12)
    add("B", "CALLS  +  4h ≤ -3%  +  DTE 1–2  +  iv_rank≥0.60",
        calls & (spot4h <= -3.0) & dte12 & (iv_rank >= 0.60))
    add("B", "CALLS  +  4h ≤ -1%  (any dip)",
        calls & (spot4h <= -1.0))
    add("B", "CALLS  +  4h ≤ -1%  +  iv_rank≥0.60",
        calls & (spot4h <= -1.0) & (iv_rank >= 0.60))
    add("B", "CALLS  +  4h ≥ +3%  (strong continuation)",
        calls & (spot4h >= 3.0))
    add("B", "CALLS  +  4h ≥ +3%  +  iv_rank≥0.60",
        calls & (spot4h >= 3.0) & (iv_rank >= 0.60))
    add("B", "PUTS   +  aligned_4h ≥ +3%",
        puts & (df["aligned_4h"] >= 3.0))
    add("B", "PUTS   +  aligned_4h ≥ +3%  +  iv_rank≥0.60",
        puts & (df["aligned_4h"] >= 3.0) & (iv_rank >= 0.60))

    # =========================================================================
    # C — MTF PULLBACK: CALLS IN 4H UPTREND + 1H PULLBACK
    # =========================================================================
    _hdr("C — MTF PULLBACK (calls: 4h uptrend + 1h pullback)")
    add("C", "CALLS  +  4h=+1:+3%  +  1h≤-1.5%  [n≈198, 66%]",
        calls & (spot4h >= 1.0) & (spot4h <= 3.0) & (spot1h <= -1.5))
    add("C", "CALLS  +  4h=+1:+3%  +  1h≤-0.5%",
        calls & (spot4h >= 1.0) & (spot4h <= 3.0) & (spot1h <= -0.5))
    add("C", "CALLS  +  4h≥+1%    +  1h≤-0.5%",
        calls & (spot4h >= 1.0) & (spot1h <= -0.5))
    add("C", "CALLS  +  4h≥+1%    +  1h≤-0.15%",
        calls & (spot4h >= 1.0) & (spot1h <= -0.15))
    add("C", "CALLS  +  4h≥+0.3%  +  1h≤-0.5%",
        calls & (spot4h >= 0.3) & (spot1h <= -0.5))
    add("C", "CALLS  +  4h≥+1%    +  1h<0  (any pullback)",
        calls & (spot4h >= 1.0) & (spot1h < 0))
    add("C", "CALLS  +  4h≥+1%    +  1h≤-0.5%  +  iv_rank≥0.60",
        calls & (spot4h >= 1.0) & (spot1h <= -0.5) & (iv_rank >= 0.60))
    add("C", "CALLS  +  4h≥+1%    +  1h≤-0.5%  +  hv≥median",
        calls & (spot4h >= 1.0) & (spot1h <= -0.5) & (hv >= hv_med))
    add("C", "CALLS  +  4h=+1:+3%  +  1h≤-0.5%  +  iv_rank≥0.60",
        calls & (spot4h >= 1.0) & (spot4h <= 3.0) & (spot1h <= -0.5) & (iv_rank >= 0.60))
    add("C", "CALLS  +  4h≥+1%    +  1h≤-0.5%  +  iv_rank≥0.60 + hv≥med",
        calls & (spot4h >= 1.0) & (spot1h <= -0.5) & (iv_rank >= 0.60) & (hv >= hv_med))

    # =========================================================================
    # D — DIRECTION-SPLIT VOL KERNELS
    # =========================================================================
    _hdr("D — DIRECTION-SPLIT: CALLS vs PUTS FOR TOP KERNELS")
    add("D", "CALLS  +  iv_rank≥0.75",
        calls & (iv_rank >= 0.75))
    add("D", "PUTS   +  iv_rank≥0.75",
        puts  & (iv_rank >= 0.75))
    add("D", "CALLS  +  iv_rank≥0.75 + hv≥median",
        calls & (iv_rank >= 0.75) & (hv >= hv_med))
    add("D", "PUTS   +  iv_rank≥0.75 + hv≥median",
        puts  & (iv_rank >= 0.75) & (hv >= hv_med))
    add("D", "CALLS  +  iv_rank≥0.60 + hv≥median",
        calls & (iv_rank >= 0.60) & (hv >= hv_med))
    add("D", "PUTS   +  iv_rank≥0.60 + hv≥median",
        puts  & (iv_rank >= 0.60) & (hv >= hv_med))
    add("D", "CALLS  +  iv_rank≥0.75 + hv≥med + DTE 1–2",
        calls & (iv_rank >= 0.75) & (hv >= hv_med) & dte12)
    add("D", "PUTS   +  iv_rank≥0.75 + hv≥med + DTE 1–2",
        puts  & (iv_rank >= 0.75) & (hv >= hv_med) & dte12)
    add("D", "CALLS  +  iv_rank≥0.75 + aligned_4h>0",
        calls & (iv_rank >= 0.75) & (a4h > 0))
    add("D", "PUTS   +  iv_rank≥0.75 + aligned_4h>0",
        puts  & (iv_rank >= 0.75) & (a4h > 0))
    add("D", "CALLS  +  iv_rank≥0.60 + hv≥med + aligned_4h>0",
        calls & (iv_rank >= 0.60) & (hv >= hv_med) & (a4h > 0))
    add("D", "PUTS   +  iv_rank≥0.60 + hv≥med + aligned_4h>0",
        puts  & (iv_rank >= 0.60) & (hv >= hv_med) & (a4h > 0))
    add("D", "CALLS  +  iv_rank≥0.75 + hv≥med + aligned_4h>0 + DTE 1–2",
        calls & (iv_rank >= 0.75) & (hv >= hv_med) & (a4h > 0) & dte12)
    add("D", "PUTS   +  iv_rank≥0.75 + hv≥med + aligned_4h>0 + DTE 1–2",
        puts  & (iv_rank >= 0.75) & (hv >= hv_med) & (a4h > 0) & dte12)

    # =========================================================================
    # Save + summary
    # =========================================================================
    out = pd.DataFrame(rows)
    out.to_csv(HERE / "04_kernel_combos.csv", index=False)
    print(f"\n  → Saved {len(out)} rows to 04_kernel_combos.csv")

    _hdr("SUMMARY — TOP 10 with ≥2 fires/week (by win_rate)")
    top = out[out["fires_per_week"] >= 2.0].nlargest(10, "win_rate")
    print(top[["filter", "win_rate", "avg_multiple", "fires_per_week",
               "opts_per_signal"]].to_string(index=False))

    _hdr("SUMMARY — TOP 10 with ≥10 fires/week")
    top10 = out[out["fires_per_week"] >= 10.0].nlargest(10, "win_rate")
    print(top10[["filter", "win_rate", "avg_multiple", "fires_per_week",
                 "opts_per_signal"]].to_string(index=False))


if __name__ == "__main__":
    main()
