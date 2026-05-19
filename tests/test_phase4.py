"""Phase 4 unit tests: signals, publishers, thresholds, adapters."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feature_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "ret_1h":   rng.normal(0, 1.0, n),
            "ret_4h":   rng.normal(0, 2.0, n),
            "vol_z":    rng.normal(0, 1.5, n),
            "rv_rank":  rng.uniform(0, 1, n),
            "feature_a": rng.standard_normal(n),
            "feature_b": rng.standard_normal(n),
        },
        index=idx,
    )


def _labels(n: int = 100, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.Series(rng.integers(0, 2, n), index=idx, name="label", dtype="int8")


def _fitted_tabular(n: int = 150):
    """Return a fitted TabularModel on synthetic data."""
    from cryoquant.models.tabular import TabularModel
    X = _feature_df(n)
    y = _labels(n)
    m = TabularModel(calibration_cv=2)
    m.fit(X, y)
    return m


# ===========================================================================
# BoolSignal
# ===========================================================================

class TestBoolSignal:
    def test_as_feature_returns_bool_series(self):
        from cryoquant.signals.base import BoolSignal
        sig = BoolSignal(
            signal_id="test_bool",
            condition=lambda df: df["ret_4h"] > 1.0,
        )
        X = _feature_df(50)
        result = sig.as_feature(X)
        assert isinstance(result, pd.Series)
        assert result.dtype == bool
        assert result.name == "test_bool"

    def test_as_feature_length_matches(self):
        from cryoquant.signals.base import BoolSignal
        sig = BoolSignal("b", condition=lambda df: pd.Series(True, index=df.index))
        X = _feature_df(80)
        assert len(sig.as_feature(X)) == 80

    def test_emit_returns_bool_emit(self):
        from cryocore.schemas import BoolEmit
        from cryoquant.signals.base import BoolSignal
        sig = BoolSignal("entry", condition=lambda df: pd.Series(True, index=df.index),
                         symbol_str="binance.spot:BTCUSDT")
        X = _feature_df(10)
        t = X.index[5]
        result = sig.emit(t, X)
        assert isinstance(result, BoolEmit)
        assert result.value is True
        assert result.signal_id == "entry"

    def test_emit_false_condition(self):
        from cryoquant.signals.base import BoolSignal
        sig = BoolSignal("no_entry", condition=lambda df: pd.Series(False, index=df.index))
        X = _feature_df(10)
        t = X.index[0]
        assert sig.emit(t, X).value is False


# ===========================================================================
# StateSignal
# ===========================================================================

class TestStateSignal:
    def _make_state_sig(self):
        from cryoquant.signals.base import StateSignal

        def state_fn(df):
            return pd.Series(
                np.where(df["ret_4h"] > 1.0, 1, np.where(df["ret_4h"] < -1.0, -1, 0)),
                index=df.index,
                dtype="int8",
            )
        return StateSignal("trend_state", state_fn=state_fn)

    def test_as_feature_int8(self):
        sig = self._make_state_sig()
        X = _feature_df(50)
        result = sig.as_feature(X)
        assert result.dtype == "int8"
        assert set(result.unique()).issubset({-1, 0, 1})

    def test_emit_valid_state(self):
        from cryocore.schemas import StateEmit
        sig = self._make_state_sig()
        X = _feature_df(20)
        t = X.index[0]
        result = sig.emit(t, X)
        assert isinstance(result, StateEmit)
        assert result.state in (-1, 0, 1)


# ===========================================================================
# ProbSignal
# ===========================================================================

class TestProbSignal:
    def test_as_feature_in_range(self):
        from cryoquant.signals.base import ProbSignal
        model = _fitted_tabular()
        X = _feature_df(150)
        sig = ProbSignal("prob_sig", model=model)
        result = sig.as_feature(X)
        assert isinstance(result, pd.Series)
        assert float(result.min()) >= 0.0
        assert float(result.max()) <= 1.0

    def test_emit_returns_prob_emit(self):
        from cryocore.schemas import ProbEmit
        from cryoquant.signals.base import ProbSignal
        model = _fitted_tabular()
        X = _feature_df(150)
        sig = ProbSignal("prob_sig", model=model, horizon_h=24, direction="magnitude",
                         default_threshold=0.5)
        t = X.index[100]
        result = sig.emit(t, X)
        assert isinstance(result, ProbEmit)
        assert 0.0 <= result.prob <= 1.0
        assert result.horizon_hours == 24
        assert result.direction == "magnitude"


# ===========================================================================
# ScoreSignal
# ===========================================================================

class TestScoreSignal:
    def _make_score_sig(self):
        from cryoquant.signals.base import ScoreSignal
        return ScoreSignal("rsi_score", score_fn=lambda df: df["ret_4h"] * 10.0)

    def test_as_feature_is_float_series(self):
        sig = self._make_score_sig()
        X = _feature_df(50)
        result = sig.as_feature(X)
        assert isinstance(result, pd.Series)
        assert result.dtype == float
        assert result.name == "rsi_score"

    def test_as_feature_unbounded(self):
        sig = self._make_score_sig()
        X = _feature_df(50)
        result = sig.as_feature(X)
        # Values are not constrained to [0, 1]
        assert result.abs().max() > 1.0

    def test_emit_returns_score_emit(self):
        from cryocore.schemas import ScoreEmit
        sig = self._make_score_sig()
        X = _feature_df(20)
        t = X.index[5]
        result = sig.emit(t, X)
        assert isinstance(result, ScoreEmit)
        assert result.signal_id == "rsi_score"
        assert isinstance(result.value, float)

    def test_emit_value_matches_as_feature(self):
        sig = self._make_score_sig()
        X = _feature_df(20)
        t = X.index[5]
        expected = float(sig.as_feature(X).loc[t])
        assert sig.emit(t, X).value == pytest.approx(expected)

    def test_string_state_signal(self):
        """StateSignal now accepts arbitrary states including strings."""
        from cryoquant.signals.base import StateSignal
        states_map = {0: "bearish", 1: "neutral", 2: "bullish"}
        def regime_fn(df):
            idx = (df["ret_4h"] > 1.0).astype(int) + (df["ret_4h"] > -0.5).astype(int)
            return idx.map(states_map).fillna("neutral")
        sig = StateSignal("regime", state_fn=regime_fn)
        X = _feature_df(30)
        result = sig.as_feature(X)
        assert set(result.unique()).issubset({"bearish", "neutral", "bullish"})
        emit = sig.emit(X.index[10], X)
        assert emit.state in {"bearish", "neutral", "bullish"}


# ===========================================================================
# from_model adapters
# ===========================================================================

class TestFromModel:
    def test_bool_from_rule(self):
        from cryoquant.models.baselines import make_pullback
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.from_model import bool_from_rule
        rule = make_pullback()
        sig = bool_from_rule(rule)
        assert isinstance(sig, BoolSignal)
        assert sig.signal_id == "pullback"

    def test_bool_from_rule_custom_name(self):
        from cryoquant.models.baselines import make_pullback
        from cryoquant.signals.from_model import bool_from_rule
        sig = bool_from_rule(make_pullback(), name="my_pullback")
        assert sig.signal_id == "my_pullback"

    def test_prob_from_model(self):
        from cryoquant.signals.base import ProbSignal
        from cryoquant.signals.from_model import prob_from_model
        model = _fitted_tabular()
        sig = prob_from_model(model, horizon_h=24)
        assert isinstance(sig, ProbSignal)
        assert sig.horizon_h == 24

    def test_state_from_model(self):
        from cryoquant.signals.base import StateSignal
        from cryoquant.signals.from_model import state_from_model
        model = _fitted_tabular()
        sig = state_from_model(model, up_thr=0.6, down_thr=0.4)
        assert isinstance(sig, StateSignal)

    def test_state_from_model_values_valid(self):
        from cryoquant.signals.from_model import state_from_model
        model = _fitted_tabular()
        X = _feature_df(150)
        sig = state_from_model(model)
        result = sig.as_feature(X)
        assert set(result.unique()).issubset({-1, 0, 1})


# ===========================================================================
# pick_threshold
# ===========================================================================

class TestPickThreshold:
    def _data(self):
        rng = np.random.default_rng(7)
        y_true = rng.integers(0, 2, 200).astype(float)
        y_prob = rng.uniform(0, 1, 200)
        return y_true, y_prob

    def test_precision_target(self):
        from cryoquant.signals.thresholds import pick_threshold
        y_true, y_prob = self._data()
        thr = pick_threshold(y_true, y_prob, target="precision", value=0.6)
        assert 0.0 <= thr <= 1.0

    def test_recall_target(self):
        from cryoquant.signals.thresholds import pick_threshold
        y_true, y_prob = self._data()
        thr = pick_threshold(y_true, y_prob, target="recall", value=0.8)
        assert 0.0 <= thr <= 1.0

    def test_f1_target(self):
        from cryoquant.signals.thresholds import pick_threshold
        y_true, y_prob = self._data()
        thr = pick_threshold(y_true, y_prob, target="f1")
        assert 0.0 <= thr <= 1.0

    def test_invalid_target_raises(self):
        from cryoquant.signals.thresholds import pick_threshold
        with pytest.raises(ValueError, match="Unknown target"):
            pick_threshold(np.array([0, 1]), np.array([0.3, 0.7]), target="bogus")


# ===========================================================================
# emit_history (csv_emitter)
# ===========================================================================

class TestEmitHistory:
    def test_bool_signal_writes_parquet(self, tmp_path):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.csv_emitter import emit_history
        sig = BoolSignal("test_bool", condition=lambda df: df["ret_4h"] > 1.0)
        X = _feature_df(50)
        out = tmp_path / "out.parquet"
        result_path = emit_history(sig, X, out)
        assert result_path.exists()
        df = pd.read_parquet(result_path)
        assert len(df) == 50
        assert "value" in df.columns
        assert "signal_id" in df.columns
        assert (df["signal_id"] == "test_bool").all()

    def test_prob_signal_writes_prob_column(self, tmp_path):
        from cryoquant.signals.base import ProbSignal
        from cryoquant.signals.publishers.csv_emitter import emit_history
        model = _fitted_tabular()
        X = _feature_df(150)
        sig = ProbSignal("prob_test", model=model)
        out = tmp_path / "prob.parquet"
        emit_history(sig, X, out)
        df = pd.read_parquet(out)
        assert "prob" in df.columns
        assert not df["prob"].isna().all()
        assert float(df["prob"].min()) >= 0.0
        assert float(df["prob"].max()) <= 1.0

    def test_state_signal_writes_state_column(self, tmp_path):
        from cryoquant.signals.base import StateSignal
        from cryoquant.signals.publishers.csv_emitter import emit_history
        sig = StateSignal("state_test", state_fn=lambda df: pd.Series(
            np.where(df["ret_4h"] > 1.0, 1, np.where(df["ret_4h"] < -1.0, -1, 0)),
            index=df.index, dtype="int8",
        ))
        X = _feature_df(50)
        out = tmp_path / "state.parquet"
        emit_history(sig, X, out)
        df = pd.read_parquet(out)
        assert "state" in df.columns
        non_nan_states = df["state"].dropna()
        assert set(non_nan_states.astype(int).unique()).issubset({-1, 0, 1})

    def test_output_has_ts_index(self, tmp_path):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.csv_emitter import emit_history
        sig = BoolSignal("ts_test", condition=lambda df: pd.Series(True, index=df.index))
        X = _feature_df(30)
        out = emit_history(sig, X, tmp_path / "ts.parquet")
        df = pd.read_parquet(out)
        assert df.index.name == "ts"


# ===========================================================================
# pine_emitter
# ===========================================================================

class TestPineEmitter:
    def test_bool_signal_starts_with_version5(self):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.pine_emitter import emit_pine
        sig = BoolSignal("entry", condition=lambda df: df["ret_4h"] > 1.0)
        pine = emit_pine(sig)
        assert pine.startswith("//@version=5")

    def test_bool_signal_has_one_indicator_call(self):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.pine_emitter import emit_pine
        sig = BoolSignal("entry", condition=lambda df: df["ret_4h"] > 1.0)
        pine = emit_pine(sig)
        assert pine.count("indicator(") == 1

    def test_state_signal_starts_with_version5(self):
        from cryoquant.signals.base import StateSignal
        from cryoquant.signals.publishers.pine_emitter import emit_pine
        sig = StateSignal("trend", state_fn=lambda df: pd.Series(0, index=df.index, dtype="int8"))
        pine = emit_pine(sig)
        assert pine.startswith("//@version=5")
        assert pine.count("indicator(") == 1

    def test_prob_signal_raises_type_error(self):
        from cryoquant.signals.base import ProbSignal
        from cryoquant.signals.publishers.pine_emitter import emit_pine
        model = _fitted_tabular()
        X = _feature_df(150)
        sig = ProbSignal("prob_sig", model=model)
        with pytest.raises(TypeError, match="ProbSignal"):
            emit_pine(sig)

    def test_custom_name_in_output(self):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.pine_emitter import emit_pine
        sig = BoolSignal("internal_id", condition=lambda df: pd.Series(True, index=df.index))
        pine = emit_pine(sig, name="My Custom Signal")
        assert "My Custom Signal" in pine

    def test_signal_id_in_output(self):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.pine_emitter import emit_pine
        sig = BoolSignal("pullback_v2", condition=lambda df: pd.Series(True, index=df.index))
        pine = emit_pine(sig)
        assert "pullback_v2" in pine


# ===========================================================================
# CryoTrader adapter
# ===========================================================================

class TestCryoTraderAdapter:
    def _ctx(self, **feats):
        return SimpleNamespace(features=feats, timestamp=pd.Timestamp("2024-01-01", tz="UTC"))

    def test_bool_signal_adapter_returns_bool(self):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.cryotrader_adapter import to_cryotrader_condition
        sig = BoolSignal("b", condition=lambda df: df["ret_4h"] > 1.0)
        cond = to_cryotrader_condition(sig)
        ctx = self._ctx(ret_4h=2.0, ret_1h=-0.3)
        assert isinstance(cond(ctx), bool)
        assert cond(ctx) is True

    def test_bool_signal_false(self):
        from cryoquant.signals.base import BoolSignal
        from cryoquant.signals.publishers.cryotrader_adapter import to_cryotrader_condition
        sig = BoolSignal("b", condition=lambda df: df["ret_4h"] > 1.0)
        cond = to_cryotrader_condition(sig)
        ctx = self._ctx(ret_4h=0.5)
        assert cond(ctx) is False

    def test_prob_signal_adapter_threshold(self):
        from cryoquant.signals.base import ProbSignal
        from cryoquant.signals.publishers.cryotrader_adapter import to_cryotrader_condition
        model = _fitted_tabular()
        X = _feature_df(150)
        sig = ProbSignal("p", model=model)
        cond = to_cryotrader_condition(sig, threshold=0.0)
        # threshold=0 → always True if prob >= 0
        ctx = SimpleNamespace(features=dict(zip(X.columns, X.iloc[0].values)),
                              timestamp=X.index[0])
        assert isinstance(cond(ctx), bool)

    def test_state_signal_adapter_positive_state_only(self):
        from cryoquant.signals.base import StateSignal
        from cryoquant.signals.publishers.cryotrader_adapter import to_cryotrader_condition
        sig = StateSignal("s", state_fn=lambda df: pd.Series(1, index=df.index, dtype="int8"))
        cond = to_cryotrader_condition(sig)
        ctx = self._ctx(ret_4h=1.5)
        assert cond(ctx) is True

    def test_state_signal_adapter_negative_state(self):
        from cryoquant.signals.base import StateSignal
        from cryoquant.signals.publishers.cryotrader_adapter import to_cryotrader_condition
        sig = StateSignal("s", state_fn=lambda df: pd.Series(-1, index=df.index, dtype="int8"))
        cond = to_cryotrader_condition(sig)
        ctx = self._ctx(ret_4h=-1.5)
        assert cond(ctx) is False

    def test_invalid_signal_type_raises(self):
        from cryoquant.signals.publishers.cryotrader_adapter import to_cryotrader_condition
        with pytest.raises(TypeError):
            to_cryotrader_condition("not_a_signal")


# ===========================================================================
# Signal as feature (replay consistency)
# ===========================================================================

class TestSignalAsFeature:
    def test_bool_replay_consistency(self):
        """as_feature result matches per-bar emit calls."""
        from cryoquant.signals.base import BoolSignal
        sig = BoolSignal("r", condition=lambda df: df["ret_4h"] > 0.5)
        X = _feature_df(20)
        feature_series = sig.as_feature(X)
        for t in X.index[:10]:
            assert sig.emit(t, X).value == feature_series[t]

    def test_prob_replay_consistency(self):
        from cryoquant.signals.base import ProbSignal
        model = _fitted_tabular()
        X = _feature_df(150)
        sig = ProbSignal("p", model=model, direction="magnitude",
                         default_threshold=0.5, horizon_h=24)
        feature_series = sig.as_feature(X)
        for t in X.index[:5]:
            emitted_prob = sig.emit(t, X).prob
            assert feature_series[t] == pytest.approx(emitted_prob, abs=1e-6)
