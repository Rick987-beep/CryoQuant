"""Tests for crunch fund vintage backtester."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.crunch_fund import (
    CrunchFundSpec,
    analytical_notional_for_10x,
    analytical_tier_c_peak_nav,
    aggregate_config_results,
    evaluate_episode,
    fund_vintage_starts,
    iter_specs,
    run_fund_vintage,
)


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.bdate_range("2015-01-01", "2022-12-31", tz="UTC")


def _features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"is_roll_window": False}, index=idx)


def test_analytical_notional_for_10x() -> None:
    n = analytical_notional_for_10x(5_000_000, 200, duration=5.0, target_multiple=10.0)
    assert n == pytest.approx(450_000_000, rel=0.01)


def test_analytical_tier_c_peak_at_450m() -> None:
    peak = analytical_tier_c_peak_nav(450_000_000, 5_000_000, 200)
    assert peak == pytest.approx(10.0, rel=0.01)


def test_fund_vintage_starts(idx: pd.DatetimeIndex) -> None:
    starts = fund_vintage_starts(idx, fund_years=5, freq="QS")
    assert len(starts) >= 1
    assert starts[0] >= idx[0]


def test_run_fund_vintage_covid_episode(idx: pd.DatetimeIndex) -> None:
    rng = np.random.default_rng(1)
    spread = pd.Series(55 + rng.normal(0, 0.5, len(idx)).cumsum(), index=idx).clip(45, 160)
    spread.loc["2020-03-20"] = 150.0
    feat = _features(idx)
    spec = CrunchFundSpec(
        strategy="standing", notional_usd=100_000_000,
        entry_max_bps=70, exit_bps=None, collateral_usd=5_000_000,
    )
    t0 = pd.Timestamp("2015-01-01", tz="UTC")
    t1 = pd.Timestamp("2020-12-31", tz="UTC")
    ep = [{"id": "covid", "tier": "A", "start": "2020-02-01", "end": "2020-04-30"}]
    result = run_fund_vintage(spread, feat, spec, t0, t1, episodes=ep)
    assert result.metrics["terminal_nav"] > 0
    assert len(result.episodes) == 1
    assert result.episodes[0]["crisis_nav_peak_multiple"] > 1.0


def test_evaluate_episode_synthetic() -> None:
    ep = {"id": "tier_c", "tier": "C", "synthetic": True, "delta_bps": 200}
    attr = pd.DataFrame({"total": [0.0]})
    attr.attrs["notional_usd"] = 450_000_000
    out = evaluate_episode(
        pd.Series([1.0]), pd.Series([1.0]), attr, ep, collateral_usd=5_000_000,
    )
    assert out["hit_10x"] is True
    assert out["crisis_nav_peak_multiple"] == pytest.approx(10.0, rel=0.05)


def test_iter_specs_count() -> None:
    specs = iter_specs()
    standing_spike = [s for s in specs if s.strategy != "pyramid"]
    pyramid = [s for s in specs if s.strategy == "pyramid"]
    assert len(standing_spike) == 6 * 3 * 4 * 2
    assert len(pyramid) == 3 * 1 * 2 * 3 * 2 * 2
    assert len(specs) == len(standing_spike) + len(pyramid)


def test_run_fund_vintage_pyramid(idx: pd.DatetimeIndex) -> None:
    rng = __import__("numpy").random.default_rng(2)
    spread = pd.Series(55 + rng.normal(0, 0.5, len(idx)).cumsum(), index=idx).clip(45, 160)
    spread.loc["2020-03-20"] = 150.0
    feat = _features(idx)
    spec = CrunchFundSpec(
        strategy="pyramid", notional_usd=100_000_000,
        entry_max_bps=60, exit_bps=None,
        addon_entry_bps=100, addon_retreat_bps=110, addon_hold_days=30,
        collateral_usd=5_000_000,
    )
    t0 = pd.Timestamp("2015-01-01", tz="UTC")
    t1 = pd.Timestamp("2020-12-31", tz="UTC")
    ep = [{"id": "covid", "tier": "A", "start": "2020-02-01", "end": "2020-04-30"}]
    result = run_fund_vintage(spread, feat, spec, t0, t1, episodes=ep)
    assert result.metrics["terminal_nav"] > 0
    assert result.positions.max() <= 2.0
    assert result.episodes[0]["crisis_nav_peak_multiple"] > 1.0


def test_aggregate_config_results() -> None:
    df = pd.DataFrame([
        {"run_id": "a", "strategy": "standing", "notional_usd": 1e8, "entry_max_bps": 60,
         "exit_bps": None, "vintage_start": "2015-01-01", "terminal_nav": 0.5,
         "crisis_nav_peak_tier_bc": 2.0, "distance_to_10x_tier_bc": 8.0, "hit_10x_tier_bc": False,
         "covid_peak_multiple": 1.5, "calm_burn_usd": -1e6, "notional_for_10x": 450e6,
         "years_to_depletion": 3.0},
        {"run_id": "a", "strategy": "standing", "notional_usd": 1e8, "entry_max_bps": 60,
         "exit_bps": None, "vintage_start": "2016-01-01", "terminal_nav": 0.4,
         "crisis_nav_peak_tier_bc": 2.5, "distance_to_10x_tier_bc": 7.5, "hit_10x_tier_bc": False,
         "covid_peak_multiple": 1.6, "calm_burn_usd": -1.1e6, "notional_for_10x": 450e6,
         "years_to_depletion": 2.5},
    ])
    agg = aggregate_config_results(df)
    assert len(agg) == 1
    assert agg.iloc[0]["max_crisis_peak_tier_bc"] == 2.5
