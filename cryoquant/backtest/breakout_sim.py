"""Channel-breakout trend-following simulator with dynamic trailing exits.

Implements a Donchian-channel-breakout entry combined with a trailing
Donchian or Supertrend exit and an ATR-based hard stop.  Supports long,
short, and both-direction modes.  Returns a ``SpotResult`` (same interface
as ``cryoquant.backtest.spot_pnl.simulate``) so the result is directly
compatible with ``deflated_sharpe``, ``bootstrap_ci``, and all report
renderers.

Key differences from ``spot_pnl.simulate``
-------------------------------------------
- Dynamic exits: trailing Donchian channel OR Supertrend direction flip.
- Hard stop: ATR-based, checked against intraday low/high.
- Long, short, and two-sided (``"both"``) direction support.
- No fixed hold period — each trade runs until an exit condition fires.

Signal convention (all closed-bar safe)
----------------------------------------
- Entry fires at close of bar i → executed at open of bar i+1.
- Trailing-stop exit fires at close of bar i → open of bar i+1.
- Hard-stop exit fires when bar low/high breaches the stop level.
  If price opened through the stop (gap), filled at bar open.

Usage::

    from cryoquant.backtest.breakout_sim import BreakoutConfig, simulate_breakout

    cfg = BreakoutConfig(entry_n=55, exit_n=20, direction="long", fee_bps=5.0)
    result = simulate_breakout(bars, cfg)
    print(result.metrics)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from cryoquant.backtest.metrics import compute_metrics, empty_metrics
from cryoquant.backtest.spot_pnl import SpotResult
from cryoquant.backtest.trades import enrich_trades, _empty_enriched
from cryoquant.features.primitives import atr, donchian, ema, supertrend


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BreakoutConfig:
    """All tuning knobs for a single breakout-simulator run.

    Parameters
    ----------
    entry_n:             Donchian entry-channel window (bars).
    exit_n:              Donchian trailing-stop channel window (bars).
    direction:           ``"long"`` / ``"short"`` / ``"both"``.
                         ``"both"`` enters on whichever breakout fires first;
                         long takes priority on a simultaneous signal.
    stop_atr_mult:       ATR multiplier for the hard stop (default 2.0).
    atr_n:               ATR period for the hard stop (default 20).
    fee_bps:             Round-trip fee in basis points (5 bps ≈ ETF;
                         10 bps ≈ crypto spot).
    use_supertrend_exit: Replace Donchian trailing stop with a Supertrend
                         direction flip.
    st_n:                Supertrend ATR period (used when
                         ``use_supertrend_exit=True``).
    st_mult:             Supertrend ATR multiplier.
    """

    entry_n: int
    exit_n: int
    direction: Literal["long", "short", "both"] = "long"
    stop_atr_mult: float = 2.0
    atr_n: int = 20
    fee_bps: float = 5.0
    use_supertrend_exit: bool = False
    st_n: int = 10
    st_mult: float = 3.0


# ---------------------------------------------------------------------------
# Private: precomputed indicator bundle
# ---------------------------------------------------------------------------

@dataclass
class _Indicators:
    closes: np.ndarray
    opens: np.ndarray
    lows: np.ndarray
    highs: np.ndarray
    entry_upper: np.ndarray
    entry_lower: np.ndarray
    exit_lower: np.ndarray
    exit_upper: np.ndarray
    atr_arr: np.ndarray
    filt: np.ndarray              # boolean entry-filter (all-True if no filter)
    st_dir: np.ndarray | None     # Supertrend direction (+1/-1), None if unused


def _precompute(
    bars: pd.DataFrame,
    config: BreakoutConfig,
    entry_filter: pd.Series | None,
) -> _Indicators:
    closes = bars["close"].to_numpy(dtype=float)
    opens  = bars["open"].to_numpy(dtype=float)
    lows   = bars["low"].to_numpy(dtype=float)
    highs  = bars["high"].to_numpy(dtype=float)

    dc_entry = donchian(bars["close"], config.entry_n)
    dc_exit  = donchian(bars["close"], config.exit_n)
    atr_arr  = atr(bars, config.atr_n).to_numpy(dtype=float)

    st_dir: np.ndarray | None = None
    if config.use_supertrend_exit:
        st_dir = supertrend(bars, config.st_n, config.st_mult)["direction"].to_numpy(dtype=float)

    filt = (
        entry_filter.reindex(bars.index, fill_value=False)
                    .fillna(False)
                    .to_numpy(dtype=bool)
        if entry_filter is not None
        else np.ones(len(bars), dtype=bool)
    )

    return _Indicators(
        closes=closes,
        opens=opens,
        lows=lows,
        highs=highs,
        entry_upper=dc_entry["upper"].to_numpy(dtype=float),
        entry_lower=dc_entry["lower"].to_numpy(dtype=float),
        exit_lower=dc_exit["lower"].to_numpy(dtype=float),
        exit_upper=dc_exit["upper"].to_numpy(dtype=float),
        atr_arr=atr_arr,
        filt=filt,
        st_dir=st_dir,
    )


# ---------------------------------------------------------------------------
# Private: bar-by-bar state machine
# ---------------------------------------------------------------------------

def _run_trade_loop(
    n: int,
    config: BreakoutConfig,
    ind: _Indicators,
    index: pd.DatetimeIndex,
) -> list[dict]:
    """Execute the entry/exit state machine and return raw trade rows."""
    fee_rt = config.fee_bps / 10_000.0 * 2.0

    in_trade = False
    entry_price = 0.0
    hard_stop = 0.0
    entry_ts_val = None
    entry_bar_idx = -1
    current_dir: Literal["long", "short"] = "long"

    trade_rows: list[dict] = []

    for i in range(n - 1):
        if not in_trade:
            long_signal  = ind.closes[i] > ind.entry_upper[i]
            short_signal = ind.closes[i] < ind.entry_lower[i]

            if config.direction == "long":
                breakout, trade_dir = long_signal, "long"
            elif config.direction == "short":
                breakout, trade_dir = short_signal, "short"
            else:  # "both" — long takes priority on simultaneous breakout
                if long_signal:
                    breakout, trade_dir = True, "long"
                elif short_signal:
                    breakout, trade_dir = True, "short"
                else:
                    breakout, trade_dir = False, "long"  # unused

            entry_valid = (
                breakout
                and ind.filt[i]
                and not np.isnan(ind.entry_upper[i])
                and not np.isnan(ind.atr_arr[i])
                and not np.isnan(ind.opens[i + 1])
            )
            if entry_valid:
                eb = i + 1
                ep = ind.opens[eb]
                hs = (
                    ep - config.stop_atr_mult * ind.atr_arr[i]
                    if trade_dir == "long"
                    else ep + config.stop_atr_mult * ind.atr_arr[i]
                )
                in_trade = True
                current_dir = trade_dir
                entry_price = ep
                hard_stop = hs
                entry_ts_val = index[eb]
                entry_bar_idx = eb

        else:
            hard_hit = (
                ind.lows[i] <= hard_stop
                if current_dir == "long"
                else ind.highs[i] >= hard_stop
            )

            if config.use_supertrend_exit and ind.st_dir is not None:
                trail_hit = (
                    ind.st_dir[i] == -1.0
                    if current_dir == "long"
                    else ind.st_dir[i] == 1.0
                )
            elif current_dir == "long":
                trail_hit = (
                    not np.isnan(ind.exit_lower[i])
                    and ind.closes[i] <= ind.exit_lower[i]
                )
            else:
                trail_hit = (
                    not np.isnan(ind.exit_upper[i])
                    and ind.closes[i] >= ind.exit_upper[i]
                )

            if hard_hit or trail_hit:
                if hard_hit:
                    xp = (
                        min(ind.opens[i], hard_stop)
                        if current_dir == "long"
                        else max(ind.opens[i], hard_stop)
                    )
                    xi = i
                    exit_type = "hard_stop"
                else:
                    xi = min(i + 1, n - 1)
                    xp = ind.opens[xi] if i + 1 < n else ind.closes[i]
                    exit_type = "trail"

                raw_ret = (xp - entry_price) / entry_price
                pnl = (raw_ret if current_dir == "long" else -raw_ret) - fee_rt

                trade_rows.append({
                    "entry_ts":    entry_ts_val,
                    "exit_ts":     index[xi],
                    "entry_price": entry_price,
                    "exit_price":  xp,
                    "pnl_pct":     pnl,
                    "fee_pct":     fee_rt,
                    "side":        current_dir,
                    "exit_type":   exit_type,
                    "_entry_bar":  entry_bar_idx,
                    "_exit_bar":   xi,
                })
                in_trade = False

    # Force-close any open trade at end of data
    if in_trade:
        xi = n - 1
        xp = ind.closes[xi]
        raw_ret = (xp - entry_price) / entry_price
        pnl = (raw_ret if current_dir == "long" else -raw_ret) - fee_rt
        trade_rows.append({
            "entry_ts":    entry_ts_val,
            "exit_ts":     index[xi],
            "entry_price": entry_price,
            "exit_price":  xp,
            "pnl_pct":     pnl,
            "fee_pct":     fee_rt,
            "side":        current_dir,
            "exit_type":   "end_of_data",
            "_entry_bar":  entry_bar_idx,
            "_exit_bar":   xi,
        })

    return trade_rows


# ---------------------------------------------------------------------------
# Private: MTM equity curve reconstruction
# ---------------------------------------------------------------------------

def _build_equity_curve(
    trade_rows: list[dict],
    closes: np.ndarray,
    index: pd.DatetimeIndex,
) -> pd.Series:
    """Build a bar-level MTM equity curve from closed trade records.

    During open positions the portfolio is valued at the close price (MTM).
    At the exit bar the equity is set to the *settled* value (actual fill
    price including fees) rather than the close-based MTM.  This prevents
    a discontinuity between the exit bar and the subsequent flat period when
    a hard stop fills at a price different from the bar's close.
    """
    n = len(closes)
    equity_arr = np.ones(n, dtype=float)
    current_eq = 1.0
    prev = 0

    for row in trade_rows:
        ei = row["_entry_bar"]
        xi = row["_exit_bar"]
        ep = row["entry_price"]
        d  = row["side"]
        pnl = row["pnl_pct"]

        # Flat period before this trade
        equity_arr[prev:ei] = current_eq

        # MTM during the trade: close-based mark
        if d == "long":
            raw_rets = closes[ei : xi + 1] / ep - 1.0
        else:
            raw_rets = 1.0 - closes[ei : xi + 1] / ep
        equity_arr[ei : xi + 1] = current_eq * (1.0 + raw_rets)

        # Override the exit bar with the settled (fill-price) equity so that
        # equity_arr[xi] == equity_arr[xi+1:next_ei] and there is no cliff.
        settled = current_eq * (1.0 + pnl)
        equity_arr[xi] = settled
        current_eq = settled
        prev = xi + 1

    equity_arr[prev:] = current_eq  # flat tail after last trade
    return pd.Series(equity_arr, index=index, name="equity")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def simulate_breakout(
    bars: pd.DataFrame,
    config: BreakoutConfig,
    entry_filter: pd.Series | None = None,
) -> SpotResult:
    """Simulate a channel-breakout trend-following strategy bar by bar.

    Parameters
    ----------
    bars:         OHLCV DataFrame with tz-aware UTC DatetimeIndex.
    config:       ``BreakoutConfig`` capturing all tuning knobs.
    entry_filter: Optional boolean Series aligned to bars.index.
                  When provided, entry signals are suppressed on bars
                  where the value is False or NaN.  Use
                  ``cryoquant.features.filters`` to build common filters
                  (``adx_filter``, ``ema_trend_filter``).

    Returns
    -------
    ``SpotResult`` with equity, enriched trades DataFrame, and metrics dict.
    The trades DataFrame includes extra columns:
    - ``exit_type``: ``"trail"`` | ``"hard_stop"`` | ``"end_of_data"``
    - ``side``:      ``"long"`` | ``"short"``
    """
    n = len(bars)
    min_bars = max(config.entry_n, config.exit_n, config.atr_n) + 2
    if n < min_bars:
        return _empty_result(bars)

    ind = _precompute(bars, config, entry_filter)
    trade_rows = _run_trade_loop(n, config, ind, bars.index)

    if not trade_rows:
        return _empty_result(bars)

    equity_bar = _build_equity_curve(trade_rows, ind.closes, bars.index)

    # Resample to calendar-daily NAV so Sharpe / CAGR are on daily frequency
    # regardless of the underlying bar size.
    equity_daily = equity_bar.resample("1D").last().dropna()
    equity_daily.name = "equity"

    # Strip internal bar-index columns before enrichment
    trades_df = pd.DataFrame([
        {k: v for k, v in row.items() if not k.startswith("_")}
        for row in trade_rows
    ])

    enriched = enrich_trades(trades_df, equity_bar, bars_index=bars.index)
    metrics  = compute_metrics(enriched, equity_daily)

    return SpotResult(equity=equity_daily, trades=enriched, metrics=metrics)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_result(bars: pd.DataFrame) -> SpotResult:
    equity = pd.Series(np.ones(len(bars)), index=bars.index, name="equity")
    return SpotResult(equity=equity, trades=_empty_enriched(), metrics=empty_metrics())
