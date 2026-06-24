"""Tests for CDX → SpotResult adapter."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.trades import TRADE_COLUMNS
from src.backtest_cds import run_overlay
from src.cds_cost_model import CdsEconomicsConfig
from src.cds_to_spot import (
    cds_trades_to_minimal,
    overlay_to_spot,
    portfolio_to_spot,
    spot_trades_schema,
)
from src.portfolio_backtest import PortfolioSpec, run_portfolio


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.bdate_range("2018-01-01", "2019-06-30", tz="UTC")


@pytest.fixture
def spread(idx: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(55.0 + np.arange(len(idx)) * 0.02, index=idx, name="spread_bps")


def _position(idx: pd.DatetimeIndex, start: int, end: int, side: float = 1.0) -> pd.Series:
    pos = pd.Series(0.0, index=idx)
    pos.iloc[start:end] = side
    return pos


def test_cds_trades_to_minimal_maps_spread_prices(spread: pd.Series) -> None:
    idx = spread.index
    trades = pd.DataFrame([{
        "entry_ts": idx[10],
        "exit_ts": idx[20],
        "side": "long_protection",
        "pnl_pct": 0.01,
        "pnl_usd": 50_000.0,
        "carry_usd": 40_000.0,
        "mtm_usd": 8_000.0,
    }])
    minimal = cds_trades_to_minimal(trades, spread, collateral_usd=5_000_000.0)
    assert minimal.iloc[0]["entry_price"] == pytest.approx(float(spread.iloc[10]))
    assert minimal.iloc[0]["exit_price"] == pytest.approx(float(spread.iloc[20]))
    assert minimal.iloc[0]["side"] == "long"
    assert minimal.iloc[0]["exit_type"] == "cds_overlay"
    assert minimal.iloc[0]["fee_pct"] == pytest.approx(2_000.0 / 5_000_000.0)


def test_cds_trades_to_minimal_empty() -> None:
    out = cds_trades_to_minimal(pd.DataFrame(), pd.Series(dtype=float), 1.0)
    assert out.empty


def test_overlay_to_spot_produces_trade_schema(spread: pd.Series) -> None:
    pos = _position(spread.index, 5, 40, side=1.0)
    econ = CdsEconomicsConfig(collateral_usd=5_000_000.0)
    overlay = run_overlay(
        spread, pos, name="test_tail", notional_usd=100_000_000.0,
        config=econ, collateral_usd=1_250_000.0,
    )
    spot = overlay_to_spot(overlay, spread, extra_metrics={"calm_pnl_usd": 123.0})
    assert spot.metrics["calm_pnl_usd"] == 123.0
    assert len(spot.equity) == len(spread)
    assert spot_trades_schema(spot.trades)
    assert set(TRADE_COLUMNS).issubset(set(spot.trades.columns))


def test_overlay_to_spot_extra_metrics_merged(spread: pd.Series) -> None:
    pos = _position(spread.index, 0, 30, side=-1.0)
    overlay = run_overlay(
        spread, pos, name="short_leg", notional_usd=50_000_000.0,
        collateral_usd=1_750_000.0,
    )
    spot = overlay_to_spot(
        overlay, spread,
        extra_metrics={"carry_funding_ratio": 1.5, "covid_pnl_usd": -1e5},
    )
    assert spot.metrics["carry_funding_ratio"] == 1.5
    assert spot.metrics["covid_pnl_usd"] == -1e5


def test_portfolio_to_spot(idx: pd.DatetimeIndex, spread: pd.Series) -> None:
    feat = pd.DataFrame(
        {"regime_velocity": "moderate", "is_roll_window": False},
        index=idx,
    )
    result = run_portfolio(
        spread, feat,
        spec=PortfolioSpec(name="p1", apply_mutex=True, yield_strategy="Y1_calm_underwriter"),
    )
    spot = portfolio_to_spot(result, spread)
    assert spot.metrics["nav_end"] == pytest.approx(float(result.equity.iloc[-1]))
    assert "covid_pnl_usd" in spot.metrics
    assert spot_trades_schema(spot.trades)
    if not spot.trades.empty:
        assert spot.trades["run_id"].eq("p1").all()


def test_spread_lookup_uses_prior_bar_on_gap(spread: pd.Series) -> None:
    idx = spread.index
    gap_ts = idx[10] + pd.Timedelta(hours=12)
    trades = pd.DataFrame([{
        "entry_ts": gap_ts,
        "exit_ts": idx[11],
        "side": "short_protection",
        "pnl_pct": 0.0,
        "pnl_usd": 0.0,
    }])
    minimal = cds_trades_to_minimal(trades, spread, collateral_usd=1.0)
    assert minimal.iloc[0]["entry_price"] == pytest.approx(float(spread.iloc[10]))


def test_short_protection_side_mapping(spread: pd.Series) -> None:
    idx = spread.index
    trades = pd.DataFrame([{
        "entry_ts": idx[0],
        "exit_ts": idx[5],
        "side": "short_protection",
        "pnl_pct": 0.01,
        "pnl_usd": 100.0,
    }])
    minimal = cds_trades_to_minimal(trades, spread, collateral_usd=1.0)
    assert minimal.iloc[0]["side"] == "short"
