"""Threshold selection utilities.

pick_threshold(y_true, y_prob, target, value) -> float
    Binary-search over the probability threshold to satisfy a target metric.
    Supported targets: "precision", "recall", "f1".
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import precision_recall_curve


def pick_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    target: str = "precision",
    value: float = 0.6,
) -> float:
    """Find the lowest probability threshold that achieves a target metric value.

    Args:
        y_true:  Binary labels (0/1 or bool).
        y_prob:  Predicted positive-class probabilities.
        target:  "precision" | "recall" | "f1".
        value:   Desired metric value.

    Returns:
        Probability threshold in [0, 1].
        Falls back to the highest threshold if the target is not achievable.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    precision, recall, thresholds = precision_recall_curve(y_true, y_prob)
    # precision_recall_curve returns arrays of length n+1, n+1, n
    # precision[i] and recall[i] correspond to thresholds[i] for i < len(thresholds)
    prec = precision[:-1]
    rec = recall[:-1]

    if target == "precision":
        idx = np.where(prec >= value)[0]
        if len(idx) == 0:
            return float(thresholds[-1])
        # Highest threshold that still meets precision (most selective)
        return float(thresholds[idx[-1]])

    if target == "recall":
        idx = np.where(rec >= value)[0]
        if len(idx) == 0:
            return float(thresholds[0])
        # Lowest threshold that meets recall (least selective)
        return float(thresholds[idx[0]])

    if target == "f1":
        denom = prec + rec
        with np.errstate(invalid="ignore"):
            f1 = np.where(denom > 0, 2.0 * prec * rec / denom, 0.0)
        return float(thresholds[int(np.argmax(f1))])

    raise ValueError(f"Unknown target {target!r}. Use 'precision', 'recall', or 'f1'.")
