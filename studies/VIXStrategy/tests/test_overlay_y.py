"""Tests for Overlay Y mean-reversion sleeve."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.band_features import build_y_features, pct_rank, zscore
from src.overlay_y import Y1Config, Y2Config, Y3Config, simulate_y1, simulate_y2, simulate_y3, DEFAULT_ACCOUNT
import pytest


def _mr_bars(n: int = 80) -> pd.DataFrame:
    """Synthetic mean-reverting-ish path with clear dips and spikes."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2018-01-01", periods=n, freq="B", tz="UTC")
    x = 20.0 + np.sin(np.linspace(0, 8 * np.pi, n)) * 3.0 + rng.normal(0, 0.3, n)
    # Inject a dip and a spike
    x[30] = 12.0
    x[31] = 13.0
    x[50] = 28.0
    x[51] = 26.0
    close = pd.Series(x, index=idx)
    high = close + 0.8
    low = close - 0.8
    # Ensure dip low reaches far
    low.iloc[30] = 11.0
    high.iloc[50] = 29.0
    open_ = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1.0},
        index=idx,
    )


def test_features_causal_shift():
    bars = _mr_bars(80)
    feat = build_y_features(bars, z_n=10, rank_w=20)
    assert feat["sma_prev"].iloc[15] == pytest.approx(feat["sma"].iloc[14])


def test_y1_produces_trades_and_bar_log():
    bars = _mr_bars(80)
    res = simulate_y1(bars, Y1Config(n=10, z_enter=1.0, max_hold=10, contracts=1))
    assert len(res.bar_log) == len(bars)
    assert res.equity.iloc[0] == pytest.approx(DEFAULT_ACCOUNT.initial_cash)
    assert "n_trades" in res.metrics
    assert "position_contracts" in res.bar_log.columns


def test_y1_mutex_blocks_entries():
    bars = _mr_bars(80)
    tac = pd.Series(True, index=bars.index)
    res = simulate_y1(bars, Y1Config(n=10, z_enter=1.0), t_tactical_on=tac)
    assert res.metrics["n_trades"] == 0


def test_y2_and_y3_smoke():
    bars = _mr_bars(100)
    r2 = simulate_y2(bars, Y2Config(w=20, lo=0.2, hi=0.8, max_hold=8))
    r3 = simulate_y3(bars)
    assert len(r2.equity) == len(bars)
    assert len(r3.equity) == len(bars)
    assert r2.equity.iloc[0] == pytest.approx(100_000.0)


def test_dollar_pnl_scales_with_contracts_and_multiplier():
    bars = _mr_bars(100)
    r1 = simulate_y3(bars, Y3Config(contracts=1), account=DEFAULT_ACCOUNT)
    r2 = simulate_y3(bars, Y3Config(contracts=2), account=DEFAULT_ACCOUNT)
    if r1.metrics["n_trades"] == 0:
        pytest.skip("no trades in synthetic path")
    # Terminal P&L vs start should roughly double with 2 contracts (additive $ MTM)
    pnl1 = float(r1.equity.iloc[-1] - r1.equity.iloc[0])
    pnl2 = float(r2.equity.iloc[-1] - r2.equity.iloc[0])
    assert pnl2 == pytest.approx(2.0 * pnl1, rel=1e-9)
    if len(r1.trades):
        assert float(r1.trades.iloc[0]["qty"]) == 1.0
        assert "pnl_abs" in r1.trades.columns


def test_pct_rank_bounds():
    s = pd.Series(np.arange(10, dtype=float))
    r = pct_rank(s, 5)
    assert r.iloc[-1] == 1.0
