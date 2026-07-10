"""Tests for event_calendar fetch helpers."""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

STUDY_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(STUDY_SRC))

from cryoquant.data.sources.event_schema import release_slot_nyc  # noqa: E402
from event_calendar import events_in_hold_window  # noqa: E402


def test_release_slot_nyc():
    et = ZoneInfo("America/New_York")
    morning = datetime(2025, 6, 10, 8, 30, tzinfo=et).astimezone(timezone.utc)
    afternoon = datetime(2025, 6, 10, 14, 0, tzinfo=et).astimezone(timezone.utc)
    evening = datetime(2025, 6, 10, 17, 0, tzinfo=et).astimezone(timezone.utc)
    assert release_slot_nyc(morning) == "morning"
    assert release_slot_nyc(afternoon) == "afternoon"
    assert release_slot_nyc(evening) == "evening"


def test_events_in_hold_window_uses_index():
    et = ZoneInfo("America/New_York")
    afternoon = pd.Timestamp(datetime(2025, 1, 29, 14, 0, tzinfo=et)).tz_convert("UTC")
    cal = pd.DataFrame(
        {
            "event_id": ["fomc-2025-01-29"],
            "event_type": ["fomc"],
            "event_date": ["2025-01-29"],
            "release_slot": ["afternoon"],
        },
        index=pd.DatetimeIndex([afternoon], name="timestamp"),
    )
    hits = events_in_hold_window(cal, date(2025, 1, 29))
    assert len(hits) == 1

    morning = pd.Timestamp(datetime(2025, 1, 29, 8, 30, tzinfo=et)).tz_convert("UTC")
    cal2 = cal.copy()
    cal2.index = pd.DatetimeIndex([morning], name="timestamp")
    assert events_in_hold_window(cal2, date(2025, 1, 29)).empty
