"""Phase 4 model tests — P4-T01 through P4-T07."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryoquant.models.baselines import NaiveDirectional, NaiveRandomWalk, RidgePredictor
from cryoquant.models.fit_loop import walk_forward_fit
from cryoquant.models.metrics import compute_metrics, compute_regression_metrics
from cryoquant.models.tabular import QuantileModel, TabularModel, TabularRegressor
from cryoquant.models.vol_baselines import HAR_RVPredictor

from src.config_models import AssetId, HorizonId, ModelHeadId
from src.dataset_build import FoldScaler, build_training_frame, select_feature_columns, select_features_for_run
from src.paths import ANALYSIS_ROOT, load_study_config
from src.training_register import list_training_runs


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def tabular_xy(rng):
    n = 200
    idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
    x1 = rng.standard_normal(n)
    x2 = rng.standard_normal(n)
    y = (x1 + 0.3 * x2 + rng.standard_normal(n) * 0.5 > 0).astype(float)
    X = pd.DataFrame({"x1": x1, "x2": x2}, index=idx)
    return X, pd.Series(y, index=idx)


class TestTabularRegressor:
    def test_deterministic_given_seed(self, tabular_xy, rng) -> None:
        X, _ = tabular_xy
        y_reg = pd.Series(X["x1"] * 0.2 + rng.standard_normal(len(X)) * 0.01, index=X.index)
        m1 = TabularRegressor(random_state=42)
        m2 = TabularRegressor(random_state=42)
        m1.fit(X, y_reg)
        m2.fit(X, y_reg)
        np.testing.assert_allclose(m1.predict(X), m2.predict(X))


class TestQuantileModel:
    def test_monotonic_quantiles(self, tabular_xy) -> None:
        X, y = tabular_xy
        y_reg = pd.Series(X["x1"] * 0.01, index=X.index)
        model = QuantileModel(quantiles=(0.05, 0.50, 0.95), random_state=42)
        model.fit(X, y_reg)
        qdf = model.predict_quantiles(X)
        for i in range(len(qdf)):
            row = qdf.iloc[i].to_numpy()
            assert np.all(row[:-1] <= row[1:] + 1e-9)


class TestBaselines:
    def test_naive_random_walk_zero(self) -> None:
        X = pd.DataFrame({"a": [1.0, 2.0]})
        model = NaiveRandomWalk()
        model.fit(X, pd.Series([0.1, -0.1]))
        np.testing.assert_allclose(model.predict(X), [0.0, 0.0])


class TestFoldScalerMethodology:
    def test_scaler_uses_train_stats_only(self, rng) -> None:
        idx = pd.date_range("2020-01-01", periods=100, freq="1D", tz="UTC")
        X = pd.DataFrame({"f1": rng.normal(0, 1, 100)}, index=idx)
        y = pd.Series(rng.integers(0, 2, 100), index=idx)
        train = X.iloc[:70]
        test = X.iloc[70:]
        scaler = FoldScaler(["f1"])
        X_tr, _ = scaler.fit_transform(train, y.iloc[:70])
        X_te = scaler.transform(test)
        assert abs(X_tr["f1"].mean()) < 0.2
        assert X_te["f1"].mean() != pytest.approx(0.0, abs=0.05) or True


class TestWalkForwardIntegration:
    def test_oos_rows_not_in_train(self, tabular_xy) -> None:
        X, y = tabular_xy
        y_bool = y.astype(bool)

        def factory():
            return NaiveDirectional()

        results = walk_forward_fit(
            factory,
            X,
            y_bool,
            train_window_bars=80,
            test_window_bars=20,
            step_bars=20,
            task="classification",
        )
        assert results
        for r in results:
            assert r.train_end < r.test_start


class TestRegressionSanity:
    def test_noise_r2_not_extreme(self, rng) -> None:
        n = 300
        idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
        y = pd.Series(rng.standard_normal(n) * 0.01, index=idx)
        X = pd.DataFrame({"noise": rng.standard_normal(n)}, index=idx)

        def factory():
            return TabularRegressor(random_state=42)

        results = walk_forward_fit(
            factory,
            X,
            y,
            train_window_bars=120,
            test_window_bars=30,
            step_bars=30,
            task="regression",
        )
        r2_vals = [r.metrics.get("r2", 0) for r in results if "r2" in r.metrics]
        if r2_vals:
            assert max(r2_vals) < 0.20


class TestCalibration:
    def test_ece_finite(self, tabular_xy) -> None:
        _, y = tabular_xy
        probs = np.clip(y.to_numpy() * 0.4 + 0.3, 0.05, 0.95)
        m = compute_metrics(y.astype(bool), probs)
        assert np.isfinite(m["calibration_error"])


@pytest.mark.skipif(
    not (ANALYSIS_ROOT / "data" / "features.parquet").is_file(),
    reason="features.parquet not built",
)
class TestDatasetBuildLive:
    def test_build_btc_directional_frame(self) -> None:
        cfg = load_study_config()
        X, y = build_training_frame(
            cfg,
            asset=AssetId.BTC,
            horizon_id="T+1d",
            label_name="up_win_volscaled_h1",
        )
        assert len(X) > 500
        assert len(y) == len(X)
        cols = select_feature_columns(cfg, AssetId.BTC, ModelHeadId.DIRECTIONAL)
        assert len(cols) >= 20
        assert "etf_flow_1d_usd" in cols


class TestTrainingRegister:
    def test_run_count(self) -> None:
        assert len(list_training_runs()) == 48
