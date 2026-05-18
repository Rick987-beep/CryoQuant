"""Pine v5 -faithful technical indicator library.

Conventions, mirrored from Pine v5:

- All inputs/outputs are pandas Series aligned to bar close timestamps.
- Warmup: indicators that need n bars return NaN for the first n-1 (or seeded)
  bars. We seed `ema` and `rma` from the first SMA(n) value, exactly like Pine.
- `ema` uses alpha = 2/(n+1).
- `rma` (Wilder smoothing) uses alpha = 1/n. This is what Pine `ta.rma` does
  and what `ta.atr` / `ta.adx` are built on.
- `tr`, `atr`, `adx`, `+di`, `-di` follow Wilder (1978).
- `hma` = `wma(2*wma(n/2) - wma(n), sqrt(n))`, integer rounding.
- `linreg` returns the value on the regression line at the *last* bar of the
  window (matches Pine `ta.linreg(src, n, 0)`).
- `highest`/`lowest` are inclusive of the current bar (Pine semantics).
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _seeded_recursive_ma(s: pd.Series, n: int, alpha: float) -> pd.Series:
    """Pine-faithful seeded recursive MA.

    Pine v5's ta.ema / ta.rma seed at index n-1 over the bars [0, n-1]. NaN
    inputs in that seed window are treated as zero (Pine's `na` propagates as
    0 inside the recursive sum). After seeding, NaN inputs hold the previous
    value. This matches PineTS for both clean inputs (e.g. close) and inputs
    with leading NaN (e.g. plusDM where `ta.change` is `na` on bar 0).
    """
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
        if np.isnan(x):
            out[i] = prev
        else:
            out[i] = alpha * x + (1 - alpha) * prev
    return pd.Series(out, index=s.index)


def ema(s: pd.Series, n: int) -> pd.Series:
    """Pine v5 `ta.ema`: SMA-seeded EMA, alpha = 2/(n+1)."""
    return _seeded_recursive_ma(s, n, 2.0 / (n + 1.0))


def rma(s: pd.Series, n: int) -> pd.Series:
    """Pine v5 `ta.rma` / Wilder smoothing: SMA-seeded, alpha = 1/n."""
    return _seeded_recursive_ma(s, n, 1.0 / n)


def wma(s: pd.Series, n: int) -> pd.Series:
    """Pine v5 `ta.wma`: linearly weighted MA, weights 1..n."""
    weights = np.arange(1, n + 1, dtype=float)
    denom = weights.sum()
    return s.rolling(n, min_periods=n).apply(
        lambda x: np.dot(x, weights) / denom, raw=True
    )


def _round_half_up(x: float) -> int:
    """Pine's math.round: half away from zero (not banker's rounding)."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def hma(s: pd.Series, n: int) -> pd.Series:
    """Pine v5 `ta.hma`: `wma(2*wma(src, n//2) - wma(src, n), floor(sqrt(n)))`.

    Note: Pine uses integer division for `n/2` (since `n` is int) and
    `math.floor(math.sqrt(n))` for the outer length. Empirically verified
    against `ta.hma` via PineTS.
    """
    n_half = n // 2
    n_sqrt = int(math.floor(math.sqrt(n)))
    return wma(2 * wma(s, n_half) - wma(s, n), n_sqrt)


# ---------------------------------------------------------------------------
# Range / volatility
# ---------------------------------------------------------------------------

