"""11_binance_signal_audit.py — Replicate backtester momentum signal using Binance klines.

Compares:
  A) Binance-based signal (exact _lookup_mom replica, as used by l_momentum backtester)
  B) Deribit-based signal (as used in our research analysis scripts 07/08)

For every 4h UTC boundary in the backtest window (2026-01-01 → 2026-05-12):
  1. Compute both momentum values
  2. Flag whether each fires the signal (mom_4h >= 1.5%, mom_1h >= 0.5%, aligned)
  3. For Binance-signal windows: check if a qualifying Deribit option exists
     (DTE=4 or 5, abs(delta) in [0.30, 0.40], spread <= 10%)

Outputs:
  binance_signal_audit.csv     — per-boundary detail
  (printed summary)
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Config — matches Combo C (best starred run in the backtester)
# ---------------------------------------------------------------------------
BACKTEST_START = datetime(2026, 1, 1,  0, 0, 0, tzinfo=timezone.utc)
BACKTEST_END   = datetime(2026, 5, 12, 0, 0, 0, tzinfo=timezone.utc)

KLINE_4H_PATH = Path("/Users/ulrikdeichsel/CryoBacktester/indicators/data/BTCUSDT_4h.parquet")
KLINE_1H_PATH = Path("/Users/ulrikdeichsel/CryoBacktester/indicators/data/BTCUSDT_1h.parquet")

MOM_4H_THR = 1.5   # %
MOM_1H_THR = 0.5   # %

DELTA_LO   = 0.30
DELTA_HI   = 0.40
DTE_RANGE  = {4, 5}
SPREAD_MAX = 10.0  # % of mark

# ---------------------------------------------------------------------------
# Load Binance klines — exact same prep as backtester indicators.py
# ---------------------------------------------------------------------------
print("Loading Binance klines ...")
df_4h = pd.read_parquet(KLINE_4H_PATH)
df_1h = pd.read_parquet(KLINE_1H_PATH)

# Ensure tz-aware UTC index
for df in (df_4h, df_1h):
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")

mom_4h_series = df_4h["close"].pct_change(1) * 100.0
mom_1h_series = df_1h["close"].pct_change(1) * 100.0


def _lookup_mom(series: pd.Series, dt: datetime, interval_h: int) -> float | None:
    """Exact replica of backtester _lookup_mom."""
    bar_ts = dt.replace(minute=0, second=0, microsecond=0) - timedelta(hours=interval_h)
    try:
        val = series.loc[bar_ts]
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return float(val)
    except KeyError:
        return None


# ---------------------------------------------------------------------------
# Load candidates_enriched — Deribit-based option data + our momentum values
# ---------------------------------------------------------------------------
print("Loading candidates_enriched.parquet ...")
df_cands = pd.read_parquet(HERE / "candidates_enriched.parquet")
df_cands["entry_dt"] = pd.to_datetime(df_cands["entry_ts_us"], unit="us", utc=True).dt.floor("4h")

# Pre-filter to options that pass DTE / delta / spread (backtester's hard filters)
df_qual = df_cands[
    df_cands["dte_at_entry"].isin(DTE_RANGE) &
    df_cands["delta_at_entry"].abs().between(DELTA_LO, DELTA_HI) &
    (df_cands["spread_pct"] <= SPREAD_MAX)
].copy()

# Index by (boundary, is_call) for fast lookup
qual_index: dict[tuple, bool] = {}   # (boundary_dt, is_call) -> True if any qualifying option exists
for (bdt, is_call), _ in df_qual.groupby(["entry_dt", "is_call"]):
    qual_index[(bdt, is_call)] = True

# Similarly: how many Deribit-signal windows are there in the backtest period?
df_cands_window = df_cands[
    df_cands["dte_at_entry"].isin(DTE_RANGE) &
    df_cands["delta_at_entry"].abs().between(DELTA_LO, DELTA_HI) &
    (df_cands["spread_pct"] <= SPREAD_MAX) &
    (df_cands["entry_dt"] >= BACKTEST_START) &
    (df_cands["entry_dt"] <= BACKTEST_END)
].copy()

# Deribit signal: aligned 4h + 1h
deribit_call_sig = (
    (df_cands_window["spot_4h_chg_pct"] >= MOM_4H_THR) &
    (df_cands_window["spot_1h_chg_pct"] >= MOM_1H_THR) &
    (df_cands_window["is_call"] == True)
)
deribit_put_sig = (
    (df_cands_window["spot_4h_chg_pct"] <= -MOM_4H_THR) &
    (df_cands_window["spot_1h_chg_pct"] <= -MOM_1H_THR) &
    (df_cands_window["is_call"] == False)
)
df_deribit_sig = df_cands_window[deribit_call_sig | deribit_put_sig]
deribit_sig_windows = df_deribit_sig["entry_dt"].nunique()

# ---------------------------------------------------------------------------
# Walk every 4h boundary in the backtest window
# ---------------------------------------------------------------------------
print(f"Walking 4h boundaries from {BACKTEST_START.date()} to {BACKTEST_END.date()} ...")

boundaries = []
dt = BACKTEST_START
while dt <= BACKTEST_END:
    boundaries.append(dt)
    dt += timedelta(hours=4)

rows = []
for dt in boundaries:
    m4h = _lookup_mom(mom_4h_series, dt, 4)
    m1h = _lookup_mom(mom_1h_series, dt, 1)

    if m4h is None or m1h is None:
        rows.append({"dt": dt, "binance_signal": "no_data", "direction": None,
                     "m4h_binance": None, "m1h_binance": None,
                     "has_qualifying_option": False, "option_data_available": False})
        continue

    # Determine Binance signal direction
    if m4h >= MOM_4H_THR and m1h >= MOM_1H_THR:
        direction, signal = "call", True
    elif m4h <= -MOM_4H_THR and m1h <= -MOM_1H_THR:
        direction, signal = "put", True
    else:
        direction, signal = None, False

    # Check for qualifying Deribit option at this boundary
    has_opt = False
    opt_data_available = False
    if signal and dt <= BACKTEST_END:
        is_call = direction == "call"
        opt_data_available = dt.date().isoformat() <= "2026-04-28"  # our data coverage
        if opt_data_available:
            has_opt = qual_index.get((dt, is_call), False)

    rows.append({
        "dt":                      dt,
        "binance_signal":          direction if signal else "none",
        "direction":               direction,
        "m4h_binance":             round(m4h, 3),
        "m1h_binance":             round(m1h, 3),
        "has_qualifying_option":   has_opt,
        "opt_data_available":      opt_data_available,
    })

df_audit = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total       = len(df_audit)
no_data     = (df_audit["binance_signal"] == "no_data").sum()
signal_all  = df_audit["binance_signal"].isin(["call", "put"])
n_signal    = signal_all.sum()
n_call_sig  = (df_audit["binance_signal"] == "call").sum()
n_put_sig   = (df_audit["binance_signal"] == "put").sum()

# Only evaluate option availability where we have Deribit data coverage
covered     = signal_all & df_audit["opt_data_available"]
n_covered   = covered.sum()
n_with_opt  = df_audit[covered]["has_qualifying_option"].sum()

print()
print("=" * 55)
print("BINANCE SIGNAL AUDIT  (Combo C thresholds: 4h≥1.5%, 1h≥0.5%)")
print("=" * 55)
print(f"Backtest window:               {BACKTEST_START.date()} → {BACKTEST_END.date()}")
print(f"Total 4h boundaries:           {total}")
print(f"  No kline data:               {no_data}")
print()
print(f"Binance signal fires:          {n_signal}  ({n_call_sig} call / {n_put_sig} put)")
print(f"  ... within Deribit coverage: {n_covered}")
print(f"  ... + qualifying option:     {n_with_opt}  ← expected backtester entries (covered window)")
print()
print(f"Deribit-signal windows (our analysis, same thresholds): {deribit_sig_windows}")
print(f"  [Deribit uses Deribit spot 1-min; backtester uses Binance klines]")
print()
print(f"Actual backtester trades (Combo C):  27")
print()

# Show signal windows with no qualifying option
no_opt_windows = df_audit[covered & ~df_audit["has_qualifying_option"]]
if len(no_opt_windows):
    print(f"Signal windows blocked by no qualifying option: {len(no_opt_windows)}")
    for _, row in no_opt_windows.iterrows():
        print(f"  {row['dt'].strftime('%Y-%m-%d %H:%M')} UTC  {row['binance_signal']:4s}  "
              f"m4h={row['m4h_binance']:+.2f}%  m1h={row['m1h_binance']:+.2f}%")

# Binance vs Deribit divergence: find boundaries where one fires but not the other
print()
print("--- Divergence check (Binance vs Deribit signal) ---")

# Merge Deribit signals onto the boundaries
deribit_sig_set = set(df_deribit_sig["entry_dt"].unique())
df_audit["deribit_signal"] = df_audit["dt"].isin(deribit_sig_set)

binance_not_deribit = signal_all & ~df_audit["deribit_signal"] & df_audit["opt_data_available"]
deribit_not_binance = ~signal_all & df_audit["deribit_signal"]

print(f"Binance signal fires but Deribit does NOT: {binance_not_deribit.sum()}")
print(f"Deribit signal fires but Binance does NOT: {deribit_not_binance.sum()}")
print(f"Both fire:  {(signal_all & df_audit['deribit_signal']).sum()}")
print(f"Neither:    {(~signal_all & ~df_audit['deribit_signal'] & df_audit['opt_data_available']).sum()}")

# Show the divergent windows
if deribit_not_binance.sum() > 0:
    print(f"\nWindows where Deribit fires but Binance does NOT (explains missing backtester entries):")
    div_rows = df_audit[deribit_not_binance].copy()
    # Attach Deribit momentum for comparison
    deribit_mom = df_deribit_sig[["entry_dt", "spot_4h_chg_pct", "spot_1h_chg_pct", "is_call"]].drop_duplicates("entry_dt")
    deribit_mom = deribit_mom.set_index("entry_dt")
    for _, row in div_rows.iterrows():
        dmom = deribit_mom.loc[row["dt"]] if row["dt"] in deribit_mom.index else None
        d4h = f"{dmom['spot_4h_chg_pct']:+.2f}%" if dmom is not None else "?"
        d1h = f"{dmom['spot_1h_chg_pct']:+.2f}%" if dmom is not None else "?"
        b4h = f"{row['m4h_binance']:+.2f}%" if row['m4h_binance'] is not None else "no_data"
        b1h = f"{row['m1h_binance']:+.2f}%" if row['m1h_binance'] is not None else "no_data"
        print(f"  {row['dt'].strftime('%Y-%m-%d %H:%M')}  "
              f"Deribit: 4h={d4h} 1h={d1h}  |  Binance: 4h={b4h} 1h={b1h}")

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
out_csv = HERE / "binance_signal_audit.csv"
df_audit.to_csv(out_csv, index=False)
print(f"\nSaved: {out_csv}")
