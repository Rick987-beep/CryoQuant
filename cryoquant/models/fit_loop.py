"""Walk-forward model fitting loop."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from cryoquant.models.cv import walk_forward
from cryoquant.models.metrics import compute_metrics, compute_regression_metrics

TaskKind = Literal["classification", "regression", "quantile"]


@dataclass
class FoldResult:
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    metrics: dict[str, float]
    y_prob: pd.Series | None = None
    y_pred: pd.Series | None = None
    y_quantiles: pd.DataFrame | None = None


def walk_forward_fit(
    model_factory: Callable[[], Any],
    X: pd.DataFrame,
    y: pd.Series,
    *,
    train_window_bars: int,
    test_window_bars: int,
    step_bars: int | None = None,
    embargo_bars: int = 0,
    threshold: float = 0.5,
    task: TaskKind = "classification",
    metrics_fn: Callable | None = None,
) -> list[FoldResult]:
    """Walk-forward train/predict over aligned ``X`` and ``y``.

    Rows with NaN in ``y`` are dropped before splitting.  Each fold fits a fresh
    model from ``model_factory()`` on the training window and predicts on the
    test window.

    *task*:
        ``classification`` — expects ``predict_proba``; metrics via ``compute_metrics``.
        ``regression`` — expects ``predict``; metrics via ``compute_regression_metrics``.
        ``quantile`` — expects ``predict_quantiles``; pinball loss in metrics.
    """
    aligned = pd.concat([X, y.rename("_y")], axis=1).dropna(subset=["_y"])
    if aligned.empty:
        return []

    X_clean = aligned.drop(columns=["_y"])
    y_clean = aligned["_y"]

    if task == "classification":
        y_clean = y_clean.astype(bool)
        default_metrics = compute_metrics
    else:
        y_clean = y_clean.astype(float)
        default_metrics = compute_regression_metrics

    metrics_fn = metrics_fn or default_metrics

    n = len(aligned)
    results: list[FoldResult] = []
    fold_id = 0

    for train_idx, test_idx in walk_forward(
        n, train_window_bars, test_window_bars, step=step_bars
    ):
        if embargo_bars > 0:
            train_idx = train_idx[train_idx < int(test_idx[0]) - embargo_bars]
            if len(train_idx) == 0:
                continue

        X_tr = X_clean.iloc[train_idx]
        y_tr = y_clean.iloc[train_idx]
        X_te = X_clean.iloc[test_idx]
        y_te = y_clean.iloc[test_idx]

        if len(X_tr) < 10 or len(X_te) < 1:
            continue

        # Drop rows with NaN features on train/test
        tr_mask = X_tr.notna().all(axis=1)
        te_mask = X_te.notna().all(axis=1)
        X_tr, y_tr = X_tr.loc[tr_mask], y_tr.loc[tr_mask]
        X_te, y_te = X_te.loc[te_mask], y_te.loc[te_mask]
        if len(X_tr) < 10 or len(X_te) < 1:
            continue

        model = model_factory()
        model.fit(X_tr, y_tr)

        y_prob = None
        y_pred = None
        y_quantiles = None
        metrics: dict[str, float]

        if task == "classification":
            probs = model.predict_proba(X_te)
            if hasattr(probs, "ndim") and probs.ndim > 1:
                probs = probs[:, 1]
            probs = np.asarray(probs, dtype=float)
            y_prob = pd.Series(probs, index=X_te.index, name="prob")
            metrics = metrics_fn(y_te, probs, threshold=threshold)
        elif task == "quantile":
            qdf = model.predict_quantiles(X_te)
            y_quantiles = qdf
            y_pred = pd.Series(model.predict(X_te), index=X_te.index, name="pred")
            metrics = metrics_fn(y_te, y_pred.to_numpy(), quantile_preds=qdf)
        else:
            preds = np.asarray(model.predict(X_te), dtype=float)
            y_pred = pd.Series(preds, index=X_te.index, name="pred")
            metrics = metrics_fn(y_te, preds)

        results.append(
            FoldResult(
                fold_id=fold_id,
                train_start=pd.Timestamp(X_tr.index[0]),
                train_end=pd.Timestamp(X_tr.index[-1]),
                test_start=pd.Timestamp(X_te.index[0]),
                test_end=pd.Timestamp(X_te.index[-1]),
                metrics=metrics,
                y_prob=y_prob,
                y_pred=y_pred,
                y_quantiles=y_quantiles,
            )
        )
        fold_id += 1

    return results


def concat_oos_probs(results: list[FoldResult]) -> pd.Series:
    """Stitch out-of-sample probabilities across folds (later folds win on overlap)."""
    parts: list[pd.Series] = []
    for r in results:
        if r.y_prob is not None and not r.y_prob.empty:
            parts.append(r.y_prob)
    if not parts:
        return pd.Series(dtype=float)
    combined = pd.concat(parts)
    return combined[~combined.index.duplicated(keep="last")].sort_index()


def concat_oos_preds(results: list[FoldResult]) -> pd.Series:
    """Stitch OOS point predictions across folds."""
    parts: list[pd.Series] = []
    for r in results:
        if r.y_pred is not None and not r.y_pred.empty:
            parts.append(r.y_pred)
    if not parts:
        return pd.Series(dtype=float)
    combined = pd.concat(parts)
    return combined[~combined.index.duplicated(keep="last")].sort_index()
