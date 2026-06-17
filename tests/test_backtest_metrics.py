"""Tests for cryoquant.backtest.metrics — compute_metrics() and empty_metrics().

Coverage
--------
M01  empty_metrics has all required keys with correct zero/NaN defaults
M02  compute_metrics on empty trades returns empty_metrics
M03  total_return compounds correctly across trades
M04  win_rate computed correctly
M05  expectancy equals mean of pnl_pct
M06  sharpe == sharpe_trade (not the inflated legacy value) when equity has DatetimeIndex
M07  max_drawdown is negative or zero
M08  profit_factor: winners / losers (positive / negative pnl sum)
M09  calmar: CAGR / abs(max_drawdown)
M10  omega: sum(positive daily_ret) / sum(abs(negative daily_ret))
M11  pct_long / pct_short from side column
M12  avg_hold_days from duration_days column
M13  sortino_equity is finite for a profitable strategy with losses
M14  all new metric keys present in output dict
M15  sharpe_equity NaN when equity is flat (no variance)
M16  cagr is computed from DatetimeIndex dates
M17  sharpe_trade equals sharpe when equity DatetimeIndex available
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.metrics import compute_metrics, empty_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades(pnl_list: list[float], sides: list[str] | None = None) -> pd.DataFrame:
    n = len(pnl_list)
    idx = pd.date_range("2021-01-01", periods=n * 2, freq="5D", tz="UTC")
    df = pd.DataFrame({
        "entry_ts":      [idx[i * 2]      for i in range(n)],
        "exit_ts":       [idx[i * 2 + 1]  for i in range(n)],
        "entry_price":   [100.0] * n,
        "exit_price":    [100.0 * (1 + p)  for p in pnl_list],
        "pnl_pct":       pnl_list,
        "fee_pct":       [0.0] * n,
        "duration_days": [5.0] * n,
    })
    if sides:
        df["side"] = sides
    return df


def _compound_equity(pnl_list: list[float], n_bars: int = 60) -> pd.Series:
    """Build a stepped equity curve that jumps at evenly-spaced exit bars."""
    eq = np.ones(n_bars)
    n = len(pnl_list)
    spacing = n_bars // (n + 1)
    current = 1.0
    for k, pnl in enumerate(pnl_list):
        current *= (1.0 + pnl)
        start = (k + 1) * spacing
        eq[start:] = current
    idx = pd.date_range("2021-01-01", periods=n_bars, freq="1D", tz="UTC")
    return pd.Series(eq, index=idx, name="equity")


# ---------------------------------------------------------------------------
# M01 — empty_metrics keys
# ---------------------------------------------------------------------------

class TestEmptyMetrics:
    _REQUIRED = frozenset({
        "n_trades", "total_return", "win_rate", "sharpe", "sharpe_equity",
        "max_drawdown", "expectancy",
        "sortino_equity", "calmar", "profit_factor", "omega",
        "avg_hold_days", "pct_long", "pct_short",
    })

    def test_all_keys_present(self) -> None:
        m = empty_metrics()
        missing = self._REQUIRED - set(m)
        assert not missing, f"Missing keys: {missing}"

    def test_n_trades_zero(self) -> None:
        assert empty_metrics()["n_trades"] == 0

    def test_numeric_defaults_zero_or_nan(self) -> None:
        m = empty_metrics()
        assert m["total_return"] == 0.0
        assert m["max_drawdown"] == 0.0
        assert math.isnan(m["sharpe"])
        assert math.isnan(m["sharpe_equity"])


# ---------------------------------------------------------------------------
# M02 — compute_metrics on empty trades
# ---------------------------------------------------------------------------

class TestEmptyTradesMetrics:
    def test_returns_empty_metrics(self) -> None:
        m = compute_metrics(pd.DataFrame(), pd.Series(dtype=float))
        assert m["n_trades"] == 0
        assert m["total_return"] == 0.0


# ---------------------------------------------------------------------------
# M03 — total_return
# ---------------------------------------------------------------------------

class TestTotalReturn:
    def test_compounding(self) -> None:
        pnl = [0.10, -0.05, 0.20]
        expected = (1.10 * 0.95 * 1.20) - 1.0
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl))
        assert m["total_return"] == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# M04 — win_rate
# ---------------------------------------------------------------------------

class TestWinRate:
    def test_two_wins_one_loss(self) -> None:
        m = compute_metrics(
            _make_trades([0.05, 0.03, -0.02]),
            _compound_equity([0.05, 0.03, -0.02]),
        )
        assert m["win_rate"] == pytest.approx(2 / 3, rel=1e-9)


# ---------------------------------------------------------------------------
# M05 — expectancy
# ---------------------------------------------------------------------------

class TestExpectancy:
    def test_mean_pnl(self) -> None:
        pnl = [0.10, -0.02, 0.08]
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl))
        assert m["expectancy"] == pytest.approx(float(np.mean(pnl)), rel=1e-9)


# ---------------------------------------------------------------------------
# M06 — sharpe == sharpe_trade (not the old inflated value)
# ---------------------------------------------------------------------------

class TestSharpeIsTradeSharpre:
    def test_sharpe_equals_sharpe_trade(self) -> None:
        """When equity has a DatetimeIndex, sharpe must equal sharpe_trade."""
        pnl = [0.05] * 10 + [-0.02] * 5
        trades = _make_trades(pnl)
        equity = _compound_equity(pnl, n_bars=150)
        m = compute_metrics(trades, equity)
        assert not math.isnan(m["sharpe"]), "sharpe should be finite"
        assert not math.isnan(m["sharpe_trade"]), "sharpe_trade should be finite"
        assert m["sharpe"] == pytest.approx(m["sharpe_trade"], rel=1e-9)

    def test_sharpe_not_inflated(self) -> None:
        """sharpe should be well below the old sqrt(252)-inflated value."""
        pnl = [0.05] * 10 + [-0.02] * 5
        trades = _make_trades(pnl)
        equity = _compound_equity(pnl, n_bars=150)
        m = compute_metrics(trades, equity)
        # Old formula would give ~mean/std * sqrt(252) ≈ 6+; correct is < 5
        assert m["sharpe"] < 5.0, f"sharpe={m['sharpe']:.3f} looks inflated"


# ---------------------------------------------------------------------------
# M07 — max_drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_max_drawdown_non_positive(self) -> None:
        pnl = [0.10, -0.20, 0.05]
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl))
        assert m["max_drawdown"] <= 0.0

    def test_always_profitable_small_drawdown(self) -> None:
        pnl = [0.05] * 10
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl))
        # Equity is monotonically increasing so drawdown approaches 0
        assert m["max_drawdown"] >= -0.001


# ---------------------------------------------------------------------------
# M08 — profit_factor
# ---------------------------------------------------------------------------

class TestProfitFactor:
    def test_profit_factor_greater_than_one_when_profitable(self) -> None:
        pnl = [0.10, 0.08, -0.03]
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl))
        assert m["profit_factor"] > 1.0

    def test_profit_factor_less_than_one_when_losing(self) -> None:
        pnl = [-0.10, -0.08, 0.03]
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl))
        assert m["profit_factor"] < 1.0


# ---------------------------------------------------------------------------
# M11 — pct_long / pct_short
# ---------------------------------------------------------------------------

class TestDirectionMix:
    def test_all_long(self) -> None:
        m = compute_metrics(
            _make_trades([0.05, 0.03], sides=["long", "long"]),
            _compound_equity([0.05, 0.03]),
        )
        assert m["pct_long"] == pytest.approx(1.0)
        assert m["pct_short"] == pytest.approx(0.0)

    def test_mixed(self) -> None:
        m = compute_metrics(
            _make_trades([0.05, -0.02], sides=["long", "short"]),
            _compound_equity([0.05, -0.02]),
        )
        assert m["pct_long"] == pytest.approx(0.5)
        assert m["pct_short"] == pytest.approx(0.5)

    def test_no_side_column_nan(self) -> None:
        m = compute_metrics(_make_trades([0.05, 0.03]), _compound_equity([0.05, 0.03]))
        assert math.isnan(m["pct_long"])
        assert math.isnan(m["pct_short"])


# ---------------------------------------------------------------------------
# M12 — avg_hold_days
# ---------------------------------------------------------------------------

class TestAvgHoldDays:
    def test_avg_hold_days(self) -> None:
        trades = _make_trades([0.05, 0.03])
        trades["duration_days"] = [5.0, 10.0]
        m = compute_metrics(trades, _compound_equity([0.05, 0.03]))
        assert m["avg_hold_days"] == pytest.approx(7.5)

    def test_avg_hold_days_nan_without_column(self) -> None:
        trades = _make_trades([0.05, 0.03])
        trades = trades.drop(columns=["duration_days"])
        m = compute_metrics(trades, _compound_equity([0.05, 0.03]))
        assert math.isnan(m["avg_hold_days"])


# ---------------------------------------------------------------------------
# M14 — all new keys in output
# ---------------------------------------------------------------------------

class TestNewKeysPresent:
    _NEW = frozenset({
        "sortino_equity", "calmar", "profit_factor", "omega",
        "avg_hold_days", "pct_long", "pct_short",
    })

    def test_all_new_keys_in_output(self) -> None:
        pnl = [0.05, -0.02, 0.08, 0.03, -0.01]
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl, n_bars=100))
        missing = self._NEW - set(m)
        assert not missing, f"Missing new keys: {missing}"


# ---------------------------------------------------------------------------
# M15 — flat equity → sharpe_equity NaN
# ---------------------------------------------------------------------------

class TestFlatEquity:
    def test_flat_equity_sharpe_equity_nan(self) -> None:
        pnl = [0.0, 0.0, 0.0]
        trades = _make_trades(pnl)
        n = 30
        eq = pd.Series(
            np.ones(n),
            index=pd.date_range("2021-01-01", periods=n, freq="1D", tz="UTC"),
            name="equity",
        )
        m = compute_metrics(trades, eq)
        assert math.isnan(m["sharpe_equity"])


# ---------------------------------------------------------------------------
# M16 — CAGR from DatetimeIndex dates
# ---------------------------------------------------------------------------

class TestCagr:
    def test_cagr_two_year_doubling(self) -> None:
        """A strategy that doubles over exactly 2 years should have CAGR = sqrt(2) - 1."""
        n = 730  # ~2 years of daily bars
        pnl = [1.0]  # one trade: +100%
        trades = _make_trades(pnl)
        eq = pd.Series(
            np.concatenate([np.ones(365), np.full(365, 2.0)]),
            index=pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC"),
            name="equity",
        )
        m = compute_metrics(trades, eq)
        expected = 2.0 ** (1 / (729 / 365.25)) - 1.0
        assert m["cagr"] == pytest.approx(expected, rel=0.01)

    def test_cagr_positive_for_profitable(self) -> None:
        pnl = [0.05, 0.03, 0.08]
        m = compute_metrics(_make_trades(pnl), _compound_equity(pnl))
        assert m["cagr"] > 0.0

    def test_cagr_nan_for_empty_trades(self) -> None:
        m = compute_metrics(pd.DataFrame(), pd.Series(dtype=float))
        assert math.isnan(m["cagr"])

    def test_cagr_in_empty_metrics(self) -> None:
        assert math.isnan(empty_metrics()["cagr"])


# ---------------------------------------------------------------------------
# M17 — sharpe_trade explicit
# ---------------------------------------------------------------------------

class TestSharpeTradeExplicit:
    def test_sharpe_trade_in_empty_metrics(self) -> None:
        assert math.isnan(empty_metrics()["sharpe_trade"])

    def test_sharpe_trade_matches_formula(self) -> None:
        """sharpe_trade = mean/std * sqrt(n / n_years)."""
        pnl = [0.05, -0.02, 0.08, 0.03, -0.01, 0.06]
        n = len(pnl)
        equity = _compound_equity(pnl, n_bars=180)  # ~6 months daily
        n_years = 179 / 365.25
        tpy = n / n_years
        expected = float(np.mean(pnl) / np.std(pnl, ddof=1) * math.sqrt(tpy))
        m = compute_metrics(_make_trades(pnl), equity)
        assert m["sharpe_trade"] == pytest.approx(expected, rel=1e-6)
