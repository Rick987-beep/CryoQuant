"""Tests for multi-overlay portfolio backtest."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.metrics_portfolio import carry_funding_ratio, episode_pnl_usd
from src.portfolio_backtest import (
    PortfolioSpec,
    build_positions,
    run_portfolio,
    run_walk_forward_oos,
    walk_forward_blocks,
)


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.bdate_range("2015-01-01", "2020-12-31", tz="UTC")


def _features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "regime_velocity": "moderate",
            "is_roll_window": False,
        },
        index=idx,
    )


def test_attribution_sums_to_total(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(55 + np.sin(np.arange(len(idx)) / 30) * 8, index=idx)
    feat = _features(idx)
    spec = PortfolioSpec(name="test", apply_mutex=True)
    result = run_portfolio(spread, feat, spec=spec)
    diff = result.attribution["total"] - (
        result.attribution["pnl_tail"] + result.attribution["pnl_yield"]
    )
    assert diff.abs().max() < 1e-9
    assert result.equity.iloc[0] == pytest.approx(
        1.0 + result.attribution["total"].iloc[0] / result.collateral_usd
    )


def test_mutex_no_overlap_when_enabled(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series(np.linspace(55, 70, len(idx)), index=idx)
    feat = _features(idx)
    spec_on = PortfolioSpec(name="mutex_on", apply_mutex=True, yield_strategy="Y1_calm_underwriter")
    spec_off = PortfolioSpec(name="mutex_off", apply_mutex=False, yield_strategy="Y1_calm_underwriter")
    on = run_portfolio(spread, feat, spec=spec_on)
    off = run_portfolio(spread, feat, spec=spec_off)
    assert on.metrics["mutex_overlap_days"] == 0
    assert off.metrics["mutex_overlap_days"] >= 0


def test_mutex_forces_yield_flat_when_tail_long(idx: pd.DatetimeIndex) -> None:
    spread = pd.Series([58.0] * len(idx), index=idx)
    feat = _features(idx)
    tail_pos, yield_pos = build_positions(
        spread, feat, None,
        PortfolioSpec(name="t", apply_mutex=True, tail_entry_max_bps=65, yield_strategy="Y1_calm_underwriter"),
    )
    overlap = (tail_pos != 0) & (yield_pos != 0)
    assert not overlap.any()


def test_empty_spread_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        run_portfolio(
            pd.Series(dtype=float),
            pd.DataFrame(),
            spec=PortfolioSpec(name="x"),
        )


def test_portfolio_positions_causal(idx: pd.DatetimeIndex) -> None:
    rng = np.random.default_rng(1)
    spread = pd.Series(55 + rng.normal(0, 1, len(idx)).cumsum() * 0.15, index=idx).clip(48, 78)
    feat = _features(idx)
    spec = PortfolioSpec(name="causal", apply_mutex=True)

    full_tail, full_yield = build_positions(spread, feat, None, spec)
    for i in range(60, len(spread)):
        slc = spread.iloc[: i + 1]
        f = feat.iloc[: i + 1]
        t, y = build_positions(slc, f, None, spec)
        assert t.iloc[-1] == full_tail.iloc[i]
        assert y.iloc[-1] == full_yield.iloc[i]


def test_walk_forward_blocks_non_overlapping_test(idx: pd.DatetimeIndex) -> None:
    long_idx = pd.bdate_range("2000-01-01", "2025-12-31", tz="UTC")
    blocks = walk_forward_blocks(long_idx, train_years=8, test_years=3)
    assert len(blocks) >= 2
    for i in range(len(blocks) - 1):
        assert blocks[i]["test_end"] < blocks[i + 1]["test_start"]


def test_walk_forward_oos_runs() -> None:
    idx = pd.bdate_range("2000-01-01", "2025-12-31", tz="UTC")
    spread = pd.Series(60.0, index=idx)
    spread.iloc[1000:1100] = 90.0
    feat = _features(idx)
    spec = PortfolioSpec(name="wf", apply_mutex=True)
    wf = run_walk_forward_oos(spread, feat, spec=spec, train_years=8, test_years=3)
    assert wf["metrics"]["n_blocks"] >= 1
    assert len(wf["oos_equity"]) > 0


def test_carry_funding_ratio_denominator() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="B", tz="UTC")
    y = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0], index=idx)
    c = pd.Series([-50.0, -50.0, -50.0, -50.0, -50.0], index=idx)
    assert carry_funding_ratio(y, c) == pytest.approx(2.0)


def test_episode_pnl_empty_range() -> None:
    idx = pd.bdate_range("2020-01-01", "2020-01-10", tz="UTC")
    attr = pd.DataFrame({"total": 1.0}, index=idx)
    assert episode_pnl_usd(attr, "2019-01-01", "2019-02-01") == 0.0
