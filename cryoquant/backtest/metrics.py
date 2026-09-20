"""Shared backtest metrics for CryoQuant simulators.

Single source of truth for all scalar performance metrics used by
``spot_pnl.simulate``, ``turtle_simulate``, and any future simulator.

Public interface::

    compute_metrics(trades, equity, *, bars_per_year=252) -> dict
    empty_metrics() -> dict

Sharpe conventions
------------------
``sharpe``        — Primary Sharpe reported in leaderboards.  When equity has a
                    DatetimeIndex (i.e. the simulator provides calendar-daily NAV)
                    this equals ``sharpe_trade`` (mean/std of per-trade P&L ×
                    √(trades/year)).  This is what most systematic traders report.
``sharpe_trade``  — Explicit alias kept for clarity and backward compatibility.
``sharpe_equity`` — Daily NAV Sharpe: mean/std of daily log-returns × √252.
                    Useful for comparing against fund benchmarks.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def empty_metrics() -> dict:
    """Return a metrics dict with all keys set to NaN / zero."""
    return {
        # Backward-compatible keys (used by existing tests and sweep CSV)
        "n_trades":      0,
        "total_return":  0.0,
        "win_rate":      float("nan"),
        "sharpe":        float("nan"),
        "sharpe_equity": float("nan"),
        "max_drawdown":  0.0,
        "expectancy":    float("nan"),
        # New keys
        "sortino_equity": float("nan"),
        "calmar":         float("nan"),
        "profit_factor":  float("nan"),
        "omega":          float("nan"),
        "avg_hold_days":  float("nan"),
        "pct_long":       float("nan"),
        "pct_short":      float("nan"),
        # Calendar-based metrics
        "cagr":          float("nan"),
        "sharpe_trade":  float("nan"),
    }


def compute_metrics(
    trades: pd.DataFrame,
    equity: pd.Series,
    *,
    bars_per_year: int = 252,
) -> dict:
    """Compute scalar performance metrics from a trade log and equity curve.

    Parameters
    ----------
    trades:
        Trade DataFrame. Must contain ``pnl_pct``.  Optionally contains
        ``side`` (for long/short mix) and ``duration_days`` (for
        ``avg_hold_days``).
    equity:
        Equity curve indexed by bar timestamp (starts at 1.0).
    bars_per_year:
        Used for annualisation of equity-based Sharpe/Sortino.  Use 252
        for daily bars, 252*6.5 for hourly, or pass the actual value for
        the bar frequency.

    Returns
    -------
    dict with all keys from ``empty_metrics()``.
    """
    if trades is None or trades.empty:
        return empty_metrics()

    pnl_arr = trades["pnl_pct"].to_numpy(dtype=float)
    n = len(pnl_arr)
    if n == 0:
        return empty_metrics()

    m = empty_metrics()
    m["n_trades"] = n

    # --- Basic trade-level stats ---
    # Prefer dollar PnL for win/loss aggregates when present (account mode).
    if "pnl_abs" in trades.columns and trades["pnl_abs"].notna().any():
        dollar = trades["pnl_abs"].to_numpy(dtype=float)
        m["win_rate"] = float(np.mean(dollar > 0))
        m["expectancy"] = float(np.mean(dollar))
        wins_d = dollar[dollar > 0]
        losses_d = dollar[dollar < 0]
        gross_win = float(wins_d.sum()) if len(wins_d) else 0.0
        gross_loss = float(-losses_d.sum()) if len(losses_d) else 0.0
    else:
        m["win_rate"] = float(np.mean(pnl_arr > 0))
        m["expectancy"] = float(np.mean(pnl_arr))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        gross_win = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(-losses.sum()) if len(losses) else 0.0
    m["profit_factor"] = min(gross_win / gross_loss, 99.9) if gross_loss > 0 else 99.9
    m["total_return"] = float(np.prod(1.0 + pnl_arr) - 1.0)

    # --- Legacy sharpe: inflated placeholder; overridden below when n_years known ---
    # Set initially so callers that pass no equity still get a non-NaN value.
    if n > 1 and np.std(pnl_arr, ddof=1) > 0:
        m["sharpe"] = float(
            np.mean(pnl_arr) / np.std(pnl_arr, ddof=1) * math.sqrt(float(bars_per_year))
        )

    # --- Equity-curve metrics ---
    if equity is not None and len(equity) > 1:
        eq = equity.to_numpy(dtype=float)
        initial = float(eq[0]) if float(eq[0]) != 0.0 else 1.0

        # --- Calendar-based n_years (uses DatetimeIndex when available) ---
        n_years: float
        try:
            idx = equity.index
            t0 = pd.Timestamp(idx.min())
            t1 = pd.Timestamp(idx.max())
            n_years = max((t1 - t0).days / 365.25, 1e-6)
        except Exception:
            n_years = max(len(equity) / float(bars_per_year), 1e-6)

        # Account-level total return + CAGR (works for unit NAV and dollar equity)
        final = float(eq[-1])
        m["total_return"] = float(final / initial - 1.0)
        if final > 0 and initial > 0 and n_years > 0:
            cagr = float((final / initial) ** (1.0 / n_years) - 1.0)
            m["cagr"] = cagr
        else:
            cagr = float("nan")

        # Trade Sharpe: mean(trade_pnl) / std(trade_pnl) × sqrt(trades/year)
        # This is the metric most systematic traders report — it focuses on
        # trade-outcome consistency rather than bar-frequency noise.
        tpy = n / n_years  # trades per year
        if n > 1 and np.std(pnl_arr, ddof=1) > 0:
            sharpe_trade = float(
                np.mean(pnl_arr) / np.std(pnl_arr, ddof=1) * math.sqrt(tpy)
            )
            m["sharpe_trade"] = sharpe_trade
            # Override the legacy inflated value with the correct number
            m["sharpe"] = sharpe_trade

        # Max drawdown
        peak = np.maximum.accumulate(eq)
        with np.errstate(divide="ignore", invalid="ignore"):
            dd = np.where(peak > 0, (eq - peak) / peak, 0.0)
        m["max_drawdown"] = float(np.min(dd))

        # Daily returns (equity is already daily-resampled when passed correctly)
        safe_eq = np.where(eq == 0, np.nan, eq)
        with np.errstate(divide="ignore", invalid="ignore"):
            daily_ret = np.diff(safe_eq) / safe_eq[:-1]
        daily_ret = daily_ret[~np.isnan(daily_ret)]

        if len(daily_ret) > 1:
            mu  = float(np.nanmean(daily_ret))
            std = float(np.nanstd(daily_ret, ddof=1))

            # sharpe_equity: always annualise with sqrt(252) since equity is daily
            if std > 0:
                m["sharpe_equity"] = float(mu / std * math.sqrt(252.0))

            # Sortino (downside std of daily returns)
            neg = daily_ret[daily_ret < 0]
            if len(neg) > 0:
                downside_std = float(np.std(neg, ddof=1))
                if downside_std > 0:
                    m["sortino_equity"] = float(
                        mu / downside_std * math.sqrt(252.0)
                    )

            # Omega (sum positive / sum absolute negative)
            pos_sum = float(daily_ret[daily_ret > 0].sum())
            neg_sum = float(abs(daily_ret[daily_ret < 0].sum()))
            if neg_sum > 0:
                m["omega"] = pos_sum / neg_sum

        # Calmar = CAGR / abs(max_drawdown) using date-based CAGR
        if m["max_drawdown"] < 0 and not math.isnan(cagr):
            m["calmar"] = cagr / abs(m["max_drawdown"])

    # --- Direction mix ---
    if "side" in trades.columns:
        total = len(trades)
        m["pct_long"]  = float((trades["side"] == "long").sum()  / total)
        m["pct_short"] = float((trades["side"] == "short").sum() / total)

    # --- Avg hold duration ---
    if "duration_days" in trades.columns:
        hold = trades["duration_days"].dropna()
        if len(hold) > 0:
            m["avg_hold_days"] = float(hold.mean())

    return m
