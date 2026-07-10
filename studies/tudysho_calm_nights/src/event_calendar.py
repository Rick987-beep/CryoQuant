"""Study helpers for joining scheduled events to slot-A hold windows.

Framework fetch/persist lives in ``cryoquant.data.sources.economic_events``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pandas as pd

from cryoquant.data.sources.economic_events import (
    DEFAULT_MAG7,
    fetch_scheduled_events,
    ingest_scheduled_events,
    load_scheduled_events,
    release_slot_nyc,
)

__all__ = [
    "DEFAULT_MAG7",
    "MAG7_TICKERS",
    "build_event_calendar",
    "events_in_hold_window",
    "events_on_date",
    "fetch_scheduled_events",
    "ingest_scheduled_events",
    "load_scheduled_events",
    "release_slot_nyc",
]

MAG7_TICKERS = DEFAULT_MAG7


def build_event_calendar(
    start: date,
    end: date,
    *,
    tickers: tuple[str, ...] = DEFAULT_MAG7,
    session: object | None = None,
) -> pd.DataFrame:
    """Fetch merged calendar (network). Prefer ``ingest_scheduled_events`` + ``load`` for studies."""
    return fetch_scheduled_events(start, end, earnings_tickers=tickers, session=session)


def events_on_date(cal: pd.DataFrame, d: date) -> pd.DataFrame:
    if cal.empty:
        return cal.copy()
    if "event_date" in cal.columns:
        return cal[cal["event_date"] == d.isoformat()].copy()
    return cal[cal.index.date == d].copy()


def events_in_hold_window(
    cal: pd.DataFrame,
    entry_day: date,
    *,
    window_start_nyc: time = time(12, 0),
    expiry_utc: datetime | None = None,
) -> pd.DataFrame:
    """Events from afternoon decision clock through overnight hold (slot A)."""
    if cal.empty:
        return cal.copy()

    from sessions import hold_night_bounds_utc, nyc_dt, to_utc

    start_utc = to_utc(nyc_dt(entry_day, window_start_nyc))
    if expiry_utc is None:
        _, end_utc = hold_night_bounds_utc(entry_day)
    else:
        end_utc = expiry_utc

    if isinstance(cal.index, pd.DatetimeIndex) and cal.index.name == "timestamp":
        ts = cal.index
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        mask = (ts >= start_utc) & (ts <= end_utc)
        return cal.loc[mask].copy()

    ts = pd.to_datetime(cal["event_utc"], utc=True)
    mask = (ts >= start_utc) & (ts <= end_utc)
    return cal.loc[mask].copy()
