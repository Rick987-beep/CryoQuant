"""Data loader — the primary entry point for all market data.

load(symbol, tf, start, end) -> pd.DataFrame

On first call: fetches from the appropriate source, writes partitioned parquet,
registers in the catalog. On subsequent calls: reads from disk.

Partition layout::

    STORE_ROOT/<source>/<venue>_<ticker>/<tf>/year=YYYY/month=MM.parquet

The loader checks which year-month partitions are missing and only fetches those,
avoiding redundant network calls.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from cryocore.instruments import Symbol
from cryocore.schemas import OHLCVBars
from cryocore.time import tf_to_seconds
from cryoquant import config
from cryoquant.data import catalog as cat

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

def _fetch(symbol: Symbol, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Dispatch to the correct source module."""
    venue = symbol.venue
    if venue in ("binance.spot",):
        from cryoquant.data.sources.binance_spot import fetch_klines
        return fetch_klines(symbol, tf, start, end)
    if venue in ("binance.perp",):
        from cryoquant.data.sources.binance_perp import fetch_klines
        return fetch_klines(symbol, tf, start, end)
    raise ValueError(
        f"No source registered for venue {venue!r}. "
        "For deribit options use deribit_options directly; "
        "for FRED use fred.fetch_series directly."
    )


# ---------------------------------------------------------------------------
# Partition helpers
# ---------------------------------------------------------------------------

def _partition_path(symbol: Symbol, tf: str, year: int, month: int) -> "Path":
    from pathlib import Path
    source = "binance_spot" if symbol.venue == "binance.spot" else symbol.venue.replace(".", "_")
    return (
        config.STORE_ROOT
        / source
        / f"{symbol.venue.replace('.', '_')}_{symbol.ticker}"
        / tf
        / f"year={year}"
        / f"month={month:02d}.parquet"
    )


def _missing_partitions(
    symbol: Symbol, tf: str, start: datetime, end: datetime
) -> list[tuple[int, int]]:
    """Return list of (year, month) tuples not yet on disk."""
    periods = pd.period_range(start=start, end=end, freq="M")
    missing = []
    for p in periods:
        path = _partition_path(symbol, tf, p.year, p.month)
        if not path.exists():
            missing.append((p.year, p.month))
    return missing


# ---------------------------------------------------------------------------
# Public load function
# ---------------------------------------------------------------------------

def load(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load OHLCV data for *symbol* at *tf* between *start* and *end*.

    Fetches missing partitions from the source, then reads from disk.
    Validates the result against OHLCVBars schema.

    Args:
        symbol: The instrument to load.
        tf:     Timeframe string (e.g. "1h", "4h", "1d").
        start:  Start of the range (tz-aware UTC, inclusive).
        end:    End of the range (tz-aware UTC, inclusive). Defaults to now.

    Returns:
        DataFrame with tz-aware UTC DatetimeIndex "timestamp" and
        columns open, high, low, close, volume (all float64).
    """
    end = end or datetime.now(timezone.utc)

    # Identify and fetch missing partitions
    missing = _missing_partitions(symbol, tf, start, end)
    if missing:
        # Batch the entire missing span into one fetch call to minimise API calls
        min_year, min_month = min(missing)
        max_year, max_month = max(missing)
        fetch_start = datetime(min_year, min_month, 1, tzinfo=timezone.utc)
        # End of the last missing month
        last_period_end = pd.Timestamp(year=max_year, month=max_month, day=1, tz="UTC") + pd.offsets.MonthEnd(1)
        fetch_end = last_period_end.to_pydatetime().replace(tzinfo=timezone.utc)

        log.info(
            "Fetching %s %s %s → %s (%d missing partitions)",
            symbol, tf, fetch_start.date(), fetch_end.date(), len(missing),
        )
        fresh = _fetch(symbol, tf, fetch_start, fetch_end)
        _write_partitions(symbol, tf, fresh)

    # Read all relevant partitions from disk
    df = _read_partitions(symbol, tf, start, end)

    # Validate
    OHLCVBars.validate_df(df)

    return df.sort_index()


# ---------------------------------------------------------------------------
# Read/write helpers
# ---------------------------------------------------------------------------

def _write_partitions(symbol: Symbol, tf: str, df: pd.DataFrame) -> None:
    """Write a DataFrame into year/month partitions."""
    if df.empty:
        return

    df = df.sort_index()
    years_months = df.groupby([df.index.year, df.index.month])  # type: ignore[arg-type]

    all_paths = []
    for (year, month), chunk in years_months:
        path = _partition_path(symbol, tf, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Merge with any existing data for that partition
        if path.exists():
            existing = pd.read_parquet(path)
            chunk = pd.concat([existing, chunk])
            chunk = chunk[~chunk.index.duplicated(keep="last")].sort_index()

        chunk.to_parquet(path)
        all_paths.append(path)
        log.debug("Wrote partition %s (%d rows)", path, len(chunk))

    # Update catalog with the full range written
    if all_paths:
        all_df = pd.concat([pd.read_parquet(p) for p in all_paths])
        all_df = all_df[~all_df.index.duplicated(keep="last")].sort_index()
        source = symbol.venue.replace(".", "_")
        cat.register(
            source=source,
            symbol=symbol,
            tf=tf,
            path=all_paths[0].parent,
            row_count=len(all_df),
            ts_min=all_df.index.min().to_pydatetime(),
            ts_max=all_df.index.max().to_pydatetime(),
            schema_hash=cat.dataframe_schema_hash(all_df),
        )


def _read_partitions(symbol: Symbol, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Read and concat all partitions that overlap [start, end]."""
    periods = pd.period_range(start=start, end=end, freq="M")
    parts = []
    for p in periods:
        path = _partition_path(symbol, tf, p.year, p.month)
        if path.exists():
            parts.append(pd.read_parquet(path))

    if not parts:
        raise FileNotFoundError(
            f"No data on disk for {symbol} {tf} in [{start.date()}, {end.date()}]. "
            "Try loader.load() with a wider range or check STORE_ROOT."
        )

    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # Clip to requested range
    return df.loc[pd.Timestamp(start):pd.Timestamp(end)]
