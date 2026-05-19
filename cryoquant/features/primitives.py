"""Tier-1 price-action and volatility primitives.

All functions are:
- Pure (no side effects, no caching)
- Vectorised over pd.Series/DataFrame
- Closed-bar safe: inputs must be from closed bars; callers handle shifting

Naming mirrors Pine v5 where applicable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(s: pd.Series, n: int) -> pd.Series:
    """Simple moving average over n bars."""
    return s.rolling(n, min_periods=n).mean()


def _seeded_recursive_ma(s: pd.Series, n: int, alpha: float) -> pd.Series:
    """Pine v5-faithful seeded recursive MA (used by ema and rma)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    arr = s.to_numpy(dtype=float)
    out = np.full_like(arr, np.nan)
    if len(arr) < n:
        return pd.Series(out, index=s.index)
    seed_window = arr[:n]
    seed = np.where(np.isnan(seed_window), 0.0, seed_window).sum() / n
    out[n - 1] = seed
    for i in range(n, len(arr)):
        x = arr[i]
        prev = out[i - 1]
        out[i] = prev if np.isnan(x) else alpha * x + (1 - alpha) * prev
    return pd.Series(out, index=s.index)


def ema(s: pd.Series, n: int) -> pd.Series:
    """Pine v5 ta.ema: SMA-seeded EMA, alpha = 2/(n+1)."""
    return _seeded_recursive_ma(s, n, 2.0 / (n + 1.0))


def rma(s: pd.Series, n: int) -> pd.Series:
    """Pine v5 ta.rma (Wilder smoothing): SMA-seeded, alpha = 1/n."""
    return _seeded_recursive_ma(s, n, 1.0 / n)


def wma(s: pd.Series, n: int) -> pd.Series:
    """Linearly weighted MA, weights 1..n."""
    weights = np.arange(1, n + 1, dtype=float)
    denom = weights.sum()
    return s.rolling(n, min_periods=n).apply(lambda x: np.dot(x, weights) / denom, raw=True)


# ---------------------------------------------------------------------------
# Range / True Range / ATR
# ---------------------------------------------------------------------------

def tr(df: pd.DataFrame) -> pd.Series:
    """True range: max(h-l, |h-prev_c|, |l-prev_c|). First bar = h-l."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_c = close.shift(1)
    a = high - low
    b = (high - prev_c).abs()
    c = (low - prev_c).abs()
    out = pd.concat([a, b, c], axis=1).max(axis=1)
    out.iloc[0] = high.iloc[0] - low.iloc[0]
    return out


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range via Wilder smoothing."""
    return rma(tr(df), n)


def atr_pct(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR as a percentage of close price."""
    return atr(df, n) / df["close"].replace(0, np.nan) * 100


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """Pine v5 ta.rsi: Wilder-smoothed RSI."""
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = rma(gain, n)
    avg_loss = rma(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def bb(src: pd.Series, n: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands. Pine uses population std (ddof=0)."""
    basis = sma(src, n)
    dev = src.rolling(n, min_periods=n).std(ddof=0) * mult
    return pd.DataFrame({"upper": basis + dev, "basis": basis, "lower": basis - dev})


def bb_width(src: pd.Series, n: int = 20, mult: float = 2.0) -> pd.Series:
    """BBW as percentage: 100 * (upper - lower) / basis."""
    bands = bb(src, n, mult)
    return 100.0 * (bands["upper"] - bands["lower"]) / bands["basis"].replace(0, np.nan)


# ---------------------------------------------------------------------------
# Realised volatility
# ---------------------------------------------------------------------------

def realised_vol(close: pd.Series, n: int = 24, annualise_factor: float = 8760) -> pd.Series:
    """Annualised realised volatility from log-returns.

    Args:
        close:            Close price series.
        n:                Rolling window (bars).
        annualise_factor: Bars per year. 8760 for 1h crypto; 252 for daily.
    """
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(n, min_periods=n).std() * np.sqrt(annualise_factor) * 100


def rv_rank(close: pd.Series, n: int = 24, lookback: int = 720) -> pd.Series:
    """Rolling percentile rank of realised vol."""
    rv = realised_vol(close, n)
    return rv.rolling(lookback, min_periods=lookback // 2).rank(pct=True)


def vol_z(volume: pd.Series, n: int = 24) -> pd.Series:
    """Volume z-score relative to trailing n-bar mean/std."""
    mean = volume.rolling(n, min_periods=n // 2).mean()
    std = volume.rolling(n, min_periods=n // 2).std(ddof=0)
    return (volume - mean) / std.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Range ratio
# ---------------------------------------------------------------------------

def range_ratio(df: pd.DataFrame, n: int = 24) -> pd.Series:
    """Current bar's (high-low)/close range vs the trailing n-bar average."""
    bar_range_pct = (df["high"] - df["low"]) / df["close"].replace(0, np.nan) * 100
    avg = bar_range_pct.rolling(n, min_periods=n // 2).mean()
    return bar_range_pct / avg.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Resampling + HTF alignment (ported from pineforge.data)
# ---------------------------------------------------------------------------

_TF_TO_PANDAS: dict[str, str] = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h",
    "8h": "8h", "12h": "12h", "1d": "1D", "1w": "1W",
}


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample OHLCV to a coarser timeframe (left-labelled, left-closed)."""
    if tf not in _TF_TO_PANDAS:
        raise ValueError(f"unsupported tf {tf!r}")
    rule = _TF_TO_PANDAS[tf]
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])


def htf_align(base_df: pd.DataFrame, htf_series: pd.Series, *, htf: str) -> pd.Series:
    """Forward-fill an HTF series onto a base-TF DataFrame, closed-bar safe.

    Mirrors Pine's `request.security(..., lookahead=barmerge.lookahead_off)`.
    """
    if htf not in _TF_TO_PANDAS:
        raise ValueError(f"unsupported htf {htf!r}")
    step = pd.tseries.frequencies.to_offset(_TF_TO_PANDAS[htf])
    htf_close_ts = htf_series.index + step
    feed = pd.DataFrame({"close_ts": htf_close_ts, "value": htf_series.to_numpy()})
    feed = feed.sort_values("close_ts").reset_index(drop=True)
    base = pd.DataFrame({"base_ts": base_df.index})
    base = base.sort_values("base_ts").reset_index(drop=True)
    joined = pd.merge_asof(base, feed, left_on="base_ts", right_on="close_ts", direction="backward")
    return pd.Series(joined["value"].to_numpy(), index=base_df.index, name=htf_series.name)
