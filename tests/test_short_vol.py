"""Unit tests for short-vol backtest."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.option_lookup import ExitRule
from cryoquant.backtest.short_vol import ShortVolConfig, evaluate_short_vol
from cryoquant.backtest.short_vol_metrics import cvar_loss, trade_sharpe
from cryoquant.signals.base import BoolSignal


def _synthetic_chain(
    expiry_date: date,
    strike: float,
    *,
    call_delta: float = 0.15,
    put_delta: float = 0.15,
) -> pd.DataFrame:
    expiry = _to_expiry_label(expiry_date)
    rows = [
        {
            "expiry": expiry,
            "strike": strike,
            "is_call": True,
            "bid_price": 0.02,
            "ask_price": 0.025,
            "delta": call_delta,
        },
        {
            "expiry": expiry,
            "strike": strike,
            "is_call": False,
            "bid_price": 0.02,
            "ask_price": 0.025,
            "delta": -put_delta,
        },
    ]
    return pd.DataFrame(rows)


def _to_expiry_label(d: date) -> str:
    months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    return f"{d.day}{months[d.month - 1]}{str(d.year)[2:]}"


@pytest.fixture
def chain_dir(tmp_path: Path) -> Path:
    fire = date(2025, 6, 1)
    exit_d = fire + timedelta(days=1)
    expiry = fire + timedelta(days=7)
    spot = 100_000.0
    strike = 110_000.0
    entry_chain = _synthetic_chain(expiry, strike)
    entry_chain.to_parquet(tmp_path / f"options_{fire.isoformat()}.parquet")
    exit_chain = _synthetic_chain(expiry, strike)
    exit_chain.loc[:, "bid_price"] = [0.005, 0.005]
    exit_chain.loc[:, "ask_price"] = [0.008, 0.008]
    exit_chain.to_parquet(tmp_path / f"options_{exit_d.isoformat()}.parquet")
    for d in (fire, exit_d):
        pd.DataFrame({"close": [spot]}).to_parquet(tmp_path / f"spot_{d.isoformat()}.parquet")
    return tmp_path


def test_short_vol_seller_profit_when_pinned(chain_dir: Path) -> None:
    fire_ts = pd.Timestamp("2025-06-01", tz="UTC")
    bars = pd.DataFrame(
        {"close": [100_000.0, 100_000.0]},
        index=pd.DatetimeIndex([fire_ts, fire_ts + pd.Timedelta(days=1)], tz="UTC"),
    )
    signal = BoolSignal("t", lambda df: pd.Series([True, False], index=df.index))
    cfg = ShortVolConfig(
        structure="strangle",
        target_delta=0.15,
        dte=7,
        exit_rule=ExitRule(hold_h=24),
        tilt="symmetric",
    )
    result = evaluate_short_vol(signal, bars, cfg=cfg, chains_dir=chain_dir)
    assert result.fires_with_data >= 1
    assert result.pnl_pct[0] > 0


def test_cvar_manual_tail() -> None:
    pnl = np.array([0.1, 0.05, -0.2, -0.3, -0.1])
    got = cvar_loss(pnl, alpha=0.4)
    assert got == pytest.approx(np.mean([-0.3, -0.2]), rel=1e-6)


def test_trade_sharpe_positive() -> None:
    pnl = [0.01, 0.02, 0.015, 0.01]
    sh = trade_sharpe(pnl)
    assert sh > 0


def test_zero_vol_edge_zero_fires() -> None:
    """Policy gate: no vol edge should not fire (tested via BoolSignal false)."""
    bars = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2025-01-01", tz="UTC")]))
    signal = BoolSignal("never", lambda df: pd.Series(False, index=df.index))
    cfg = ShortVolConfig(structure="strangle", target_delta=0.15, dte=1)
    result = evaluate_short_vol(signal, bars, cfg=cfg, chains_dir=Path("/nonexistent"))
    assert result.fires_evaluated == 0
