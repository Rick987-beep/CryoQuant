"""Model evaluation metrics.

compute_metrics()     — AUC, Brier, log_loss, ECE, win-rate and expectancy at threshold.
reliability_diagram() — fraction-positive vs mean-predicted-probability per bin.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss
from sklearn.metrics import log_loss as _sk_log_loss
from sklearn.metrics import roc_auc_score


def compute_metrics(
    y_true: np.ndarray | pd.Series,
    y_prob: np.ndarray | pd.Series,
    threshold: float = 0.5,
) -> dict:
    """Compute a standard set of binary classification metrics.

    Args:
        y_true:    Binary labels (0/1 or bool).
        y_prob:    Predicted positive-class probabilities.
        threshold: Decision threshold for win_rate_at_thr / expectancy_at_thr.

    Returns:
        dict with keys:
            auc, brier, log_loss, calibration_error,
            win_rate_at_thr, expectancy_at_thr, n_fires.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    valid = ~(np.isnan(y_true) | np.isnan(y_prob))
    y_true, y_prob = y_true[valid], y_prob[valid]

    single_class = len(np.unique(y_true)) < 2

    auc = float("nan") if single_class else float(roc_auc_score(y_true, y_prob))
    brier = float("nan") if single_class else float(brier_score_loss(y_true, y_prob))
    ll = float("nan") if single_class else float(
        _sk_log_loss(y_true, np.column_stack([1.0 - y_prob, y_prob]))
    )
    cal_err = float("nan") if single_class else float(_ece(y_true, y_prob))

    fired = y_prob >= threshold
    n_fires = int(fired.sum())
    win_rate = float(y_true[fired].mean()) if n_fires > 0 else float("nan")
    expectancy = float((2.0 * y_true[fired] - 1.0).mean()) if n_fires > 0 else float("nan")

    return {
        "auc": auc,
        "brier": brier,
        "log_loss": ll,
        "calibration_error": cal_err,
        "win_rate_at_thr": win_rate,
        "expectancy_at_thr": expectancy,
        "n_fires": n_fires,
    }


def reliability_diagram(
    y_true: np.ndarray | pd.Series,
    y_prob: np.ndarray | pd.Series,
    n_bins: int = 10,
) -> pd.DataFrame:
    """Build a calibration (reliability) diagram as a DataFrame.

    Returns columns: bin_lower, bin_upper, mean_predicted, fraction_positive, count.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    valid = ~(np.isnan(y_true) | np.isnan(y_prob))
    y_true, y_prob = y_true[valid], y_prob[valid]

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (y_prob >= lo) & (y_prob < hi)
        n = int(mask.sum())
        rows.append({
            "bin_lower": round(float(lo), 4),
            "bin_upper": round(float(hi), 4),
            "mean_predicted": float(y_prob[mask].mean()) if n > 0 else float("nan"),
            "fraction_positive": float(y_true[mask].mean()) if n > 0 else float("nan"),
            "count": n,
        })
    return pd.DataFrame(rows)


def _ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error."""
    total = len(y_true)
    if total == 0:
        return float("nan")
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (y_prob >= lo) & (y_prob < hi)
        n = mask.sum()
        if n == 0:
            continue
        avg_conf = float(y_prob[mask].mean())
        avg_acc = float(y_true[mask].mean())
        ece += (n / total) * abs(avg_conf - avg_acc)
    return ece


def compute_regression_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    *,
    quantile_preds: pd.DataFrame | None = None,
) -> dict[str, float]:
    """MAE, RMSE, R²; optional mean pinball loss when quantile_preds supplied."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    valid = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_true, y_pred = y_true[valid], y_pred[valid]
    if len(y_true) == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "r2": float("nan")}

    err = y_true - y_pred
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = float("nan") if ss_tot == 0 else float(1.0 - ss_res / ss_tot)

    out = {"mae": mae, "rmse": rmse, "r2": r2}
    if quantile_preds is not None and not quantile_preds.empty:
        out["pinball_loss"] = float(_mean_pinball(y_true, quantile_preds))
    return out


def qlike(y_true: np.ndarray | pd.Series, y_pred: np.ndarray | pd.Series) -> float:
    """QLIKE loss for variance/vol forecasts (positive values only)."""
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    valid = (y > 0) & (p > 0) & np.isfinite(y) & np.isfinite(p)
    if valid.sum() == 0:
        return float("nan")
    y, p = y[valid], p[valid]
    return float(np.mean(np.log(p / y) + y / p - 1.0))


def _mean_pinball(y_true: np.ndarray, quantile_preds: pd.DataFrame) -> float:
    """Average pinball loss across quantile columns."""
    losses: list[float] = []
    n = len(quantile_preds.columns)
    for col in quantile_preds.columns:
        # infer quantile from q05 -> 0.05
        q_str = col.lstrip("q")
        q = int(q_str) / 100.0
        pred = quantile_preds[col].to_numpy(dtype=float)
        diff = y_true - pred
        losses.append(float(np.nanmean(np.where(diff >= 0, q * diff, (q - 1.0) * diff))))
    return float(np.mean(losses)) if losses else float("nan")
