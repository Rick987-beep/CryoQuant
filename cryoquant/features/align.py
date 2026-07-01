"""Align time series onto a target bar index (closed-bar safe for daily macro).

Public helpers for joining OHLCV bars with macro/scalar series from different
frequencies or timestamps.  For higher-timeframe bar alignment onto a lower-TF
frame, use ``primitives.htf_align`` instead.

Public interface::

    align_series, align_frame_column, align_many, join_features
    align_by_available_utc  — event frames with publication-time index
    union_daily_index       — sorted union of daily OHLCV indices
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

DEFAULT_FFILL_LIMIT_DAYS = 35


def align_series(
    target_index: pd.DatetimeIndex,
    series: pd.Series,
    *,
    method: Literal["asof", "ffill"] = "asof",
    ffill_limit: int | None = DEFAULT_FFILL_LIMIT_DAYS,
    name: str | None = None,
) -> pd.Series:
    """Align ``series`` onto ``target_index``.

    Args:
        target_index: UTC (or tz-aware) DatetimeIndex to align onto.
        series: Source values indexed by timestamp.
        method: ``asof`` — merge_asof backward (macro onto bars); ``ffill`` —
            ``reindex`` forward-fill for same-frequency data.
        ffill_limit: For ``asof``, calendar days after which stale values become
            NaN.  ``None`` disables the staleness cap.
        name: Output series name; defaults to ``series.name``.

    Returns:
        pd.Series aligned to ``target_index``.
    """
    out_name = name if name is not None else series.name

    if series is None or series.empty:
        return pd.Series(np.nan, index=target_index, name=out_name)

    if method == "ffill":
        s = _ensure_utc_index(series)
        result = s.reindex(target_index, method="ffill")
        result.name = out_name
        return result

    return _align_asof(target_index, series, ffill_limit=ffill_limit, name=out_name)


def align_frame_column(
    target_index: pd.DatetimeIndex,
    frame: pd.DataFrame,
    column: str = "close",
    **kwargs,
) -> pd.Series:
    """Align a single column from ``frame`` onto ``target_index``."""
    if column not in frame.columns:
        raise KeyError(f"column {column!r} not in frame (have {list(frame.columns)})")
    return align_series(target_index, frame[column], **kwargs)


def align_many(
    target_index: pd.DatetimeIndex,
    series_map: dict[str, pd.Series],
    *,
    prefix: str = "",
    **kwargs,
) -> pd.DataFrame:
    """Align multiple series; output columns are ``prefix + key``."""
    cols: dict[str, pd.Series] = {}
    for key, ser in series_map.items():
        col = f"{prefix}{key}"
        cols[col] = align_series(target_index, ser, name=col, **kwargs)
    return pd.DataFrame(cols, index=target_index)


def join_features(
    primary: pd.DataFrame,
    *others: pd.DataFrame,
    how: Literal["inner", "outer"] = "inner",
) -> pd.DataFrame:
    """Index-join feature frames on DatetimeIndex.

    Raises:
        ValueError: if duplicate column names would be introduced.
    """
    out = primary.copy()
    for other in others:
        overlap = set(out.columns) & set(other.columns)
        if overlap:
            raise ValueError(f"duplicate columns on join: {sorted(overlap)}")
        out = out.join(other, how=how)
    return out


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

  Used for ETF flows, corporate treasury events, and on-chain metrics where ingest
  stores ``(value, available_utc)``.
    """
    out_name = name or value_col
    if frame is None or frame.empty or value_col not in frame.columns:
        return pd.Series(np.nan, index=target_index, name=out_name)

    target_index = pd.DatetimeIndex(target_index).tz_convert("UTC").as_unit("ns")
    avail = pd.DatetimeIndex(pd.to_datetime(frame[available_col], utc=True)).as_unit("ns")
    s = pd.Series(frame[value_col].to_numpy(), index=avail, name=out_name)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return align_series(target_index, s, ffill_limit=ffill_limit, name=s.name)


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


def _ensure_utc_index(series: pd.Series) -> pd.Series:
    s = series.copy()
    if s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    else:
        s.index = s.index.tz_convert("UTC")
    return s


def _align_asof(
    target_idx: pd.DatetimeIndex,
    series: pd.Series,
    *,
    ffill_limit: int | None,
    name: str | None,
) -> pd.Series:
    """merge_asof backward with optional staleness cap (matches MacroFeatures)."""
    s = _ensure_utc_index(series)

    target = pd.DataFrame({"ts": target_idx}, index=target_idx)
    src = pd.DataFrame({"ts_src": s.index, "val": s.to_numpy()}).sort_values("ts_src")
    merged = pd.merge_asof(
        target, src, left_on="ts", right_on="ts_src", direction="backward"
    )

    result = pd.Series(merged["val"].to_numpy(), index=target_idx, name=name)

    if ffill_limit is not None:
        ts_src = pd.DatetimeIndex(merged["ts_src"])
        if ts_src.tz is None:
            ts_src = ts_src.tz_localize("UTC")
        lag_days = (target_idx - ts_src).days
        result[lag_days > ffill_limit] = np.nan

    return result
