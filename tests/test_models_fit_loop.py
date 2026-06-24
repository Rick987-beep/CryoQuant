"""Tests for cryoquant.models.fit_loop."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryoquant.models.baselines import RuleModel
from cryoquant.models.fit_loop import concat_oos_probs, walk_forward_fit


def _synthetic_xy(n: int = 200, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    x1 = rng.standard_normal(n)
    x2 = rng.standard_normal(n)
    prob = 1 / (1 + np.exp(-(x1 + 0.5 * x2)))
    y = (prob > 0.5).astype(bool)
    X = pd.DataFrame({"x1": x1, "x2": x2}, index=idx)
    return X, pd.Series(y, index=idx, name="label")


class TestWalkForwardFit:
    def test_returns_fold_results(self) -> None:
        X, y = _synthetic_xy(300)
        rule = RuleModel(
            condition=lambda df: df["x1"] > 0,
            name="test_rule",
        )

        def factory():
            return rule

        results = walk_forward_fit(
            factory,
            X,
            y,
            train_window_bars=120,
            test_window_bars=30,
            step_bars=30,
        )
        assert len(results) >= 1
        assert "auc" in results[0].metrics
        assert results[0].y_prob is not None
        assert len(results[0].y_prob) == 30

    def test_empty_after_dropna(self) -> None:
        X, y = _synthetic_xy(50)
        y = pd.Series(np.nan, index=y.index, name="label")
        results = walk_forward_fit(
            lambda: RuleModel(condition=lambda df: True, name="r"),
            X,
            y,
            train_window_bars=20,
            test_window_bars=10,
        )
        assert results == []


class TestConcatOosProbs:
    def test_stitches_probs(self) -> None:
        from cryoquant.models.fit_loop import FoldResult

        idx1 = pd.date_range("2020-01-01", periods=5, freq="1h", tz="UTC")
        idx2 = pd.date_range("2020-01-06", periods=5, freq="1h", tz="UTC")
        r1 = FoldResult(0, idx1[0], idx1[-1], idx1[0], idx1[-1], {}, pd.Series(0.6, index=idx1))
        r2 = FoldResult(1, idx2[0], idx2[-1], idx2[0], idx2[-1], {}, pd.Series(0.7, index=idx2))
        out = concat_oos_probs([r1, r2])
        assert len(out) == 10

    def test_empty_results(self) -> None:
        assert concat_oos_probs([]).empty
