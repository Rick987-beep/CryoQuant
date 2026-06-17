"""Vectorised spot P&L simulator.

Simulates a simple next-open, fixed-hold strategy driven by a BoolSignal or
ProbSignal. Non-overlapping: a new trade is only entered after the previous
one has closed.

Public interface::

    simulate(signal, bars, thr=None, hold_h=24, exec="next_open", fee_bps=1.0)
    -> SpotResult
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class SpotResult(BaseModel):
    """Outcome of a spot_pnl simulation.

    Attributes:
        equity:   Equity curve indexed by bar timestamp (starts at 1.0;
                  jumps at trade close).
        trades:   DataFrame with one row per trade.  Columns:
                  entry_ts, exit_ts, entry_price, exit_price, pnl_pct, fee_pct
        metrics:  Scalar summary statistics.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

def simulate(
    signal: object,
    bars: pd.DataFrame,
    *,
    thr: float | None = None,
    hold_h: int = 24,
    exec: Literal["next_open"] = "next_open",  # noqa: A002
    fee_bps: float = 1.0,
) -> SpotResult:
    """Simulate a fixed-hold spot strategy.

    Parameters
    ----------
    signal:   A BoolSignal or ProbSignal (duck-typed).
    bars:     OHLCV DataFrame indexed by tz-aware DatetimeIndex (UTC).
              Must contain ``open``, ``close`` columns.
    thr:      Probability threshold for ProbSignal (uses signal.default_threshold
              if None).
    hold_h:   Number of bars to hold after entry (bars are assumed to be 1h
              unless the index says otherwise).
    exec:     Execution convention. Only ``"next_open"`` is implemented.
    fee_bps:  Round-trip fee in basis points (applied once at entry + once at
              exit).

    Returns
    -------
    SpotResult with equity curve, trades DataFrame, and metrics dict.
    """
    if exec != "next_open":
        raise NotImplementedError("Only exec='next_open' is implemented")

    n = len(bars)
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)

    # ── Fire mask ────────────────────────────────────────────────────────────
    from cryoquant.signals.base import ProbSignal

    # Duck-type: ProbSignal or anything with default_threshold → treat as probability
    is_prob = isinstance(signal, ProbSignal) or hasattr(signal, "default_threshold")

    if is_prob:
        _thr = thr if thr is not None else signal.default_threshold
        probs = signal.as_feature(bars).to_numpy(dtype=float)
        fires_arr = (probs >= _thr).astype(bool)
    else:
        # BoolSignal or duck-typed object with as_feature
        fires_arr = signal.as_feature(bars).fillna(False).to_numpy(dtype=bool)

    # Guard: cannot enter a trade that would exit beyond the data
    max_entry = n - hold_h - 1  # last bar that can fire safely

    # ── Identify non-overlapping trades ──────────────────────────────────────
    entry_idx_list: list[int] = []
    exit_idx_list: list[int] = []
    last_exit = -1

    for i in range(max_entry + 1):
        if not fires_arr[i]:
            continue
        entry = i + 1
        if entry <= last_exit:
            continue  # previous trade still open
        exit_ = entry + hold_h
        if exit_ >= n:
            break
        entry_idx_list.append(entry)
        exit_idx_list.append(exit_)
        last_exit = exit_

    if not entry_idx_list:
        from cryoquant.backtest.metrics import empty_metrics
        from cryoquant.backtest.trades import _empty_enriched
        equity = pd.Series(np.ones(n), index=bars.index, name="equity")
        return SpotResult(
            equity=equity,
            trades=_empty_enriched(),
            metrics=empty_metrics(),
        )

    entry_idx = np.array(entry_idx_list)
    exit_idx = np.array(exit_idx_list)

    # ── Vectorised P&L ───────────────────────────────────────────────────────
    fee_one_way = fee_bps / 10_000.0
    fee_round_trip = fee_one_way * 2.0

    entry_prices = opens[entry_idx]
    exit_prices = opens[exit_idx]
    pnl_arr = (exit_prices - entry_prices) / entry_prices - fee_round_trip

    # ── Build trades DataFrame ────────────────────────────────────────────────
    idx = bars.index
    trades_df = pd.DataFrame(
        {
            "entry_ts":    idx[entry_idx].to_pydatetime(),
            "exit_ts":     idx[exit_idx].to_pydatetime(),
            "entry_price": entry_prices,
            "exit_price":  exit_prices,
            "pnl_pct":     pnl_arr,
            "fee_pct":     np.full(len(entry_idx), fee_round_trip),
        }
    )

    # ── Equity curve ─────────────────────────────────────────────────────────
    equity_arr = np.ones(n, dtype=float)
    # Compound returns: each trade updates equity at its exit bar
    current_equity = 1.0
    for k in range(len(exit_idx)):
        current_equity *= 1.0 + pnl_arr[k]
        # Fill from this exit bar forward until next exit (or end)
        start = exit_idx[k]
        end = exit_idx[k + 1] if k + 1 < len(exit_idx) else n
        equity_arr[start:end] = current_equity
    equity = pd.Series(equity_arr, index=bars.index, name="equity")

    # ── Aggregate metrics ────────────────────────────────────────────────────
    from cryoquant.backtest.metrics import compute_metrics, empty_metrics
    from cryoquant.backtest.trades import enrich_trades

    enriched = enrich_trades(trades_df, equity)
    metrics = compute_metrics(enriched, equity)

    return SpotResult(equity=equity, trades=enriched, metrics=metrics)


# ---------------------------------------------------------------------------
# Metric helpers (kept for backward compatibility; delegate to framework)
# ---------------------------------------------------------------------------

def _empty_metrics() -> dict:
    from cryoquant.backtest.metrics import empty_metrics
    return empty_metrics()
