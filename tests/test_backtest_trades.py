"""Tests for cryoquant.backtest.trades — TradeLog schema and enrich_trades().

Coverage
--------
TR01  enrich_trades adds all TRADE_COLUMNS to minimal simulator output
TR02  trade_id is sequential 0-based
TR03  run_id default is empty string; custom value propagates
TR04  side defaults to "long"; exit_type defaults to "fixed_hold"
TR05  qty is 1.0 placeholder
TR06  gross_pnl_pct = pnl_pct + fee_pct
TR07  duration_days: positive for normal entry/exit pairs
TR08  duration_bars computed when bars_index supplied
TR09  equity_before and equity_after are finite for non-empty equity curve
TR10  pnl_abs = pnl_pct * equity_before
TR11  enrich_trades on empty DataFrame returns _empty_enriched schema
TR12  enrich_trades raises ValueError when required columns are missing
TR13  enrich_trades with side and exit_type from simulator preserves them
TR14  _empty_enriched returns DataFrame with all TRADE_COLUMNS
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.trades import (
    TRADE_COLUMNS,
    _empty_enriched,
    enrich_trades,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_trades(n: int = 3) -> pd.DataFrame:
    """Return a minimal trade DataFrame as a simulator would output."""
    idx = pd.date_range("2021-01-01", periods=n * 2, freq="5D", tz="UTC")
    rng = np.random.default_rng(42)
    pnl = rng.uniform(-0.03, 0.08, n).tolist()
    return pd.DataFrame({
        "entry_ts":    [idx[i * 2]     for i in range(n)],
        "exit_ts":     [idx[i * 2 + 1] for i in range(n)],
        "entry_price": [100.0 + i * 10 for i in range(n)],
        "exit_price":  [110.0 + i * 10 for i in range(n)],
        "pnl_pct":     pnl,
        "fee_pct":     [0.001] * n,
    })


def _make_equity(n_bars: int = 30) -> pd.Series:
    """Return a synthetic stepped equity curve."""
    idx = pd.date_range("2021-01-01", periods=n_bars, freq="5D", tz="UTC")
    vals = np.ones(n_bars)
    # Simulate equity jumps at a few bars
    vals[5:]  = 1.05
    vals[11:] = 1.03
    vals[17:] = 1.11
    return pd.Series(vals, index=idx, name="equity")


# ---------------------------------------------------------------------------
# TR01 — all TRADE_COLUMNS present
# ---------------------------------------------------------------------------

class TestEnrichTradesColumns:
    def test_all_columns_present(self) -> None:
        trades = _make_minimal_trades(3)
        equity = _make_equity()
        result = enrich_trades(trades, equity)
        missing = set(TRADE_COLUMNS) - set(result.columns)
        assert not missing, f"Missing columns: {missing}"

    def test_column_order(self) -> None:
        trades = _make_minimal_trades(3)
        equity = _make_equity()
        result = enrich_trades(trades, equity)
        assert list(result.columns) == TRADE_COLUMNS


# ---------------------------------------------------------------------------
# TR02 — trade_id is sequential 0-based
# ---------------------------------------------------------------------------

class TestTradeId:
    def test_sequential_zero_based(self) -> None:
        trades = _make_minimal_trades(4)
        result = enrich_trades(trades, _make_equity())
        assert list(result["trade_id"]) == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# TR03 — run_id
# ---------------------------------------------------------------------------

class TestRunId:
    def test_default_empty_string(self) -> None:
        result = enrich_trades(_make_minimal_trades(2), _make_equity())
        assert (result["run_id"] == "").all()

    def test_custom_run_id(self) -> None:
        result = enrich_trades(_make_minimal_trades(2), _make_equity(), run_id="my_run")
        assert (result["run_id"] == "my_run").all()


# ---------------------------------------------------------------------------
# TR04 — defaults for side and exit_type
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_side_defaults_long(self) -> None:
        result = enrich_trades(_make_minimal_trades(2), _make_equity())
        assert (result["side"] == "long").all()

    def test_exit_type_defaults_fixed_hold(self) -> None:
        result = enrich_trades(_make_minimal_trades(2), _make_equity())
        assert (result["exit_type"] == "fixed_hold").all()


# ---------------------------------------------------------------------------
# TR05 — qty placeholder
# ---------------------------------------------------------------------------

class TestQty:
    def test_qty_is_one(self) -> None:
        result = enrich_trades(_make_minimal_trades(3), _make_equity())
        assert (result["qty"] == 1.0).all()


# ---------------------------------------------------------------------------
# TR06 — gross_pnl_pct
# ---------------------------------------------------------------------------

class TestGrossPnl:
    def test_gross_equals_net_plus_fee(self) -> None:
        trades = _make_minimal_trades(3)
        expected = trades["pnl_pct"].values + trades["fee_pct"].values
        result = enrich_trades(trades, _make_equity())
        np.testing.assert_allclose(result["gross_pnl_pct"].values, expected, rtol=1e-10)


# ---------------------------------------------------------------------------
# TR07 — duration_days positive
# ---------------------------------------------------------------------------

class TestDuration:
    def test_duration_days_positive(self) -> None:
        result = enrich_trades(_make_minimal_trades(3), _make_equity())
        assert (result["duration_days"] > 0).all()

    def test_duration_bars_with_index(self) -> None:
        trades = _make_minimal_trades(2)
        equity = _make_equity(30)
        result = enrich_trades(trades, equity, bars_index=equity.index)
        assert result["duration_bars"].notna().all()
        assert (result["duration_bars"] >= 0).all()

    def test_duration_bars_nan_without_index(self) -> None:
        result = enrich_trades(_make_minimal_trades(2), _make_equity())
        # duration_bars should be NaN when no bars_index provided
        assert result["duration_bars"].isna().all()


# ---------------------------------------------------------------------------
# TR09 / TR10 — equity context
# ---------------------------------------------------------------------------

class TestEquityContext:
    def test_equity_before_finite(self) -> None:
        result = enrich_trades(_make_minimal_trades(3), _make_equity())
        assert result["equity_before"].notna().all()
        assert (result["equity_before"] > 0).all()

    def test_pnl_abs_equals_pnl_pct_times_equity_before(self) -> None:
        trades = _make_minimal_trades(3)
        result = enrich_trades(trades, _make_equity())
        expected = result["pnl_pct"] * result["equity_before"]
        np.testing.assert_allclose(
            result["pnl_abs"].values, expected.values, rtol=1e-10
        )


# ---------------------------------------------------------------------------
# TR11 — empty input
# ---------------------------------------------------------------------------

class TestEmptyTrades:
    def test_empty_returns_correct_schema(self) -> None:
        empty = pd.DataFrame(
            columns=["entry_ts", "exit_ts", "entry_price", "exit_price",
                     "pnl_pct", "fee_pct"]
        )
        result = enrich_trades(empty, pd.Series(dtype=float))
        assert list(result.columns) == TRADE_COLUMNS
        assert len(result) == 0


# ---------------------------------------------------------------------------
# TR12 — missing required columns raises ValueError
# ---------------------------------------------------------------------------

class TestMissingColumns:
    def test_raises_on_missing_pnl_pct(self) -> None:
        bad = _make_minimal_trades(2).drop(columns=["pnl_pct"])
        with pytest.raises(ValueError, match="missing required columns"):
            enrich_trades(bad, _make_equity())


# ---------------------------------------------------------------------------
# TR13 — side and exit_type preserved from simulator
# ---------------------------------------------------------------------------

class TestPreserveSideExitType:
    def test_side_short_preserved(self) -> None:
        trades = _make_minimal_trades(2)
        trades["side"] = "short"
        result = enrich_trades(trades, _make_equity())
        assert (result["side"] == "short").all()

    def test_exit_type_trail_preserved(self) -> None:
        trades = _make_minimal_trades(2)
        trades["exit_type"] = "trail"
        result = enrich_trades(trades, _make_equity())
        assert (result["exit_type"] == "trail").all()


# ---------------------------------------------------------------------------
# TR14 — _empty_enriched schema
# ---------------------------------------------------------------------------

class TestEmptyEnriched:
    def test_columns_match_trade_columns(self) -> None:
        result = _empty_enriched()
        assert list(result.columns) == TRADE_COLUMNS
        assert len(result) == 0