def tr(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Pine v5 `ta.tr`: max(h-l, |h-prevc|, |l-prevc|). First bar = h-l."""
    prev_close = close.shift(1)
    a = high - low
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    out = pd.concat([a, b, c], axis=1).max(axis=1)
    # Pine: on the first bar, prevc is NaN, so b and c are NaN; tr = h-l.
    out.iloc[0] = (high.iloc[0] - low.iloc[0])
    return out


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Pine v5 `ta.atr`: rma(tr, n)."""
    return rma(tr(high, low, close), n)


# ---------------------------------------------------------------------------
# ADX / DMI
# ---------------------------------------------------------------------------

def dmi(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.DataFrame:
    """Pine v5 `ta.dmi(n, n)` returns +DI, -DI, ADX. Wilder method.

    +DM_t = up if up > down and up > 0 else 0,   up   = high_t - high_{t-1}
    -DM_t = dn if dn > up   and dn > 0 else 0,   down = low_{t-1} - low_t
    +DI = 100 * rma(+DM, n) / rma(tr, n)
    -DI = 100 * rma(-DM, n) / rma(tr, n)
    DX  = 100 * |+DI - -DI| / (+DI + -DI)
    ADX = rma(DX, n)
    """
    up = high.diff()
    down = -low.diff()
    # Pine v5 ta.dmi: plusDM/minusDM are `na` on bar 0 (because ta.change is na),
    # so ta.rma waits one extra bar before seeding.
    up_arr = up.to_numpy(dtype=float)
    down_arr = down.to_numpy(dtype=float)
    plus_arr = np.where((up_arr > down_arr) & (up_arr > 0), up_arr, 0.0)
    minus_arr = np.where((down_arr > up_arr) & (down_arr > 0), down_arr, 0.0)
    nan_mask = np.isnan(up_arr) | np.isnan(down_arr)
    plus_arr[nan_mask] = np.nan
    minus_arr[nan_mask] = np.nan
    plus_dm = pd.Series(plus_arr, index=high.index)
    minus_dm = pd.Series(minus_arr, index=high.index)
    tr_ = tr(high, low, close)
    atr_ = rma(tr_, n)
    plus_di = 100.0 * rma(plus_dm, n) / atr_
    minus_di = 100.0 * rma(minus_dm, n) / atr_
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_ = rma(dx, n)
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": adx_})


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return dmi(high, low, close, n)["adx"]


# ---------------------------------------------------------------------------
# Range/highest/lowest
# ---------------------------------------------------------------------------

def highest(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).max()


def lowest(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).min()


def donchian(high: pd.Series, low: pd.Series, n: int = 20) -> pd.DataFrame:
    upper = highest(high, n)
    lower = lowest(low, n)
    mid = (upper + lower) / 2.0
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower})


def opening_range(
    high: pd.Series, low: pd.Series, n: int,
) -> pd.DataFrame:
    """Prior-N-bar consolidation range, *excluding* the current bar.

    Returns a DataFrame with columns:
        or_high : max(high) over the prior n bars (shifted by 1)
        or_low  : min(low)  over the prior n bars (shifted by 1)

    Use as a closed-bar-safe ORB reference: a breakout test on bar t looks
    at OR built from bars [t-n, t-1]. Warmup (first n+1 bars) is NaN.
    """
    return pd.DataFrame({
        "or_high": highest(high, n).shift(1),
        "or_low":  lowest(low,  n).shift(1),
    })


# ---------------------------------------------------------------------------
# Linear regression
# ---------------------------------------------------------------------------

