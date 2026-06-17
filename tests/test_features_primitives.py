"""Unit tests for Phase 2 feature primitives.

Covers: donchian, adx, keltner, supertrend, macd, roc,
        linear_reg_slope, hurst, obv, vwap, relative_strength.

All tests use synthetic data only — no network access.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_trending(n: int = 100, slope: float = 1.0, start: float = 100.0) -> pd.DataFrame:
    """Monotone rising OHLCV series."""
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    close = pd.Series(start + slope * np.arange(n), index=idx)
    spread = 0.5
    return pd.DataFrame({
        "open":   close,
        "high":   close + spread,
        "low":    close - spread,
        "close":  close,
        "volume": pd.Series(1000.0, index=idx),
    }, index=idx)


def _make_flat(n: int = 60, price: float = 100.0) -> pd.DataFrame:
    """Flat price series (zero volatility)."""
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    s = pd.Series(price, index=idx)
    return pd.DataFrame({
        "open": s, "high": s + 0.01, "low": s - 0.01,
        "close": s, "volume": pd.Series(1000.0, index=idx),
    }, index=idx)


def _make_bearish(n: int = 100, slope: float = 1.0, start: float = 200.0) -> pd.DataFrame:
    """Monotone falling OHLCV series."""
    return _make_trending(n=n, slope=-slope, start=start)


# ===========================================================================
# donchian
# ===========================================================================

class TestDonchian:
    def test_output_columns(self):
        from cryoquant.features.primitives import donchian
        df = make_ohlcv(n=60)
        result = donchian(df["close"], 20)
        assert set(result.columns) == {"upper", "lower", "mid"}

    def test_upper_ge_lower(self):
        from cryoquant.features.primitives import donchian
        df = make_ohlcv(n=60)
        result = donchian(df["close"], 20).dropna()
        assert (result["upper"] >= result["lower"]).all()

    def test_mid_is_midpoint(self):
        from cryoquant.features.primitives import donchian
        df = make_ohlcv(n=60)
        result = donchian(df["close"], 20).dropna()
        expected_mid = (result["upper"] + result["lower"]) / 2
        pd.testing.assert_series_equal(result["mid"], expected_mid, check_names=False)

    def test_no_lookahead(self):
        """donchian[T] must be unchanged after appending future bars."""
        from cryoquant.features.primitives import donchian
        df = _make_trending(n=80)
        mid = 50
        full = donchian(df["close"], 20)
        cut = donchian(df["close"].iloc[:mid], 20)
        pd.testing.assert_series_equal(
            full["upper"].iloc[:mid].rename(None),
            cut["upper"].rename(None),
            rtol=1e-9, check_names=False,
        )

    def test_upper_is_prior_n_bar_high(self):
        """On a monotone series, upper at bar T equals close at bar T-1."""
        from cryoquant.features.primitives import donchian
        df = _make_trending(n=60)
        result = donchian(df["close"], 1)
        # n=1 channel: upper = shift(1).rolling(1).max() = previous close
        valid = result["upper"].dropna()
        expected = df["close"].shift(1).dropna()
        pd.testing.assert_series_equal(valid, expected.iloc[-len(valid):], check_names=False)

    def test_nan_before_warmup(self):
        from cryoquant.features.primitives import donchian
        df = make_ohlcv(n=60)
        result = donchian(df["close"], 20)
        # First (n+1) bars are NaN (shift + rolling)
        assert result["upper"].iloc[:20].isna().all()
        assert result["upper"].iloc[20:].notna().all()


# ===========================================================================
# adx
# ===========================================================================

class TestAdx:
    def test_range_0_to_100(self):
        from cryoquant.features.primitives import adx
        df = make_ohlcv(n=200)
        result = adx(df, 14).dropna()
        assert (result >= 0).all() and (result <= 100).all()

    def test_no_nan_after_warmup(self):
        from cryoquant.features.primitives import adx
        df = make_ohlcv(n=200)
        result = adx(df, 14)
        # ADX needs 2×n bars to warm up (smoothed DM then smoothed DX)
        assert result.iloc[28:].notna().all()

    def test_trending_higher_than_flat(self):
        """Trending series should produce a higher ADX than a flat series."""
        from cryoquant.features.primitives import adx
        trend_df = _make_trending(n=200)
        flat_df = _make_flat(n=200)
        adx_trend = adx(trend_df, 14).dropna().mean()
        adx_flat = adx(flat_df, 14).dropna().mean()
        assert adx_trend > adx_flat


# ===========================================================================
# keltner
# ===========================================================================

class TestKeltner:
    def test_output_columns(self):
        from cryoquant.features.primitives import keltner
        df = make_ohlcv(n=60)
        result = keltner(df, 20, 1.5)
        assert set(result.columns) == {"upper", "lower"}

    def test_upper_gt_lower(self):
        from cryoquant.features.primitives import keltner
        df = make_ohlcv(n=60)
        result = keltner(df, 20, 1.5).dropna()
        assert (result["upper"] > result["lower"]).all()

    def test_close_often_inside_channel(self):
        """For a low-volatility series, close should stay inside the channel."""
        from cryoquant.features.primitives import keltner
        df = _make_flat(n=100)
        ch = keltner(df, 20, 2.0).dropna()
        close = df["close"].loc[ch.index]
        inside = (close >= ch["lower"]) & (close <= ch["upper"])
        assert inside.mean() > 0.9


# ===========================================================================
# supertrend
# ===========================================================================

class TestSupertrend:
    def test_output_columns(self):
        from cryoquant.features.primitives import supertrend
        df = make_ohlcv(n=100)
        result = supertrend(df, 10, 3.0)
        assert set(result.columns) == {"value", "direction"}

    def test_direction_values(self):
        """Direction must be +1 or -1 (no other values) after warmup."""
        from cryoquant.features.primitives import supertrend
        df = make_ohlcv(n=100)
        result = supertrend(df, 10, 3.0)
        dirs = result["direction"].dropna()
        assert set(dirs.unique()).issubset({1.0, -1.0})

    def test_bullish_on_sustained_uptrend(self):
        """Strong uptrend → final direction should be bullish (+1)."""
        from cryoquant.features.primitives import supertrend
        df = _make_trending(n=200, slope=2.0)
        result = supertrend(df, 10, 3.0)
        last = result["direction"].dropna().iloc[-1]
        assert last == 1.0

    def test_bearish_on_sustained_downtrend(self):
        """Strong downtrend → final direction should be bearish (−1)."""
        from cryoquant.features.primitives import supertrend
        df = _make_bearish(n=200, slope=2.0)
        result = supertrend(df, 10, 3.0)
        last = result["direction"].dropna().iloc[-1]
        assert last == -1.0

    def test_flip_on_trend_reversal(self):
        """Trend flip: 100 up bars then 100 down bars → direction changes."""
        from cryoquant.features.primitives import supertrend
        df_up = _make_trending(n=100, slope=2.0)
        df_dn = _make_bearish(n=100, slope=2.0, start=float(df_up["close"].iloc[-1]))
        df_dn.index = pd.date_range(
            df_up.index[-1] + pd.Timedelta("1D"), periods=100, freq="D", tz="UTC"
        )
        df = pd.concat([df_up, df_dn])
        result = supertrend(df, 10, 3.0)["direction"].dropna()
        # Should have at least one +1 and one -1
        assert 1.0 in result.values and -1.0 in result.values


# ===========================================================================
# macd
# ===========================================================================

class TestMacd:
    def test_output_columns(self):
        from cryoquant.features.primitives import macd
        df = make_ohlcv(n=100)
        result = macd(df["close"])
        assert set(result.columns) == {"macd", "signal", "hist"}

    def test_hist_equals_macd_minus_signal(self):
        from cryoquant.features.primitives import macd
        df = make_ohlcv(n=100)
        result = macd(df["close"]).dropna()
        expected = result["macd"] - result["signal"]
        pd.testing.assert_series_equal(result["hist"], expected, check_names=False, rtol=1e-10)

    def test_positive_hist_on_uptrend(self):
        """On a sustained uptrend the fast EMA > slow EMA → positive histogram."""
        from cryoquant.features.primitives import macd
        df = _make_trending(n=200, slope=1.0)
        result = macd(df["close"]).dropna()
        # After initial warmup (slow EMA needs 26 bars, signal 9 more)
        assert result["hist"].iloc[-50:].mean() > 0


# ===========================================================================
# roc
# ===========================================================================

class TestRoc:
    def test_zero_on_flat(self):
        from cryoquant.features.primitives import roc
        s = pd.Series(100.0, index=pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC"))
        result = roc(s, 10).dropna()
        assert (result.abs() < 1e-10).all()

    def test_positive_on_uptrend(self):
        from cryoquant.features.primitives import roc
        s = pd.Series(np.arange(1, 51, dtype=float),
                      index=pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC"))
        result = roc(s, 5).dropna()
        assert (result > 0).all()

    def test_magnitude(self):
        """roc(s, 1) should equal single-bar return."""
        from cryoquant.features.primitives import roc
        s = pd.Series([100.0, 110.0, 99.0, 110.0],
                      index=pd.date_range("2020-01-01", periods=4, freq="D", tz="UTC"))
        result = roc(s, 1).dropna()
        expected = pd.Series([0.1, -0.1, 11/99],
                              index=s.index[1:])
        pd.testing.assert_series_equal(result, expected, check_names=False, rtol=1e-9)


# ===========================================================================
# linear_reg_slope
# ===========================================================================

class TestLinearRegSlope:
    def test_positive_on_uptrend(self):
        from cryoquant.features.primitives import linear_reg_slope
        s = pd.Series(np.arange(1, 101, dtype=float),
                      index=pd.date_range("2020-01-01", periods=100, freq="D", tz="UTC"))
        result = linear_reg_slope(s, 20).dropna()
        assert (result > 0).all()

    def test_negative_on_downtrend(self):
        from cryoquant.features.primitives import linear_reg_slope
        s = pd.Series(np.arange(100, 0, -1, dtype=float),
                      index=pd.date_range("2020-01-01", periods=100, freq="D", tz="UTC"))
        result = linear_reg_slope(s, 20).dropna()
        assert (result < 0).all()

    def test_zero_on_flat(self):
        from cryoquant.features.primitives import linear_reg_slope
        s = pd.Series(50.0, index=pd.date_range("2020-01-01", periods=60, freq="D", tz="UTC"))
        result = linear_reg_slope(s, 20).dropna()
        assert (result.abs() < 1e-9).all()

    def test_slope_value(self):
        """Slope of y=x should equal 1.0."""
        from cryoquant.features.primitives import linear_reg_slope
        s = pd.Series(np.arange(0, 40, dtype=float),
                      index=pd.date_range("2020-01-01", periods=40, freq="D", tz="UTC"))
        result = linear_reg_slope(s, 10).dropna()
        assert np.allclose(result.values, 1.0, atol=1e-9)

    def test_no_lookahead(self):
        from cryoquant.features.primitives import linear_reg_slope
        s = pd.Series(np.random.default_rng(7).standard_normal(100).cumsum() + 100,
                      index=pd.date_range("2020-01-01", periods=100, freq="D", tz="UTC"))
        mid = 60
        full = linear_reg_slope(s, 20)
        cut = linear_reg_slope(s.iloc[:mid], 20)
        pd.testing.assert_series_equal(
            full.iloc[:mid].rename(None), cut.rename(None),
            rtol=1e-9, check_names=False,
        )


# ===========================================================================
# hurst
# ===========================================================================

@pytest.mark.slow
class TestHurst:
    def test_range_0_to_1(self):
        from cryoquant.features.primitives import hurst
        df = make_ohlcv(n=200)
        result = hurst(df["close"], n=64).dropna()
        assert (result >= 0).all() and (result <= 1).all()

    def test_trending_ar1_above_half(self):
        """AR(1) with strong positive autocorrelation → H > 0.5 (persistent)."""
        from cryoquant.features.primitives import hurst
        rng = np.random.default_rng(42)
        n = 300
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        # AR(1) with phi=0.85: each return ~ 0.85 * prev_return + noise → trending
        noise = rng.normal(0, 1, n)
        returns = np.zeros(n)
        for i in range(1, n):
            returns[i] = 0.85 * returns[i - 1] + 0.15 * noise[i]
        s = pd.Series(100 + np.cumsum(returns), index=idx)
        result = hurst(s, n=64).dropna()
        assert result.mean() > 0.5, f"Expected H > 0.5 for persistent AR(1), got {result.mean():.3f}"

    def test_mean_reverting_ar1_below_half(self):
        """AR(1) with strong negative autocorrelation → H < 0.5 (anti-persistent)."""
        from cryoquant.features.primitives import hurst
        rng = np.random.default_rng(7)
        n = 300
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        # AR(1) with phi=-0.85: each return flips sign → mean-reverting
        noise = rng.normal(0, 1, n)
        returns = np.zeros(n)
        for i in range(1, n):
            returns[i] = -0.85 * returns[i - 1] + 0.15 * noise[i]
        s = pd.Series(100 + np.cumsum(returns), index=idx)
        result = hurst(s, n=64).dropna()
        assert result.mean() < 0.5, f"Expected H < 0.5 for anti-persistent AR(1), got {result.mean():.3f}"

    def test_no_nan_after_warmup(self):
        from cryoquant.features.primitives import hurst
        df = make_ohlcv(n=200)
        result = hurst(df["close"], n=64)
        assert result.iloc[64:].notna().all()


# ===========================================================================
# obv
# ===========================================================================

class TestObv:
    def test_monotone_increasing_when_always_up(self):
        from cryoquant.features.primitives import obv
        n = 50
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        close = pd.Series(100 + np.arange(n, dtype=float), index=idx)
        vol = pd.Series(1000.0, index=idx)
        result = obv(close, vol)
        diffs = result.diff().dropna()
        assert (diffs > 0).all()

    def test_monotone_decreasing_when_always_down(self):
        from cryoquant.features.primitives import obv
        n = 50
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        close = pd.Series(200 - np.arange(n, dtype=float), index=idx)
        vol = pd.Series(1000.0, index=idx)
        result = obv(close, vol)
        diffs = result.diff().dropna()
        assert (diffs < 0).all()

    def test_flat_price_no_change(self):
        from cryoquant.features.primitives import obv
        n = 50
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        close = pd.Series(100.0, index=idx)
        vol = pd.Series(1000.0, index=idx)
        result = obv(close, vol)
        # diff == 0 since close.diff() == 0 everywhere
        assert (result.diff().dropna().abs() < 1e-10).all()


# ===========================================================================
# vwap
# ===========================================================================

class TestVwap:
    def test_daily_bars_returns_typical_price(self):
        """For daily bars (one bar per day) VWAP = (H+L+C)/3."""
        from cryoquant.features.primitives import vwap
        df = make_ohlcv(n=30, freq="D")
        result = vwap(df)
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        pd.testing.assert_series_equal(result, tp.rename("vwap"), rtol=1e-9)

    def test_intraday_resets_each_day(self):
        """First bar of each day should equal its own typical price."""
        from cryoquant.features.primitives import vwap
        df = make_ohlcv(n=48, freq="1h")   # 2 days × 24h
        result = vwap(df)
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        # First bar of each day: cumulative vol = bar vol → vwap = tp
        first_bars = df.groupby(df.index.normalize()).head(1).index
        for ts in first_bars:
            assert abs(result[ts] - tp[ts]) < 1e-9

    def test_no_nan(self):
        from cryoquant.features.primitives import vwap
        df = make_ohlcv(n=60)
        assert vwap(df).notna().all()


# ===========================================================================
# relative_strength
# ===========================================================================

class TestRelativeStrength:
    def test_outperformer_gt_one(self):
        from cryoquant.features.primitives import relative_strength
        idx = pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC")
        a = pd.Series(100 + np.arange(50, dtype=float) * 2, index=idx)   # +2/day
        b = pd.Series(100 + np.arange(50, dtype=float) * 1, index=idx)   # +1/day
        result = relative_strength(a, b, 10).dropna()
        assert (result > 1).all()

    def test_underperformer_lt_one(self):
        from cryoquant.features.primitives import relative_strength
        idx = pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC")
        a = pd.Series(100 + np.arange(50, dtype=float) * 1, index=idx)
        b = pd.Series(100 + np.arange(50, dtype=float) * 2, index=idx)
        result = relative_strength(a, b, 10).dropna()
        assert (result < 1).all()

    def test_equal_series_returns_one(self):
        from cryoquant.features.primitives import relative_strength
        idx = pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC")
        s = pd.Series(100 + np.arange(50, dtype=float), index=idx)
        result = relative_strength(s, s, 10).dropna()
        assert np.allclose(result.values, 1.0, atol=1e-9)

    def test_nan_when_benchmark_flat(self):
        """NaN when benchmark return is zero (division by zero guard)."""
        from cryoquant.features.primitives import relative_strength
        idx = pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC")
        a = pd.Series(100 + np.arange(50, dtype=float), index=idx)
        b = pd.Series(100.0, index=idx)   # flat → pct_change = 0
        result = relative_strength(a, b, 5).dropna()
        assert result.isna().all() or len(result) == 0


# ===========================================================================
# resample
# ===========================================================================

class TestResample:
    def _bars_1h(self, n: int = 200) -> pd.DataFrame:
        from cryoquant.features.primitives import resample
        rng = np.random.default_rng(2)
        closes = 100.0 + rng.standard_normal(n).cumsum()
        highs = closes + rng.uniform(0.1, 1.0, n)
        lows = closes - rng.uniform(0.1, 1.0, n)
        idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
        return pd.DataFrame(
            {"open": closes, "high": highs, "low": lows, "close": closes, "volume": 1.0},
            index=idx,
        )

    def test_4h_high_is_max_of_constituent_1h(self) -> None:
        from cryoquant.features.primitives import resample
        bars_1h = self._bars_1h()
        bars_4h = resample(bars_1h, "4h")
        start_1h = bars_1h.index[4]
        end_1h = bars_1h.index[7]
        expected_high = bars_1h.loc[start_1h:end_1h, "high"].max()
        assert bars_4h.iloc[1]["high"] == pytest.approx(expected_high)

    def test_4h_low_is_min_of_constituent_1h(self) -> None:
        from cryoquant.features.primitives import resample
        bars_1h = self._bars_1h()
        bars_4h = resample(bars_1h, "4h")
        start_1h = bars_1h.index[4]
        end_1h = bars_1h.index[7]
        expected_low = bars_1h.loc[start_1h:end_1h, "low"].min()
        assert bars_4h.iloc[1]["low"] == pytest.approx(expected_low)

    def test_4h_bar_count(self) -> None:
        from cryoquant.features.primitives import resample
        idx = pd.date_range("2020-01-01", periods=96, freq="1h", tz="UTC")
        bars_1h = pd.DataFrame(
            {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0},
            index=idx,
        )
        bars_4h = resample(bars_1h, "4h")
        assert len(bars_4h) == 24
