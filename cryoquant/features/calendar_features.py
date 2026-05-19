"""Calendar-based features derived from a UTC DatetimeIndex.

All functions accept a pd.DatetimeIndex and return a pd.Series aligned to it.
No side effects; Tier-1 (no caching, no versioning).
"""
from __future__ import annotations

import pandas_market_calendars as mcal
import pandas as pd


def dow(idx: pd.DatetimeIndex) -> pd.Series:
    """Day of week (0=Monday … 6=Sunday)."""
    return pd.Series(idx.dayofweek, index=idx, dtype="int8", name="dow")


def hour_utc(idx: pd.DatetimeIndex) -> pd.Series:
    """Hour of day in UTC (0–23)."""
    utc = idx.tz_convert("UTC") if idx.tz is not None else idx
    return pd.Series(utc.hour, index=idx, dtype="int8", name="hour_utc")


def is_weekend(idx: pd.DatetimeIndex) -> pd.Series:
    """True on Saturday (5) and Sunday (6)."""
    return pd.Series(idx.dayofweek >= 5, index=idx, dtype=bool, name="is_weekend")


def is_us_session(idx: pd.DatetimeIndex) -> pd.Series:
    """True when bar's UTC hour falls in the NYSE regular session (13:30–20:00 UTC).

    Approximate: uses UTC 13–21 to cover seasonal DST offsets without requiring
    a full calendar. Pair with is_us_trading_day for strict checks.
    """
    utc = idx.tz_convert("UTC") if idx.tz is not None else idx
    hour = utc.hour
    in_window = (hour >= 13) & (hour < 21)
    return pd.Series(in_window, index=idx, dtype=bool, name="is_us_session")


def is_eu_session(idx: pd.DatetimeIndex) -> pd.Series:
    """True when bar's UTC hour is in the EU trading window (07:00–16:00 UTC)."""
    utc = idx.tz_convert("UTC") if idx.tz is not None else idx
    hour = utc.hour
    in_window = (hour >= 7) & (hour < 16)
    return pd.Series(in_window, index=idx, dtype=bool, name="is_eu_session")


def is_asia_session(idx: pd.DatetimeIndex) -> pd.Series:
    """True when bar's UTC hour is in the Asian trading window (00:00–08:00 UTC)."""
    utc = idx.tz_convert("UTC") if idx.tz is not None else idx
    hour = utc.hour
    in_window = hour < 8
    return pd.Series(in_window, index=idx, dtype=bool, name="is_asia_session")


def is_us_holiday(idx: pd.DatetimeIndex) -> pd.Series:
    """True on weekdays when the NYSE is closed (US holidays).

    Uses pandas_market_calendars for an authoritative, future-proof holiday list.
    """
    utc = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    bar_dates = utc.normalize()
    start = bar_dates.min().strftime("%Y-%m-%d")
    end   = bar_dates.max().strftime("%Y-%m-%d")

    nyse = mcal.get_calendar("XNYS")
    schedule = nyse.schedule(start_date=start, end_date=end)
    trading_dates = pd.DatetimeIndex(schedule.index.normalize())

    is_weekday = pd.Series(bar_dates.dayofweek < 5, index=idx)
    is_trading = pd.Series(bar_dates.isin(trading_dates), index=idx)
    return (is_weekday & ~is_trading).rename("is_us_holiday")


def minutes_since_midnight_utc(idx: pd.DatetimeIndex) -> pd.Series:
    """Minutes elapsed since midnight UTC."""
    utc = idx.tz_convert("UTC") if idx.tz is not None else idx
    mins = utc.hour * 60 + utc.minute
    return pd.Series(mins, index=idx, dtype="int16", name="minutes_since_midnight_utc")
