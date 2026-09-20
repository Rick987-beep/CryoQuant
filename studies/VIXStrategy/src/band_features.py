"""Causal band / mean-reversion features for VIX Overlay Y (and T later).

Levels used for OHLC *touch* fills are shifted one bar so bar ``t`` high/low
never leak into the same-bar level calculation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cryoquant.features.primitives import sma


def rolling_std(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n, min_periods=n).std(ddof=0)


def zscore(close: pd.Series, n: int) -> pd.Series:
    mu = sma(close, n)
    sd = rolling_std(close, n)
    return (close - mu) / sd.replace(0.0, np.nan)


def pct_rank(close: pd.Series, w: int) -> pd.Series:
    """Percentile rank of close vs prior ``w`` closes (inclusive window)."""

    def _rank(x: np.ndarray) -> float:
        if np.isnan(x[-1]):
            return float("nan")
        return float((x <= x[-1]).sum() - 1) / max(len(x) - 1, 1)

    return close.rolling(w, min_periods=w).apply(_rank, raw=True)


def rolling_quantile_price(close: pd.Series, w: int, q: float) -> pd.Series:
    """Rolling quantile of close (price level at rank ``q``)."""
    return close.rolling(w, min_periods=w).quantile(q)


def rolling_median(close: pd.Series, w: int) -> pd.Series:
    return close.rolling(w, min_periods=w).median()


def build_y_features(
    bars: pd.DataFrame,
    *,
    z_n: int = 20,
    rank_w: int = 60,
    peak_n: int = 20,
) -> pd.DataFrame:
    """Feature frame aligned to ``bars``; touch levels are prior-close shifted."""
    close = bars["close"].astype(float)
    feat = pd.DataFrame(index=bars.index)
    feat["sma"] = sma(close, z_n)
    feat["std"] = rolling_std(close, z_n)
    feat["z"] = zscore(close, z_n)
    feat["pct_rank"] = pct_rank(close, rank_w)
    feat["median"] = rolling_median(close, rank_w)
    feat["peak"] = close.rolling(peak_n, min_periods=peak_n).max()
    feat["giveback"] = 1.0 - close / feat["peak"]
    feat["mom_3"] = close / close.shift(3) - 1.0

    # Prior-close levels for same-bar high/low touches
    feat["sma_prev"] = feat["sma"].shift(1)
    feat["std_prev"] = feat["std"].shift(1)
    feat["median_prev"] = feat["median"].shift(1)
    feat["pct_rank_prev"] = feat["pct_rank"].shift(1)
    feat["giveback_prev"] = feat["giveback"].shift(1)
    feat["mom_3_prev"] = feat["mom_3"].shift(1)
    return feat
