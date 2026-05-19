"""Unit tests for EmaCross signal and DailyEmaCrossFeatures builder."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feature_df(n: int = 30, up_at: int | None = 10, down_at: int | None = 20) -> pd.DataFrame:
    """Synthetic features DataFrame with manual cross flags."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1d", tz="UTC")
    cross_up   = pd.Series(False, index=idx)
    cross_down = pd.Series(False, index=idx)
    if up_at is not None:
        cross_up.iloc[up_at] = True
    if down_at is not None:
        cross_down.iloc[down_at] = True
    close = pd.Series(100.0, index=idx)
    return pd.DataFrame({
        "cross_up":   cross_up,
        "cross_down": cross_down,
        "open":  close,
        "high":  close,
        "low":   close,
        "close": close,
        "volume": pd.Series(1.0, index=idx),
    })


def _make_crossing_ohlcv(n_flat: int = 30, n_high: int = 30) -> pd.DataFrame:
    """Price flat at 100 then jumps to 200 — forces an EMA 7/21 up-cross."""
    flat   = np.full(n_flat, 100.0)
    high   = np.full(n_high, 200.0)
    closes = np.concatenate([flat, high])
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="1d", tz="UTC")
    s = pd.Series(closes, index=idx)
    return pd.DataFrame({
        "open": s, "high": s, "low": s, "close": s,
        "volume": pd.Series(1.0, index=idx),
    })


# ===========================================================================
# DailyEmaCrossFeatures
# ===========================================================================

class TestDailyEmaCrossFeatures:

    def _build(self, df: pd.DataFrame) -> pd.DataFrame:
        from cryoquant.features.builders import DailyEmaCrossFeatures, DatasetRef
        from cryocore.instruments import Symbol
        import cryoquant.features.store as store_mod

        builder = DailyEmaCrossFeatures()
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1d")
        with tempfile.TemporaryDirectory() as td:
            store_mod.config.FEATURE_STORE_DIR = Path(td)
            result = builder.build({ref: df})
        return result

    def test_output_columns(self):
        df = _make_crossing_ohlcv()
        result = self._build(df)
        expected = {"ema_7", "ema_21", "cross_up", "cross_down",
                    "open", "high", "low", "close", "volume"}
        assert expected.issubset(set(result.columns))

    def test_up_cross_detected(self):
        """After a price jump from 100 → 200, an up-cross must fire."""
        df = _make_crossing_ohlcv(n_flat=30, n_high=30)
        result = self._build(df)
        assert result["cross_up"].sum() >= 1, "Expected at least one up-cross"

    def test_down_cross_detected(self):
        """After a price drop from 200 → 100, a down-cross must fire."""
        high_price = np.full(30, 200.0)
        low_price  = np.full(30, 100.0)
        closes = np.concatenate([high_price, low_price])
        idx = pd.date_range("2020-01-01", periods=len(closes), freq="1d", tz="UTC")
        s = pd.Series(closes, index=idx)
        df = pd.DataFrame({"open": s, "high": s, "low": s, "close": s,
                           "volume": pd.Series(1.0, index=idx)})
        result = self._build(df)
        assert result["cross_down"].sum() >= 1, "Expected at least one down-cross"

    def test_no_cross_when_flat(self):
        """Flat price → EMAs are equal → no cross events."""
        n = 60
        idx = pd.date_range("2020-01-01", periods=n, freq="1d", tz="UTC")
        s = pd.Series(100.0, index=idx)
        df = pd.DataFrame({"open": s, "high": s, "low": s, "close": s,
                           "volume": pd.Series(1.0, index=idx)})
        result = self._build(df)
        # After EMA warmup the EMAs are equal so no crossovers
        assert result["cross_up"].fillna(False).sum() == 0
        assert result["cross_down"].fillna(False).sum() == 0

    def test_no_lookahead(self):
        """feature[T] must be unchanged when bars after T are removed."""
        from cryoquant.features.builders import DailyEmaCrossFeatures, DatasetRef
        from cryocore.instruments import Symbol
        import cryoquant.features.store as store_mod

        df = _make_crossing_ohlcv(n_flat=40, n_high=40)
        builder = DailyEmaCrossFeatures()
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1d")
        mid = len(df) // 2

        with tempfile.TemporaryDirectory() as td:
            store_mod.config.FEATURE_STORE_DIR = Path(td)
            out_full = builder.build({ref: df})
            out_cut  = builder.build({ref: df.iloc[:mid]})

        overlap = out_cut.index
        for col in ["ema_7", "ema_21", "cross_up"]:
            pd.testing.assert_series_equal(
                out_full.loc[overlap, col].rename(None),
                out_cut[col].rename(None),
                check_names=False,
                rtol=1e-6,
            )


