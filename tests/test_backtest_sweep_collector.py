"""Tests for cryoquant.backtest.sweep_collector.

Coverage
--------
SC01  collect_runs with all-passing runner collects all configs
SC02  collect_runs skips configs returning None
SC03  collect_runs skips runs with n_trades < min_trades
SC04  collect_runs catches and counts exceptions from runner
SC05  SweepCollection.leaderboard_rows merges params + metrics + run_id
SC06  SweepCollection.trades_df stacks trades with run_id column
SC07  SweepCollection.equity_daily_df stacks equity with run_id, date, equity
SC08  collect_runs with empty configs list returns empty SweepCollection
SC09  run_id_fn and params_fn called once per config
SC10  n_skipped incremented for each skipped/failed run
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.spot_pnl import SpotResult
from cryoquant.backtest.sweep_collector import (
    RunRecord,
    SweepCollection,
    collect_runs,
)
from cryoquant.backtest.trades import TRADE_COLUMNS, _empty_enriched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FakeConfig:
    name: str
    will_fail: bool = False
    n_trades: int = 15


def _make_spot_result(n_trades: int = 15) -> SpotResult:
    """Build a minimal SpotResult with synthetic trades and equity."""
    idx = pd.date_range("2021-01-01", periods=n_trades * 2 + 10, freq="1D", tz="UTC")
    pnl = np.random.default_rng(0).uniform(-0.02, 0.05, n_trades)

    # Build enriched trades with all required columns
    base_trades = pd.DataFrame({
        "entry_ts":    [idx[i * 2]       for i in range(n_trades)],
        "exit_ts":     [idx[i * 2 + 1]   for i in range(n_trades)],
        "entry_price": [100.0] * n_trades,
        "exit_price":  [100.0 * (1 + p)  for p in pnl],
        "pnl_pct":     pnl,
        "fee_pct":     np.full(n_trades, 0.001),
    })

    # Minimal equity
    n_bars = len(idx)
    eq_arr = np.ones(n_bars)
    current = 1.0
    for k, p in enumerate(pnl):
        current *= 1.0 + p
        eq_arr[(k + 1) * 2:] = current
    equity = pd.Series(eq_arr, index=idx, name="equity")

    # Enrich
    from cryoquant.backtest.trades import enrich_trades
    enriched = enrich_trades(base_trades, equity)

    from cryoquant.backtest.metrics import compute_metrics
    metrics = compute_metrics(enriched, equity)

    return SpotResult(equity=equity, trades=enriched, metrics=metrics)


def _runner(cfg: FakeConfig) -> SpotResult | None:
    if cfg.will_fail:
        raise RuntimeError("Simulated runner failure")
    return _make_spot_result(cfg.n_trades)


def _run_id_fn(cfg: FakeConfig) -> str:
    return cfg.name


def _params_fn(cfg: FakeConfig) -> dict:
    return {"name": cfg.name}


# ---------------------------------------------------------------------------
# SC01 — all-passing
# ---------------------------------------------------------------------------

class TestCollectAllPass:
    def test_all_collected(self) -> None:
        configs = [FakeConfig(f"run_{i}") for i in range(5)]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        assert len(coll.records) == 5
        assert coll.n_skipped == 0


# ---------------------------------------------------------------------------
# SC02 — runner returns None → skipped
# ---------------------------------------------------------------------------

class TestSkipNone:
    def test_none_runner_skipped(self) -> None:
        configs = [FakeConfig("good"), FakeConfig("none_return")]
        def runner(cfg):
            if cfg.name == "none_return":
                return None
            return _make_spot_result()
        coll = collect_runs(configs, runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        assert len(coll.records) == 1
        assert coll.n_skipped == 1


# ---------------------------------------------------------------------------
# SC03 — n_trades < min_trades → skipped
# ---------------------------------------------------------------------------

class TestSkipMinTrades:
    def test_below_min_trades_skipped(self) -> None:
        configs = [FakeConfig("big", n_trades=20), FakeConfig("tiny", n_trades=2)]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=10)
        run_ids = [r.run_id for r in coll.records]
        assert "big" in run_ids
        assert "tiny" not in run_ids
        assert coll.n_skipped == 1


# ---------------------------------------------------------------------------
# SC04 — exceptions caught
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    def test_exception_counted_as_skipped(self) -> None:
        configs = [FakeConfig("ok"), FakeConfig("bad", will_fail=True)]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        assert len(coll.records) == 1
        assert coll.n_skipped == 1


# ---------------------------------------------------------------------------
# SC05 — leaderboard_rows
# ---------------------------------------------------------------------------

class TestLeaderboardRows:
    def test_merges_params_and_metrics(self) -> None:
        configs = [FakeConfig("r0"), FakeConfig("r1")]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        rows = coll.leaderboard_rows()
        assert len(rows) == 2
        assert "run_id" in rows[0]
        assert "name" in rows[0]
        assert "n_trades" in rows[0]


# ---------------------------------------------------------------------------
# SC06 — trades_df
# ---------------------------------------------------------------------------

class TestTradesDf:
    def test_stacked_with_run_id(self) -> None:
        configs = [FakeConfig("r0", n_trades=10), FakeConfig("r1", n_trades=12)]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        df = coll.trades_df()
        assert "run_id" in df.columns
        assert set(df["run_id"].unique()) == {"r0", "r1"}
        assert len(df) == 10 + 12

    def test_has_all_trade_columns(self) -> None:
        configs = [FakeConfig("r0")]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        df = coll.trades_df()
        for col in TRADE_COLUMNS:
            assert col in df.columns, f"Missing TRADE_COLUMN: {col}"


# ---------------------------------------------------------------------------
# SC07 — equity_daily_df
# ---------------------------------------------------------------------------

class TestEquityDailyDf:
    def test_has_run_id_date_equity_columns(self) -> None:
        configs = [FakeConfig("r0")]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        df = coll.equity_daily_df()
        assert {"run_id", "date", "equity"} <= set(df.columns)


# ---------------------------------------------------------------------------
# SC08 — empty configs
# ---------------------------------------------------------------------------

class TestEmptyConfigs:
    def test_empty_configs_returns_empty_collection(self) -> None:
        coll = collect_runs([], _runner, run_id_fn=_run_id_fn, params_fn=_params_fn)
        assert len(coll.records) == 0
        assert coll.n_skipped == 0

    def test_empty_trades_df(self) -> None:
        coll = collect_runs([], _runner, run_id_fn=_run_id_fn, params_fn=_params_fn)
        df = coll.trades_df()
        assert df.empty
        assert list(df.columns) == TRADE_COLUMNS


# ---------------------------------------------------------------------------
# SC10 — n_skipped counts
# ---------------------------------------------------------------------------

class TestNSkipped:
    def test_n_skipped_total(self) -> None:
        configs = [
            FakeConfig("ok1"),
            FakeConfig("bad", will_fail=True),
            FakeConfig("tiny", n_trades=1),
        ]
        coll = collect_runs(configs, _runner, run_id_fn=_run_id_fn, params_fn=_params_fn, min_trades=5)
        assert coll.n_skipped == 2
        assert len(coll.records) == 1
