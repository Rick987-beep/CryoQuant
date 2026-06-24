"""Tests for yield overlay regime gates."""
from __future__ import annotations

import pandas as pd
import pytest

from src.yield_gates import calm_allowed, apply_tail_mutex, consecutive_true


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=10, freq="B", tz="UTC")


def test_calm_allowed_blocks_high_spread(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([50, 70, 79, 80, 90, 60, 60, 60, 60, 60], index=idx, dtype=float)
    velocity = pd.Series(["low"] * 10, index=idx)
    allowed = calm_allowed(spread, regime_velocity=velocity, stress_bps=80.0)
    assert allowed.iloc[:3].all()
    assert not allowed.iloc[3]
    assert not allowed.iloc[4]


def test_calm_allowed_blocks_high_velocity(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([60.0] * 10, index=idx)
    velocity = pd.Series(["moderate"] * 5 + ["high"] * 5, index=idx)
    allowed = calm_allowed(spread, regime_velocity=velocity, stress_bps=80.0)
    assert allowed.iloc[:5].all()
    assert not allowed.iloc[5:].any()


def test_calm_allowed_blocks_when_tail_long(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([60.0] * 10, index=idx)
    velocity = pd.Series(["low"] * 10, index=idx)
    tail = pd.Series([0.0] * 5 + [1.0] * 5, index=idx)
    allowed = calm_allowed(spread, regime_velocity=velocity, tail_position=tail)
    assert allowed.iloc[:5].all()
    assert not allowed.iloc[5:].any()


def test_calm_allowed_nan_spread_blocked(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([60.0, float("nan"), 60.0], index=idx[:3])
    velocity = pd.Series(["low"] * 3, index=idx[:3])
    allowed = calm_allowed(spread, regime_velocity=velocity)
    assert allowed.iloc[0]
    assert not allowed.iloc[1]
    assert allowed.iloc[2]


def test_calm_allowed_missing_velocity_blocked(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([60.0] * 5, index=idx[:5])
    allowed = calm_allowed(spread, regime_velocity=None, require_velocity_low=True)
    assert not allowed.any()


def test_apply_tail_mutex(idx: pd.DatetimeIndex) -> None:
    pos = pd.Series([-1.0] * 10, index=idx)
    tail = pd.Series([0.0] * 4 + [1.0] * 6, index=idx)
    out = apply_tail_mutex(pos, tail)
    assert (out.iloc[:4] == -1.0).all()
    assert (out.iloc[4:] == 0.0).all()


def test_consecutive_true(idx: pd.DatetimeIndex) -> None:
    mask = pd.Series([False, True, True, True, False, True, False], index=idx[:7])
    out = consecutive_true(mask, 2)
    assert not out.iloc[0]
    assert not out.iloc[1]
    assert out.iloc[2]
    assert out.iloc[3]
    assert not out.iloc[4]
