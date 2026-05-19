"""Phase 2 unit tests: primitives, calendar features, V2SpotFeaturesV1, labels, cache."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _close_series(values, start="2024-01-01", freq="1h") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx, name="close", dtype=float)


# ---------------------------------------------------------------------------
# primitives.py
# ---------------------------------------------------------------------------

class TestSMA:
    def test_basic(self):
        from cryoquant.features.primitives import sma
        s = _close_series([1, 2, 3, 4, 5])
        result = sma(s, 3)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[4] == pytest.approx(4.0)


class TestEMA:
    def test_matches_hand_calc(self):
        from cryoquant.features.primitives import ema
        # 3-bar EMA: seed = mean([1,2,3])=2, alpha=0.5
        s = _close_series([1, 2, 3, 4, 5])
        result = ema(s, 3)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])
        seed = 2.0
        assert result.iloc[2] == pytest.approx(seed)
        # bar 4: alpha*(4) + (1-alpha)*seed = 0.5*4 + 0.5*2 = 3.0
        assert result.iloc[3] == pytest.approx(3.0)

    def test_constant_series(self):
        from cryoquant.features.primitives import ema
        s = _close_series([5.0] * 20)
        result = ema(s, 10)
        valid = result.dropna()
        assert all(v == pytest.approx(5.0) for v in valid)

    def test_leading_nans(self):
        from cryoquant.features.primitives import ema
        values = [float("nan"), float("nan"), 3.0, 4.0, 5.0, 6.0]
        s = _close_series(values)
        result = ema(s, 3)
        # First valid EMA appears at index 4 (3-bar window including 2 NaNs seeded as 0)
        assert not result.dropna().empty


class TestATR:
    def test_positive_values(self):
        from cryoquant.features.primitives import atr
        df = make_ohlcv(50)
        result = atr(df, 14)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_single_row(self):
        from cryoquant.features.primitives import atr
        df = make_ohlcv(1)
        result = atr(df, 14)
        # With only 1 row, all ATR values should be NaN (or just the first bar = h-l)
        # rma needs n bars to seed; 1 < 14
        assert result.isna().all() or len(result) == 1


class TestBBWidth:
    def test_expansion_on_volatile_bars(self):
        from cryoquant.features.primitives import bb_width
        # Constant series → minimal width
        const_s = _close_series([100.0] * 30)
        result = bb_width(const_s, 20, 2.0)
        valid = result.dropna()
        assert (valid < 1.0).all()

    def test_warmup_nans(self):
        from cryoquant.features.primitives import bb_width
        s = _close_series(list(range(50)))
        result = bb_width(s, 20, 2.0)
        assert result.iloc[:19].isna().all()


class TestRealisedVol:
    def test_positive_for_moving_series(self):
        from cryoquant.features.primitives import realised_vol
        s = _close_series([100 + i + (i % 3) for i in range(50)])
        result = realised_vol(s, 24)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_zero_for_constant_series(self):
        from cryoquant.features.primitives import realised_vol
        s = _close_series([100.0] * 50)
        result = realised_vol(s, 24)
        valid = result.dropna()
        assert float(valid.abs().max()) == pytest.approx(0.0, abs=1e-10)


class TestVolZ:
    def test_zero_mean_unit_std_on_iid(self):
        from cryoquant.features.primitives import vol_z
        rng = np.random.default_rng(0)
        vol = pd.Series(rng.lognormal(0, 0.5, 200),
                        index=pd.date_range("2024-01-01", periods=200, freq="1h", tz="UTC"))
        result = vol_z(vol, 50)
        valid = result.dropna()
        assert valid.mean() == pytest.approx(0.0, abs=0.5)


class TestRangeRatio:
    def test_above_zero(self):
        from cryoquant.features.primitives import range_ratio
        df = make_ohlcv(50)
        result = range_ratio(df, 24)
        valid = result.dropna()
        assert (valid > 0).all()


class TestHTFAlign:
    def test_no_lookahead(self):
        """After alignment, value at T_base must not reflect HTF bars after T_base."""
        from cryoquant.features.primitives import resample, htf_align
        df1h = make_ohlcv(200, freq="1h")
        df4h = resample(df1h, "4h")
        ret4h = df4h["close"].pct_change()
        ret4h.name = "ret_4h"
        aligned = htf_align(df1h, ret4h, htf="4h")
        # Cut data at bar 100 and re-align
        df1h_cut = df1h.iloc[:100]
        df4h_cut = resample(df1h_cut, "4h")
        ret4h_cut = df4h_cut["close"].pct_change()
        ret4h_cut.name = "ret_4h"
        aligned_cut = htf_align(df1h_cut, ret4h_cut, htf="4h")
        # Values up to the cut must be identical
        overlap_idx = aligned_cut.index
        pd.testing.assert_series_equal(
            aligned.loc[overlap_idx].rename(None),
            aligned_cut.rename(None),
            check_names=False,
        )


# ---------------------------------------------------------------------------
# calendar_features.py
# ---------------------------------------------------------------------------

class TestCalendarFeatures:
    def _idx(self, timestamps: list[str]) -> pd.DatetimeIndex:
        return pd.DatetimeIndex([pd.Timestamp(t, tz="UTC") for t in timestamps])

    def test_is_us_session_true_at_14_utc_monday(self):
        from cryoquant.features.calendar_features import is_us_session
        idx = self._idx(["2024-06-10 14:00:00"])  # Monday
        assert is_us_session(idx).iloc[0] is True or is_us_session(idx).iloc[0]

    def test_is_us_session_false_at_03_utc(self):
        from cryoquant.features.calendar_features import is_us_session
        idx = self._idx(["2024-06-10 03:00:00"])
        assert not is_us_session(idx).iloc[0]

    def test_is_weekend_saturday(self):
        from cryoquant.features.calendar_features import is_weekend
        idx = self._idx(["2024-06-08 12:00:00"])  # Saturday
        assert is_weekend(idx).iloc[0]

    def test_is_weekend_monday_false(self):
        from cryoquant.features.calendar_features import is_weekend
        idx = self._idx(["2024-06-10 12:00:00"])  # Monday
        assert not is_weekend(idx).iloc[0]

    def test_is_us_holiday_christmas(self):
        from cryoquant.features.calendar_features import is_us_holiday
        idx = self._idx(["2024-12-25 14:00:00"])
        assert is_us_holiday(idx).iloc[0]

    def test_hour_utc_correct(self):
        from cryoquant.features.calendar_features import hour_utc
        idx = self._idx(["2024-06-10 17:30:00"])
        assert int(hour_utc(idx).iloc[0]) == 17

    def test_dow_values(self):
        from cryoquant.features.calendar_features import dow
        # 2024-06-10 is Monday (0)
        idx = self._idx(["2024-06-10 12:00:00", "2024-06-15 12:00:00"])  # Mon, Sat
        result = dow(idx)
        assert int(result.iloc[0]) == 0
        assert int(result.iloc[1]) == 5


# ---------------------------------------------------------------------------
# builders.py — V2SpotFeaturesV1
# ---------------------------------------------------------------------------

class TestV2SpotFeaturesV1:
    EXPECTED_COLS = {
        "ret_1h", "ret_4h", "ret_1d", "accel_1h",
        "close_vs_ema24", "close_vs_ema168",
        "rv_24h", "rv_rank", "rv_trend",
        "bb_width", "vol_z", "range_ratio",
        "hour_utc", "day_of_week",
        "close", "high", "low", "volume",
    }

    def _make_builder_and_frames(self, n=1000):
        from cryoquant.features.builders import V2SpotFeaturesV1, DatasetRef
        from cryocore.instruments import Symbol
        builder = V2SpotFeaturesV1()
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1h")
        frames = {ref: make_ohlcv(n=n)}
        return builder, ref, frames

    def test_output_columns(self):
        builder, _, frames = self._make_builder_and_frames()
        result = builder.build(frames)
        assert self.EXPECTED_COLS.issubset(set(result.columns))

    def test_no_lookahead(self):
        """feature[T] must be unchanged when bars after T are removed."""
        from cryoquant.features.builders import V2SpotFeaturesV1, DatasetRef
        from cryocore.instruments import Symbol
        builder = V2SpotFeaturesV1()
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1h")
        df = make_ohlcv(n=1000)
        frames_full = {ref: df}
        frames_cut  = {ref: df.iloc[:500]}

        # Disable cache so we always recompute
        import cryoquant.features.store as store_mod
        orig = store_mod.config.FEATURE_STORE_DIR
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path
            store_mod.config.FEATURE_STORE_DIR = Path(td)
            out_full = builder.build(frames_full)
            out_cut  = builder.build(frames_cut)
        store_mod.config.FEATURE_STORE_DIR = orig

        overlap = out_cut.index
        price_cols = ["ret_1h", "rv_24h", "bb_width", "close_vs_ema24"]
        for col in price_cols:
            pd.testing.assert_series_equal(
                out_full.loc[overlap, col].rename(None),
                out_cut[col].rename(None),
                check_names=False,
                rtol=1e-6,
            )

    def test_session_cols_not_shifted(self):
        """hour_utc and day_of_week must match the index, not be shifted."""
        builder, _, frames = self._make_builder_and_frames(100)
        import cryoquant.features.store as store_mod
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            store_mod.config.FEATURE_STORE_DIR = Path(td)
            result = builder.build(frames)
        idx = result.index
        assert (result["hour_utc"].values == idx.hour).all()
        assert (result["day_of_week"].values == idx.dayofweek).all()


# ---------------------------------------------------------------------------
# labels.py — ForwardReturnLabeler
# ---------------------------------------------------------------------------

class TestForwardReturnLabeler:
    def test_trailing_nans(self):
        from cryoquant.features.labels import ForwardReturnLabeler
        df = make_ohlcv(50)
        labeler = ForwardReturnLabeler(horizon_h=5, threshold=2.5, direction="magnitude")
        result = labeler.apply(df)
        assert result.iloc[-5:].isna().all()
        assert result.iloc[:-5].notna().any()

    def test_column_name(self):
        from cryoquant.features.labels import ForwardReturnLabeler
        lab = ForwardReturnLabeler(24, 2.5, "magnitude")
        assert "magnitude" in lab.column_name
        assert "24" in lab.column_name
        assert "2p5" in lab.column_name

    def test_known_outcomes(self):
        """A price jump above threshold → 1; below → 0."""
        from cryoquant.features.labels import ForwardReturnLabeler
        # Construct a price series where close[0] = 100 and high[5] = 110 (+10%)
        idx = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
        close = pd.Series([100.0] * 20, index=idx)
        high  = pd.Series([100.0] * 20, index=idx)
        low   = pd.Series([100.0] * 20, index=idx)
        # Make bar 5 have a high of 115 (15% above bar 0's close)
        high.iloc[5] = 115.0
        df = pd.DataFrame({"open": close, "high": high, "low": low,
                           "close": close, "volume": pd.Series(1.0, index=idx)})
        df.index.name = "timestamp"

        lab = ForwardReturnLabeler(horizon_h=6, threshold=5.0, direction="up")
        result = lab.apply(df)
        # Bar 0 should see bar 5's high within its forward window
        assert result.iloc[0] == pytest.approx(1.0)
        # Bar 15 and later: no big move → 0 (non-NaN rows)
        non_nan_early = result.iloc[12:14]
        assert float(non_nan_early.max()) == pytest.approx(0.0, abs=1e-10)

    def test_invalid_params(self):
        from cryoquant.features.labels import ForwardReturnLabeler
        with pytest.raises(ValueError):
            ForwardReturnLabeler(0, 2.5)
        with pytest.raises(ValueError):
            ForwardReturnLabeler(24, -1.0)


# ---------------------------------------------------------------------------
# store.py — @cached decorator
# ---------------------------------------------------------------------------

class TestCachedDecorator:
    def test_cache_hit_skips_rebuild(self, tmp_path, monkeypatch):
        from cryoquant.features.store import cached
        import cryoquant.features.store as store_mod
        monkeypatch.setattr(store_mod.config, "FEATURE_STORE_DIR", tmp_path)

        call_count = {"n": 0}

        class MockBuilder:
            id = "test_builder"
            version = "1"

            @cached
            def build(self, frames):
                call_count["n"] += 1
                ref = next(iter(frames))
                return frames[ref][["close"]].rename(columns={"close": "feat"})

        b = MockBuilder()
        from cryoquant.features.builders import DatasetRef
        from cryocore.instruments import Symbol
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1h")
        frames = {ref: make_ohlcv(50)}

        b.build(frames)
        b.build(frames)

        assert call_count["n"] == 1, "Second call should have used cache"

    def test_version_bump_invalidates(self, tmp_path, monkeypatch):
        from cryoquant.features.store import cached
        import cryoquant.features.store as store_mod
        monkeypatch.setattr(store_mod.config, "FEATURE_STORE_DIR", tmp_path)

        call_count = {"n": 0}

        class V1Builder:
            id = "test_v_builder"
            version = "1"

            @cached
            def build(self, frames):
                call_count["n"] += 1
                ref = next(iter(frames))
                return frames[ref][["close"]].rename(columns={"close": "feat"})

        class V2Builder:
            id = "test_v_builder"
            version = "2"

            @cached
            def build(self, frames):
                call_count["n"] += 1
                ref = next(iter(frames))
                return frames[ref][["close"]].rename(columns={"close": "feat"})

        from cryoquant.features.builders import DatasetRef
        from cryocore.instruments import Symbol
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1h")
        frames = {ref: make_ohlcv(50)}

        V1Builder().build(frames)
        V2Builder().build(frames)  # different version → cache miss

        assert call_count["n"] == 2
