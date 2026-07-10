"""Equity earnings calendar — Yahoo Finance via yfinance.

Persist via ``macro_store.write_frame("yahoo_calendar", series_id, df)``.
"""
from __future__ import annotations

import logging
from datetime import date, timezone
from typing import Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from cryoquant.data.sources.event_schema import (
    DEFAULT_MAG7,
    EVENT_TIERS,
    records_to_event_frame,
)

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def fetch_earnings_events(
    start: date,
    end: date | None = None,
    tickers: Sequence[str] = DEFAULT_MAG7,
    *,
    session: object | None = None,
) -> pd.DataFrame:
    """Quarterly earnings dates/times for *tickers*."""
    del session
    end_d = end or date.today()
    records: list[dict] = []

    for symbol in tickers:
        symbol = symbol.upper()
        try:
            edf = yf.Ticker(symbol).earnings_dates
        except Exception as exc:
            log.warning("earnings fetch failed for %s: %s", symbol, exc)
            continue
        if edf is None or edf.empty:
            continue

        for ts, _row in edf.iterrows():
            if not isinstance(ts, pd.Timestamp):
                continue
            if ts.tzinfo is None:
                ts = ts.tz_localize(_ET)
            else:
                ts = ts.tz_convert(_ET)
            event_utc = ts.astimezone(timezone.utc)
            event_d = ts.date()
            if event_d < start or event_d > end_d:
                continue
            records.append(
                {
                    "event_id": f"earnings-{symbol}-{event_d.isoformat()}",
                    "source": "yahoo_calendar",
                    "event_type": "earnings",
                    "tier": EVENT_TIERS["earnings"],
                    "title": f"{symbol} quarterly earnings",
                    "symbol": symbol,
                    "event_date": event_d.isoformat(),
                    "event_time_et": ts.strftime("%H:%M"),
                    "event_utc": event_utc,
                }
            )

    return records_to_event_frame(records)
