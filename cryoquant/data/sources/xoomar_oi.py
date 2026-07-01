"""Xoomar Pulse — free historical perp open interest (Binance archives from 2021).

Docs: https://xoomar.com/markets/api/open-interest
No API key. Rate limit ~30 req/min/IP. Up to 5000 rows per call.

Public interface::

    fetch_open_interest_daily(ticker, start, end, *, session) -> pd.DataFrame

Columns: ``open_interest``, optional ``open_interest_usd``, ``long_short_ratio``.
Persist via ``macro_store.write_series("xoomar", f"{ticker}_open_interest", ...)``.
History from 2021-01; pre-2021 is NaN by design.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

log = logging.getLogger(__name__)

_BASE_URL = "https://xoomar.com/api/markets/open-interest"
_MIN_INTERVAL_S = 2.1  # ~30 req/min

# Map Binance tickers → Xoomar slugs
_SLUGS: dict[str, str] = {
    "BTCUSDT": "btc",
    "ETHUSDT": "eth",
    "SOLUSDT": "sol",
}


def fetch_open_interest_daily(
    ticker: str,
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
    exchange: str = "binance",
) -> pd.DataFrame:
    """Fetch daily open interest for a Binance perp ticker.

    Returns DataFrame indexed by UTC midnight with columns:
    ``open_interest`` (contracts), ``open_interest_usd``, ``long_short_ratio`` (optional).
    """
    slug = _SLUGS.get(ticker.upper())
    if not slug:
        raise ValueError(f"No Xoomar slug for ticker {ticker!r}; known: {list(_SLUGS)}")

    end_d = end or date.today()
    sess = session or requests.Session()
    rows: list[dict] = []

    # Walk in ~120-day windows (well under 5000-row cap at daily)
    cursor = start
    while cursor <= end_d:
        chunk_end = min(cursor + timedelta(days=120), end_d)
        params = {
            "period": "1d",
            "from": cursor.isoformat(),
            "to": chunk_end.isoformat(),
        }
        url = f"{_BASE_URL}/{slug}"
        r = sess.get(url, params=params, timeout=60)
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "5"))
            log.warning("Xoomar 429 — sleeping %ds", retry_after)
            time.sleep(retry_after)
            continue
        r.raise_for_status()
        data = r.json().get("data") or []
        for item in data:
            if item.get("exchange", "binance") != exchange:
                continue
            ts = pd.Timestamp(item["ts"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            ts = ts.normalize()
            rows.append(
                {
                    "timestamp": ts,
                    "open_interest": float(item["openInterest"]) if item.get("openInterest") else float("nan"),
                    "open_interest_usd": float(item["openInterestValue"]) if item.get("openInterestValue") else float("nan"),
                    "long_short_ratio": float(item["longShortRatio"]) if item.get("longShortRatio") else float("nan"),
                }
            )
        time.sleep(_MIN_INTERVAL_S)
        cursor = chunk_end + timedelta(days=1)

    if not rows:
        return pd.DataFrame(
            columns=["open_interest", "open_interest_usd", "long_short_ratio"],
        )

    df = pd.DataFrame(rows).drop_duplicates(subset=["timestamp"], keep="last")
    df = df.set_index("timestamp").sort_index()
    df.index.name = "timestamp"
    return df.loc[(df.index.date >= start) & (df.index.date <= end_d)]
