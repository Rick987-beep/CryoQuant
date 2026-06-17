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


# ---------------------------------------------------------------------------
# Trend indicators (new in Phase 2)
# ---------------------------------------------------------------------------

def donchian(close: pd.Series, n: int) -> pd.DataFrame:
    """Donchian channel: N-bar rolling high/low of the *previous* bar's close.

    The shift-1 is applied internally — callers do NOT need to shift again.
    Upper and lower represent the breakout levels known at bar open.
    """
    shifted = close.shift(1)
    upper = shifted.rolling(n, min_periods=n).max()
    lower = shifted.rolling(n, min_periods=n).min()
    mid = (upper + lower) / 2.0
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": mid}, index=close.index)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average Directional Index (Wilder-smoothed ADX), range 0–100.

    Builds on existing ``tr`` / ``rma`` primitives.
    """
    high = df["high"]
    low = df["low"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    dm_plus_raw = high - prev_high
    dm_minus_raw = prev_low - low

    dm_plus = np.where(
        (dm_plus_raw > dm_minus_raw) & (dm_plus_raw > 0), dm_plus_raw, 0.0
    )
    dm_minus = np.where(
        (dm_minus_raw > dm_plus_raw) & (dm_minus_raw > 0), dm_minus_raw, 0.0
    )

    dm_plus_s = pd.Series(dm_plus, index=high.index)
    dm_minus_s = pd.Series(dm_minus, index=high.index)
    tr_s = tr(df)

    smooth_tr = rma(tr_s, n)
    smooth_plus = rma(dm_plus_s, n)
    smooth_minus = rma(dm_minus_s, n)

    di_plus = 100.0 * smooth_plus / smooth_tr.replace(0, np.nan)
    di_minus = 100.0 * smooth_minus / smooth_tr.replace(0, np.nan)

    di_sum = (di_plus + di_minus).replace(0, np.nan)
    dx = 100.0 * (di_plus - di_minus).abs() / di_sum
    return rma(dx, n).rename("adx")


def keltner(df: pd.DataFrame, n: int = 20, mult: float = 1.5) -> pd.DataFrame:
    """Keltner Channel: EMA(n) ± mult × ATR(n).

    Returns DataFrame with columns ``upper`` and ``lower``.
    """
    basis = ema(df["close"], n)
    band = mult * atr(df, n)
    return pd.DataFrame({"upper": basis + band, "lower": basis - band}, index=df.index)


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """ATR-based Supertrend indicator (Pine v5–faithful).

    Returns DataFrame with columns:
      ``value``     — the active band level (support or resistance)
      ``direction`` — +1 (bullish) or −1 (bearish)
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    hl2 = (high + low) / 2.0
    atr_vals = atr(df, n).to_numpy(dtype=float)

    basic_upper = hl2 + mult * atr_vals
    basic_lower = hl2 - mult * atr_vals

    final_upper = np.full(len(close), np.nan)
    final_lower = np.full(len(close), np.nan)
    direction = np.full(len(close), np.nan)
    value = np.full(len(close), np.nan)

    # Find first bar where ATR is valid
    first = next((i for i, v in enumerate(atr_vals) if not np.isnan(v)), None)
    if first is None:
        return pd.DataFrame({"value": value, "direction": direction}, index=df.index)

    for i in range(first, len(close)):
        if i == first:
            final_upper[i] = basic_upper[i]
            final_lower[i] = basic_lower[i]
            direction[i] = 1.0
        else:
            # Lower band: ratchet upward while price stays above
            final_lower[i] = (
                max(basic_lower[i], final_lower[i - 1])
                if close[i - 1] > final_lower[i - 1]
                else basic_lower[i]
            )
            # Upper band: ratchet downward while price stays below
            final_upper[i] = (
                min(basic_upper[i], final_upper[i - 1])
                if close[i - 1] < final_upper[i - 1]
                else basic_upper[i]
            )
            # Direction flip
            prev_dir = direction[i - 1]
            if prev_dir == -1.0 and close[i] > final_upper[i - 1]:
                direction[i] = 1.0
            elif prev_dir == 1.0 and close[i] < final_lower[i - 1]:
                direction[i] = -1.0
            else:
                direction[i] = prev_dir

        value[i] = final_lower[i] if direction[i] == 1.0 else final_upper[i]

    return pd.DataFrame(
        {"value": pd.Series(value, index=df.index),
         "direction": pd.Series(direction, index=df.index)},
    )


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """MACD line, signal line, and histogram.

    Returns DataFrame with columns ``macd``, ``signal``, ``hist``.
    """
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": histogram},
        index=close.index,
    )


