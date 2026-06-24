"""Tests for tail insurance signals."""
from __future__ import annotations

import pandas as pd
import pytest

from src.signals_tail import pyramid_tail_insurance, standing_tail_insurance


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.bdate_range("2020-01-01", periods=80, tz="UTC")


def test_pyramid_addon_enters_at_threshold(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(55.0, index=idx)
    spread.iloc[20:40] = 105.0
    pos = pyramid_tail_insurance(
        spread,
        entry_max_bps=60,
        base_exit_bps=9_999,
        addon_entry_bps=100,
        addon_retreat_bps=90,
        addon_hold_days=30,
    )
    assert pos.iloc[:20].max() == 1.0
    assert pos.iloc[20:40].min() == 2.0


def test_pyramid_addon_exits_on_retreat(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(55.0, index=idx)
    spread.iloc[10:25] = 105.0
    spread.iloc[25:35] = 95.0
    pos = pyramid_tail_insurance(
        spread,
        entry_max_bps=60,
        base_exit_bps=9_999,
        addon_entry_bps=100,
        addon_retreat_bps=100,
        addon_hold_days=60,
    )
    assert pos.iloc[10:25].min() >= 2.0
    assert pos.iloc[30] == 1.0


def test_pyramid_addon_exits_on_hold_days(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(55.0, index=idx)
    spread.iloc[10:50] = 130.0
    pos = pyramid_tail_insurance(
        spread,
        entry_max_bps=60,
        base_exit_bps=9_999,
        addon_entry_bps=100,
        addon_retreat_bps=50,
        addon_hold_days=10,
    )
    assert pos.iloc[10:20].min() >= 2.0
    assert pos.iloc[20] == 1.0  # add-on closed after 10 days (may re-enter if still stressed)


def test_pyramid_position_never_exceeds_two(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(55.0, index=idx)
    spread.iloc[30:] = 200.0
    pos = pyramid_tail_insurance(
        spread,
        entry_max_bps=60,
        base_exit_bps=150,
        addon_entry_bps=80,
        addon_retreat_bps=100,
        addon_hold_days=5,
    )
    assert pos.max() <= 2.0


def test_pyramid_causal_no_future_spread(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(55.0, index=idx)
    spread.iloc[40:] = 150.0
    full = pyramid_tail_insurance(
        spread, entry_max_bps=60, base_exit_bps=9_999,
        addon_entry_bps=100, addon_retreat_bps=90, addon_hold_days=30,
    )
    truncated = pyramid_tail_insurance(
        spread.iloc[:50], entry_max_bps=60, base_exit_bps=9_999,
        addon_entry_bps=100, addon_retreat_bps=90, addon_hold_days=30,
    )
    pd.testing.assert_series_equal(full.iloc[:50], truncated, check_names=False)


def test_standing_unchanged(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(55.0, index=idx)
    spread.iloc[30:] = 120.0
    pos = standing_tail_insurance(spread, entry_max_bps=60, exit_bps=100)
    assert pos.iloc[0] == 1.0
    assert pos.iloc[29] == 1.0
    assert pos.iloc[30] == 1.0  # exit triggers same bar; flat from next day
    assert pos.iloc[31] == 0.0
