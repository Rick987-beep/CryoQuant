"""Phase 3 unit tests: RuleModel, TabularModel, CV, metrics, registry."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feature_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Synthetic feature DataFrame with the V2 column set."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "ret_1h":          rng.normal(0, 1.0, n),
            "ret_4h":          rng.normal(0, 2.0, n),
            "ret_1d":          rng.normal(0, 4.0, n),
            "accel_1h":        rng.normal(0, 0.5, n),
            "close_vs_ema24":  rng.normal(0, 1.5, n),
            "close_vs_ema168": rng.normal(0, 2.0, n),
            "rv_24h":          np.abs(rng.normal(30, 10, n)),
            "rv_rank":         rng.uniform(0, 1, n),
            "rv_trend":        rng.normal(0, 5, n),
            "bb_width":        np.abs(rng.normal(2, 0.5, n)),
            "vol_z":           rng.normal(0, 1.5, n),
            "range_ratio":     np.abs(rng.normal(1, 0.3, n)),
            "hour_utc":        rng.integers(0, 24, n),
            "day_of_week":     rng.integers(0, 7, n),
        },
        index=idx,
    )


def _labels(n: int = 200, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.Series(rng.integers(0, 2, n), index=idx, name="label", dtype="int8")


# ===========================================================================
# RuleModel
# ===========================================================================

class TestRuleModel:
    def test_predict_before_fit_returns_0_5(self):
        from cryoquant.models.baselines import make_pullback
        m = make_pullback()
        X = _feature_df(50)
        probs = m.predict_proba(X)
        assert probs.shape == (50,)
        # Unfitted: all probs should be 0.5 (both states of unfitted rate)
        assert set(np.unique(probs)).issubset({0.5})

    def test_fit_records_empirical_win_rate(self):
        from cryoquant.models.baselines import RuleModel
        # Always-true condition
        m = RuleModel(condition=lambda df: pd.Series(True, index=df.index), name="always")
        X = _feature_df(100)
        y = _labels(100)
        m.fit(X, y)
        expected = float(y.mean())
        probs = m.predict_proba(X)
        assert np.all(probs == pytest.approx(expected))

    def test_fit_never_fires(self):
        from cryoquant.models.baselines import RuleModel
        m = RuleModel(condition=lambda df: pd.Series(False, index=df.index), name="never")
        X = _feature_df(100)
        y = _labels(100)
        m.fit(X, y)
        # n_fires = 0, win_rate stays at default 0.5
        assert m._n_fires == 0
        probs = m.predict_proba(X)
        # all predicted as NOT triggered → prob = 1 - 0.5 = 0.5
        assert np.all(probs == pytest.approx(0.5))

    def test_pullback_condition_shape(self):
        from cryoquant.models.baselines import make_pullback
        m = make_pullback()
        X = _feature_df(100)
        probs = m.predict_proba(X)
        assert probs.shape == (100,)
        assert np.allclose(probs, 0.5)  # unfitted win_rate defaults to 0.5

    def test_save_load_roundtrip(self, tmp_path):
        from cryoquant.models.baselines import RuleModel
        m = RuleModel(condition=lambda df: pd.Series(True, index=df.index), name="test_rule")
        m._win_rate = 0.72
        m._n_fires = 42
        p = tmp_path / "rule.json"
        m.save(p)
        m2 = RuleModel.load(p)
        assert m2.name == "test_rule"
        assert m2._win_rate == pytest.approx(0.72)
        assert m2._n_fires == 42

    def test_model_id_equals_name(self):
        from cryoquant.models.baselines import make_vol_burst
        m = make_vol_burst()
        assert m.model_id == "vol_burst"

    def test_vol_burst_fires_on_high_vol(self):
        from cryoquant.models.baselines import make_vol_burst
        m = make_vol_burst()
        X = _feature_df(10)
        # Manually set high vol conditions
        X = X.copy()
        X["vol_z"] = 2.0
        X["rv_rank"] = 0.9
        m._win_rate = 0.65
        probs = m.predict_proba(X)
        assert np.all(probs == pytest.approx(0.65))

    def test_factories_return_independent_instances(self):
        from cryoquant.models.baselines import make_pullback
        a = make_pullback()
        b = make_pullback()
        a._win_rate = 0.99
        assert b._win_rate == pytest.approx(0.5)  # b not affected


# ===========================================================================
# TabularModel
# ===========================================================================

class TestTabularModel:
    def test_predict_proba_shape_and_range(self):
        from cryoquant.models.tabular import TabularModel
        m = TabularModel(calibration_cv=2)
        X = _feature_df(150)
        y = _labels(150)
        m.fit(X, y)
        probs = m.predict_proba(X)
        assert probs.shape == (150,)
        assert float(probs.min()) >= 0.0
        assert float(probs.max()) <= 1.0

    def test_feature_importances_shape(self):
        from cryoquant.models.tabular import TabularModel
        m = TabularModel(calibration_cv=2)
        X = _feature_df(150)
        y = _labels(150)
        m.fit(X, y)
        imp = m.feature_importances_
        assert imp is not None
        assert len(imp) == X.shape[1]
        assert imp.index.tolist() == sorted(X.columns.tolist(), key=lambda c: -imp[c])

    def test_feature_importances_none_before_fit(self):
        from cryoquant.models.tabular import TabularModel
        m = TabularModel()
        assert m.feature_importances_ is None

    def test_save_load_roundtrip(self, tmp_path):
        from cryoquant.models.tabular import TabularModel
        m = TabularModel(calibration_cv=2)
        X = _feature_df(150)
        y = _labels(150)
        m.fit(X, y)
        probs_before = m.predict_proba(X)
        path = tmp_path / "model.pkl"
        m.save(path)
        m2 = TabularModel.load(path)
        probs_after = m2.predict_proba(X)
        np.testing.assert_array_almost_equal(probs_before, probs_after)

    def test_model_id(self):
        from cryoquant.models.tabular import TabularModel
        assert TabularModel().model_id == "tabular"


# ===========================================================================
# purged_kfold
# ===========================================================================

class TestPurgedKFold:
    def test_k_splits_produced(self):
        from cryoquant.models.cv import purged_kfold
        splits = list(purged_kfold(100, n_splits=5))
        assert len(splits) == 5

    def test_test_folds_cover_full_range(self):
        from cryoquant.models.cv import purged_kfold
        n = 100
        covered = np.zeros(n, dtype=bool)
        for _, test in purged_kfold(n, n_splits=5):
            covered[test] = True
        assert covered.all()

    def test_embargo_removes_bars_after_test(self):
        from cryoquant.models.cv import purged_kfold
        n = 50
        embargo = 5
        for train, test in purged_kfold(n, n_splits=5, embargo_bars=embargo):
            test_end = test[-1] + 1
            # No training index should fall in (test_end, test_end + embargo)
            forbidden = set(range(test_end, min(test_end + embargo, n)))
            assert len(forbidden & set(train.tolist())) == 0

    def test_train_test_no_overlap(self):
        from cryoquant.models.cv import purged_kfold
        for train, test in purged_kfold(100, n_splits=5, embargo_bars=3):
            assert len(set(train.tolist()) & set(test.tolist())) == 0

    def test_requires_at_least_2_splits(self):
        from cryoquant.models.cv import purged_kfold
        with pytest.raises(ValueError):
            list(purged_kfold(100, n_splits=1))


# ===========================================================================
# walk_forward
# ===========================================================================

class TestWalkForward:
    def test_window_sizes(self):
        from cryoquant.models.cv import walk_forward
        for train, test in walk_forward(200, train_window=100, test_window=20):
            assert len(train) == 100
            assert len(test) == 20

    def test_no_train_test_overlap(self):
        from cryoquant.models.cv import walk_forward
        for train, test in walk_forward(200, train_window=100, test_window=20):
            assert len(set(train.tolist()) & set(test.tolist())) == 0

    def test_step_advances_correctly(self):
        from cryoquant.models.cv import walk_forward
        starts = [int(train[0]) for train, _ in walk_forward(300, 100, 20, step=20)]
        assert starts == list(range(0, len(starts) * 20, 20))

    def test_stops_before_overflow(self):
        from cryoquant.models.cv import walk_forward
        splits = list(walk_forward(100, train_window=80, test_window=30))
        # 80 + 30 = 110 > 100, so no splits
        assert len(splits) == 0

    def test_produces_at_least_one_split(self):
        from cryoquant.models.cv import walk_forward
        splits = list(walk_forward(100, train_window=60, test_window=20))
        assert len(splits) >= 1


# ===========================================================================
# compute_metrics
# ===========================================================================

class TestComputeMetrics:
    def _perfect(self):
        y_true = np.array([0, 0, 1, 1], dtype=float)
        y_prob = np.array([0.1, 0.2, 0.8, 0.9])
        return y_true, y_prob

    def test_all_keys_present(self):
        from cryoquant.models.metrics import compute_metrics
        y_true, y_prob = self._perfect()
        m = compute_metrics(y_true, y_prob)
        for key in ("auc", "brier", "log_loss", "calibration_error",
                    "win_rate_at_thr", "expectancy_at_thr", "n_fires"):
            assert key in m

    def test_perfect_model_auc(self):
        from cryoquant.models.metrics import compute_metrics
        y_true, y_prob = self._perfect()
        m = compute_metrics(y_true, y_prob)
        assert m["auc"] == pytest.approx(1.0)

    def test_n_fires_at_threshold(self):
        from cryoquant.models.metrics import compute_metrics
        y_true = np.array([0, 1, 1, 0], dtype=float)
        y_prob = np.array([0.3, 0.6, 0.8, 0.4])
        m = compute_metrics(y_true, y_prob, threshold=0.5)
        assert m["n_fires"] == 2  # 0.6 and 0.8 >= 0.5

    def test_win_rate_at_thr(self):
        from cryoquant.models.metrics import compute_metrics
        y_true = np.array([1, 1, 0], dtype=float)
        y_prob = np.array([0.9, 0.8, 0.6])
        m = compute_metrics(y_true, y_prob, threshold=0.5)
        assert m["win_rate_at_thr"] == pytest.approx(2 / 3)

    def test_all_finite(self):
        from cryoquant.models.metrics import compute_metrics
        rng = np.random.default_rng(1)
        y_true = rng.integers(0, 2, 200).astype(float)
        y_prob = rng.uniform(0, 1, 200)
        m = compute_metrics(y_true, y_prob)
        for k, v in m.items():
            assert np.isfinite(v), f"metric {k} is not finite: {v}"

    def test_single_class_auc_is_nan(self):
        from cryoquant.models.metrics import compute_metrics
        y_true = np.zeros(10)
        y_prob = np.random.default_rng(0).uniform(0, 1, 10)
        m = compute_metrics(y_true, y_prob)
        assert np.isnan(m["auc"])


# ===========================================================================
# reliability_diagram
# ===========================================================================

class TestReliabilityDiagram:
    def test_returns_dataframe_with_required_cols(self):
        from cryoquant.models.metrics import reliability_diagram
        rng = np.random.default_rng(0)
        y_true = rng.integers(0, 2, 100).astype(float)
        y_prob = rng.uniform(0, 1, 100)
        df = reliability_diagram(y_true, y_prob, n_bins=10)
        for col in ("bin_lower", "bin_upper", "mean_predicted", "fraction_positive", "count"):
            assert col in df.columns

    def test_n_bins_rows(self):
        from cryoquant.models.metrics import reliability_diagram
        rng = np.random.default_rng(1)
        y_true = rng.integers(0, 2, 200).astype(float)
        y_prob = rng.uniform(0, 1, 200)
        df = reliability_diagram(y_true, y_prob, n_bins=5)
        assert len(df) == 5

    def test_count_sums_to_n(self):
        from cryoquant.models.metrics import reliability_diagram
        rng = np.random.default_rng(2)
        y_true = rng.integers(0, 2, 100).astype(float)
        y_prob = rng.uniform(0, 1, 100)
        df = reliability_diagram(y_true, y_prob, n_bins=10)
        assert df["count"].sum() == 100


# ===========================================================================
# Registry
# ===========================================================================

class TestRegistry:
    def test_register_and_retrieve(self, tmp_path):
        from cryoquant.models.registry import get_model, register
        db = tmp_path / "test.duckdb"
        register(
            "abc123", "lgbm",
            feature_set_id="v2spot", feature_set_version="1",
            labeler="mag_win_t2p5_h24",
            hparams={"n_estimators": 200},
            metrics={"auc": 0.58},
            artifact_path=tmp_path / "model.pkl",
            db_path=db,
        )
        row = get_model("abc123", db_path=db)
        assert row is not None
        assert row["model_id"] == "abc123"
        assert row["class"] == "lgbm"

    def test_register_idempotent(self, tmp_path):
        from cryoquant.models.registry import get_model, list_models, register
        db = tmp_path / "idem.duckdb"
        for _ in range(3):
            register("dup_id", "rule", db_path=db)
        df = list_models(db_path=db)
        assert len(df) == 1  # only one row

    def test_get_model_missing_returns_none(self, tmp_path):
        from cryoquant.models.registry import get_model
        db = tmp_path / "empty.duckdb"
        assert get_model("doesnotexist", db_path=db) is None

    def test_list_models_empty_returns_df(self, tmp_path):
        from cryoquant.models.registry import list_models
        db = tmp_path / "empty2.duckdb"
        df = list_models(db_path=db)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_generate_model_id_deterministic(self):
        from cryoquant.models.registry import generate_model_id
        id1 = generate_model_id("lgbm", "v2spot", "1", "mag", {"n_estimators": 200})
        id2 = generate_model_id("lgbm", "v2spot", "1", "mag", {"n_estimators": 200})
        assert id1 == id2

    def test_generate_model_id_differs_on_hparams(self):
        from cryoquant.models.registry import generate_model_id
        id1 = generate_model_id("lgbm", "v2spot", "1", "mag", {"n_estimators": 200})
        id2 = generate_model_id("lgbm", "v2spot", "1", "mag", {"n_estimators": 100})
        assert id1 != id2

    def test_generate_model_id_hparam_order_invariant(self):
        from cryoquant.models.registry import generate_model_id
        id1 = generate_model_id("lgbm", hparams={"a": 1, "b": 2})
        id2 = generate_model_id("lgbm", hparams={"b": 2, "a": 1})
        assert id1 == id2


# ===========================================================================
# CLI
# ===========================================================================

class TestCLIModels:
    def test_models_list_empty(self, tmp_path, monkeypatch):
        import cryoquant.config as cfg
        monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "cat.duckdb")
        from cryoquant.cli import main
        rc = main(["models", "list"])
        assert rc == 0

    def test_models_inspect_missing(self, tmp_path, monkeypatch):
        import cryoquant.config as cfg
        monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "cat.duckdb")
        from cryoquant.cli import main
        rc = main(["models", "inspect", "nonexistent_id"])
        assert rc == 1

    def test_signals_publish_stub(self, capsys, tmp_path, monkeypatch):
        import cryoquant.config as cfg
        monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "cat.duckdb")
        from cryoquant.cli import main
        rc = main(["signals", "publish", "my_signal", "--out", str(tmp_path / "out.parquet")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "my_signal" in out
