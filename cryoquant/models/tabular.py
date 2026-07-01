"""TabularModel — LGBMClassifier wrapped in isotonic calibration.

Always uses CalibratedClassifierCV so predict_proba is well-calibrated.
predict_proba() returns 1-D positive-class probabilities.
feature_importances_ averages across calibration folds.
save() / load() use joblib.
"""
from __future__ import annotations

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import StratifiedKFold

log = logging.getLogger(__name__)


class TabularModel:
    """sklearn-compatible tabular classifier with built-in isotonic calibration.

    Parameters
    ----------
    estimator:
        Base classifier.  Defaults to LGBMClassifier with sane hyperparameters.
    calibration_method:
        "isotonic" (default) or "sigmoid".
    calibration_cv:
        Number of CV folds for calibration.  Set to "prefit" to calibrate a
        pre-fitted estimator (then pass estimator=<fitted>).
    """

    def __init__(
        self,
        estimator=None,
        calibration_method: str = "isotonic",
        calibration_cv: int | str = 5,
    ) -> None:
        base = estimator or LGBMClassifier(
            n_estimators=200,
            num_leaves=31,
            learning_rate=0.05,
            random_state=42,
            verbose=-1,
        )
        self._calibration_method = calibration_method
        if isinstance(calibration_cv, int):
            cv: int | str | StratifiedKFold = StratifiedKFold(
                n_splits=calibration_cv,
                shuffle=True,
                random_state=42,
            )
        else:
            cv = calibration_cv
        self._calibrated: CalibratedClassifierCV = CalibratedClassifierCV(
            base, method=calibration_method, cv=cv
        )
        self._feature_names: list[str] = []
        self._is_fitted: bool = False

    # ------------------------------------------------------------------
    # Model protocol
    # ------------------------------------------------------------------

    @property
    def model_id(self) -> str:
        return "tabular"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._feature_names = list(X.columns)
        y_bin = np.asarray(y).astype(int)
        if len(y_bin) == 0:
            raise ValueError("Cannot fit TabularModel on empty y")
        counts = np.bincount(y_bin)
        if len(counts) < 2 or counts.min() == 0:
            raise ValueError("TabularModel requires both classes in y")
        min_class = int(counts.min())
        n_splits = max(2, min(3, min_class))
        base = self._calibrated.estimator
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        self._calibrated = CalibratedClassifierCV(
            base,
            method=self._calibration_method,
            cv=cv,
        )
        self._calibrated.fit(X, y)
        self._is_fitted = True
        log.debug("TabularModel fitted on %d samples, %d features", len(X), len(X.columns))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return 1-D array of positive-class probabilities, shape (n_samples,).

        If *X* is a DataFrame and the model has stored feature names, only the
        trained feature columns are selected — extra columns (e.g. OHLCV
        passthroughs) are silently ignored.
        """
        if isinstance(X, pd.DataFrame) and self._feature_names:
            X = X[self._feature_names]
        return self._calibrated.predict_proba(X)[:, 1]

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        log.debug("Saved TabularModel to %s", path)

    @classmethod
    def load(cls, path: Path | str) -> "TabularModel":
        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError(f"Expected TabularModel, got {type(model)}")
        return model

    # ------------------------------------------------------------------
    # Extra helpers
    # ------------------------------------------------------------------

    @property
    def feature_importances_(self) -> pd.Series | None:
        """Average feature importances across calibration folds (None if unavailable)."""
        if not self._is_fitted:
            return None
        imps = []
        for cc in self._calibrated.calibrated_classifiers_:
            est = cc.estimator
            if hasattr(est, "feature_importances_"):
                imps.append(est.feature_importances_)
        if not imps:
            return None
        arr = np.mean(imps, axis=0)
        return pd.Series(arr, index=self._feature_names, name="importance").sort_values(
            ascending=False
        )


class TabularRegressor:
    """LightGBM regressor with the same fit/predict/save API as TabularModel."""

    def __init__(self, estimator=None, random_state: int = 42) -> None:
        from lightgbm import LGBMRegressor

        self._estimator = estimator or LGBMRegressor(
            n_estimators=200,
            num_leaves=31,
            learning_rate=0.05,
            random_state=random_state,
            verbose=-1,
        )
        self._feature_names: list[str] = []
        self._is_fitted: bool = False
        self._random_state = random_state

    @property
    def model_id(self) -> str:
        return "tabular_regressor"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._feature_names = list(X.columns)
        self._estimator.fit(X, y)
        self._is_fitted = True
        log.debug(
            "TabularRegressor fitted on %d samples, %d features",
            len(X),
            len(X.columns),
        )

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if isinstance(X, pd.DataFrame) and self._feature_names:
            X = X[self._feature_names]
        return np.asarray(self._estimator.predict(X), dtype=float)

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path | str) -> "TabularRegressor":
        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError(f"Expected TabularRegressor, got {type(model)}")
        return model

    @property
    def feature_importances_(self) -> pd.Series | None:
        if not self._is_fitted or not hasattr(self._estimator, "feature_importances_"):
            return None
        return pd.Series(
            self._estimator.feature_importances_,
            index=self._feature_names,
            name="importance",
        ).sort_values(ascending=False)


class QuantileModel:
    """One LightGBM quantile regressor per quantile level."""

    DEFAULT_QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

    def __init__(
        self,
        quantiles: tuple[float, ...] | list[float] | None = None,
        lgbm_params: dict | None = None,
        random_state: int = 42,
    ) -> None:
        self.quantiles = tuple(sorted(set(quantiles or self.DEFAULT_QUANTILES)))
        self._lgbm_params = dict(lgbm_params or {})
        self._random_state = random_state
        self._models: dict[float, object] = {}
        self._feature_names: list[str] = []
        self._is_fitted: bool = False

    @property
    def model_id(self) -> str:
        return "quantile_lgbm"

    def _make_estimator(self, alpha: float):
        from lightgbm import LGBMRegressor

        params = {
            "objective": "quantile",
            "alpha": alpha,
            "n_estimators": 150,
            "num_leaves": 15,
            "max_depth": 4,
            "min_child_samples": 50,
            "learning_rate": 0.05,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": self._random_state,
            "verbose": -1,
        }
        params.update(self._lgbm_params)
        params["objective"] = "quantile"
        params["alpha"] = alpha
        return LGBMRegressor(**params)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._feature_names = list(X.columns)
        self._models = {}
        for q in self.quantiles:
            est = self._make_estimator(q)
            est.fit(X, y)
            self._models[q] = est
        self._is_fitted = True

    def predict_quantiles(self, X: pd.DataFrame) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame) and self._feature_names:
            X = X[self._feature_names]
        cols: dict[str, np.ndarray] = {}
        for q in self.quantiles:
            cols[f"q{int(round(q * 100)):02d}"] = self._models[q].predict(X)
        out = pd.DataFrame(cols, index=X.index if isinstance(X, pd.DataFrame) else None)
        return _enforce_monotonic_quantiles(out)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        qcols = self.predict_quantiles(X)
        med_col = f"q{int(round(0.50 * 100)):02d}"
        if med_col in qcols.columns:
            return qcols[med_col].to_numpy(dtype=float)
        mid = qcols.columns[len(qcols.columns) // 2]
        return qcols[mid].to_numpy(dtype=float)

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path | str) -> "QuantileModel":
        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError(f"Expected QuantileModel, got {type(model)}")
        return model


def _enforce_monotonic_quantiles(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure q05 <= q10 <= ... <= q95 row-wise."""
    arr = df.to_numpy(dtype=float).copy()
    for i in range(arr.shape[0]):
        arr[i] = np.maximum.accumulate(arr[i])
    return pd.DataFrame(arr, index=df.index, columns=df.columns)
