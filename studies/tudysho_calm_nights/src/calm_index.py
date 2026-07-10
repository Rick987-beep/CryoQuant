"""Continuous calmness indices (0–1) and causal morning score."""

from __future__ import annotations

import numpy as np
import pandas as pd


def causal_percentile_calm(
    series: pd.Series,
    *,
    window: int = 60,
    min_periods: int = 20,
) -> pd.Series:
    """Causal calm index: 1 = calmer than most of the past *window* days.

    Uses only strictly prior observations (no lookahead). Lower raw values
    imply calmer sessions, so percentile rank is inverted.
    """
    values = series.astype(float).to_numpy()
    out = np.full(len(values), np.nan)
    for i in range(len(values)):
        start = max(0, i - window)
        hist = values[start:i]
        hist = hist[~np.isnan(hist)]
        if len(hist) < min_periods:
            continue
        val = values[i]
        if np.isnan(val):
            continue
        # fraction of past days with strictly lower (calmer) raw extrusion
        calmer_frac = float(np.mean(hist > val))
        out[i] = np.clip(calmer_frac, 0.0, 1.0)
    return pd.Series(out, index=series.index, name=series.name)


def extrusion_calm_index(
    range_norm: pd.Series,
    path_norm: pd.Series | None = None,
    *,
    range_weight: float = 0.7,
    path_weight: float = 0.3,
    window: int = 60,
    min_periods: int = 20,
) -> pd.Series:
    """Composite 0–1 calm index from normalized extrusion (higher = calmer)."""
    m_range = causal_percentile_calm(
        range_norm, window=window, min_periods=min_periods
    )
    if path_norm is None:
        return m_range.rename("calm_index")

    m_path = causal_percentile_calm(
        path_norm, window=window, min_periods=min_periods
    )
    w_sum = range_weight + path_weight
    composite = (range_weight * m_range + path_weight * m_path) / w_sum
    return composite.clip(0.0, 1.0).rename("calm_index")


def attach_calm_indices(
    daily: pd.DataFrame,
    *,
    window: int = 60,
    min_periods: int = 20,
) -> pd.DataFrame:
    """Add morning_calm_index (MCI) and hold_night_calm_index (HCI) columns."""
    from extrusion import normalize_extrusion

    df = daily.sort_values("entry_date").reset_index(drop=True).copy()

    for col, norm_col in [
        ("predictor_path", "predictor_path_norm"),
        ("hold_night_path", "hold_night_path_norm"),
    ]:
        if norm_col not in df.columns and col in df.columns:
            df[norm_col] = normalize_extrusion(
                df[col], rolling=window, entry_dates=df["entry_date"]
            )

    df["morning_calm_index"] = extrusion_calm_index(
        df["predictor_range_norm"],
        df.get("predictor_path_norm"),
        window=window,
        min_periods=min_periods,
    )

    if "hold_night_range_norm" in df.columns:
        df["hold_night_calm_index"] = extrusion_calm_index(
            df["hold_night_range_norm"],
            df.get("hold_night_path_norm"),
            window=window,
            min_periods=min_periods,
        )

    return df