def roc(close: pd.Series, n: int) -> pd.Series:
    """Rate of Change: (close / close.shift(n)) − 1."""
    return (close / close.shift(n) - 1.0).rename(f"roc_{n}")


# ---------------------------------------------------------------------------
# Statistical / advanced trend primitives
# ---------------------------------------------------------------------------

def linear_reg_slope(s: pd.Series, n: int) -> pd.Series:
    """OLS slope of s over a rolling n-bar window (raw units per bar).

    To convert to a normalised % return equivalent in the caller::

        slope_pct = linear_reg_slope(close, n) / close * n * 100
    """
    x = np.arange(n, dtype=float)
    x -= x.mean()
    ss_x = float((x ** 2).sum())

    def _slope(y: np.ndarray) -> float:
        if np.isnan(y).any():
            return np.nan
        y_dm = y - y.mean()
        return float(np.dot(x, y_dm) / ss_x)

    return s.rolling(n, min_periods=n).apply(_slope, raw=True).rename("lin_slope")


def hurst(close: pd.Series, n: int = 64) -> pd.Series:
    """Hurst exponent (R/S analysis) over a rolling window.

    H > 0.5 → trending (persistent); H ≈ 0.5 → random walk; H < 0.5 → mean-reverting.

    For each lag size the window is divided into non-overlapping sub-windows of
    that size; R/S is averaged across sub-windows before taking log, giving a
    more robust slope estimate than single-sub-window R/S.

    .. warning::
        This function is slow (O(n · window) per call).
        Always use it inside a ``@cached`` FeatureBuilder.
    """
    log_ret = np.log(close / close.shift(1))

    def _rs_hurst(window: np.ndarray) -> float:
        if np.isnan(window).any():
            return np.nan
        lags, log_rs_means = [], []
        for lag in [4, 8, 16, 32]:
            n_sub = len(window) // lag
            if n_sub < 2:
                break
            rs_subs = []
            for k in range(n_sub):
                sub = window[k * lag : (k + 1) * lag]
                m = sub.mean()
                cumdev = np.cumsum(sub - m)
                R = cumdev.max() - cumdev.min()
                S = sub.std(ddof=0)
                if S < 1e-12:
                    continue
                rs_subs.append(R / S)
            if not rs_subs:
                continue
            lags.append(np.log(lag))
            log_rs_means.append(np.log(np.mean(rs_subs)))
        if len(lags) < 2:
            return np.nan
        slope, _ = np.polyfit(lags, log_rs_means, 1)
        return float(np.clip(slope, 0.0, 1.0))

    return log_ret.rolling(n, min_periods=n).apply(_rs_hurst, raw=True).rename("hurst")


# ---------------------------------------------------------------------------
# Volume primitives
# ---------------------------------------------------------------------------

def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume: cumulative signed volume.

    Positive volume is added when close > prev close; subtracted otherwise.
    """
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum().rename("obv")


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-Weighted Average Price with a daily reset at midnight UTC.

    For intraday bars this is the true running VWAP; for daily bars it
    degenerates to the typical price (H+L+C)/3 (volume cancels out).
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    dates = df.index.normalize()
    tp_vol = tp * df["volume"]
    result = tp_vol.groupby(dates).cumsum() / df["volume"].groupby(dates).cumsum()
    return result.rename("vwap")


# ---------------------------------------------------------------------------
# Cross-series
# ---------------------------------------------------------------------------

def relative_strength(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    """RS of series a vs benchmark b over n bars.

    ``RS = a.pct_change(n) / b.pct_change(n)``

    Values > 1 mean a outperformed b over the period; < 1 means underperformed.
    Returns NaN where b's return is zero.
    """
    b_ret = b.pct_change(n).replace(0, np.nan)
    return (a.pct_change(n) / b_ret).rename("rs")
