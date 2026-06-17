"""Tests for cryoquant.backtest.bundle — RunBundle, write_bundle, load_bundle.

Coverage
--------
B01  write_bundle creates expected files
B02  load_bundle round-trips meta.json
B03  load_bundle round-trips leaderboard DataFrame
B04  load_bundle round-trips trades DataFrame
B05  load_bundle round-trips equity_daily DataFrame
B06  write_bundle adds bundle_version and created_at to meta
B07  load_bundle on missing directory raises FileNotFoundError
B08  Empty DataFrames do not write parquet files
B09  load_bundle returns empty DataFrames for missing parquet files
B10  write_bundle returns absolute Path
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.bundle import RunBundle, load_bundle, write_bundle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bundle(tmp_path: Path) -> tuple[Path, RunBundle]:
    leaderboard = pd.DataFrame({
        "run_id":       ["r1", "r2"],
        "n_trades":     [20, 15],
        "sharpe_equity": [1.5, 0.8],
    })
    trades = pd.DataFrame({
        "run_id":    ["r1", "r1", "r2"],
        "trade_id":  [0, 1, 0],
        "pnl_pct":   [0.05, -0.02, 0.08],
    })
    equity_daily = pd.DataFrame({
        "run_id": ["r1", "r1", "r2"],
        "date":   pd.date_range("2021-01-01", periods=3, tz="UTC"),
        "equity": [1.0, 1.05, 1.03],
    })
    bundle = RunBundle(
        meta={"study": "test_study", "n_runs": 2},
        leaderboard=leaderboard,
        trades=trades,
        equity_daily=equity_daily,
    )
    bundle_dir = tmp_path / "bundle"
    return bundle_dir, bundle


# ---------------------------------------------------------------------------
# B01 — expected files created
# ---------------------------------------------------------------------------

class TestWriteBundleFiles:
    def test_all_expected_files_created(self, tmp_path: Path) -> None:
        bundle_dir, bundle = _make_bundle(tmp_path)
        write_bundle(bundle_dir, bundle)
        assert (bundle_dir / "meta.json").exists()
        assert (bundle_dir / "leaderboard.parquet").exists()
        assert (bundle_dir / "leaderboard.csv").exists()
        assert (bundle_dir / "trades.parquet").exists()
        assert (bundle_dir / "equity_daily.parquet").exists()


# ---------------------------------------------------------------------------
# B02 — meta round-trip
# ---------------------------------------------------------------------------

class TestMetaRoundTrip:
    def test_meta_round_trip(self, tmp_path: Path) -> None:
        bundle_dir, bundle = _make_bundle(tmp_path)
        write_bundle(bundle_dir, bundle)
        loaded = load_bundle(bundle_dir)
        assert loaded.meta["study"] == "test_study"
        assert loaded.meta["n_runs"] == 2


# ---------------------------------------------------------------------------
# B03 — leaderboard round-trip
# ---------------------------------------------------------------------------

class TestLeaderboardRoundTrip:
    def test_leaderboard_round_trip(self, tmp_path: Path) -> None:
        bundle_dir, bundle = _make_bundle(tmp_path)
        write_bundle(bundle_dir, bundle)
        loaded = load_bundle(bundle_dir)
        assert list(loaded.leaderboard["run_id"]) == ["r1", "r2"]
        assert list(loaded.leaderboard["n_trades"]) == [20, 15]


# ---------------------------------------------------------------------------
# B04 — trades round-trip
# ---------------------------------------------------------------------------

class TestTradesRoundTrip:
    def test_trades_round_trip(self, tmp_path: Path) -> None:
        bundle_dir, bundle = _make_bundle(tmp_path)
        write_bundle(bundle_dir, bundle)
        loaded = load_bundle(bundle_dir)
        assert len(loaded.trades) == 3
        np.testing.assert_allclose(
            sorted(loaded.trades["pnl_pct"].values),
            sorted([0.05, -0.02, 0.08]),
        )


# ---------------------------------------------------------------------------
# B05 — equity_daily round-trip
# ---------------------------------------------------------------------------

class TestEquityDailyRoundTrip:
    def test_equity_daily_round_trip(self, tmp_path: Path) -> None:
        bundle_dir, bundle = _make_bundle(tmp_path)
        write_bundle(bundle_dir, bundle)
        loaded = load_bundle(bundle_dir)
        assert len(loaded.equity_daily) == 3


# ---------------------------------------------------------------------------
# B06 — auto-adds bundle_version and created_at
# ---------------------------------------------------------------------------

class TestMetaAutoKeys:
    def test_bundle_version_added(self, tmp_path: Path) -> None:
        bundle_dir, bundle = _make_bundle(tmp_path)
        write_bundle(bundle_dir, bundle)
        with open(bundle_dir / "meta.json") as f:
            meta = json.load(f)
        assert "bundle_version" in meta
        assert "created_at" in meta


# ---------------------------------------------------------------------------
# B07 — missing directory raises
# ---------------------------------------------------------------------------

class TestLoadMissingDir:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_bundle(tmp_path / "does_not_exist")


# ---------------------------------------------------------------------------
# B08 — empty DataFrames do not write parquet
# ---------------------------------------------------------------------------

class TestEmptyDataFramesNotWritten:
    def test_empty_trades_no_parquet(self, tmp_path: Path) -> None:
        bundle = RunBundle(
            meta={"study": "empty"},
            leaderboard=pd.DataFrame(),
            trades=pd.DataFrame(),
            equity_daily=pd.DataFrame(),
        )
        bundle_dir = tmp_path / "empty_bundle"
        write_bundle(bundle_dir, bundle)
        assert not (bundle_dir / "trades.parquet").exists()
        assert not (bundle_dir / "equity_daily.parquet").exists()
        assert not (bundle_dir / "leaderboard.parquet").exists()


# ---------------------------------------------------------------------------
# B09 — load returns empty DataFrames for missing parquet
# ---------------------------------------------------------------------------

class TestLoadMissingParquet:
    def test_missing_parquet_returns_empty_df(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "sparse"
        bundle_dir.mkdir()
        with open(bundle_dir / "meta.json", "w") as f:
            json.dump({"study": "sparse"}, f)
        loaded = load_bundle(bundle_dir)
        assert loaded.trades.empty
        assert loaded.leaderboard.empty
        assert loaded.equity_daily.empty


# ---------------------------------------------------------------------------
# B10 — returns absolute path
# ---------------------------------------------------------------------------

class TestWriteBundleReturnsPath:
    def test_returns_absolute_path(self, tmp_path: Path) -> None:
        bundle_dir, bundle = _make_bundle(tmp_path)
        result = write_bundle(bundle_dir, bundle)
        assert result.is_absolute()


# ---------------------------------------------------------------------------
# B11 — end-to-end sweep pipeline with breakout_sim
# ---------------------------------------------------------------------------

class TestSweepPipelineIntegration:
    """collect_runs → score_leaderboard → write_bundle → load_bundle."""

    def test_breakout_sweep_round_trip(self, tmp_path: Path) -> None:
        from dataclasses import dataclass
        from typing import Literal

        import numpy as np
        import pandas as pd

        from cryoquant.backtest.breakout_sim import BreakoutConfig, simulate_breakout
        from cryoquant.backtest.scoring import ScoringConfig, score_leaderboard
        from cryoquant.backtest.sweep_collector import collect_runs

        @dataclass(frozen=True)
        class MiniCfg:
            direction: Literal["long", "short"]
            entry_n: int
            exit_n: int

            @property
            def run_id(self) -> str:
                return f"{self.direction}_e{self.entry_n}_x{self.exit_n}"

        def _bars(step: float, n: int = 500) -> pd.DataFrame:
            rng = np.random.default_rng(7)
            close = 100.0 + np.arange(n) * step + rng.normal(0, 2, n) * 0.3
            close = np.clip(close, 50, None)
            idx = pd.date_range("2016-01-01", periods=n, freq="1D", tz="UTC")
            return pd.DataFrame(
                {"open": close, "high": close + 0.5, "low": close - 0.5,
                 "close": close, "volume": 1.0},
                index=idx,
            )

        cfgs = [
            MiniCfg("long", 20, 10),
            MiniCfg("long", 40, 20),
            MiniCfg("short", 20, 10),
            MiniCfg("short", 40, 20),
        ]

        def runner(cfg: MiniCfg):
            bars = _bars(0.5 if cfg.direction == "long" else -0.5)
            config = BreakoutConfig(
                entry_n=cfg.entry_n, exit_n=cfg.exit_n,
                direction=cfg.direction, fee_bps=0.0,
            )
            return simulate_breakout(bars, config)

        coll = collect_runs(
            cfgs, runner,
            run_id_fn=lambda c: c.run_id,
            params_fn=lambda c: {"direction": c.direction, "entry_n": c.entry_n},
            min_trades=1,
        )
        assert len(coll.records) >= 1

        lb = pd.DataFrame(coll.leaderboard_rows())
        for col in ("dsr", "profit_factor", "calmar"):
            if col not in lb.columns:
                lb[col] = 0.5

        scoring = ScoringConfig(
            weights={"sharpe_equity": 1.0},
            higher_is_better=("sharpe_equity",),
            rank_column="composite_score",
            min_trades=1,
        )
        scored = score_leaderboard(lb, scoring)
        assert "composite_score" in scored.columns

        bundle = RunBundle(
            meta={"study": "integration_test", "n_runs": len(cfgs)},
            leaderboard=scored,
            trades=coll.trades_df(),
            equity_daily=coll.equity_daily_df(),
        )
        bundle_dir = write_bundle(tmp_path / "sweep_bundle", bundle)
        loaded = load_bundle(bundle_dir)
        assert loaded.meta["study"] == "integration_test"
        assert len(loaded.leaderboard) == len(scored)
        assert "run_id" in loaded.leaderboard.columns
