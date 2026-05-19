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
        self._calibrated: CalibratedClassifierCV = CalibratedClassifierCV(
            base, method=calibration_method, cv=calibration_cv
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
