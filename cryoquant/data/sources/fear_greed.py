"""Crypto Fear & Greed Index — alternative.me public API."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pandas as pd
import requests

log = logging.getLogger(__name__)

_API_URL = "https://api.alternative.me/fng/"


def fetch_series(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
    limit: int = 0,
) -> pd.DataFrame:
    """Fetch daily Fear & Greed index.

    Returns DataFrame with UTC DatetimeIndex and column ``value`` (0–100).
    """
    sess = session or requests.Session()
    params: dict[str, int | str] = {"format": "json", "limit": limit or 0}
    r = sess.get(_API_URL, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data") or []
    if not rows:
        return pd.DataFrame(
            {"value": pd.Series(dtype=float)},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    records: list[tuple[datetime, float]] = []
    end_d = end or date.today()
    for row in rows:
        ts = datetime.fromtimestamp(int(row["timestamp"]), tz=timezone.utc)
        d = ts.date()
        if d < start or d > end_d:
            continue
        records.append((ts.replace(hour=0, minute=0, second=0, microsecond=0), float(row["value"])))

    if not records:
        return pd.DataFrame(
            {"value": pd.Series(dtype=float)},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    idx, vals = zip(*sorted(records, key=lambda x: x[0]))
    out = pd.DataFrame({"value": vals}, index=pd.DatetimeIndex(idx, tz="UTC"))
    out.index.name = "timestamp"
    return out.sort_index().loc[~out.index.duplicated(keep="last")]
