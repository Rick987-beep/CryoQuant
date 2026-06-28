"""Phase 3 labeler unit and methodology tests (P3-T01–T05)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv


class TestForwardReturnLabelerP3:
    """P3-T01: trailing H rows NaN; forward window only."""

    def test_trailing_nans(self):
        from cryoquant.features.labels import ForwardReturnLabeler

        df = make_ohlcv(50)
        labeler = ForwardReturnLabeler(horizon_h=5, threshold=2.5, direction="magnitude")
        result = labeler.apply(df)
        assert result.iloc[-5:].isna().all()
        assert result.iloc[:-5].notna().any()

    def test_volscaled_column_name(self):
        from cryoquant.features.labels import ForwardReturnLabeler

        lab = ForwardReturnLabeler(5, 1.5, "up")
        assert lab.column_name_volscaled() == "up_win_volscaled_h5"


class TestForwardReturnLabelerLeakageP3:
    """P3-T02: label at t reacts to future bars, not past-only changes."""

    def test_future_window_changes_label(self):
        from cryoquant.features.labels import ForwardReturnLabeler

        df = make_ohlcv(40)
        lab = ForwardReturnLabeler(horizon_h=5, threshold=1.0, direction="up")
        base = lab.apply(df)
        t = 10

        mutated = df.copy()
        mutated.iloc[t + 1 : t + 6, mutated.columns.get_loc("high")] *= 1.25
        changed = lab.apply(mutated)
        assert changed.iloc[t] == pytest.approx(1.0)
        assert base.iloc[t] != pytest.approx(1.0)

    def test_past_bar_change_does_not_affect_label(self):
        from cryoquant.features.labels import ForwardReturnLabeler

        df = make_ohlcv(40)
        lab = ForwardReturnLabeler(horizon_h=5, threshold=2.0, direction="magnitude")
        base = lab.apply(df)
        t = 20

        mutated = df.copy()
        if t > 0:
            mutated.iloc[t - 1, mutated.columns.get_loc("close")] *= 0.5
        same = lab.apply(mutated)
        assert base.iloc[t] == pytest.approx(same.iloc[t])


class TestLogReturnLabelerP3:
    """P3-T03: log return equals ln(close[t+H]/close[t])."""

    def test_log_return_formula(self):
        from cryoquant.features.labels import LogReturnLabeler

        df = make_ohlcv(30)
        h = 5
        out = LogReturnLabeler(h).apply(df)
        manual = np.log(df["close"].shift(-h) / df["close"])
        manual.iloc[-h:] = np.nan
        pd.testing.assert_series_equal(out, manual.rename(out.name), check_names=True)


class TestExceedanceLabelerP3:
    """P3-T04: call exceedance vs strike from threshold."""

    def test_call_terminal_exceedance(self):
        from cryoquant.features.labels import ExceedanceLabeler

        idx = pd.date_range("2024-01-01", periods=12, freq="D", tz="UTC")
        close = pd.Series([100.0] * 12, index=idx)
        df = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1.0,
            },
            index=idx,
        )
        thr = 0.05
        df.iloc[6, df.columns.get_loc("close")] = 110.0  # +10% at t+5 from t=1

        lab = ExceedanceLabeler(5, "call", threshold_log_return=thr)
        out = lab.apply(df)
        assert out.iloc[1] == pytest.approx(1.0)
        assert out.iloc[-5:].isna().all()


class TestVolScaledThresholdP3:
    """P3-T05: vol-scaled threshold rises with trailing vol."""

    def test_threshold_increases_with_vol(self):
        from cryoquant.features.labels import VolScaledThreshold

        idx = pd.date_range("2024-01-01", periods=80, freq="D", tz="UTC")
        rng = np.random.default_rng(0)
        calm = 100 + rng.normal(0, 0.1, 40).cumsum()
        wild = np.concatenate([calm, calm[-1] + rng.normal(0, 5, 40).cumsum()])
        close = pd.Series(wild, index=idx)
        thr = VolScaledThreshold.apply(close, horizon_bars=5, window=5, k=1.0)
        assert thr.iloc[-1] > thr.iloc[30]

    def test_volscaled_apply_uses_volscaled_name(self):
        from cryoquant.features.labels import ForwardReturnLabeler, VolScaledThreshold

        df = make_ohlcv(30, freq="D")
        thr = VolScaledThreshold.apply(df["close"], horizon_bars=5, window=5, k=1.0)
        out = ForwardReturnLabeler(5, 1.5, "up").apply(df, threshold_pct=thr)
        assert out.name == "up_win_volscaled_h5"


class TestRealizedVolLabelerP3:
    def test_h1_produces_finite_values(self):
        from cryoquant.features.labels import RealizedVolLabeler

        df = make_ohlcv(20, freq="D")
        out = RealizedVolLabeler(1).apply(df)
        assert out.iloc[-1:].isna().all()
        assert out.iloc[:-1].notna().all()
        assert (out.dropna() > 0).all()


class TestVRPRealizationLabelerP3:
    def test_vrp_is_iv_minus_forward_rv(self):
        from cryoquant.features.labels import RealizedVolLabeler, VRPRealizationLabeler

        idx = pd.date_range("2024-01-01", periods=20, freq="D", tz="UTC")
        close = pd.Series(np.linspace(100, 110, 20), index=idx)
        df = pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1.0},
            index=idx,
        )
        iv = pd.Series(50.0, index=idx)
        h = 5
        vrp = VRPRealizationLabeler(h).apply(df, iv)
        rv = RealizedVolLabeler(h).apply(df)
        pd.testing.assert_series_equal(vrp, (iv - rv).rename(vrp.name), check_names=True)


class TestCausalQuantileP3:
    def test_quantile_at_t_ignores_own_forward_return(self):
        from cryoquant.features.labels import causal_forward_return_quantile

        idx = pd.date_range("2024-01-01", periods=300, freq="D", tz="UTC")
        rng = np.random.default_rng(1)
        close = pd.Series(100 * np.exp(rng.normal(0, 0.01, 300).cumsum()), index=idx)
        h = 5
        t = 100
        base = causal_forward_return_quantile(close, h, 0.9, 60)
        mutated = close.copy()
        # Spike only the terminal close for *t*'s forward window — must not move q at t.
        mutated.iloc[t + h] *= 3.0
        changed = causal_forward_return_quantile(mutated, h, 0.9, 60)
        assert base.iloc[t] == pytest.approx(changed.iloc[t])


class TestExceedancePutP3:
    def test_put_terminal_exceedance(self):
        from cryoquant.features.labels import ExceedanceLabeler

        idx = pd.date_range("2024-01-01", periods=12, freq="D", tz="UTC")
        close = pd.Series([100.0] * 12, index=idx)
        df = pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1.0},
            index=idx,
        )
        thr = -0.05
        df.iloc[6, df.columns.get_loc("close")] = 90.0
        out = ExceedanceLabeler(5, "put", threshold_log_return=thr).apply(df)
        assert out.iloc[1] == pytest.approx(1.0)
