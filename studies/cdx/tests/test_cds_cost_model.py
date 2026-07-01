"""Tests for CDX.NA.IG CDS economics."""
from __future__ import annotations

import pandas as pd
import pytest

from src.cds_cost_model import (
    CdsEconomicsConfig,
    daily_cds_pnl,
    replay_constant_position,
)


@pytest.fixture
def cfg() -> CdsEconomicsConfig:
    return CdsEconomicsConfig(
        duration=5.0,
        day_count=360,
        bid_ask_bps=0.0,
        roll_cost_bps=0.0,
        financing_rate=0.0,
        collateral_usd=5_000_000,
    )


def test_zero_position_zero_carry(cfg: CdsEconomicsConfig) -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="B", tz="UTC")
    spread = pd.Series([50.0] * 5, index=idx)
    pos = pd.Series(0.0, index=idx)
    pnl = daily_cds_pnl(spread, pos, 100_000_000, config=cfg)
    assert pnl["carry"].sum() == 0.0
    assert pnl["mtm"].sum() == 0.0


def test_long_protection_pays_carry(cfg: CdsEconomicsConfig) -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="B", tz="UTC")
    spread = pd.Series([50.0, 50.0, 50.0], index=idx)
    pos = pd.Series(1.0, index=idx)
    pnl = daily_cds_pnl(spread, pos, 100_000_000, config=cfg)
    assert pnl["carry"].sum() < 0


def test_widening_profits_long_protection(cfg: CdsEconomicsConfig) -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="B", tz="UTC")
    spread = pd.Series([50.0, 60.0, 70.0], index=idx)
    pos = pd.Series(1.0, index=idx)
    pnl = daily_cds_pnl(spread, pos, 100_000_000, config=cfg)
    assert pnl["mtm"].sum() > 0


def test_theoretical_vs_modeled_covid_scale(cfg: CdsEconomicsConfig) -> None:
    """50 → 152 bps over ~6 weeks should be large positive MTM on $100M."""
    idx = pd.bdate_range("2020-02-20", "2020-04-01", tz="UTC")
    spread = pd.Series(50.0, index=idx)
    # ramp to ~152 by 2020-03-20
    ramp_end = pd.Timestamp("2020-03-20", tz="UTC")
    for ts in idx:
        if ts <= ramp_end:
            frac = (ts - idx[0]).days / max((ramp_end - idx[0]).days, 1)
            spread.loc[ts] = 50 + 102 * frac
        else:
            spread.loc[ts] = 152.0

    result = replay_constant_position(
        spread,
        entry_date="2020-02-24",
        exit_date="2020-03-23",
        notional_usd=100_000_000,
        config=cfg,
    )
    assert result["total_pnl_usd"] > 1_000_000
    assert abs(result["total_pnl_usd"] - result["theoretical_pnl_usd"]) < 500_000
