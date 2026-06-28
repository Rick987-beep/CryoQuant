"""DefiLlama free API — stablecoin supply (not Pro ETF/DAT endpoints)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pandas as pd
import requests

log = logging.getLogger(__name__)

_STABLECOIN_CHART = "https://stablecoins.llama.fi/stablecoincharts/all"


def fetch_stablecoin_supply(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch aggregate stablecoin circulating supply (USD).

    Returns DataFrame with UTC daily index and column ``value``.
    """
    sess = session or requests.Session()
    r = sess.get(_STABLECOIN_CHART, timeout=60)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return pd.DataFrame(
            {"value": pd.Series(dtype=float)},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    end_d = end or date.today()
    records: list[tuple[datetime, float]] = []
    for row in rows:
        ts = datetime.fromtimestamp(int(row["date"]), tz=timezone.utc)
        d = ts.date()
        if d < start or d > end_d:
            continue
        total = row.get("totalCirculatingUSD") or {}
        val = total.get("peggedUSD")
        if val is None:
            continue
        day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        records.append((day, float(val)))

    if not records:
        return pd.DataFrame(
            {"value": pd.Series(dtype=float)},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    idx, vals = zip(*sorted(records, key=lambda x: x[0]))
    out = pd.DataFrame({"value": vals}, index=pd.DatetimeIndex(idx, tz="UTC"))
    out.index.name = "timestamp"
    return out.sort_index().loc[~out.index.duplicated(keep="last")]
