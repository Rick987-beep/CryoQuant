"""Tests for cryoquant.backtest.replay and account."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.account import (
    VXM,
    VX,
    AccountConfig,
    ExecutionModel,
    apply_fill_price,
    build_futures_equity,
    futures_pnl_dollars,
)
from cryoquant.backtest.replay import (
    ReplayConfig,
    long_touch_fill,
    replay_weights,
    short_touch_fill,
)


def _bars(n: int = 10, start: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    close = start + np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )


def test_long_touch_fill_level_and_gap():
    assert long_touch_fill(10.0, 9.0, 9.5) == pytest.approx(9.5)
    assert long_touch_fill(9.0, 8.5, 9.5) == pytest.approx(9.0)  # gap through
    assert long_touch_fill(10.0, 9.6, 9.5) is None


def test_short_touch_fill_level_and_gap():
    assert short_touch_fill(10.0, 11.0, 10.5) == pytest.approx(10.5)
    assert short_touch_fill(11.0, 11.5, 10.5) == pytest.approx(11.0)
    assert short_touch_fill(10.0, 10.2, 10.5) is None


def test_replay_weights_next_open_equity():
    bars = _bars(5, start=100.0)
    w = pd.Series([1.0, 1.0, 1.0, 0.0, 0.0], index=bars.index)
    res = replay_weights(bars, w, config=ReplayConfig(fee_bps=0.0, symbol="TEST"))
    assert len(res.bar_log) == 5
    assert res.equity.iloc[0] == pytest.approx(1.0)
    assert res.equity.iloc[1] == pytest.approx(1.0 * (bars["close"].iloc[1] / bars["close"].iloc[0]))


def test_replay_weights_rejects_touch_exec():
    bars = _bars(3)
    w = pd.Series(0.0, index=bars.index)
    with pytest.raises(NotImplementedError):
        replay_weights(bars, w, config=ReplayConfig(exec="touch"))


def test_vxm_multiplier_is_100_vx_is_1000():
    assert VXM.multiplier == 100.0
    assert VX.multiplier == 1000.0
    assert VXM.tick_value == pytest.approx(1.0)


def test_futures_pnl_short_and_execution_hooks():
    acct = AccountConfig(
        initial_cash=100_000.0,
        instrument=VXM,
        execution=ExecutionModel(fee_per_side=2.5, spread_ticks=2.0, slippage_ticks=0.0),
        contracts=1,
    )
    fill = apply_fill_price(20.0, side="short", is_entry=True, account=acct)
    assert fill < 20.0
    gross, fee, net = futures_pnl_dollars(
        side="short",
        contracts=1,
        entry_price=20.0,
        exit_price=18.0,
        account=AccountConfig(instrument=VXM, execution=ExecutionModel(fee_per_side=2.5)),
    )
    assert gross == pytest.approx(200.0)  # 1 * 100 * 2
    assert fee == pytest.approx(5.0)
    assert net == pytest.approx(195.0)


def test_build_futures_equity_short_round_trip():
    close = np.array([20.0, 21.0, 19.0, 18.0], dtype=float)
    acct = AccountConfig(initial_cash=100_000.0, instrument=VXM, contracts=1)
    trades = [
        {
            "entry_i": 1,
            "exit_i": 3,
            "side": "short",
            "qty": 1,
            "entry_price": 21.0,
            "exit_price": 18.0,
        }
    ]
    eq = build_futures_equity(close, trades, account=acct)
    assert eq.iloc[0] == pytest.approx(100_000.0)
    # Short from 21→18 = +3 points × $100 = +$300
    assert eq.iloc[-1] == pytest.approx(100_300.0)
