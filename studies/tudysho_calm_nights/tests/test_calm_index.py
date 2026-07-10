"""Tests for continuous calm index and entry schedule."""

from __future__ import annotations

import sys
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

STUDY_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(STUDY_SRC))

from calm_index import causal_percentile_calm  # noqa: E402
from entry_schedule import (  # noqa: E402
    EntryWindow,
    mci_to_entry_minutes,
    minutes_to_hhmm,
)


def test_causal_index_no_lookahead():
    s = pd.Series([1.0, 2.0, 3.0, 1.0, 0.5, 2.5])
    c = causal_percentile_calm(s, window=10, min_periods=2)
    assert np.isnan(c.iloc[0])
    assert 0 <= c.iloc[-1] <= 1


def test_entry_monotone_in_mci():
    w = EntryWindow(earliest=time(12, 0), latest=time(16, 0), step_minutes=15)
    early = mci_to_entry_minutes(1.0, w)
    late = mci_to_entry_minutes(0.0, w)
    assert early < late
    assert early == 12 * 60
    assert late == 16 * 60


def test_entry_rounds_to_step():
    w = EntryWindow(earliest=time(12, 0), latest=time(16, 0), step_minutes=15)
    t = mci_to_entry_minutes(0.5, w)
    assert t % 15 == 0


def test_minutes_to_hhmm():
    assert minutes_to_hhmm(14 * 60) == "14:00"


def test_london_us_predictor_bounds():
    from datetime import date

    from sessions import predictor_bounds_utc, NYSE_MIDDAY, to_utc, nyc_dt

    d = date(2025, 7, 1)
    start, end = predictor_bounds_utc(d, "london_us")
    assert start.hour == 7 and start.tzinfo is not None
    assert to_utc(nyc_dt(d, NYSE_MIDDAY)) < end
    us_start, us_end = predictor_bounds_utc(d, "us_morning")
    assert us_start > start
    assert us_end == end
