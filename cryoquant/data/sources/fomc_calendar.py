"""FOMC rate-decision calendar — Fed published meeting schedule."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# FOMC rate-decision announcement days (day 2 of scheduled meetings, ~2:00 PM ET).
# Source: Federal Reserve FOMC calendars; updated through 2026.
_FOMC_DECISION_DATES: tuple[date, ...] = (
    # 2018
    date(2018, 3, 21), date(2018, 6, 13), date(2018, 9, 26), date(2018, 12, 19),
    # 2019
    date(2019, 1, 30), date(2019, 3, 20), date(2019, 5, 1), date(2019, 6, 19),
    date(2019, 7, 31), date(2019, 9, 18), date(2019, 10, 30), date(2019, 12, 11),
    # 2020
    date(2020, 1, 29), date(2020, 3, 3), date(2020, 3, 15), date(2020, 3, 19),
    date(2020, 4, 29), date(2020, 6, 10), date(2020, 7, 29), date(2020, 9, 16),
    date(2020, 11, 5), date(2020, 12, 16),
    # 2021
    date(2021, 1, 27), date(2021, 3, 17), date(2021, 4, 28), date(2021, 6, 16),
    date(2021, 7, 28), date(2021, 9, 22), date(2021, 11, 3), date(2021, 12, 15),
    # 2022
    date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15),
    date(2022, 7, 27), date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14),
    # 2023
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
    date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13),
    # 2024
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    # 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
    # 2026 (Fed published calendar)
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
)

_FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def decision_available_utc(decision_date: date) -> datetime:
    """§D.3: announcement ~2:00 PM ET → 19:00 UTC (EST) / 18:00 UTC (EDT)."""
    local = datetime.combine(decision_date, time(14, 0), tzinfo=_ET)
    return local.astimezone(timezone.utc)


def fetch_fomc_decision_days(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Return daily FOMC decision flags between *start* and *end*.

    Columns: ``is_fomc_decision_day``, ``available_utc``, ``decision_date``.
    Index: UTC midnight on decision days only (sparse); expand in features if needed.
    """
    end_d = end or date.today()
    dates = _resolve_decision_dates(start, end_d, session=session)

    records = []
    for d in dates:
        if d < start or d > end_d:
            continue
        avail = decision_available_utc(d)
        records.append(
            {
                "timestamp": pd.Timestamp(d, tz="UTC"),
                "decision_date": d,
                "available_utc": avail,
                "is_fomc_decision_day": 1.0,
            }
        )

    if not records:
        return pd.DataFrame(
            columns=["decision_date", "available_utc", "is_fomc_decision_day"],
        )

    df = pd.DataFrame(records).set_index("timestamp").sort_index()
    df.index.name = "timestamp"
    return df


def expand_daily_flags(sparse: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Map sparse FOMC flags onto a daily BTC index using §D.3 available_utc."""
    if sparse.empty:
        return pd.Series(0.0, index=index, name="is_fomc_decision_day")

    out = pd.Series(0.0, index=index, name="is_fomc_decision_day")
    for _, row in sparse.iterrows():
        avail = pd.Timestamp(row["available_utc"])
        if avail.tzinfo is None:
            avail = avail.tz_localize("UTC")
        else:
            avail = avail.tz_convert("UTC")
        # Flag visible on first bar at or after available_utc
        mask = index >= avail.floor("D")
        if mask.any():
            out.loc[index[mask][0]] = 1.0
    return out


def _resolve_decision_dates(
    start: date,
    end: date,
    *,
    session: requests.Session | None = None,
) -> list[date]:
    static = [d for d in _FOMC_DECISION_DATES if start <= d <= end]
    try:
        fetched = _fetch_fed_calendar(start, end, session=session)
        merged = sorted(set(static) | set(fetched))
        return [d for d in merged if start <= d <= end]
    except Exception as exc:
        log.warning("Fed calendar fetch failed (%s); using static dates only", exc)
        return static


def _fetch_fed_calendar(
    start: date,
    end: date,
    *,
    session: requests.Session | None = None,
) -> list[date]:
    """Best-effort parse of Fed FOMC calendar page for decision dates."""
    sess = session or requests.Session()
    r = sess.get(_FED_CALENDAR_URL, timeout=30)
    r.raise_for_status()
    text = r.text
    # Match "Month DD-DD, YYYY" meeting blocks; take last day as decision day.
    pattern = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:-\d{1,2})?,\s+(\d{4})",
        re.IGNORECASE,
    )
    month_map = {
        m.lower(): i for i, m in enumerate(
            ["January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"],
            start=1,
        )
    }
    dates: list[date] = []
    for month_name, day_str, year_str in pattern.findall(text):
        y = int(year_str)
        if y < start.year - 1 or y > end.year + 1:
            continue
        m = month_map[month_name.lower()]
        d = date(y, m, int(day_str))
        if start <= d <= end:
            dates.append(d)
    return sorted(set(dates))
