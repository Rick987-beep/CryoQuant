"""
backtest.py — Vectorized daily backtester for CDX spread signals.

Timing: pos[t] is set using info at close of bar t.
        PnL[t+1] = pos[t] * pct_change(spread)[t+1]
        (trade executes at next close — conservative daily assumption)

No transaction costs by design (focus on signal quality).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class Result:
    name: str
    total_ret_pct: float
    cagr_pct: float
    ann_vol_pct: float
    sharpe: float
    max_dd_pct: float
    n_trades: int
    avg_hold_days: float
    win_rate_pct: float
    pct_in_market: float
    daily_pnl: pd.Series
    equity: pd.Series
    positions: pd.Series

    def summary(self) -> dict:
        return {
            "name":           self.name,
            "total_ret%":     round(self.total_ret_pct, 2),
            "cagr%":          round(self.cagr_pct, 2),
            "ann_vol%":       round(self.ann_vol_pct, 2),
            "sharpe":         round(self.sharpe, 3),
            "max_dd%":        round(self.max_dd_pct, 2),
            "n_trades":       self.n_trades,
            "avg_hold_d":     round(self.avg_hold_days, 1),
            "win_rate%":      round(self.win_rate_pct, 1),
            "in_mkt%":        round(self.pct_in_market, 1),
        }


def run(s: pd.Series, positions: pd.Series, *, name: str = "strategy") -> Result:
    """
    s         : spread levels, DatetimeIndex ascending.
    positions : signal series (+1/0/-1) aligned to same index.
    """
    ret = s.pct_change()
    pos = positions.reindex(s.index).fillna(0)

    # PnL: position on bar t earns return from t → t+1
    daily_pnl = pos.shift(1) * ret
    daily_pnl = daily_pnl.fillna(0)

    # Equity curve
    equity = (1 + daily_pnl).cumprod()

    # ── Trade segmentation ─────────────────────────────────────────────────
    pos_arr   = pos.values
    trade_starts, trade_ends = [], []
    i = 0
    while i < len(pos_arr):
        if pos_arr[i] != 0:
            j = i + 1
            while j < len(pos_arr) and pos_arr[j] == pos_arr[i]:
                j += 1
            trade_starts.append(i)
            trade_ends.append(j - 1)
            i = j
        else:
            i += 1

    n_trades    = len(trade_starts)
    avg_hold    = float(np.mean([e - s_i for s_i, e in zip(trade_starts, trade_ends)])) if n_trades else 0.0

    # Per-trade P&L: from entry+1 bar to exit+1 bar (next-bar execution)
    trade_pnls = []
    for ts, te in zip(trade_starts, trade_ends):
        slc = daily_pnl.iloc[ts + 1 : te + 2]
        trade_pnls.append(float(slc.sum()))

    win_rate = float(np.mean([p > 0 for p in trade_pnls])) * 100 if trade_pnls else 0.0

    # ── Aggregate metrics ──────────────────────────────────────────────────
    n_days     = len(daily_pnl)
    ann        = 252
    n_years    = n_days / ann
    total_ret  = float(equity.iloc[-1] - 1) * 100
    cagr       = (equity.iloc[-1] ** (1 / n_years) - 1) * 100 if n_years > 0 else 0.0
    ann_vol    = float(daily_pnl.std()) * np.sqrt(ann) * 100
    sharpe     = (float(daily_pnl.mean()) * ann) / (float(daily_pnl.std()) * np.sqrt(ann)) \
                 if daily_pnl.std() > 0 else 0.0

    roll_max   = equity.cummax()
    max_dd     = float(((equity - roll_max) / roll_max).min()) * 100

    pct_in_mkt = float((pos.abs() > 0).mean()) * 100

    return Result(
        name          = name,
        total_ret_pct = total_ret,
        cagr_pct      = cagr,
        ann_vol_pct   = ann_vol,
        sharpe        = sharpe,
        max_dd_pct    = max_dd,
        n_trades      = n_trades,
        avg_hold_days = avg_hold,
        win_rate_pct  = win_rate,
        pct_in_market = pct_in_mkt,
        daily_pnl     = daily_pnl,
        equity        = equity,
        positions     = pos,
    )


def grid_search(signal_fn, param_grid: list[dict], s: pd.Series) -> pd.DataFrame:
    """Run all param combos for a signal function. Returns sorted DataFrame."""
    rows = []
    for params in param_grid:
        pos = signal_fn(s, **params)
        r   = run(s, pos, name=str(params))
        row = {"params": params} | r.summary()
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)
    return df
