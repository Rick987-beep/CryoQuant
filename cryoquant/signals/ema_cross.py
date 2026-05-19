"""EMA 7/21 daily crossover signal.

Uses DailyEmaCrossFeatures columns: cross_up, cross_down.

Factories
---------
make_ema_cross()       -> StateSignal  (+1 / 0 / -1)
make_ema_cross_long()  -> BoolSignal   (True on bullish cross only)
make_ema_cross_short() -> BoolSignal   (True on bearish cross only)
"""
from __future__ import annotations

import pandas as pd

from cryoquant.signals.base import BoolSignal, StateSignal

_SYMBOL = "binance.spot:BTCUSDT"


def make_ema_cross() -> StateSignal:
    """StateSignal: +1 on bullish cross, -1 on bearish cross, 0 otherwise."""

    def _state_fn(df: pd.DataFrame) -> pd.Series:
        up   = df["cross_up"].fillna(False).astype(bool)
        down = df["cross_down"].fillna(False).astype(bool)
        states = pd.Series(0, index=df.index, dtype="int8")
        states[up]   = 1
        states[down] = -1
        return states

    return StateSignal(
        signal_id="ema_cross_7_21_1d",
        state_fn=_state_fn,
        version="1",
        symbol_str=_SYMBOL,
    )


def make_ema_cross_long() -> BoolSignal:
    """BoolSignal: fires True on bullish EMA 7/21 cross (long entry)."""
    return BoolSignal(
        signal_id="ema_cross_long_7_21_1d",
        condition=lambda df: df["cross_up"].fillna(False).astype(bool),
        version="1",
        symbol_str=_SYMBOL,
    )


def make_ema_cross_short() -> BoolSignal:
    """BoolSignal: fires True on bearish EMA 7/21 cross (short entry)."""
    return BoolSignal(
        signal_id="ema_cross_short_7_21_1d",
        condition=lambda df: df["cross_down"].fillna(False).astype(bool),
        version="1",
        symbol_str=_SYMBOL,
    )
