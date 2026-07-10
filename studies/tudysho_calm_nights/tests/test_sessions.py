"""Tests for NYC session boundaries."""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

STUDY_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(STUDY_SRC))

from sessions import (  # noqa: E402
    hold_from_entry_bounds_utc,
    hold_night_bounds_utc,
    parse_entry_time_nyc,
    session_bounds_utc,
    SESSIONS_SLOT_A,
    to_utc,
    nyc_dt,
)


def test_parse_entry_time_nyc():
    assert parse_entry_time_nyc("12:00") == time(12, 0)
    assert parse_entry_time_nyc("16:00") == time(16, 0)
    assert parse_entry_time_nyc(time(14, 30)) == time(14, 30)


def test_hold_night_matches_entry_at_close():
    d = date(2025, 6, 30)  # Monday
    close_hold = hold_night_bounds_utc(d)
    entry_hold = hold_from_entry_bounds_utc(d, "16:00")
    assert close_hold == entry_hold


def test_hold_from_12_starts_earlier_than_close():
    d = date(2025, 7, 1)
    h12 = hold_from_entry_bounds_utc(d, "12:00")
    h16 = hold_night_bounds_utc(d)
    assert h12[0] < h16[0]
    assert h12[1] == h16[1]


def test_hold_ends_at_08_utc_next_day():
    d = date(2025, 7, 1)
    _, end = hold_night_bounds_utc(d)
    assert end.hour == 8
    assert end.minute == 0
    assert end.tzinfo == timezone.utc
    assert end.date() == date(2025, 7, 2)


def test_session_bounds_us_morning():
    d = date(2025, 7, 1)
    morning = next(s for s in SESSIONS_SLOT_A if s.name == "us_morning")
    start, end = session_bounds_utc(d, morning)
    assert start < end
    # 09:30 NYC in summer ≈ 13:30 UTC
    assert start.hour in (13, 14)
