"""Statistical validation utilities (López de Prado-style harness)."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cryoquant.models.metrics import compute_metrics, reliability_diagram


class LeakageSuspected(Exception):
    """Raised when OOS metric exceeds sanity threshold (likely leakage)."""


@dataclass
class LeakageFlag:
    feature: str
    reason: str
    detail: str
    label: str | None = None
    correlation: float | None = None


@dataclass
class LeakageReport:
    flags: list[LeakageFlag] = field(default_factory=list)
    features_scanned: int = 0
    labels_scanned: int = 0

    @property
    def critical_count(self) -> int:
        return len(self.flags)


@dataclass
class PermutationResult:
    real_metric: float
    perm_metrics: list[float]
    p_value: float
    n_permutations: int
    metric_name: str
    higher_is_better: bool

    @property
    def beats_null(self) -> bool:
        if not np.isfinite(self.p_value):
            return False
        return self.p_value <= 0.05


DEFAULT_NAME_PATTERNS = ("fwd_", "target_", "_lead", "_future", "label_")


def check_oos_r2_sanity(r2: float, threshold: float = 0.20) -> None:
    """Raise LeakageSuspected if R² exceeds threshold on noise-like returns."""
    if np.isfinite(r2) and r2 > threshold:
        raise LeakageSuspected(f"R²={r2:.3f} > {threshold} — possible leakage")


def _name_matches(patterns: tuple[str, ...], col: str) -> bool:
    low = col.lower()
    return any(p in low for p in patterns)


def leakage_feature_scan(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    corr_threshold: float = 0.90,
    name_patterns: tuple[str, ...] = DEFAULT_NAME_PATTERNS,
) -> LeakageReport:
    """Flag features with |corr|>threshold to any label or suspicious names."""
    report = LeakageReport()
    feat_cols = [c for c in features.columns if c not in ("timestamp", "asset")]
    report.features_scanned = len(feat_cols)

    for col in feat_cols:
        if _name_matches(name_patterns, col):
            report.flags.append(
                LeakageFlag(feature=col, reason="name_pattern", detail="suspicious column name")
            )

    if labels.empty or features.empty:
        report.labels_scanned = 0
        return report

    lab = labels.copy()
    lab["timestamp"] = pd.to_datetime(lab["timestamp"], utc=True)
    feat = features.copy()
    feat["timestamp"] = pd.to_datetime(feat["timestamp"], utc=True)

    merged = feat.merge(
        lab,
        on=["timestamp", "asset"],
        how="inner",
    )
    label_names = lab["label_name"].unique()
    report.labels_scanned = len(label_names)

    for lname in label_names:
        sub = merged[merged["label_name"] == lname]
        if sub.empty:
            continue
        y = sub["value"].astype(float)
        for col in feat_cols:
            if col not in sub.columns:
                continue
            x = pd.to_numeric(sub[col], errors="coerce")
            valid = x.notna() & y.notna()
            if valid.sum() < 30:
                continue
            corr = float(x[valid].corr(y[valid]))
            if np.isfinite(corr) and abs(corr) > corr_threshold:
                report.flags.append(
                    LeakageFlag(
                        feature=col,
                        reason="high_correlation",
                        detail=f"|ρ|={abs(corr):.3f} > {corr_threshold}",
                        label=str(lname),
                        correlation=corr,
                    )
                )
    return report


def permutation_p_value(
    real: float,
    permuted: list[float],
    *,
    higher_is_better: bool,
) -> float:
    """One-sided p-value: fraction of permutations at least as good as real."""
    vals = [v for v in permuted if np.isfinite(v)]
    if not vals or not np.isfinite(real):
        return float("nan")
    if higher_is_better:
        return float(np.mean([v >= real for v in vals]))
    return float(np.mean([v <= real for v in vals]))


def permutation_test(
    metric_fn: Callable[[np.ndarray, np.ndarray], float],
    X: pd.DataFrame,
    y: pd.Series,
    *,
    fit_predict_fn: Callable[[pd.DataFrame, pd.Series, pd.DataFrame], np.ndarray],
    n_permutations: int = 10,
    seed: int = 42,
    higher_is_better: bool = True,
    metric_name: str = "metric",
    min_train: int = 200,
    test_frac: float = 0.15,
) -> PermutationResult:
    """Single hold-out permutation test (fast sanity check on synthetic or smoke data).

    Uses last ``test_frac`` of rows as test; train on prior rows. Shuffles ``y`` in train+test
    for null distribution. For walk-forward permutation batteries, orchestrate
    ``permutation_test`` inside your study's validation loop.
    """
    aligned = pd.concat([X, y.rename("_y")], axis=1).dropna(subset=["_y"])
    if len(aligned) < min_train + 20:
        return PermutationResult(
            real_metric=float("nan"),
            perm_metrics=[],
            p_value=float("nan"),
            n_permutations=0,
            metric_name=metric_name,
            higher_is_better=higher_is_better,
        )

    n_test = max(int(len(aligned) * test_frac), 20)
    split = len(aligned) - n_test
    X_tr = aligned.iloc[:split].drop(columns=["_y"])
    y_tr = aligned.iloc[:split]["_y"]
    X_te = aligned.iloc[split:].drop(columns=["_y"])
    y_te = aligned.iloc[split:]["_y"]

    tr_mask = X_tr.notna().all(axis=1)
    te_mask = X_te.notna().all(axis=1)
    X_tr, y_tr = X_tr.loc[tr_mask], y_tr.loc[tr_mask]
    X_te, y_te = X_te.loc[te_mask], y_te.loc[te_mask]
    if len(X_tr) < min_train or len(X_te) < 5:
        return PermutationResult(
            real_metric=float("nan"),
            perm_metrics=[],
            p_value=float("nan"),
            n_permutations=0,
            metric_name=metric_name,
            higher_is_better=higher_is_better,
        )

    real_pred = fit_predict_fn(X_tr, y_tr, X_te)
    real_metric = float(metric_fn(y_te.to_numpy(), real_pred))

    rng = np.random.default_rng(seed)
    perm_metrics: list[float] = []
    y_all = aligned["_y"].to_numpy()
    for _ in range(n_permutations):
        shuffled = rng.permutation(y_all)
        y_tr_p = pd.Series(shuffled[: len(y_tr)], index=y_tr.index)
        y_te_p = pd.Series(shuffled[len(y_tr) : len(y_tr) + len(y_te)], index=y_te.index)
        pred = fit_predict_fn(X_tr, y_tr_p, X_te)
        perm_metrics.append(float(metric_fn(y_te_p.to_numpy(), pred)))

    p = permutation_p_value(real_metric, perm_metrics, higher_is_better=higher_is_better)
    return PermutationResult(
        real_metric=real_metric,
        perm_metrics=perm_metrics,
        p_value=p,
        n_permutations=n_permutations,
        metric_name=metric_name,
        higher_is_better=higher_is_better,
    )


def quantile_cdf_value(
    quantile_levels: tuple[float, ...],
    quantile_values: np.ndarray,
    x: float,
) -> float:
    """Piecewise-linear CDF at ``x`` from predicted quantile knots."""
    levels = np.asarray(quantile_levels, dtype=float)
    values = np.asarray(quantile_values, dtype=float)
    order = np.argsort(values)
    levels = levels[order]
    values = values[order]

    if not np.isfinite(x):
        return float("nan")
    if x <= values[0]:
        return float(levels[0])
    if x >= values[-1]:
        return float(levels[-1])

    idx = np.searchsorted(values, x, side="right")
    x0, x1 = values[idx - 1], values[idx]
    q0, q1 = levels[idx - 1], levels[idx]
    if x1 == x0:
        return float(q1)
    t = (x - x0) / (x1 - x0)
    return float(q0 + t * (q1 - q0))


def exceedance_prob_from_quantiles(
    quantile_levels: tuple[float, ...],
    quantile_values: np.ndarray,
    strike_log_return: float,
    side: str,
) -> float:
    """P(call exceedance) = P(log_return > strike); P(put) = P(log_return < strike)."""
    cdf = quantile_cdf_value(quantile_levels, quantile_values, strike_log_return)
    if side == "call":
        return float(1.0 - cdf)
    if side == "put":
        return float(cdf)
    raise ValueError(f"side must be 'call' or 'put', got {side!r}")


def parse_exceedance_label(label_name: str) -> tuple[str, float, str] | None:
    """Parse exceedance_call_d0p15_h5 -> (side, delta, horizon_suffix)."""
    m = re.match(r"exceedance_(call|put)_d0p(\d+)_h(\d+)", label_name)
    if not m:
        return None
    side, delta_int, h_suffix = m.groups()
    return side, int(delta_int) / 100.0, f"h{h_suffix}"


def calibration_summary(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    n_bins: int = 10,
) -> dict[str, Any]:
    """ECE, Brier, reliability diagram payload."""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    valid = np.isfinite(y_true) & np.isfinite(y_prob)
    y_true, y_prob = y_true[valid], y_prob[valid]
    if len(y_true) == 0:
        return {"n": 0, "ece": float("nan"), "brier": float("nan"), "reliability": []}

    m = compute_metrics(y_true.astype(bool), y_prob)
    rel = reliability_diagram(y_true, y_prob, n_bins=n_bins)
    return {
        "n": int(len(y_true)),
        "ece": m["calibration_error"],
        "brier": m["brier"],
        "reliability": rel.to_dict(orient="records"),
    }


def verify_walk_forward_embargo(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    embargo_bars: int,
) -> bool:
    """Train window must end at least ``embargo_bars`` before test start."""
    if len(test_idx) == 0 or len(train_idx) == 0:
        return True
    test_start = int(test_idx[0])
    max_train = int(train_idx.max())
    if embargo_bars <= 0:
        return max_train < test_start
    return max_train < test_start - embargo_bars


def verify_purged_kfold_embargo(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    embargo_bars: int,
    n: int,
) -> bool:
    """Train must not include test fold or embargo tail."""
    if len(test_idx) == 0:
        return True
    test_start = int(test_idx[0])
    test_end = int(test_idx[-1])
    embargo_end = min(test_end + embargo_bars, n)
    for i in train_idx:
        if test_start <= int(i) < embargo_end:
            return False
    return True


def verify_embargo_excludes_train(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    embargo_bars: int,
) -> bool:
    """Alias for purged-kfold style check (legacy)."""
    n = int(max(train_idx.max() if len(train_idx) else 0, test_idx.max() if len(test_idx) else 0)) + 1
    return verify_purged_kfold_embargo(train_idx, test_idx, embargo_bars, n)
