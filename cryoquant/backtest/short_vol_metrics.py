"""Short-vol-specific metrics (OTM calibration, tail loss, trade Sharpe)."""
from __future__ import annotations

import numpy as np


def cvar_loss(pnl_pct: np.ndarray | list[float], *, alpha: float = 0.05) -> float:
    """Mean P&L in the worst ``alpha`` tail (negative = loss for seller)."""
    arr = np.asarray(pnl_pct, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    if len(arr) == 1:
        return float(arr[0])
    n_tail = max(1, int(np.ceil(alpha * len(arr))))
    sorted_pnl = np.sort(arr)
    return float(np.mean(sorted_pnl[:n_tail]))


def otm_rate_vs_delta(realized_otm: np.ndarray, predicted_otm: np.ndarray) -> dict[str, float]:
    """Compare realized vs predicted OTM rates."""
    r = np.asarray(realized_otm, dtype=float)
    p = np.asarray(predicted_otm, dtype=float)
    valid = np.isfinite(r) & np.isfinite(p)
    r, p = r[valid], p[valid]
    if len(r) == 0:
        return {"n": 0, "realized_otm_rate": float("nan"), "predicted_otm_rate": float("nan"), "gap": float("nan")}
    rr = float(np.mean(r))
    pr = float(np.mean(p))
    return {"n": int(len(r)), "realized_otm_rate": rr, "predicted_otm_rate": pr, "gap": rr - pr}


def calibration_gap(realized_otm_rate: float, implied_delta: float) -> float:
    """Realized OTM minus market-implied OTM (1 - delta for short OTM leg)."""
    return float(realized_otm_rate - (1.0 - implied_delta))


def trade_sharpe(pnl_pct: np.ndarray | list[float], *, periods_per_year: float = 252.0) -> float:
    arr = np.asarray(pnl_pct, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 2:
        return float("nan")
    std = float(np.std(arr, ddof=1))
    if std <= 0:
        return float("nan")
    return float(np.mean(arr) / std * np.sqrt(periods_per_year))
