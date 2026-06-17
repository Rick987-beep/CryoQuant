"""Unit tests for cryoquant.features.filters — entry-filter factories."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryoquant.features.filters import adx_filter, ema_trend_filter
from cryoquant.features.primitives import adx as _adx
from cryoquant.features.primitives import ema as _ema


def _bars(closes: list[float], *, n: int | None = None) -> pd.DataFrame:
    n = n or len(closes)
    c = np.array(closes[:n], dtype=float)
    idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
    return pd.DataFrame(
        {"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1.0},
        index=idx,
    )


def _noisy_trend(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    closes = 100.0 + rng.standard_normal(n).cumsum()
    closes = np.clip(closes, 1, None)
    return _bars(closes.tolist())


class TestEmaTrendFilter:
    def test_long_filter_when_above_ema(self) -> None:
        bars = _noisy_trend()
        filt = ema_trend_filter(bars, n=200, direction="long")
        e200 = _ema(bars["close"], 200)
        valid = filt & e200.notna()
        assert (bars.loc[valid[valid].index, "close"] > e200[valid[valid].index]).all()

    def test_short_filter_when_below_ema(self) -> None:
        bars = _noisy_trend()
        filt = ema_trend_filter(bars, n=200, direction="short")
        e200 = _ema(bars["close"], 200)
        valid = filt & e200.notna()
        assert (bars.loc[valid[valid].index, "close"] < e200[valid[valid].index]).all()

    def test_both_direction_always_true(self) -> None:
        bars = _noisy_trend()
        filt = ema_trend_filter(bars, n=200, direction="both")
        assert filt.all()


class TestAdxFilter:
    def test_returns_true_only_above_threshold(self) -> None:
        bars = _noisy_trend(n=200)
        threshold = 20.0
        filt = adx_filter(bars, threshold=threshold)
        adx_vals = _adx(bars, 14)
        valid = filt & adx_vals.notna()
        assert (adx_vals[valid[valid].index] > threshold).all()

    def test_index_aligned_to_bars(self) -> None:
        bars = _noisy_trend()
        filt = adx_filter(bars)
        assert filt.index.equals(bars.index)