# ===========================================================================
# EmaCross StateSignal
# ===========================================================================

class TestEmaCross:

    def test_up_cross_fires_plus_one(self):
        from cryoquant.signals.ema_cross import make_ema_cross
        df = _make_feature_df(n=30, up_at=10, down_at=None)
        sig = make_ema_cross()
        states = sig.as_feature(df)
        assert int(states.iloc[10]) == 1
        assert (states == 1).sum() == 1

    def test_down_cross_fires_minus_one(self):
        from cryoquant.signals.ema_cross import make_ema_cross
        df = _make_feature_df(n=30, up_at=None, down_at=15)
        sig = make_ema_cross()
        states = sig.as_feature(df)
        assert int(states.iloc[15]) == -1
        assert (states == -1).sum() == 1

    def test_no_cross_all_zero(self):
        from cryoquant.signals.ema_cross import make_ema_cross
        df = _make_feature_df(n=30, up_at=None, down_at=None)
        sig = make_ema_cross()
        states = sig.as_feature(df)
        assert (states == 0).all()

    def test_both_directions_same_bar(self):
        """If cross_up and cross_down both True on same bar, down wins (last write)."""
        from cryoquant.signals.ema_cross import make_ema_cross
        df = _make_feature_df(n=10, up_at=5, down_at=5)
        sig = make_ema_cross()
        states = sig.as_feature(df)
        assert int(states.iloc[5]) == -1

    def test_dtype_is_int8(self):
        from cryoquant.signals.ema_cross import make_ema_cross
        df = _make_feature_df(n=20, up_at=5, down_at=10)
        sig = make_ema_cross()
        assert sig.as_feature(df).dtype == np.dtype("int8")

    def test_series_name(self):
        from cryoquant.signals.ema_cross import make_ema_cross
        df = _make_feature_df(n=10, up_at=5, down_at=None)
        sig = make_ema_cross()
        assert sig.as_feature(df).name == "ema_cross_7_21_1d"


# ===========================================================================
# EmaCrossLong / EmaCrossShort BoolSignals
# ===========================================================================

class TestEmaCrossBoolSignals:

    def test_long_fires_on_up_cross(self):
        from cryoquant.signals.ema_cross import make_ema_cross_long
        df = _make_feature_df(n=20, up_at=8, down_at=None)
        sig = make_ema_cross_long()
        fires = sig.as_feature(df)
        assert bool(fires.iloc[8]) is True
        assert fires.sum() == 1

    def test_long_does_not_fire_on_down_cross(self):
        from cryoquant.signals.ema_cross import make_ema_cross_long
        df = _make_feature_df(n=20, up_at=None, down_at=8)
        sig = make_ema_cross_long()
        assert sig.as_feature(df).sum() == 0

    def test_short_fires_on_down_cross(self):
        from cryoquant.signals.ema_cross import make_ema_cross_short
        df = _make_feature_df(n=20, up_at=None, down_at=8)
        sig = make_ema_cross_short()
        fires = sig.as_feature(df)
        assert bool(fires.iloc[8]) is True
        assert fires.sum() == 1

    def test_short_does_not_fire_on_up_cross(self):
        from cryoquant.signals.ema_cross import make_ema_cross_short
        df = _make_feature_df(n=20, up_at=8, down_at=None)
        sig = make_ema_cross_short()
        assert sig.as_feature(df).sum() == 0
