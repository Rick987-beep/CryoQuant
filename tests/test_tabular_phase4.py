"""CryoQuant tabular / vol baseline unit tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from cryoquant.models.baselines import NaiveRandomWalk, RollingMeanReturn
from cryoquant.models.tabular import QuantileModel, TabularRegressor
from cryoquant.models.vol_baselines import HAR_RVPredictor


def test_tabular_regressor_predict_shape() -> None:
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"a": rng.normal(size=50), "b": rng.normal(size=50)})
    y = pd.Series(rng.normal(size=50))
    m = TabularRegressor(random_state=42)
    m.fit(X, y)
    preds = m.predict(X)
    assert preds.shape == (50,)


def test_quantile_monotonic() -> None:
    rng = np.random.default_rng(1)
    X = pd.DataFrame({"a": rng.normal(size=80)})
    y = pd.Series(rng.normal(size=80) * 0.02)
    m = QuantileModel(quantiles=(0.1, 0.5, 0.9), random_state=42)
    m.fit(X, y)
    q = m.predict_quantiles(X)
    assert (q.iloc[:, 0] <= q.iloc[:, 1] + 1e-9).all()
    assert (q.iloc[:, 1] <= q.iloc[:, 2] + 1e-9).all()


def test_har_rv_baseline() -> None:
    rng = np.random.default_rng(2)
    X = pd.DataFrame({"btc_rv_24": 20 + rng.normal(size=60) * 2})
    y = pd.Series(22 + rng.normal(size=60) * 3)
    m = HAR_RVPredictor(rv_col="btc_rv_24")
    m.fit(X, y)
    preds = m.predict(X)
    assert len(preds) == 60


def test_naive_random_walk() -> None:
    m = NaiveRandomWalk()
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    m.fit(X, pd.Series([0.1, -0.1, 0.2]))
    assert np.allclose(m.predict(X), 0.0)


def test_rolling_mean_return() -> None:
    m = RollingMeanReturn()
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    m.fit(X, pd.Series([0.1, 0.2, 0.3]))
    assert np.allclose(m.predict(X), 0.2)
