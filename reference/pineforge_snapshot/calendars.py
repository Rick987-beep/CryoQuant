"""US trading-calendar helpers (NYSE / XNYS).

Authoritative source: `pandas_market_calendars`, which encodes the official
NYSE rules including Good Friday (federal-holiday lists usually miss this)
and early closes. This is the same library production trading systems use.

Public:
    is_us_trading_day(idx)        -> pd.Series[bool]   indexed by `idx`
    in_us_session(idx, start_hour, end_hour, *, calendar=True)
                                  -> pd.Series[bool]   bar-by-bar mask
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal


@lru_cache(maxsize=8)
def _xnys_trading_days(year_start: int, year_end: int) -> pd.DatetimeIndex:
    """Return UTC-tz-naive dates on which XNYS is open in [year_start, year_end]."""
    cal = mcal.get_calendar("XNYS")
    schedule = cal.schedule(
        start_date=f"{year_start}-01-01",
        end_date=f"{year_end}-12-31",
    )
    # `schedule.index` is tz-naive at NY local — convert to date-only.
    return pd.DatetimeIndex(schedule.index.normalize())


def is_us_trading_day(idx: pd.DatetimeIndex) -> pd.Series:
    """Boolean series: is the bar's UTC date a NYSE trading day?

    Uses the bar's UTC date directly. Edge cases at the NY/UTC boundary
    (NY closes 21:00 UTC in summer, 22:00 in winter) are immaterial here
    because we additionally restrict to 13:00–15:00 UTC entries — well
    inside any NY trading day.
    """
    if not isinstance(idx, pd.DatetimeIndex):
        raise TypeError("idx must be a DatetimeIndex")
    if idx.tz is None:
        raise ValueError("idx must be tz-aware (UTC expected)")

    if len(idx) == 0:
        return pd.Series([], index=idx, dtype=bool)

    y0 = int(idx.min().year)
    y1 = int(idx.max().year)
    trading = _xnys_trading_days(y0, y1)
    bar_dates = idx.tz_convert("UTC").normalize().tz_localize(None)
    mask = bar_dates.isin(trading)
    return pd.Series(mask, index=idx, dtype=bool, name="is_us_trading_day")


def in_us_session(
    idx: pd.DatetimeIndex,
    *,
    start_hour: int = 13,
    end_hour: int = 15,
    require_trading_day: bool = True,
) -> pd.Series:
    """Bar-level mask: is bar's UTC hour in [start_hour, end_hour) AND a trading day?"""
    if start_hour < 0 or end_hour > 24 or start_hour >= end_hour:
        raise ValueError("require 0 <= start_hour < end_hour <= 24")
    utc = idx.tz_convert("UTC")
    hour = utc.hour
    in_window = (hour >= start_hour) & (hour < end_hour)
    if not require_trading_day:
        return pd.Series(in_window, index=idx, dtype=bool, name="in_us_session")
    trading = is_us_trading_day(idx).to_numpy()
    return pd.Series(in_window & trading, index=idx, dtype=bool, name="in_us_session")
