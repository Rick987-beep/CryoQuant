"""Macro / derived series store.

Persists scalar time-series that are NOT OHLCV (e.g. FRED rates, CBOE VIX,
breakeven inflation) as Parquet files under STORE_ROOT/macro/ and tracks
them in the data catalog.

Storage layout::

    STORE_ROOT/macro/<source>/<series_id>/year=YYYY/month=MM.parquet

Each parquet contains a two-column table:
    timestamp TIMESTAMPTZ (UTC, index)
    value     FLOAT64

Public interface::

    write_series(source, series_id, data, *, force)
    load_series(source, series_id, start, end) -> pd.Series
    list_macro() -> pd.DataFrame
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from cryoquant import config
from cryoquant.data import catalog as cat

log = logging.getLogger(__name__)

_MACRO_ROOT = config.STORE_ROOT / "macro"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_series(
    source: str,
    series_id: str,
    data: pd.Series,
    *,
    force: bool = False,
) -> None:
    """Persist a scalar time-series to partitioned Parquet.

    Args:
        source:    Source identifier, e.g. "fred", "cboe".
        series_id: Series identifier, e.g. "US10Y", "VIX".
        data:      pd.Series with UTC tz-aware DatetimeIndex, float64 values.
        force:     If True, overwrite existing partitions entirely.
    """
    series = _validate_series(data, series_id)

    if series.empty:
        log.warning("write_series: %s/%s — empty series, nothing to write", source, series_id)
        return

    series_sorted = series.sort_index()
    groups = series_sorted.groupby([series_sorted.index.year, series_sorted.index.month])

    all_paths: list[Path] = []
    for (year, month), chunk in groups:
        path = _partition_path(source, series_id, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)

        if not force and path.exists():
            existing_df = pd.read_parquet(path)
            existing = existing_df["value"]
            existing.index = pd.DatetimeIndex(existing_df.index)
            chunk = pd.concat([existing, chunk])
            chunk = chunk[~chunk.index.duplicated(keep="last")].sort_index()

        df = chunk.rename("value").to_frame().reset_index()
        df.columns = ["timestamp", "value"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        df.to_parquet(path)
        all_paths.append(path)
        log.debug("macro_store: wrote %s/%s year=%d month=%02d (%d rows)",
                  source, series_id, year, month, len(chunk))

    # Register in catalog
    if all_paths:
        from cryocore.instruments import Symbol
        sym = Symbol(source, series_id)
        cat.register(
            source=source,
            symbol=sym,
            tf="1d",
            path=all_paths[0].parent,
            row_count=len(series_sorted),
            ts_min=series_sorted.index.min().to_pydatetime(),
            ts_max=series_sorted.index.max().to_pydatetime(),
            schema_hash="macro_scalar",
        )
        log.info("macro_store: %s/%s → %d rows [%s → %s]",
                 source, series_id, len(series_sorted),
                 series_sorted.index.min().date(), series_sorted.index.max().date())


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_series(
    source: str,
    series_id: str,
    start: datetime,
    end: datetime | None = None,
) -> pd.Series:
    """Load a macro series from disk.

    Returns a pd.Series with UTC tz-aware DatetimeIndex and float64 values,
    trimmed to [start, end].  Raises FileNotFoundError if no data on disk.
    """
    end_dt = end or datetime.now(timezone.utc)
    periods = pd.period_range(start=start, end=end_dt, freq="M")
    parts: list[pd.Series] = []

    for p in periods:
        path = _partition_path(source, series_id, p.year, p.month)
        if path.exists():
            df = pd.read_parquet(path)
            idx = pd.DatetimeIndex(df.index)
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
            s = pd.Series(df["value"].values, index=idx, name=series_id, dtype=float)
            parts.append(s)

    if not parts:
        raise FileNotFoundError(
            f"No macro data on disk for {source}/{series_id} "
            f"in [{start.date()}, {end_dt.date()}]. "
            "Run run_ingest.py --macro-only to populate."
        )

    series = pd.concat(parts)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    series.name = series_id

    start_ts = pd.Timestamp(start, tz="UTC") if start.tzinfo is None else pd.Timestamp(start).tz_convert("UTC")
    end_ts   = pd.Timestamp(end_dt, tz="UTC") if end_dt.tzinfo is None else pd.Timestamp(end_dt).tz_convert("UTC")
    return series.loc[start_ts:end_ts]


# ---------------------------------------------------------------------------
# Catalog listing
# ---------------------------------------------------------------------------

def list_macro() -> pd.DataFrame:
    """Return macro series registered in the catalog (any ``macro/`` source)."""
    df = cat.list_datasets()
    if df.empty:
        return df
    macro_sources = {
        p.name for p in _MACRO_ROOT.iterdir() if p.is_dir()
    } if _MACRO_ROOT.exists() else set()
    if not macro_sources:
        macro_sources = {"fred", "cboe"}
    return df[df["source"].isin(macro_sources)].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _partition_path(source: str, series_id: str, year: int, month: int) -> Path:
    safe_id = series_id.replace("/", "_").replace("\\", "_")
    return (
        _MACRO_ROOT
        / source
        / safe_id
        / f"year={year}"
        / f"month={month:02d}.parquet"
    )


def _validate_series(data: pd.Series, series_id: str) -> pd.Series:
    """Ensure UTC tz-aware DatetimeIndex + float64 values."""
    series = data.copy().astype(float)
    series.name = series_id

    idx = pd.DatetimeIndex(series.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    series.index = idx
    series.index.name = "timestamp"
    return series


def _validate_frame(data: pd.DataFrame, series_id: str) -> pd.DataFrame:
    frame = data.copy()
    idx = pd.DatetimeIndex(frame.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    frame.index = idx
    frame.index.name = "timestamp"
    return frame


def write_frame(
    source: str,
    series_id: str,
    data: pd.DataFrame,
    *,
    force: bool = False,
) -> None:
    """Persist a multi-column time-series (e.g. value + available_utc) to macro store."""
    frame = _validate_frame(data, series_id)
    if frame.empty:
        log.warning("write_frame: %s/%s — empty frame, nothing to write", source, series_id)
        return

    frame_sorted = frame.sort_index()
    groups = frame_sorted.groupby([frame_sorted.index.year, frame_sorted.index.month])

    all_paths: list[Path] = []
    for (year, month), chunk in groups:
        path = _partition_path(source, series_id, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)

        if not force and path.exists():
            existing_df = pd.read_parquet(path)
            existing_df.index = pd.DatetimeIndex(existing_df.index)
            if existing_df.index.tz is None:
                existing_df.index = existing_df.index.tz_localize("UTC")
            chunk = pd.concat([existing_df, chunk])
            chunk = chunk[~chunk.index.duplicated(keep="last")].sort_index()

        chunk.to_parquet(path)
        all_paths.append(path)

    if all_paths:
        from cryocore.instruments import Symbol
        sym = Symbol(source, series_id)
        cat.register(
            source=source,
            symbol=sym,
            tf="1d",
            path=all_paths[0].parent,
            row_count=len(frame_sorted),
            ts_min=frame_sorted.index.min().to_pydatetime(),
            ts_max=frame_sorted.index.max().to_pydatetime(),
            schema_hash="macro_frame",
        )
        log.info(
            "macro_store: %s/%s frame → %d rows [%s → %s]",
            source, series_id, len(frame_sorted),
            frame_sorted.index.min().date(), frame_sorted.index.max().date(),
        )


def load_frame(
    source: str,
    series_id: str,
    start: datetime,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load a multi-column macro frame from disk."""
    end_dt = end or datetime.now(timezone.utc)
    periods = pd.period_range(start=start, end=end_dt, freq="M")
    parts: list[pd.DataFrame] = []

    for p in periods:
        path = _partition_path(source, series_id, p.year, p.month)
        if path.exists():
            df = pd.read_parquet(path)
            idx = pd.DatetimeIndex(df.index)
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
            df.index = idx
            parts.append(df)

    if not parts:
        raise FileNotFoundError(
            f"No macro frame on disk for {source}/{series_id} in [{start.date()}, {end_dt.date()}]."
        )

    frame = pd.concat(parts)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    start_ts = pd.Timestamp(start, tz="UTC") if start.tzinfo is None else pd.Timestamp(start).tz_convert("UTC")
    end_ts = pd.Timestamp(end_dt, tz="UTC") if end_dt.tzinfo is None else pd.Timestamp(end_dt).tz_convert("UTC")
    return frame.loc[start_ts:end_ts]
