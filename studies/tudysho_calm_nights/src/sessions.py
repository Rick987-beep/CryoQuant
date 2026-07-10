"""NYC session windows for extrusion analysis (slot A focus)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from cryocore.calendars import get_calendar

NYC = ZoneInfo("America/New_York")
UTC = timezone.utc
_NYSE = get_calendar("nyse")

NYSE_OPEN = time(9, 30)
NYSE_MIDDAY = time(12, 0)
NYSE_CLOSE = time(16, 0)
EXPIRY_UTC = time(8, 0)


@dataclass(frozen=True)
class SessionWindow:
    name: str
    start: time
    end: time


SESSIONS_SLOT_A = (
    SessionWindow("us_morning", NYSE_OPEN, NYSE_MIDDAY),
    SessionWindow("us_afternoon", NYSE_MIDDAY, NYSE_CLOSE),
    SessionWindow("us_post_close", NYSE_CLOSE, time(23, 59, 59)),
)


def nyc_dt(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=NYC)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_trading_day(d: date) -> bool:
    """NYSE open on calendar date d (midday NYC probe)."""
    probe = datetime.combine(d, time(12, 0), tzinfo=NYC)
    return _NYSE.is_open(probe)


def session_bounds_utc(entry_day: date, session: SessionWindow) -> tuple[datetime, datetime]:
    start_nyc = nyc_dt(entry_day, session.start)
    if session.name == "us_post_close":
        end_nyc = nyc_dt(entry_day, time(23, 59, 59))
    else:
        end_nyc = nyc_dt(entry_day, session.end)
    return to_utc(start_nyc), to_utc(end_nyc) + timedelta(seconds=1)


def hold_night_bounds_utc(entry_day: date) -> tuple[datetime, datetime]:
    """Slot A baseline hold: 16:00 NYC → next-day 08:00 UTC."""
    return hold_from_entry_bounds_utc(entry_day, NYSE_CLOSE)


def parse_entry_time_nyc(entry_time: str | time) -> time:
    if isinstance(entry_time, time):
        return entry_time
    parts = entry_time.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return time(hour, minute)


def hold_from_entry_bounds_utc(entry_day: date, entry_time_nyc: str | time) -> tuple[datetime, datetime]:
    """Hold window from NYC entry time to next-day 08:00 UTC expiry."""
    t = parse_entry_time_nyc(entry_time_nyc)
    start = to_utc(nyc_dt(entry_day, t))
    expiry_day = entry_day + timedelta(days=1)
    end = datetime.combine(expiry_day, EXPIRY_UTC, tzinfo=UTC)
    return start, end


def slot_a_entry_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    d = start
    while d <= end:
        if d.weekday() in (0, 1, 2, 3) and is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def predictor_bounds_utc(entry_day: date, variant: str) -> tuple[datetime, datetime]:
    """UTC bounds for the calmness predictor window on *entry_day* (half-open end)."""
    if variant == "us_morning":
        sess = next(s for s in SESSIONS_SLOT_A if s.name == "us_morning")
        return session_bounds_utc(entry_day, sess)
    if variant == "london_us":
        start = datetime.combine(entry_day, time(7, 0), tzinfo=UTC)
        end_nyc = nyc_dt(entry_day, NYSE_MIDDAY)
        end = to_utc(end_nyc) + timedelta(seconds=1)
        return start, end
    raise ValueError(f"Unknown predictor variant: {variant!r}")
