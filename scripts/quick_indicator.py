#!/usr/bin/env python3
"""Path A example — quick indicator (2 technicals + 1 macro track).

Combines RSI + EMA on BTCUSDT 1h with VIX aligned from daily Yahoo bars.
No FeatureBuilder or model registry required.

Usage:
    python scripts/quick_indicator.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.backtest.reports import render_spot_result
from cryoquant.backtest.robustness import deflated_sharpe
from cryoquant.backtest.spot_pnl import simulate
from cryoquant.data.resolve import load_track
from cryoquant.features.align import align_series
from cryoquant.features.primitives import ema, rsi
from cryoquant.signals.base import BoolSignal

START = datetime.now(timezone.utc) - timedelta(days=180)
END = datetime.now(timezone.utc)
HOLD_H = 24
FEE_BPS = 5.0


def main() -> int:
    print("── Path A: quick indicator ─────────────────────────────────────────────")

    btc = load_track(Symbol("binance.spot", "BTCUSDT"), "1h", START, END)
    vix_daily = load_track(Symbol("yahoo", "^VIX"), "1d", START, END)
    if isinstance(vix_daily, pd.DataFrame):
        vix = align_series(btc.index, vix_daily["close"], method="asof")
    else:
        vix = align_series(btc.index, vix_daily, method="asof")

    bars = btc.copy()
    bars["rsi_14"] = rsi(bars["close"], 14)
    bars["ema_24"] = ema(bars["close"], 24)
    bars["vix"] = vix
    bars["close_vs_ema24"] = (bars["close"] / bars["ema_24"] - 1.0) * 100.0

    signal = BoolSignal(
        signal_id="quick_rsi_vix_v1",
        condition=lambda df: (df["rsi_14"] < 35) & (df["vix"] > 20) & (df["close_vs_ema24"] < 0),
        version="1",
        symbol_str="binance.spot:BTCUSDT",
    )

    result = simulate(signal, bars, hold_h=HOLD_H, fee_bps=FEE_BPS)
    m = result.metrics
    print(f"   bars: {len(bars)}  trades: {m.get('n_trades', 0)}  "
          f"win_rate: {m.get('win_rate', float('nan')):.2%}  "
          f"sharpe: {m.get('sharpe', float('nan')):.2f}")

    n_obs = len(bars)
    n_trials = 1
    dsr = deflated_sharpe(m.get("sharpe", 0.0) or 0.0, n_trials, n_obs, 0.0, 3.0)
    print(f"   deflated_sharpe: {dsr:.3f}")

    out = render_spot_result(result, "reports/quick_indicator.html")
    print(f"   report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
