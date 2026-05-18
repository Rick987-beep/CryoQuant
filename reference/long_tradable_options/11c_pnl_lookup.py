"""11c_pnl_lookup.py — Raw straddle P&L lookup (no exits).

For each (signal_fire × DTE × delta_target) combination from 11b, load the
actual 5-min forward bid data and track the straddle value from T+5min to
T+24h (or 1h before expiry, whichever comes first).

No exits are applied here — this is pure observation of what the market gave.
The distributions produced drive the exit-rule design in 11d.

Sections
--------
  A  Peak multiple distribution  (% fires reaching 1.5×, 2.0×, 2.5×, 3.0×)
  B  Time-to-peak distribution   (when does value peak after entry?)
  C  Average P&L curve           (mean multiple at T+4h, 8h, 12h, 18h, 24h)
  D  Hold-to-end distribution    (median/mean final multiple at T+24h)
  E  Recommended exit parameters (data-derived TP, time-stop, stop-loss)

Outputs
-------
  11c_pnl_summary.csv    — one row per (fire × DTE × delta_target)
  11c_pnl_curves.parquet — full 5-min bid series (for 11d exit simulation)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "pineforge"))

_OPT_UTILS_DIR = Path(__file__).resolve().parent.parent / "intraday_options"
sys.path.insert(0, str(_OPT_UTILS_DIR))
import option_utils as ou  # noqa: E402

HERE = Path(__file__).resolve().parent

# ── Config ────────────────────────────────────────────────────────────────────
FORWARD_HOURS    = 24
SAVE_CURVES      = True   # write 11c_pnl_curves.parquet (needed by 11d)
HORIZON_HOURS    = [4, 8, 12, 18, 24]
FOCUS_DTE        = [1, 2, 3]        # DTE to highlight in console tables
FOCUS_DELTA      = [0.15, 0.20, 0.25, 0.30, 0.35]   # delta targets to highlight
TP_THRESHOLDS    = [1.3, 1.5, 2.0, 2.5, 3.0]


# ── Data loading (replicated from 01_v2_scan_1h.py) ──────────────────────────

@lru_cache(maxsize=60)
def _load_merged(date_str: str) -> pd.DataFrame | None:
    try:
        df_opt  = ou.load_day(date_str)
        df_spot = ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None
    df_opt  = df_opt.sort_values("timestamp").reset_index(drop=True)
    df_spot = (df_spot.sort_values("timestamp")[["timestamp", "close"]]
               .rename(columns={"close": "spot_usd"}))
    merged = pd.merge_asof(df_opt, df_spot, on="timestamp", direction="backward")
    spot   = merged["spot_usd"].values
    merged["bid_usd"] = merged["bid_price"].values * spot
    return merged


@lru_cache(maxsize=60)
def _contract_index(date_str: str) -> dict:
    merged = _load_merged(date_str)
    if merged is None:
        return {}
    idx: dict = {}
    valid = merged[merged["bid_price"] > 0]
    for (expiry, strike, is_call), grp in valid.groupby(
        ["expiry", "strike", "is_call"], sort=False
    ):
        arr = grp[["timestamp", "bid_usd"]].sort_values("timestamp").values
        idx[(expiry, float(strike), bool(is_call))] = arr
    return idx


def _option_forward_bids(
    expiry: str, strike: float, is_call: bool,
    from_ts_us: int, to_ts_us: int,
) -> np.ndarray | None:
    """Return (timestamp, bid_usd) array for a contract over a time window."""
    from datetime import date as _date
    from_d = datetime.fromtimestamp(from_ts_us / 1e6, tz=timezone.utc).date()
    to_d   = datetime.fromtimestamp(to_ts_us   / 1e6, tz=timezone.utc).date()
    key    = (expiry, float(strike), bool(is_call))
    chunks = []
    cur = from_d
    while cur <= to_d:
        arr = _contract_index(cur.isoformat()).get(key)
        if arr is not None and len(arr):
            mask = (arr[:, 0] >= from_ts_us) & (arr[:, 0] <= to_ts_us)
            chunk = arr[mask]
            if len(chunk):
                chunks.append(chunk)
        cur += timedelta(days=1)
    if not chunks:
        return None
    return np.concatenate(chunks, axis=0)


def _expiry_cutoff_us(expiry_code: str) -> int:
    """1h before expiry (08:00 UTC → 07:00 UTC cutoff)."""
    expiry_dt = ou.parse_expiry(expiry_code)
    cutoff    = expiry_dt - timedelta(hours=1)
    return int(cutoff.timestamp() * 1_000_000)


# ── Core tracking function ────────────────────────────────────────────────────

def _track_straddle(
    expiry_code: str,
    call_strike: float,
    put_strike: float,
    entry_ts_us: int,
    entry_ask_usd: float,
) -> tuple[dict, np.ndarray] | None:
    """Track straddle bid from T+5min to T+24h (or expiry cutoff).

    Returns (summary_dict, curve_array) where curve_array is shaped (N, 2):
      col 0: hours_since_entry  (float)
      col 1: straddle_bid_usd
    Returns None if no forward data available.
    """
    cutoff_us = _expiry_cutoff_us(expiry_code)
    end_us    = min(entry_ts_us + int(FORWARD_HOURS * 3600 * 1_000_000), cutoff_us)
    start_us  = entry_ts_us + 5 * 60 * 1_000_000   # first bar after entry

    if start_us >= end_us:
        return None

    call_data = _option_forward_bids(expiry_code, call_strike, True,  start_us, end_us)
    put_data  = _option_forward_bids(expiry_code, put_strike,  False, start_us, end_us)

    if call_data is None or put_data is None or len(call_data) == 0 or len(put_data) == 0:
        return None

    # Align on common timestamps
    call_ts = call_data[:, 0].astype(np.int64)
    put_ts  = put_data[:,  0].astype(np.int64)
    common  = np.intersect1d(call_ts, put_ts)
    if len(common) == 0:
        return None

    call_bids = call_data[np.isin(call_ts, common), 1]
    put_bids  = put_data[ np.isin(put_ts,  common), 1]
    straddle  = call_bids + put_bids
    hours     = (common - entry_ts_us).astype(float) / 1_000_000 / 3600

    # Peak
    peak_i          = int(np.argmax(straddle))
    peak_bid        = float(straddle[peak_i])
    time_to_peak_h  = float(hours[peak_i])
    peak_multiple   = peak_bid / entry_ask_usd

    # Value at fixed horizons
    def _at(h: float) -> float | None:
        diffs = np.abs(hours - h)
        best  = int(np.argmin(diffs))
        if diffs[best] > 10 / 60:   # no bar within 10 min
            return None
        return float(straddle[best])

    horizon_values: dict[str, float | None] = {}
    for h in HORIZON_HOURS:
        v = _at(h)
        horizon_values[f"value_at_{h}h"]    = round(v, 2) if v is not None else None
        horizon_values[f"multiple_at_{h}h"] = round(v / entry_ask_usd, 4) if v is not None else None

    final_bid      = float(straddle[-1])
    final_multiple = final_bid / entry_ask_usd

    summary = {
        "peak_bid_usd":    round(peak_bid, 2),
        "peak_multiple":   round(peak_multiple, 4),
        "time_to_peak_h":  round(time_to_peak_h, 2),
        "final_bid_usd":   round(final_bid, 2),
        "final_multiple":  round(final_multiple, 4),
        "n_bars":          len(common),
        **horizon_values,
    }
    curve = np.column_stack([hours, straddle])
    return summary, curve


# ── Print helpers ─────────────────────────────────────────────────────────────

def _header(title: str) -> None:
    print(); print("=" * 72); print(f"  {title}"); print("=" * 72)

def _subheader(title: str) -> None:
    print(f"\n--- {title} ---")


def _pct_reaching(vals: pd.Series, threshold: float) -> float:
    return float((vals >= threshold).mean()) if len(vals) > 0 else float("nan")


def _print_reach_table(df: pd.DataFrame, signal: str, label: str) -> None:
    """Print % of fires reaching each TP threshold, by (DTE × delta_target)."""
    sub = df[(df["signal"] == signal) &
             (df["dte"].isin(FOCUS_DTE)) &
             (df["delta_target"].isin(FOCUS_DELTA))]
    if sub.empty:
        return
    tp_hdr = "  ".join(f"{t:.1f}×" for t in TP_THRESHOLDS)
    print(f"\n  {signal}  (N={len(df[df['signal']==signal]):,} available fires × combos)")
    print(f"  {'DTE':>3}  {'δ':>5}  {'N':>5}  {tp_hdr}  {'med pk':>8}  {'med T2pk':>9}")
    print("  " + "-" * 75)
    for dte in FOCUS_DTE:
        for dt in FOCUS_DELTA:
            g = sub[(sub["dte"] == dte) & (sub["delta_target"] == dt)]
            if len(g) < 3:
                continue
            reach = "  ".join(f"{_pct_reaching(g['peak_multiple'], t):>5.0%}"
                              for t in TP_THRESHOLDS)
            med_pk  = g["peak_multiple"].median()
            med_t2p = g["time_to_peak_h"].median()
            print(f"  {dte:>3}  {dt:>5.2f}  {len(g):>5}  {reach}  "
                  f"{med_pk:>7.2f}×  {med_t2p:>8.1f}h")


def _print_curve_table(df: pd.DataFrame, signal: str) -> None:
    """Print mean multiple at each horizon, for focus (DTE, delta) pairs."""
    sub = df[(df["signal"] == signal) &
             (df["dte"].isin(FOCUS_DTE)) &
             (df["delta_target"].isin(FOCUS_DELTA))]
    if sub.empty:
        return
    h_hdr = "  ".join(f"T+{h:>2}h" for h in HORIZON_HOURS)
    print(f"\n  {signal}")
    print(f"  {'DTE':>3}  {'δ':>5}  {'N':>5}  {h_hdr}  {'final':>7}")
    print("  " + "-" * 72)
    for dte in FOCUS_DTE:
        for dt in FOCUS_DELTA:
            g = sub[(sub["dte"] == dte) & (sub["delta_target"] == dt)]
            if len(g) < 3:
                continue
            vals = "  ".join(
                f"{g[f'multiple_at_{h}h'].median():>5.2f}×"
                if g[f'multiple_at_{h}h'].notna().sum() > 2 else "   — "
                for h in HORIZON_HOURS
            )
            fin = g["final_multiple"].median()
            print(f"  {dte:>3}  {dt:>5.2f}  {len(g):>5}  {vals}  {fin:>6.2f}×")


# =============================================================================
# Main
# =============================================================================

def main() -> None:

    # ── Load 11b universe ────────────────────────────────────────────────────
    print("Loading 11b_option_universe.csv …")
    universe = pd.read_csv(HERE / "11b_option_universe.csv")
    available = universe[universe["available"] == True].copy()
    print(f"  {len(available):,} available (signal_fire × DTE × delta_target) rows")

    # ── Forward tracking ─────────────────────────────────────────────────────
    print(f"Tracking forward P&L for each row …")

    summary_rows: list[dict] = []
    curve_rows:   list[dict] = []
    skipped = 0

    for i, row in enumerate(available.itertuples(index=False)):
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(available)}] …")

        # Reconstruct expiry_code from date + dte
        fire_date    = datetime.strptime(str(row.date), "%Y-%m-%d").date()
        expiry_date  = fire_date + timedelta(days=int(row.dte))
        expiry_code  = ou.format_expiry(
            datetime(expiry_date.year, expiry_date.month, expiry_date.day,
                     8, 0, tzinfo=timezone.utc)
        )
        fire_ts_us   = int(datetime.fromisoformat(
            str(row.fire_ts).replace("Z", "+00:00")
        ).timestamp() * 1_000_000)

        result = _track_straddle(
            expiry_code      = expiry_code,
            call_strike      = float(row.call_strike),
            put_strike       = float(row.put_strike),
            entry_ts_us      = fire_ts_us,
            entry_ask_usd    = float(row.straddle_ask_usd),
        )

        if result is None:
            skipped += 1
            continue

        stats, curve = result

        summary_rows.append({
            "signal":       row.signal,
            "fire_ts":      row.fire_ts,
            "date":         row.date,
            "hour_utc":     row.hour_utc,
            "rv_rank":      row.rv_rank,
            "dte":          row.dte,
            "delta_target": row.delta_target,
            "entry_ask_usd": row.straddle_ask_usd,
            "call_strike":  row.call_strike,
            "put_strike":   row.put_strike,
            **stats,
        })

        if SAVE_CURVES:
            for bar_h, bid in curve:
                curve_rows.append({
                    "signal":       row.signal,
                    "fire_ts":      row.fire_ts,
                    "dte":          row.dte,
                    "delta_target": row.delta_target,
                    "bar_h":        round(float(bar_h), 3),
                    "straddle_bid": round(float(bid), 2),
                    "entry_ask":    row.straddle_ask_usd,
                    "multiple":     round(float(bid) / float(row.straddle_ask_usd), 4),
                })

    df = pd.DataFrame(summary_rows)
    print(f"\n  Tracked: {len(df):,}  Skipped (no forward data): {skipped}")

    # =========================================================================
    # Section A — Peak multiple distribution
    # =========================================================================
    _header("A — PEAK MULTIPLE DISTRIBUTION  (no exits — what the market gave)")
    print("  (% of fires where peak straddle bid ≥ threshold, before any exit)")
    for sig in ["pullback", "vol_burst"]:
        _print_reach_table(df, sig, label=sig)

    # =========================================================================
    # Section B — Time-to-peak distribution
    # =========================================================================
    _header("B — TIME-TO-PEAK  (hours from entry to peak straddle bid)")
    for sig in ["pullback", "vol_burst"]:
        sub = df[df["signal"] == sig]
        if sub.empty:
            continue
        # Focus: DTE=2, delta=0.20 and 0.30 as representative
        for dte in FOCUS_DTE:
            for dt in [0.20, 0.30]:
                g = sub[(sub["dte"] == dte) & (sub["delta_target"] == dt)]
                if len(g) < 5:
                    continue
                pcts = np.percentile(g["time_to_peak_h"].dropna(), [25, 50, 75])
                frac_early = (g["time_to_peak_h"] <= 8).mean()
                frac_mid   = ((g["time_to_peak_h"] > 8) & (g["time_to_peak_h"] <= 16)).mean()
                print(f"  {sig:<12}  DTE {dte}  δ{dt:.2f}  "
                      f"p25={pcts[0]:.1f}h  p50={pcts[1]:.1f}h  p75={pcts[2]:.1f}h  "
                      f"≤8h={frac_early:.0%}  8-16h={frac_mid:.0%}")

    # =========================================================================
    # Section C — Average P&L curve (mean multiple at each horizon)
    # =========================================================================
    _header("C — AVERAGE P&L CURVE  (median multiple at each time horizon)")
    print("  (if you held to fixed time-stop with no TP — what would you have?)\n")
    for sig in ["pullback", "vol_burst"]:
        _print_curve_table(df, sig)

    # =========================================================================
    # Section D — Final multiple distribution (hold to T+24h)
    # =========================================================================
    _header("D — HOLD-TO-END DISTRIBUTION  (final multiple at T+24h or expiry)")
    for sig in ["pullback", "vol_burst"]:
        sub = df[(df["signal"] == sig) &
                 (df["dte"].isin(FOCUS_DTE)) &
                 (df["delta_target"].isin(FOCUS_DELTA))]
        if sub.empty:
            continue
        print(f"\n  {sig}")
        print(f"  {'DTE':>3}  {'δ':>5}  {'N':>5}  {'p10':>7}  {'p25':>7}  "
              f"{'p50':>7}  {'p75':>7}  {'p90':>7}  {'mean':>7}  {'% > 1×':>8}")
        print("  " + "-" * 74)
        for dte in FOCUS_DTE:
            for dt in FOCUS_DELTA:
                g = sub[(sub["dte"] == dte) & (sub["delta_target"] == dt)]["final_multiple"].dropna()
                if len(g) < 3:
                    continue
                pcts = np.percentile(g, [10, 25, 50, 75, 90])
                print(f"  {dte:>3}  {dt:>5.2f}  {len(g):>5}  "
                      f"{pcts[0]:>6.2f}×  {pcts[1]:>6.2f}×  {pcts[2]:>6.2f}×  "
                      f"{pcts[3]:>6.2f}×  {pcts[4]:>6.2f}×  {g.mean():>6.2f}×  "
                      f"{(g > 1.0).mean():>7.0%}")

    # =========================================================================
    # Section E — Recommended exit parameters
    # =========================================================================
    _header("E — DATA-DERIVED EXIT PARAMETER CANDIDATES")
    print("  Based on peak distribution and time-to-peak across signal tiers\n")

    for sig in ["pullback", "vol_burst"]:
        # Use DTE=2, delta=0.20 as representative
        g = df[(df["signal"] == sig) & (df["dte"] == 2) & (df["delta_target"] == 0.20)]
        if len(g) < 5:
            continue
        pm = g["peak_multiple"].dropna()
        tp_h = g["time_to_peak_h"].dropna()
        fm = g["final_multiple"].dropna()
        print(f"  {sig}  (DTE=2, δ=0.20, N={len(g)}):")
        for t in TP_THRESHOLDS:
            print(f"    TP {t:.1f}×  →  {_pct_reaching(pm, t):>4.0%} of fires reach it")
        print(f"    Median time to peak: {tp_h.median():.1f}h  "
              f"(p25={np.percentile(tp_h,25):.1f}h, p75={np.percentile(tp_h,75):.1f}h)")
        print(f"    Final multiple (hold to end): "
              f"p10={np.percentile(fm,10):.2f}×  p50={np.percentile(fm,50):.2f}×  "
              f"p90={np.percentile(fm,90):.2f}×")
        print(f"    Stop-loss candidates: "
              f"value at p10={np.percentile(fm,10):.2f}× → SL at that level limits worst losses")
        print()

    # =========================================================================
    # Save outputs
    # =========================================================================
    df.to_csv(HERE / "11c_pnl_summary.csv", index=False)
    print(f"  → Saved {len(df):,} rows to 11c_pnl_summary.csv")

    if SAVE_CURVES and curve_rows:
        df_curves = pd.DataFrame(curve_rows)
        df_curves.to_parquet(HERE / "11c_pnl_curves.parquet", index=False)
        print(f"  → Saved {len(df_curves):,} rows to 11c_pnl_curves.parquet")

    print("\nDone.")


if __name__ == "__main__":
    main()
