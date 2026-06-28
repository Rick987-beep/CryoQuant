"""Causal alignment helpers for BTCpredict Phase 2.

Study-specific wrappers around ``cryoquant.features.align`` for series that
carry explicit publication times (``available_utc``) or calendar semantics (FOMC).

All joins target the **crypto daily index** (UTC midnight bar opens). See
FEATURE_CATALOG.md §Conventions for lag rules vs tradfi series.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from cryoquant.data.sources import fomc_calendar
from cryoquant.features.align import align_series


def align_by_available_utc(
    target_index: pd.DatetimeIndex,
    frame: pd.DataFrame,
    *,
    value_col: str = "value",
    available_col: str = "available_utc",
    ffill_limit: int = 5,
    name: str | None = None,
) -> pd.Series:
    """Align sparse/event frames using ``available_utc`` (backward as-of bar time).

    Used for ETF flows, MSTR events, and Coin Metrics network metrics where
    Phase 1 ingest stores ``(value, available_utc)`` per DATA_SOURCES §E.1 / §G.3.
    """
    if frame is None or frame.empty or value_col not in frame.columns:
        out_name = name or value_col
        return pd.Series(np.nan, index=target_index, name=out_name)

    target_index = pd.DatetimeIndex(target_index).tz_convert("UTC").as_unit("ns")
    avail = pd.DatetimeIndex(pd.to_datetime(frame[available_col], utc=True)).as_unit("ns")
    s = pd.Series(frame[value_col].to_numpy(), index=avail, name=name or value_col)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return align_series(target_index, s, ffill_limit=ffill_limit, name=s.name)


def pct_change_n(s: pd.Series, n: int) -> pd.Series:
    return s.pct_change(n) * 100.0


def rolling_zscore(s: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    mp = min_periods if min_periods is not None else max(window // 2, 2)
    mu = s.rolling(window, min_periods=mp).mean()
    sd = s.rolling(window, min_periods=mp).std(ddof=0).replace(0, np.nan)
    return (s - mu) / sd


def build_fomc_calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Public FOMC **calendar** features (no announcement-outcome lag)."""
    if index.empty:
        return pd.DataFrame(
            columns=[
                "is_fomc_decision_day",
                "days_until_fomc",
                "days_since_fomc",
                "is_fomc_week",
            ]
        )

    start_d = index.min().date()
    end_d = index.max().date()
    decision_dates = sorted(
        d for d in fomc_calendar._FOMC_DECISION_DATES if start_d <= d <= end_d  # noqa: SLF001
    )
    decision_set = set(decision_dates)

    bar_dates = pd.Series([ts.date() for ts in index], index=index)
    is_decision = bar_dates.map(lambda d: 1.0 if d in decision_set else 0.0)

    days_until: list[float] = []
    days_since: list[float] = []
    for d in bar_dates:
        future = [x for x in decision_dates if x >= d]
        past = [x for x in decision_dates if x <= d]
        days_until.append(float((future[0] - d).days) if future else np.nan)
        days_since.append(float((d - past[-1]).days) if past else np.nan)

    iso_weeks = {d: d.isocalendar()[:2] for d in decision_dates}
    decision_weeks = set(iso_weeks.values())
    is_week = bar_dates.map(
        lambda d: 1.0 if d.isocalendar()[:2] in decision_weeks else 0.0
    )

    return pd.DataFrame(
        {
            "is_fomc_decision_day": is_decision.astype(float),
            "days_until_fomc": days_until,
            "days_since_fomc": days_since,
            "is_fomc_week": is_week.astype(float),
        },
        index=index,
    )


def union_daily_index(frames: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """Sorted union of daily DatetimeIndex values from OHLCV frames."""
    parts: list[pd.DatetimeIndex] = []
    for df in frames.values():
        if df is not None and not df.empty:
            idx = pd.DatetimeIndex(df.index)
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
            parts.append(idx)
    if not parts:
        return pd.DatetimeIndex([], tz="UTC")
    out = parts[0]
    for p in parts[1:]:
        out = out.union(p)
    return out.sort_values()
