"""Statistical validation unit tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryoquant.models.cv import purged_kfold, walk_forward
from cryoquant.models.cpcv import CPCVNotImplemented, combinatorial_purged_cv
from cryoquant.models.validation import (
    LeakageSuspected,
    check_oos_r2_sanity,
    exceedance_prob_from_quantiles,
    leakage_feature_scan,
    permutation_test,
    quantile_cdf_value,
    verify_purged_kfold_embargo,
    verify_walk_forward_embargo,
)


def test_purged_kfold_embargo_excludes_overlap() -> None:
    n = 100
    emb = 5
    for train_idx, test_idx in purged_kfold(n, n_splits=5, embargo_bars=emb):
        assert verify_purged_kfold_embargo(train_idx, test_idx, emb, n)


def test_walk_forward_embargo() -> None:
    n = 300
    emb = 5
    for train_idx, test_idx in walk_forward(n, 120, 30, step=30):
        if emb > 0:
            train_idx = train_idx[train_idx < int(test_idx[0]) - emb]
        if len(train_idx) == 0:
            continue
        assert verify_walk_forward_embargo(train_idx, test_idx, emb)


def test_permutation_collapses_on_synthetic() -> None:
    rng = np.random.default_rng(0)
    n = 400
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    X = pd.DataFrame({"x": rng.normal(size=n)}, index=idx)
    y = pd.Series(rng.integers(0, 2, n), index=idx)

    from cryoquant.models.baselines import NaiveDirectional

    def fit_predict(X_tr, y_tr, X_te):
        m = NaiveDirectional()
        m.fit(X_tr, y_tr)
        return m.predict_proba(X_te)

    def auc_metric(y_true, y_pred):
        from cryoquant.models.metrics import compute_metrics

        return compute_metrics(y_true.astype(bool), y_pred)["auc"]

    result = permutation_test(
        auc_metric,
        X,
        y,
        fit_predict_fn=fit_predict,
        n_permutations=8,
        seed=1,
        higher_is_better=True,
        metric_name="auc",
        min_train=100,
    )
    assert result.n_permutations == 8
    assert 0.35 <= result.real_metric <= 0.65 or np.isnan(result.real_metric)


def test_leakage_scan_flags_fwd_name() -> None:
    feat = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC"),
            "asset": ["BTC"] * 50,
            "fwd_return": np.linspace(0, 1, 50),
            "rsi": np.random.default_rng(0).normal(size=50),
        }
    )
    labels = pd.DataFrame(
        {
            "timestamp": feat["timestamp"],
            "asset": feat["asset"],
            "label_name": ["up_win_volscaled_h1"] * 50,
            "value": np.random.default_rng(1).integers(0, 2, 50),
        }
    )
    report = leakage_feature_scan(feat, labels, corr_threshold=0.99)
    assert any(f.feature == "fwd_return" for f in report.flags)


def test_check_oos_r2_sanity_raises() -> None:
    with pytest.raises(LeakageSuspected):
        check_oos_r2_sanity(0.5, threshold=0.20)


def test_quantile_cdf_monotonic() -> None:
    levels = (0.05, 0.50, 0.95)
    vals = np.array([-0.02, 0.0, 0.02])
    assert quantile_cdf_value(levels, vals, -0.05) <= 0.06
    assert quantile_cdf_value(levels, vals, 0.05) >= 0.94


def test_exceedance_prob_call_put() -> None:
    levels = (0.05, 0.50, 0.95)
    vals = np.array([-0.03, 0.0, 0.03])
    p_call = exceedance_prob_from_quantiles(levels, vals, 0.01, "call")
    p_put = exceedance_prob_from_quantiles(levels, vals, -0.01, "put")
    assert 0.0 <= p_call <= 1.0
    assert 0.0 <= p_put <= 1.0


def test_cpcv_stub_raises() -> None:
    with pytest.raises(CPCVNotImplemented):
        combinatorial_purged_cv()
