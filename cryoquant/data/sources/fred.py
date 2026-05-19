"""FRED data source — fetches macro series (DXY etc.).

Uses fredapi if FRED_API_KEY is set; otherwise falls back to FRED's public
CSV download endpoint (no key required, but rate-limited).

Public interface::

    fetch_series(series_id, start, end) -> pd.Series   # daily, UTC-indexed
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import requests

from cryoquant import config

log = logging.getLogger(__name__)

_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# Map our friendly names to FRED series IDs
_ALIASES: dict[str, str] = {
    "DXY":  "DTWEXBGS",   # Trade-weighted USD index (broad, goods & services)
    "VIX":  "VIXCLS",
    "FEDFUNDS": "FEDFUNDS",
    "CPI":  "CPIAUCSL",
}


def fetch_series(
    series_id: str,
    start: datetime,
    end: datetime | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.Series:
    """Fetch a FRED daily series.

    Args:
        series_id: FRED series ID or alias (e.g. "DXY", "DTWEXBGS").
        start:     First date (inclusive), tz-aware UTC.
        end:       Last date (inclusive). Defaults to today.

    Returns:
        pd.Series with tz-aware UTC DatetimeIndex, named series_id, float dtype.
        NaN entries (missing observations) are kept as-is.
    """
    fred_id = _ALIASES.get(series_id, series_id)
    end_dt = end or datetime.now(tz=start.tzinfo)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    # Try fredapi first
    if config.FRED_API_KEY:
        try:
            from fredapi import Fred  # type: ignore
            fred = Fred(api_key=config.FRED_API_KEY)
            raw = fred.get_series(fred_id, observation_start=start_str, observation_end=end_str)
            raw.index = pd.DatetimeIndex(raw.index, tz="UTC")
            raw.name = series_id
            return raw.astype(float)
        except Exception as exc:
            log.warning("fredapi fetch failed (%s); falling back to CSV: %s", fred_id, exc)

    # Public CSV fallback
    sess = session or requests.Session()
    params = {"id": fred_id, "vintage_date": end_str}
    r = sess.get(_FRED_CSV_URL, params=params, timeout=30)
    r.raise_for_status()

    from io import StringIO
    df = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
    df = df.rename(columns={"DATE": "date", fred_id: "value"})
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()
    df = df.loc[start_str:end_str]

    series = df["value"].astype(float)
    series.index.name = "timestamp"
    series.name = series_id
    return series
