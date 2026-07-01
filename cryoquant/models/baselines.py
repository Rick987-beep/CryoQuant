"""Rule-based baseline models.

Each RuleModel wraps a single Boolean condition, fits an empirical win rate, and
returns that rate as a probability wherever the condition fires.

Concrete rule factories (ported from reference/long_tradable_options/06_v2_spot_signals.py):
    make_pullback()   — 4h up-trend + 1h pullback (calls entry)
    make_vol_burst()  — volume spike in elevated vol regime (straddle)
    make_bear_burst() — 4h down-trend + 1h bounce (puts entry)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


class RuleModel:
    """Binary classifier driven by a hand-crafted Boolean condition.

    fit()           records empirical win rate where condition fires.
    predict_proba() returns 1-D positive-class probabilities (shape N).
    save() / load() use JSON — no heavy dependencies.
    """

    def __init__(self, condition: Callable[[pd.DataFrame], pd.Series], name: str) -> None:
        self.name = name
        self.condition = condition
        self._win_rate: float = 0.5
        self._n_fires: int = 0

    # ------------------------------------------------------------------
    # Model protocol
    # ------------------------------------------------------------------

    @property
    def model_id(self) -> str:
        return self.name

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        fired = self._apply(X)
        self._n_fires = int(fired.sum())
        if self._n_fires > 0:
            self._win_rate = float(y.loc[fired[fired].index].mean())

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return 1-D array of positive-class probabilities."""
        fired = self._apply(X)
        return np.where(fired.values, self._win_rate, 1.0 - self._win_rate).astype(float)

    def save(self, path: Path | str) -> None:
        data = {"name": self.name, "win_rate": self._win_rate, "n_fires": self._n_fires}
        Path(path).write_text(json.dumps(data))

    @classmethod
    def load(cls, path: Path | str) -> "RuleModel":
        data = json.loads(Path(path).read_text())
        obj = cls(condition=lambda _df: pd.Series(dtype=bool), name=data["name"])
        obj._win_rate = data["win_rate"]
        obj._n_fires = data["n_fires"]
        return obj

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply(self, X: pd.DataFrame) -> pd.Series:
        result = self.condition(X)
        return result.fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# Condition functions (ported from 06_v2_spot_signals.py)
# ---------------------------------------------------------------------------

def _pullback_cond(df: pd.DataFrame) -> pd.Series:
    """4h up-trend (ret_4h >= +1%) + 1h pullback (ret_1h <= -0.5%)."""
    return (df["ret_4h"] >= 1.0) & (df["ret_1h"] <= -0.5)


def _vol_burst_cond(df: pd.DataFrame) -> pd.Series:
    """Volume spike (vol_z >= 1.5) + elevated vol regime (rv_rank >= 0.60)."""
    return (df["vol_z"] >= 1.5) & (df["rv_rank"] >= 0.60)


def _bear_burst_cond(df: pd.DataFrame) -> pd.Series:
    """4h down-trend (ret_4h <= -1%) + 1h bounce (ret_1h >= +0.5%)."""
    return (df["ret_4h"] <= -1.0) & (df["ret_1h"] >= 0.5)


# ---------------------------------------------------------------------------
# Factory functions — always return a fresh, unfitted instance
# ---------------------------------------------------------------------------

def make_pullback() -> RuleModel:
    """4h up-trend + 1h pullback (calls-biased)."""
    return RuleModel(condition=_pullback_cond, name="pullback")


def make_vol_burst() -> RuleModel:
    """Volume spike + elevated vol regime (straddle-biased)."""
    return RuleModel(condition=_vol_burst_cond, name="vol_burst")


def make_bear_burst() -> RuleModel:
    """4h down-trend + 1h bounce (puts-biased)."""
    return RuleModel(condition=_bear_burst_cond, name="bear_burst")


# ---------------------------------------------------------------------------
# Reference predictors for walk-forward baselines
# ---------------------------------------------------------------------------


class NaiveRandomWalk:
    """Predict zero log-return (random walk in log space)."""

    name = "naive_random_walk"

    @property
    def model_id(self) -> str:
        return self.name

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        return None

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(X), dtype=float)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), 0.5, dtype=float)


class RollingMeanReturn:
    """Predict constant = mean training label (momentum-agnostic baseline)."""

    name = "rolling_mean_return"

    def __init__(self) -> None:
        self._mean: float = 0.0

    @property
    def model_id(self) -> str:
        return self.name

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._mean = float(np.nanmean(y))

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self._mean, dtype=float)


class RidgePredictor:
    """Ridge regression on numeric features (train-only scaling expected upstream)."""

    name = "ridge"

    def __init__(self, alpha: float = 1.0, random_state: int = 42) -> None:
        self._model = Ridge(alpha=alpha, random_state=random_state)
        self._feature_names: list[str] = []

    @property
    def model_id(self) -> str:
        return self.name

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._feature_names = list(X.columns)
        self._model.fit(X, y)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self._feature_names:
            X = X[self._feature_names]
        return np.asarray(self._model.predict(X), dtype=float)


class NaiveDirectional:
    """Predict training-set positive rate for binary directional labels."""

    name = "naive_directional"

    def __init__(self) -> None:
        self._rate: float = 0.5

    @property
    def model_id(self) -> str:
        return self.name

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        yb = np.asarray(y, dtype=float)
        self._rate = float(np.nanmean(yb)) if len(yb) else 0.5

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self._rate, dtype=float)
