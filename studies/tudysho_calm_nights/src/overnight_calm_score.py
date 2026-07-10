"""Overnight calm score — forward-looking composite for entry gating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CalmScoreWeights:
    morning_extrusion: float = 0.35
    turbulence_decay: float = 0.25
    turbulence_composite: float = 0.20
    iv_implied_calm: float = 0.20


def _norm_calm(series: pd.Series) -> pd.Series:
    """Lower raw values → higher calm score in [0, 1]."""
    s = series.astype(float)
    lo = s.quantile(0.05)
    hi = s.quantile(0.95)
    if hi <= lo:
        return pd.Series(0.5, index=s.index)
    inv = 1.0 - (s - lo) / (hi - lo)
    return inv.clip(0.0, 1.0)


def iv_implied_calm(atm_iv: pd.Series, hold_extrusion_hist: pd.Series) -> pd.Series:
    """IV-implied move vs historical hold extrusion — lower ratio = calmer."""
    ratio = atm_iv / hold_extrusion_hist.replace(0, np.nan)
    return _norm_calm(ratio)


def compute_overnight_calm_score(
    daily: pd.DataFrame,
    *,
    weights: CalmScoreWeights | None = None,
) -> pd.Series:
    """Composite calm score 0–1 (higher = calmer, safer to sell premium)."""
    w = weights or CalmScoreWeights()
    df = daily.copy()

    components: dict[str, pd.Series] = {}

    if "us_morning_range_norm" in df.columns:
        components["morning"] = _norm_calm(df["us_morning_range_norm"])

    if "turbulence_decay_score_12" in df.columns:
        components["decay"] = _norm_calm(100.0 - df["turbulence_decay_score_12"])

    if "turbulence_composite_12" in df.columns:
        components["turb"] = _norm_calm(df["turbulence_composite_12"])

    if "atm_iv" in df.columns and "hold_night_range" in df.columns:
        components["iv"] = iv_implied_calm(df["atm_iv"], df["hold_night_range"])

    if not components:
        return pd.Series(np.nan, index=df.index)

    score = pd.Series(0.0, index=df.index)
    total_w = 0.0
    weight_map = {
        "morning": w.morning_extrusion,
        "decay": w.turbulence_decay,
        "turb": w.turbulence_composite,
        "iv": w.iv_implied_calm,
    }
    for key, comp in components.items():
        wt = weight_map.get(key, 0.0)
        score = score + comp.fillna(0.5) * wt
        total_w += wt

    if total_w > 0:
        score = score / total_w
    return score.clip(0.0, 1.0)


def threshold_sweep(
    daily: pd.DataFrame,
    score: pd.Series,
    *,
    thresholds: list[float] | None = None,
    tail_col: str = "is_tail",
) -> list[dict[str, Any]]:
    """Coverage vs tail capture across score thresholds."""
    if thresholds is None:
        thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    if tail_col not in daily.columns:
        daily = daily.copy()
        daily[tail_col] = False

    results = []
    n = len(daily)
    n_tail = int(daily[tail_col].sum())
    for thr in thresholds:
        mask = score >= thr
        coverage = float(mask.sum() / n) if n else 0.0
        tails_caught = int((mask & daily[tail_col]).sum())
        tail_recall = float(tails_caught / n_tail) if n_tail else float("nan")
        results.append(
            {
                "threshold": thr,
                "coverage": coverage,
                "tail_recall": tail_recall,
                "n_selected": int(mask.sum()),
            }
        )
    return results


def evaluate_vs_turbulence_only(
    daily: pd.DataFrame,
    score: pd.Series | None = None,
    *,
    tail_col: str = "is_tail",
    turb_col: str = "turbulence_composite_12",
    turb_threshold: float = 60.0,
    score_col: str = "overnight_calm_score",
) -> dict[str, Any]:
    """Compare calm score gating vs turbulence-only at fixed coverage."""
    if tail_col not in daily.columns:
        return {"status": "no_tail_labels"}

    if score_col not in daily.columns and score is not None:
        daily = daily.copy()
        daily[score_col] = score

    sub = daily.dropna(subset=[score_col, turb_col])
    if sub.empty:
        return {"status": "insufficient_data"}

    scores = sub[score_col]
    med = scores.median()
    score_mask = scores >= med
    turb_mask = sub[turb_col] < turb_threshold

    def tail_rate(mask: pd.Series) -> float:
        sel = sub.loc[mask]
        if sel.empty:
            return float("nan")
        return float(sel[tail_col].mean())

    return {
        "score_median_threshold": float(med),
        "tail_rate_score_gate": tail_rate(score_mask),
        "tail_rate_turbulence_gate": tail_rate(turb_mask),
        "coverage_score_gate": float(score_mask.mean()),
        "coverage_turbulence_gate": float(turb_mask.mean()),
        "score_beats_turbulence": tail_rate(score_mask) < tail_rate(turb_mask),
    }
