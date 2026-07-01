"""Volatility forecast baselines — HAR-RV style persistence model."""
from __future__ import annotations

import numpy as np
import pandas as pd


class HAR_RVPredictor:
    """HAR-RV using daily RV column plus short/long rolling means of that column.

    Expects *X* to contain a column named ``rv_col`` (e.g. ``btc_rv_24``).
    Falls back to training-set mean of *y* when the column is missing.
    """

    name = "har_rv"

    def __init__(self, rv_col: str | None = None) -> None:
        self.rv_col = rv_col
        self._coef: np.ndarray | None = None
        self._fallback: float = 0.0
        self._feature_cols: list[str] = []

    @property
    def model_id(self) -> str:
        return self.name

    def _design(self, X: pd.DataFrame, rv: pd.Series) -> np.ndarray:
        rv = rv.reindex(X.index)
        rv_w = rv.rolling(5, min_periods=1).mean()
        rv_m = rv.rolling(22, min_periods=1).mean()
        return np.column_stack(
            [np.ones(len(X)), rv.to_numpy(), rv_w.to_numpy(), rv_m.to_numpy()]
        )

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._fallback = float(np.nanmean(y))
        col = self.rv_col
        if col is None or col not in X.columns:
            self._coef = None
            return
        rv = X[col].astype(float)
        design = self._design(X, rv)
        mask = ~(np.isnan(design).any(axis=1) | np.isnan(y.to_numpy()))
        if mask.sum() < 4:
            self._coef = None
            return
        self._coef, _, _, _ = np.linalg.lstsq(design[mask], y.to_numpy()[mask], rcond=None)
        self._feature_cols = [col]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self._coef is None or self.rv_col is None or self.rv_col not in X.columns:
            return np.full(len(X), self._fallback, dtype=float)
        rv = X[self.rv_col].astype(float)
        design = self._design(X, rv)
        pred = design @ self._coef
        return np.where(np.isfinite(pred), pred, self._fallback)
