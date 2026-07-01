"""Deribit volatility index (DVOL) — public REST API.

Public interface::

    fetch_dvol(underlying, start, end, *, session, resolution) -> pd.DataFrame

Returns UTC daily index and column ``dvol`` (annualised IV, %).
Persist via ``macro_store.write_series("deribit", f"{underlying}_DVOL", df["dvol"])``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pandas as pd
import requests

log = logging.getLogger(__name__)

_API_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"


def fetch_dvol(
    underlying: str,
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
    resolution: str = "1D",
) -> pd.DataFrame:
    """Fetch DVOL daily history for BTC or ETH.

    Returns DataFrame with UTC index and column ``dvol`` (annualised IV, %).
    """
    sess = session or requests.Session()
    end_d = end or date.today()
    start_ms = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(
        datetime.combine(end_d, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc).timestamp() * 1000
    )

    all_rows: list[list] = []
    chunk_ms = 999 * 86400000  # Deribit caps ~1000 points per request
    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + chunk_ms, end_ms)
        params = {
            "currency": underlying.upper(),
            "start_timestamp": cursor,
            "end_timestamp": chunk_end,
            "resolution": resolution,
        }
        r = sess.get(_API_URL, params=params, timeout=60)
        r.raise_for_status()
        result = r.json().get("result") or {}
        rows = result.get("data") or []
        if rows:
            all_rows.extend(rows)
        cursor = chunk_end + 86400000

    rows = all_rows

    if not rows:
        return pd.DataFrame(
            {"dvol": pd.Series(dtype=float)},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    # Each row: [timestamp_ms, open, high, low, close]
    idx = pd.to_datetime([row[0] for row in rows], unit="ms", utc=True)
    close = [float(row[4]) for row in rows]
    out = pd.DataFrame({"dvol": close}, index=idx)
    out.index = out.index.floor("D")
    out.index.name = "timestamp"
    return out.sort_index().loc[~out.index.duplicated(keep="last")]
