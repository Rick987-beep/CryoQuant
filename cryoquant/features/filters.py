"""Entry-filter factories for trend-following strategies.

These are Tier-1 helpers — pure functions that return a boolean Series
which callers use to gate signal entries. They belong in the features
layer, not in any simulator.

Public interface::

    adx_filter(bars, threshold=25.0, n=14) -> pd.Series
    ema_trend_filter(bars, n=200, direction="long") -> pd.Series
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from cryoquant.features.primitives import adx as _adx
from cryoquant.features.primitives import ema as _ema


def adx_filter(
    bars: pd.DataFrame,
    threshold: float = 25.0,
    n: int = 14,
) -> pd.Series:
    """Return True when ADX(n) > threshold (trending market condition).

    Parameters
    ----------
    bars:       OHLCV DataFrame with tz-aware UTC DatetimeIndex.
    threshold:  ADX level above which the market is considered trending.
                The classic Wilder threshold is 25.
    n:          ADX period (default 14, Wilder-smoothed).

    Returns
    -------
    Boolean Series aligned to bars.index.
    """
    return _adx(bars, n) > threshold


def ema_trend_filter(
    bars: pd.DataFrame,
    n: int = 200,
    direction: Literal["long", "short", "both"] = "long",
) -> pd.Series:
    """Return True when the trend condition relative to EMA(n) is met.

    Long:  close > EMA(n)  — price is above the long-run trend
    Short: close < EMA(n)  — price is below the long-run trend
    Both:  always True      — no directional gate applied

    Parameters
    ----------
    bars:       OHLCV DataFrame with tz-aware UTC DatetimeIndex.
    n:          EMA period (default 200).
    direction:  Which side of the EMA to require. Use ``"both"`` to
                allow entries regardless of EMA position.

    Returns
    -------
    Boolean Series aligned to bars.index.
    """
    e = _ema(bars["close"], n)
    if direction == "long":
        return bars["close"] > e
    if direction == "short":
        return bars["close"] < e
    return pd.Series(True, index=bars.index)
