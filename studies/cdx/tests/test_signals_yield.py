"""Tests for yield overlay strategies (Y1–Y14)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals_yield import (
    YIELD_STRATEGY_REGISTRY,
    run_yield_strategy,
    yield_band_trader,
    yield_calm_underwriter,
    yield_compression_rider,
    yield_handoff_to_tail,
    yield_partial_notional,
    yield_velocity_filtered_underwriter,
    yield_with_tail_mutex,
)


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=120, freq="B", tz="UTC")


def _features(
    idx: pd.DatetimeIndex,
    *,
    velocity: str = "low",
    roll: bool = False,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "regime_velocity": velocity,
            "is_roll_window": roll,
        },
        index=idx,
    )


def _causal_check(name: str, spread: pd.Series, features: pd.DataFrame, panel: pd.DataFrame | None = None) -> None:
    """Position at t must not change when future data is appended."""
    full = run_yield_strategy(
        name, spread, features=features, panel=panel,
    )
    for i in range(30, len(spread)):
        partial = run_yield_strategy(
            name,
            spread.iloc[: i + 1],
            features=features.iloc[: i + 1],
            panel=panel.iloc[: i + 1] if panel is not None else None,
        )
        assert partial.iloc[-1] == full.iloc[i], f"{name} lookahead at index {i}"


def test_y1_short_in_calm_flat_in_stress(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(np.linspace(55, 95, len(idx)), index=idx)
    feat = _features(idx)
    pos = yield_calm_underwriter(spread, features=feat)
    stress_pos = spread >= 80
    assert (pos[spread < 80] == -1.0).all()
    assert (pos[stress_pos] == 0.0).all()


def test_y1_no_lookahead(idx: pd.DatetimeIndex) -> None:
    rng = np.random.default_rng(42)
    spread = pd.Series(50 + rng.normal(0, 3, len(idx)).cumsum() * 0.1, index=idx).clip(40, 90)
    feat = _features(idx)
    _causal_check("Y1_calm_underwriter", spread, feat)


@pytest.mark.parametrize("name", list(YIELD_STRATEGY_REGISTRY.keys()))
def test_registry_strategies_causal(name: str, idx: pd.DatetimeIndex) -> None:
    rng = np.random.default_rng(0)
    spread = pd.Series(55 + rng.normal(0, 1, len(idx)).cumsum() * 0.2, index=idx).clip(45, 78)
    feat = _features(idx)
    panel = pd.DataFrame(
        {
            "QQQ": 300 + rng.normal(0, 1, len(idx)).cumsum(),
            "TLT": 140 + rng.normal(0, 0.5, len(idx)).cumsum() * 0.1,
            "VIX": 18 + rng.normal(0, 0.3, len(idx)).cumsum() * 0.05,
        },
        index=idx,
    )
    _causal_check(name, spread, feat, panel)


def test_y2_band_trader_state_machine(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([65.0] * 20 + [73.0] * 10 + [61.0] * 10 + [65.0] * 80, index=idx)
    feat = _features(idx)
    pos = yield_band_trader(spread, features=feat, entry_bps=72.0, exit_bps=62.0)
    assert pos.iloc[19] == 0.0
    assert pos.iloc[20] == -1.0
    assert (pos.iloc[30:40] == -1.0).any()
    assert pos.iloc[39] == 0.0 or pos.iloc[40] == 0.0


def test_y3_compression_rider_min_hold(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([70.0] * 30, index=idx[:30])
    # tightening: steady decline
    spread.iloc[10:] = np.linspace(70, 60, 20)
  # widen at end
    spread = pd.concat([spread, pd.Series([62, 64, 66], index=idx[30:33])])
    feat = _features(spread.index)
    pos = yield_compression_rider(
        spread, features=feat, lookback_days=3, consecutive_days=2, min_hold_days=5,
    )
    # Should have been short during tightening window
    assert (pos.iloc[15:25] == -1.0).any()


def test_y8_blocks_grind(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(np.linspace(60, 75, len(idx)), index=idx)  # monotonic widen, still < 80
    feat = _features(idx)
    y1 = yield_calm_underwriter(spread, features=feat)
    y8 = yield_velocity_filtered_underwriter(spread, features=feat, grind_days=3)
    assert y1.sum() < 0  # mostly short
    assert y8.iloc[-10:].eq(0.0).all()


def test_y9_partial_notional_scales(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([50.0] * 60 + [65.0] * 60, index=idx)
    feat = _features(idx)
    pos = yield_partial_notional(spread, features=feat, tight_bps=55.0, scale_tight=0.5)
    assert pos.iloc[0] == -0.5
    assert pos.iloc[70] == -1.0


def test_y4_mutex_wrapper(idx: pd.DatetimeIndex) -> None:
    base = pd.Series([-1.0] * len(idx), index=idx)
    tail = pd.Series([0.0] * 40 + [1.0] * 80, index=idx)
    out = yield_with_tail_mutex(base, tail)
    assert (out.iloc[:40] == -1.0).all()
    assert (out.iloc[40:] == 0.0).all()


def test_y14_handoff_exits_at_threshold(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(np.linspace(52, 62, 20), index=idx[:20])
    feat = _features(spread.index)
    pos = yield_handoff_to_tail(
        spread, features=feat, tight_entry_bps=55.0, handoff_bps=60.0,
    )
    assert pos.iloc[0] == -1.0
    assert pos.iloc[-1] == 0.0


def test_nan_spread_always_flat(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([60.0, np.nan, 60.0, 70.0, 90.0], index=idx[:5])
    feat = _features(spread.index)
    pos = yield_calm_underwriter(spread, features=feat)
    assert pos.iloc[1] == 0.0


def test_unknown_strategy_raises() -> None:
    spread = pd.Series([60.0], index=pd.DatetimeIndex(["2020-01-01"], tz="UTC"))
    with pytest.raises(KeyError):
        run_yield_strategy("Y99_missing", spread)
