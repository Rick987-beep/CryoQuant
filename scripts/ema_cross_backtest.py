"""EMA 7/21 crossover backtest — BTCUSDT daily.

Fetches daily bars from Binance (2020-01-01 → today), builds
DailyEmaCrossFeatures, simulates long and short legs independently,
prints metrics, and writes HTML reports.

Usage:
    python scripts/ema_cross_backtest.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from cryocore.instruments import Symbol
from cryoquant.data.loader import load
from cryoquant.features.builders import DatasetRef, DailyEmaCrossFeatures
from cryoquant.signals.ema_cross import make_ema_cross_long, make_ema_cross_short
from cryoquant.backtest.spot_pnl import simulate
from cryoquant.backtest.robustness import deflated_sharpe
from cryoquant.backtest.reports import render_spot_result

REPORTS = Path("reports")
REPORTS.mkdir(exist_ok=True)

HOLD_DAYS  = 5     # hold for 5 daily bars after a cross
FEE_BPS    = 5.0   # 5 bps round-trip
START      = datetime(2020, 1, 1, tzinfo=timezone.utc)
END        = datetime.now(timezone.utc)

# ── 1. Load 1d bars ─────────────────────────────────────────────────────────
print("── 1. Loading daily bars ───────────────────────────────────────────────")
sym    = Symbol("binance.spot", "BTCUSDT")
df_raw = load(sym, "1d", START, END)
print(f"   {len(df_raw)} bars  ({df_raw.index[0].date()} → {df_raw.index[-1].date()})")

# ── 2. Build features ────────────────────────────────────────────────────────
print("\n── 2. Building EMA cross features ──────────────────────────────────────")
ref  = DatasetRef(sym, "1d")
X    = DailyEmaCrossFeatures().build({ref: df_raw})
# Join only new columns so we don't duplicate OHLCV
new_cols = [c for c in X.columns if c not in df_raw.columns]
bars = df_raw.join(X[new_cols])
n_up   = int(X["cross_up"].fillna(False).sum())
n_down = int(X["cross_down"].fillna(False).sum())
print(f"   up-crosses: {n_up}   down-crosses: {n_down}")

# ── 3. Simulate long leg ─────────────────────────────────────────────────────
print("\n── 3. Long leg (EMA 7 crosses above EMA 21, hold 5 days) ───────────────")
long_sig    = make_ema_cross_long()
result_long = simulate(long_sig, bars, hold_h=HOLD_DAYS, fee_bps=FEE_BPS)
for k, v in result_long.metrics.items():
    print(f"   {k:20s}: {v:.4f}" if isinstance(v, float) else f"   {k:20s}: {v}")

# ── 4. Simulate short leg ────────────────────────────────────────────────────
print("\n── 4. Short leg (EMA 7 crosses below EMA 21, hold 5 days) ──────────────")
short_sig    = make_ema_cross_short()
result_short = simulate(short_sig, bars, hold_h=HOLD_DAYS, fee_bps=FEE_BPS)
for k, v in result_short.metrics.items():
    print(f"   {k:20s}: {v:.4f}" if isinstance(v, float) else f"   {k:20s}: {v}")

# ── 5. DSR ───────────────────────────────────────────────────────────────────
print("\n── 5. Deflated Sharpe Ratio ─────────────────────────────────────────────")
dsr_long = deflated_sharpe(
    sharpe=result_long.metrics["sharpe"],
    n_trials=1,
    n_obs=max(result_long.metrics["n_trades"], 1),
)
dsr_short = deflated_sharpe(
    sharpe=result_short.metrics["sharpe"],
    n_trials=2,   # tested 2 variants (long + short)
    n_obs=max(result_short.metrics["n_trades"], 1),
)
print(f"   DSR long:  {dsr_long:.3f}  (>0.95 = credible)")
print(f"   DSR short: {dsr_short:.3f}  (>0.95 = credible)")

# ── 6. HTML reports ──────────────────────────────────────────────────────────
print("\n── 6. Writing reports ───────────────────────────────────────────────────")
long_report  = REPORTS / "ema_cross_long_7_21_1d.html"
short_report = REPORTS / "ema_cross_short_7_21_1d.html"
render_spot_result(result_long,  str(long_report))
render_spot_result(result_short, str(short_report))
print(f"   {long_report}")
print(f"   {short_report}")
print("\nDone.")
