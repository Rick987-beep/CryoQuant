"""Forward-return labelers.

ForwardReturnLabeler computes binary outcome columns at a given horizon
and threshold. These are **always forward-looking** and must never be used
as model features — only as training targets.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

Direction = Literal["up", "down", "magnitude"]


class ForwardReturnLabeler:
    """Label each bar based on forward-horizon price movement.

    Args:
        horizon_h:   Look-forward window in bars (usually 1h bars, so horizon_h=24 = 1 day).
        threshold:   Price move threshold in percent (e.g. 2.5 = 2.5%).
        direction:   "up"  → fwd max high >= close*(1+thr/100)
                     "down" → fwd min low <= close*(1-thr/100)
                     "magnitude" → either direction.
    """

    def __init__(self, horizon_h: int, threshold: float, direction: Direction = "magnitude"):
        if horizon_h < 1:
            raise ValueError("horizon_h must be >= 1")
        if threshold <= 0:
            raise ValueError("threshold must be > 0")
        self.horizon_h = horizon_h
        self.threshold = threshold
        self.direction = direction

    @property
    def column_name(self) -> str:
        t = f"{self.threshold:.1f}".replace(".", "p")
        return f"{self.direction}_win_t{t}_h{self.horizon_h}"

    def apply(self, df: pd.DataFrame) -> pd.Series:
        """Return a boolean label Series aligned to df.index.

        The trailing `horizon_h` rows will be NaN (no complete forward window).
        Requires df to have columns: close, high, low.
        """
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        h     = self.horizon_h
        thr   = self.threshold / 100.0

        # Forward max-high and min-low: rolling over the NEXT h bars
        # rolling(h).max().shift(-h) at bar t = max(high[t+1..t+h])
        fwd_max_high = high.rolling(h, min_periods=h).max().shift(-h)
        fwd_min_low  = low.rolling(h, min_periods=h).min().shift(-h)

        move_up = (fwd_max_high - close) / close
        move_dn = (close - fwd_min_low)  / close

        if self.direction == "up":
            label = move_up >= thr
        elif self.direction == "down":
            label = move_dn >= thr
        else:  # magnitude
            label = (move_up >= thr) | (move_dn >= thr)

        # Trailing h rows have no complete forward window → NaN-ify
        result = label.astype(float)
        result.iloc[-h:] = float("nan")

        series = result.rename(self.column_name)
        return series
