"""Read-only adapter over CryoBacktester's Deribit option/spot parquets.

Reads directly from CRYOBACKTESTER_DATA_DIR — no copying, no re-ingestion.
Files follow the pattern:
    options_YYYY-MM-DD.parquet
    spot_YYYY-MM-DD.parquet

Public interface::

    list_dates()               -> list[datetime.date]
    load_chain(d)              -> pd.DataFrame    # option chain snapshot
    load_spot(d)               -> pd.DataFrame    # spot prices for the day
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from cryoquant import config

log = logging.getLogger(__name__)


def _data_dir() -> "Path":
    return config.CRYOBACKTESTER_DATA_DIR


def list_dates() -> list[date]:
    """Return sorted list of dates for which options parquets exist."""
    d = config.CRYOBACKTESTER_DATA_DIR
    if not d.exists():
        return []
    dates = []
    for p in sorted(d.glob("options_*.parquet")):
        try:
            dates.append(datetime.strptime(p.stem.replace("options_", ""), "%Y-%m-%d").date())
        except ValueError:
            pass
    return dates


def load_chain(d: date) -> pd.DataFrame:
    """Load the options chain snapshot for date *d*.

    Returns a DataFrame with at minimum these columns (others may be present):
        instrument_name, expiry, strike, option_type, mark_iv, bid, ask
    """
    path = config.CRYOBACKTESTER_DATA_DIR / f"options_{d.isoformat()}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Options parquet not found: {path}")
    df = pd.read_parquet(path)
    log.debug("Loaded chain %s: %d rows", d, len(df))
    return df


def load_spot(d: date) -> pd.DataFrame:
    """Load spot price data for date *d*.

    Returns a DataFrame indexed by timestamp (UTC) or with a timestamp column.
    """
    path = config.CRYOBACKTESTER_DATA_DIR / f"spot_{d.isoformat()}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Spot parquet not found: {path}")
    return pd.read_parquet(path)
