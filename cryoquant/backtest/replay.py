"""Linear market replay: target weights and OHLC touch fills.

Complements fixed-hold ``spot_pnl.simulate`` and Donchian ``breakout_sim``.
Use this for continuous weight books and level-touch entries/exits on daily
(or higher) OHLC bars.

Conventions
-----------
- **next_open:** weight decided at close of bar ``t`` is active from open of
  ``t+1``; bar PnL uses close-to-close return while the weight is held.
- **touch:** price *levels* are frozen from prior closes; bar ``t`` high/low
  may trigger fills at the level (or at open if the bar gaps through), matching
  ``breakout_sim`` hard-stop fill logic.

Public interface::

    ReplayConfig, ReplayResult
    replay_weights(bars, weights, ...)
    long_touch_fill / short_touch_fill

Dollar / futures account helpers live in ``cryoquant.backtest.account``
(``AccountConfig``, ``VXM``, ``build_futures_equity``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from cryoquant.backtest.account import AccountConfig
from cryoquant.backtest.metrics import compute_metrics, empty_metrics
from cryoquant.backtest.spot_pnl import SpotResult
from cryoquant.backtest.trades import enrich_trades, _empty_enriched

ExecMode = Literal["next_open", "touch"]


@dataclass(frozen=True)
class ReplayConfig:
    """Knobs for ``replay_weights``.

    ``account`` is reserved for dollar / futures mode callers. The legacy
    fractional ``replay_weights`` path still uses unit NAV + ``fee_bps``.
    """

    exec: ExecMode = "next_open"  # noqa: A003
    fee_bps: float = 0.0
    weight_clip: float | None = None
    feature_cols: tuple[str, ...] = ()
    symbol: str = ""
    account: AccountConfig | None = None


@dataclass
class ReplayResult:
    """Outcome of a linear replay (compatible extras beyond SpotResult)."""

    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict[str, Any]
    bar_log: pd.DataFrame
    spot: SpotResult = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "spot",
            SpotResult(equity=self.equity, trades=self.trades, metrics=self.metrics),
        )


# ---------------------------------------------------------------------------
# Touch fill helpers (gap-aware)
# ---------------------------------------------------------------------------

def long_touch_fill(open_: float, low: float, level: float) -> float | None:
    """Fill price for a buy when low touches ``level``; None if not touched."""
    if np.isnan(level) or np.isnan(low) or np.isnan(open_):
        return None
    if low > level:
        return None
    return float(min(open_, level))


def short_touch_fill(open_: float, high: float, level: float) -> float | None:
    """Fill price for a sell when high touches ``level``; None if not touched."""
    if np.isnan(level) or np.isnan(high) or np.isnan(open_):
        return None
    if high < level:
        return None
    return float(max(open_, level))


# ---------------------------------------------------------------------------
# Weight replay (next_open)
# ---------------------------------------------------------------------------

def replay_weights(
    bars: pd.DataFrame,
    weights: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    config: ReplayConfig | None = None,
) -> ReplayResult:
    """Mark-to-market a target weight series on one underlying.

    ``weights[t]`` is the desired position after close ``t``. Under
    ``exec='next_open'`` the filled weight on bar ``t`` is ``weights[t-1]``
    (shifted one bar). Turnover fees apply on ``|Δ filled_weight|``.

    ``exec='touch'`` is not handled here — build fills upstream (e.g. Overlay Y
    state machine) then pass the resulting filled-weight series with
    ``exec='next_open'``, or use study-local touch simulators.
    """
    cfg = config or ReplayConfig()
    if cfg.exec != "next_open":
        raise NotImplementedError(
            "replay_weights only supports exec='next_open'; "
            "run touch logic upstream and pass filled weights."
        )

    if not {"open", "high", "low", "close"}.issubset(bars.columns):
        raise ValueError("bars must contain open, high, low, close")

    n = len(bars)
    if n == 0:
        empty_eq = pd.Series(dtype=float, name="equity")
        return ReplayResult(
            equity=empty_eq,
            trades=_empty_enriched(),
            metrics=empty_metrics(),
            bar_log=pd.DataFrame(),
        )

    w = weights.reindex(bars.index).astype(float).fillna(0.0)
    if cfg.weight_clip is not None:
        w = w.clip(-cfg.weight_clip, cfg.weight_clip)

    # Decision at t → active from open t+1 ⇒ filled[t] = target[t-1]
    filled = w.shift(1).fillna(0.0)
    close = bars["close"].astype(float)
    ret = close.pct_change().fillna(0.0)

    fee_one = cfg.fee_bps / 10_000.0
    turnover = filled.diff().abs().fillna(filled.abs())
    fee_drag = turnover * fee_one
    pnl = filled * ret - fee_drag

    pnl_arr = pnl.to_numpy(dtype=float)
    equity_arr = np.empty(n, dtype=float)
    equity_arr[0] = 1.0
    for i in range(1, n):
        equity_arr[i] = equity_arr[i - 1] * (1.0 + pnl_arr[i])
    equity = pd.Series(equity_arr, index=bars.index, name="equity")

    trades = _trades_from_weight_changes(
        bars.index, close, filled, fee_one_way=fee_one, symbol=cfg.symbol
    )
    if len(trades):
        enriched = enrich_trades(trades, equity, bars_index=bars.index)
        metrics = compute_metrics(enriched, equity)
    else:
        enriched = _empty_enriched()
        metrics = compute_metrics(enriched, equity)

    bar_log = _build_bar_log(bars, w, filled, ret, pnl, equity, features, cfg)
    return ReplayResult(equity=equity, trades=enriched, metrics=metrics, bar_log=bar_log)


def _build_bar_log(
    bars: pd.DataFrame,
    target: pd.Series,
    filled: pd.Series,
    ret: pd.Series,
    pnl: pd.Series,
    equity: pd.Series,
    features: pd.DataFrame | None,
    cfg: ReplayConfig,
) -> pd.DataFrame:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    log = pd.DataFrame(
        {
            "timestamp": bars.index,
            "symbol": cfg.symbol or "",
            "open": bars["open"].to_numpy(dtype=float),
            "high": bars["high"].to_numpy(dtype=float),
            "low": bars["low"].to_numpy(dtype=float),
            "close": bars["close"].to_numpy(dtype=float),
            "target_weight": target.to_numpy(dtype=float),
            "position_weight": filled.to_numpy(dtype=float),
            "bar_ret": ret.to_numpy(dtype=float),
            "pnl": pnl.to_numpy(dtype=float),
            "equity": equity.to_numpy(dtype=float),
            "drawdown": dd.to_numpy(dtype=float),
            "event": "",
        },
        index=bars.index,
    )
    if "volume" in bars.columns:
        log["volume"] = bars["volume"].to_numpy(dtype=float)

    # Tag scale / enter / exit from filled weight changes
    prev = filled.shift(1).fillna(0.0)
    entered = (prev == 0) & (filled != 0)
    exited = (prev != 0) & (filled == 0)
    scaled = (prev != 0) & (filled != 0) & (prev != filled)
    log.loc[entered, "event"] = "enter"
    log.loc[exited, "event"] = "exit"
    log.loc[scaled, "event"] = "scale"

    if features is not None and cfg.feature_cols:
        feat = features.reindex(bars.index)
        for col in cfg.feature_cols:
            if col in feat.columns:
                log[f"feature_{col}"] = feat[col].to_numpy(dtype=float)
    return log


def _trades_from_weight_changes(
    index: pd.DatetimeIndex,
    close: pd.Series,
    filled: pd.Series,
    *,
    fee_one_way: float,
    symbol: str,
) -> pd.DataFrame:
    """Collapse non-zero weight runs into round-trips (sign flips split trades)."""
    f = filled.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    rows: list[dict[str, Any]] = []

    i = 0
    n = len(f)
    while i < n:
        if abs(f[i]) < 1e-15:
            i += 1
            continue
        side = "long" if f[i] > 0 else "short"
        entry_i = i
        w0 = f[i]
        # Hold while same sign
        j = i + 1
        while j < n and f[j] * w0 > 0:
            j += 1
        exit_i = j - 1 if j > i else i
        # Exit at open of first flat/opposite bar if available, else last close
        if j < n:
            exit_i = j  # first bar of new regime — use its open conceptually via close of prior
            # Use close of last in-trade bar as exit mark for weight books
            exit_i = j - 1
            exit_price = c[exit_i]
            # If next bar exists and weight dropped, prefer modeling exit at next open ≈ use close[exit_i]
        else:
            exit_price = c[exit_i]

        entry_price = c[entry_i]  # approximate for continuous weight; touch sims supply better prices
        raw = (exit_price - entry_price) / entry_price
        if side == "short":
            raw = -raw
        # Scale by average |weight| over the run
        avg_w = float(np.mean(np.abs(f[entry_i : exit_i + 1])))
        fee_rt = 2.0 * fee_one_way * avg_w
        pnl = raw * avg_w - fee_rt
        rows.append(
            {
                "entry_ts": index[entry_i].to_pydatetime(),
                "exit_ts": index[exit_i].to_pydatetime(),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "pnl_pct": float(pnl),
                "fee_pct": float(fee_rt),
                "side": side,
                "exit_type": "weight_run",
                "symbol": symbol,
                "weight_entry": float(w0),
                "weight_exit": float(f[exit_i]),
            }
        )
        i = exit_i + 1
        if j < n and abs(f[j]) > 1e-15 and i == j:
            continue
        if j > i:
            i = j

    if not rows:
        return pd.DataFrame(
            columns=["entry_ts", "exit_ts", "entry_price", "exit_price", "pnl_pct", "fee_pct"]
        )
    return pd.DataFrame(rows)