def linreg(s: pd.Series, n: int, offset: int = 0) -> pd.Series:
    """Pine v5 `ta.linreg(src, n, offset)`: value of the OLS line at index
    (n-1-offset) inside the rolling window. offset=0 => last bar of window.
    """
    arr = s.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    target_x = float(n - 1 - offset)
    for i in range(n - 1, len(arr)):
        y = arr[i - n + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        slope = ((x - x_mean) * (y - y_mean)).sum() / x_var
        intercept = y_mean - slope * x_mean
        out[i] = intercept + slope * target_x
    return pd.Series(out, index=s.index)


def linreg_slope(s: pd.Series, n: int) -> pd.Series:
    """OLS slope per bar over the trailing n bars. Not in Pine but trivially
    expressible there as `ta.linreg(src, n, 0) - ta.linreg(src, n, 1)`."""
    arr = s.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    for i in range(n - 1, len(arr)):
        y = arr[i - n + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        out[i] = ((x - x_mean) * (y - y_mean)).sum() / x_var
    return pd.Series(out, index=s.index)


# ---------------------------------------------------------------------------
# Choppiness Index, Efficiency Ratio
# ---------------------------------------------------------------------------

def choppiness(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Choppiness Index (Bliau).

    CI = 100 * log10( sum(tr, n) / (highest(high, n) - lowest(low, n)) ) / log10(n)
    Range bound 0..100. >~61.8 => choppy/range; <~38.2 => trending.
    """
    tr_ = tr(high, low, close)
    sum_tr = tr_.rolling(n, min_periods=n).sum()
    rng = highest(high, n) - lowest(low, n)
    safe_rng = rng.replace(0, np.nan)
    return 100.0 * np.log10(sum_tr / safe_rng) / math.log10(n)


def efficiency_ratio(close: pd.Series, n: int = 10) -> pd.Series:
    """Kaufman's Efficiency Ratio.

    ER = |close - close[n]| / sum(|close - close[1]|, n)
    Range 0..1. 0 = pure noise, 1 = pure straight-line trend.
    """
    change = (close - close.shift(n)).abs()
    volatility = close.diff().abs().rolling(n, min_periods=n).sum()
    return change / volatility.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Bollinger bands + width percentile
# ---------------------------------------------------------------------------

def bb(src: pd.Series, n: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """Pine v5 `ta.bb(src, n, mult)` (basis=SMA, dev=ta.stdev population).

    Pine's `ta.stdev` uses population stddev (divide by n, not n-1). pandas
    rolling().std() defaults to ddof=1 (sample); we pass ddof=0 for parity.
    """
    basis = sma(src, n)
    dev = src.rolling(n, min_periods=n).std(ddof=0) * mult
    return pd.DataFrame({"upper": basis + dev, "basis": basis, "lower": basis - dev})


def bbw(src: pd.Series, n: int = 20, mult: float = 2.0) -> pd.Series:
    """Pine `ta.bbw`: 100 * (upper - lower) / basis (percentage)."""
    bands = bb(src, n, mult)
    return 100.0 * (bands["upper"] - bands["lower"]) / bands["basis"].replace(0, np.nan)


def bbw_pct(src: pd.Series, n: int = 20, mult: float = 2.0, lookback: int = 252) -> pd.Series:
    """Trailing percentile rank of BBW.

    For each bar, the rank of BBW[i] within the trailing `lookback` BBWs,
    expressed as a fraction in [0, 1]. Low = squeeze; high = expansion.
    Useful as a regime gate: "only enter when BBW just broke above the 20th
    percentile" = squeeze release.
    """
    width = bbw(src, n, mult)
    return width.rolling(lookback, min_periods=lookback // 2).rank(pct=True)


# ---------------------------------------------------------------------------
# Supertrend (Pine v5 faithful)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """Pine v5 `ta.rsi(src, n)`: Wilder RSI using rma.

    gain = max(close - close[1], 0)
    loss = max(close[1] - close, 0)
    rsi  = 100 - 100 / (1 + rma(gain, n) / rma(loss, n))

    Returns values in [0, 100]. NaN during warmup (first n bars).
    """
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = rma(gain, n)
    avg_loss = rma(loss, n)
    # Edge cases matching Pine: if avg_loss == 0, RSI = 100 (all gains, no losses);
    # if both are 0 (flat price), RSI is NaN.
    gain_arr = avg_gain.to_numpy(dtype=float)
    loss_arr = avg_loss.to_numpy(dtype=float)
    out = np.where(
        np.isnan(gain_arr) | np.isnan(loss_arr),
        np.nan,
        np.where(
            loss_arr == 0.0,
            np.where(gain_arr == 0.0, np.nan, 100.0),
            100.0 - 100.0 / (1.0 + gain_arr / loss_arr),
        ),
    )
    return pd.Series(out, index=s.index)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def macd(
    s: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_n: int = 9,
) -> pd.DataFrame:
    """Pine v5 `ta.macd(src, fast, slow, signal_n)`.

    macd_line   = EMA(src, fast) - EMA(src, slow)
    signal_line = EMA(macd_line, signal_n)
    histogram   = macd_line - signal_line

    All three are returned as columns: macd, signal, hist.
    Warmup NaN for the first max(slow, slow + signal_n - 1) bars.
    """
    fast_ema = ema(s, fast)
    slow_ema = ema(s, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal_n)
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": histogram}
    )


# ---------------------------------------------------------------------------
# Linear regression R²
# ---------------------------------------------------------------------------

def linreg_r2(s: pd.Series, n: int) -> pd.Series:
    """OLS coefficient of determination (R²) over a trailing n-bar window.

    R² = 1 - SS_res / SS_tot, where both are computed on the price series
    vs. the linear fit over bars [i-n+1, i]. Returns values in [0, 1]:
      ~0 = no linear structure (choppy/random)
      ~1 = near-perfect straight line (strong trend)

    Not in Pine's standard library but expressible as:
        ta.linreg(src, n, 0) vs raw values. We compute it directly.
    NaN for the first n-1 bars (same warmup as linreg).
    """
    arr = s.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    for i in range(n - 1, len(arr)):
        y = arr[i - n + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        slope = ((x - x_mean) * (y - y_mean)).sum() / x_var
        intercept = y_mean - slope * x_mean
        y_hat = intercept + slope * x
        ss_res = ((y - y_hat) ** 2).sum()
        ss_tot = ((y - y_mean) ** 2).sum()
        if ss_tot == 0.0:
            out[i] = 1.0
        else:
            out[i] = 1.0 - ss_res / ss_tot
    return pd.Series(out, index=s.index)


# ---------------------------------------------------------------------------
# KAMA — Kaufman Adaptive Moving Average
# ---------------------------------------------------------------------------

def kama(s: pd.Series, n: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Adaptive Moving Average (KAMA).

    Built on the Efficiency Ratio (ER = |net n-bar move| / sum of |bar moves|):
        fast_alpha = 2 / (fast + 1)
        slow_alpha = 2 / (slow + 1)
        sc = (ER * (fast_alpha - slow_alpha) + slow_alpha) ** 2
        kama[i] = kama[i-1] + sc * (close[i] - kama[i-1])

    ER is already in ta.efficiency_ratio(). KAMA naturally slows to near-flat
    in chop (ER → 0 → sc → slow_alpha²) and speeds up in trends (ER → 1 →
    sc → fast_alpha²). This makes the *slope* of KAMA a joint direction+regime
    signal.

    Seeded at bar n (the first valid ER bar) with the close value.
    NaN before bar n.
    """
    er = efficiency_ratio(s, n)
    fast_a = 2.0 / (fast + 1.0)
    slow_a = 2.0 / (slow + 1.0)

    arr = s.to_numpy(dtype=float)
    er_arr = er.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)

    # seed on the first non-NaN ER bar
    seed_i = None
    for i in range(len(arr)):
        if not np.isnan(er_arr[i]):
            seed_i = i
            break
    if seed_i is None:
        return pd.Series(out, index=s.index)

    out[seed_i] = arr[seed_i]
    for i in range(seed_i + 1, len(arr)):
        sc = (er_arr[i] * (fast_a - slow_a) + slow_a) ** 2
        out[i] = out[i - 1] + sc * (arr[i] - out[i - 1])

    return pd.Series(out, index=s.index)


# ---------------------------------------------------------------------------
# ATR percentile
# ---------------------------------------------------------------------------

def atr_percentile(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    atr_n: int = 14,
    lookback: int = 252,
) -> pd.Series:
    """Rolling percentile rank of ATR within its own trailing history.

    Returns values in [0, 1]:
      ~0 = current ATR is very low relative to the lookback (low vol / squeeze)
      ~1 = current ATR is very high (high vol / expansion)

    Same pattern as bbw_pct but normalises ATR instead of BB width.
    Useful as a volatility regime gate: require atr_percentile > threshold
    to avoid dead-vol false trends.
    """
    atr_v = atr(high, low, close, atr_n)
    return atr_v.rolling(lookback, min_periods=lookback // 2).rank(pct=True)


# ---------------------------------------------------------------------------
# Donchian breakout state
# ---------------------------------------------------------------------------

def donchian_breakout(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 20,
) -> pd.Series:
    """Donchian channel breakout state.

    Compares the current close against the *prior* n-bar high/low (shifted
    by 1 bar so the current bar is excluded — closed-bar safe, no lookahead).

    Returns an int8 Series:
        +1 : close > prior n-bar high  (upside breakout)
        -1 : close < prior n-bar low   (downside breakout)
         0 : inside the channel        (no breakout)

    NaN during warmup (first n+1 bars).

    This is the Turtle-system entry primitive. When used as a direction filter
    rather than a trade signal, the breakout state tells you "price just left
    the n-bar range" — a clean regime-change trigger.
    """
    prior_high = highest(high, n).shift(1)
    prior_low = lowest(low, n).shift(1)
    state = np.where(
        prior_high.isna() | prior_low.isna(),
        np.nan,
        np.where(
            close > prior_high, 1,
            np.where(close < prior_low, -1, 0),
        ),
    )
    return pd.Series(state, index=close.index, dtype="float64")


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    factor: float = 3.0,
    atr_len: int = 10,
) -> pd.DataFrame:
    """Pine v5 `ta.supertrend(factor, atr_len)` returning (supertrend, direction).

    Algorithm (matches Pine's reference implementation exactly):
        src = (high + low) / 2
        atr_v = ta.atr(atr_len)
        up = src - factor*atr_v;   dn = src + factor*atr_v
        up := close[1] > up[1] ? max(up, up[1]) : up
        dn := close[1] < dn[1] ? min(dn, dn[1]) : dn
        dir starts at -1; flips to 1 when close > dn[1], to -1 when close < up[1].
        st = dir==-1 ? dn : up

    direction: -1 means long-trend (ST below price), +1 means short-trend
    (ST above price). NOTE: this is Pine's convention — it's inverted from the
    intuitive sign. We expose two columns:
        st         — the supertrend line (price)
        direction  — Pine convention (-1 = uptrend, +1 = downtrend)
        trend      — natural convention (+1 = uptrend, -1 = downtrend),
                     which is what trend candidates consume.
    """
    src = (high + low) / 2.0
    atr_v = atr(high, low, close, atr_len)
    up_basic = src - factor * atr_v
    dn_basic = src + factor * atr_v

    n = len(close)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    st = np.full(n, np.nan)

    close_arr = close.to_numpy(dtype=float)
    up_b = up_basic.to_numpy(dtype=float)
    dn_b = dn_basic.to_numpy(dtype=float)

    started = False
    for i in range(n):
        if np.isnan(atr_v.iat[i]):
            continue
        if not started:
            up[i] = up_b[i]
            dn[i] = dn_b[i]
            # Pine seeds direction=+1 (downtrend) on the first ATR bar:
            #   trend = na(trend[1]) ? 1 : ...
            direction[i] = 1
            st[i] = dn[i] if direction[i] == 1 else up[i]
            started = True
            continue
        prev_close = close_arr[i - 1]
        up[i] = max(up_b[i], up[i - 1]) if prev_close > up[i - 1] else up_b[i]
        dn[i] = min(dn_b[i], dn[i - 1]) if prev_close < dn[i - 1] else dn_b[i]
        prev_dir = direction[i - 1]
        if prev_dir == -1 and close_arr[i] < up[i - 1]:
            direction[i] = 1
        elif prev_dir == 1 and close_arr[i] > dn[i - 1]:
            direction[i] = -1
        else:
            direction[i] = prev_dir
        st[i] = dn[i] if direction[i] == 1 else up[i]

    return pd.DataFrame(
        {
            "st": pd.Series(st, index=close.index),
            "direction": pd.Series(direction, index=close.index),
            "trend": pd.Series(-direction, index=close.index),
        }
    )
