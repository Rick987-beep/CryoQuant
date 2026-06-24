"""Tests for CDX RunBundle export pipeline."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.bundle import load_bundle
from cryoquant.backtest.scoring import score_leaderboard
from cryoquant.backtest.trades import TRADE_COLUMNS
from scoring_config import CDX_OVERLAY_SCORING, CDX_PORTFOLIO_SCORING
from src.backtest_cds import run_overlay
from src.bundle_export import (
    collection_from_records,
    export_sweep_bundle,
    overlay_record,
    portfolio_record,
)
from src.cds_to_spot import overlay_to_spot
from src.portfolio_backtest import PortfolioSpec, run_portfolio


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.bdate_range("2016-01-01", "2018-12-31", tz="UTC")


@pytest.fixture
def spread(idx: pd.DatetimeIndex) -> pd.Series:
    rng = np.random.default_rng(42)
    vals = 58.0 + rng.normal(0, 0.3, len(idx)).cumsum()
    return pd.Series(np.clip(vals, 50, 85), index=idx)


def _features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"regime_velocity": "moderate", "is_roll_window": False},
        index=idx,
    )


def _position(idx: pd.DatetimeIndex, on: bool = True) -> pd.Series:
    return pd.Series(1.0 if on else 0.0, index=idx)


class TestOverlayRecord:
    def test_builds_run_record(self, spread: pd.Series) -> None:
        pos = pd.Series(0.0, index=spread.index)
        pos.iloc[10:80] = 1.0
        overlay = run_overlay(
            spread, pos, name="tail_a", notional_usd=100e6, collateral_usd=2.5e6,
        )
        rec = overlay_record(
            "tail_a",
            {"overlay": "tail", "name": "tail_a"},
            overlay, spread,
            extra_metrics={"covid_pnl_usd": 1e6},
        )
        assert rec.run_id == "tail_a"
        assert rec.params["overlay"] == "tail"
        assert rec.result.metrics["covid_pnl_usd"] == 1e6
        assert set(TRADE_COLUMNS).issubset(set(rec.result.trades.columns))


class TestExportSweepBundle:
    def test_overlay_bundle_round_trip(self, spread: pd.Series, tmp_path: Path) -> None:
        records = []
        for i, side in enumerate([1.0, -1.0]):
            pos = pd.Series(0.0, index=spread.index)
            pos.iloc[20 + i * 10 : 100 + i * 10] = side
            name = f"run_{i}"
            overlay = run_overlay(
                spread, pos, name=name, notional_usd=50e6, collateral_usd=1.75e6,
            )
            extra = {
                "overlay": "yield" if side < 0 else "tail",
                "calm_pnl_usd": 1000.0 * (i + 1),
                "carry_funding_ratio": 0.5 + i,
                "covid_pnl_usd": 500_000.0 * (i + 1),
            }
            records.append(overlay_record(
                name,
                {"overlay": extra["overlay"], "name": name},
                overlay, spread,
                extra_metrics=extra,
            ))

        collection = collection_from_records(records)
        bundle_dir = export_sweep_bundle(
            tmp_path / "phase3",
            collection,
            meta={"study": "cdx_phase3_overlay_sweep", "data_end": "2018-12-31"},
            scoring=CDX_OVERLAY_SCORING,
        )

        assert (bundle_dir / "meta.json").exists()
        assert (bundle_dir / "leaderboard.parquet").exists()
        assert (bundle_dir / "trades.parquet").exists()
        assert (bundle_dir / "equity_daily.parquet").exists()
        assert (bundle_dir / "report.html").exists()

        loaded = load_bundle(bundle_dir)
        assert loaded.meta["study"] == "cdx_phase3_overlay_sweep"
        assert len(loaded.leaderboard) == 2
        assert "composite_score" in loaded.leaderboard.columns
        assert len(loaded.trades) >= 2
        assert "run_id" in loaded.trades.columns
        assert len(loaded.equity_daily) == 2 * len(spread)

        html = (bundle_dir / "report.html").read_text(encoding="utf-8")
        assert "Sweep Leaderboard" in html
        assert "run_0" in html

    def test_portfolio_bundle_scoring(self, spread: pd.Series, tmp_path: Path) -> None:
        feat = _features(spread.index)
        records = []
        for name, mutex in [("mutex_on", True), ("mutex_off", False)]:
            result = run_portfolio(
                spread, feat,
                spec=PortfolioSpec(
                    name=name, apply_mutex=mutex, yield_strategy="Y1_calm_underwriter",
                ),
            )
            records.append(portfolio_record(
                name,
                {"name": name, "apply_mutex": mutex, "yield_strategy": "Y1_calm_underwriter"},
                result, spread,
            ))

        collection = collection_from_records(records)
        bundle_dir = export_sweep_bundle(
            tmp_path / "phase4",
            collection,
            meta={"study": "cdx_phase4_portfolio"},
            scoring=CDX_PORTFOLIO_SCORING,
            breakdown_cols=("apply_mutex",),
        )
        loaded = load_bundle(bundle_dir)
        assert len(loaded.leaderboard) == 2
        scores = loaded.leaderboard["composite_score"].dropna()
        assert len(scores) == 2

    def test_meta_includes_scoring_config(self, spread: pd.Series, tmp_path: Path) -> None:
        pos = pd.Series(0.0, index=spread.index)
        pos.iloc[5:50] = -1.0
        overlay = run_overlay(spread, pos, name="solo", notional_usd=50e6, collateral_usd=1.75e6)
        rec = overlay_record("solo", {"overlay": "yield"}, overlay, spread)
        bundle_dir = export_sweep_bundle(
            tmp_path / "solo",
            collection_from_records([rec]),
            meta={"study": "cdx_phase3_overlay_sweep"},
            scoring=CDX_OVERLAY_SCORING,
        )
        meta = json.loads((bundle_dir / "meta.json").read_text(encoding="utf-8"))
        assert "scoring" in meta
        assert meta["scoring"]["rank_column"] == "composite_score"
        assert meta["n_runs"] == 1


class TestScoringConfig:
    def test_overlay_scoring_columns_present(self, spread: pd.Series) -> None:
        pos = pd.Series(-1.0, index=spread.index)
        overlay = run_overlay(spread, pos, name="y", notional_usd=50e6, collateral_usd=1.75e6)
        spot = overlay_to_spot(
            overlay, spread,
            extra_metrics={
                "carry_funding_ratio": 1.0,
                "calm_pnl_usd": 100.0,
                "covid_pnl_usd": 200.0,
            },
        )
        rows = [{"run_id": "y", **spot.metrics}]
        lb = score_leaderboard(pd.DataFrame(rows), CDX_OVERLAY_SCORING)
        assert "composite_score" in lb.columns
        assert np.isfinite(lb.iloc[0]["composite_score"])

    def test_portfolio_scoring_handles_pnl_covid(self, spread: pd.Series) -> None:
        feat = _features(spread.index)
        result = run_portfolio(
            spread, feat,
            spec=PortfolioSpec(name="p", apply_mutex=True),
        )
        rec = portfolio_record("p", {"name": "p"}, result, spread)
        lb = pd.DataFrame([{"run_id": rec.run_id, **rec.result.metrics}])
        scored = score_leaderboard(lb, CDX_PORTFOLIO_SCORING)
        assert "composite_score" in scored.columns
        assert "pnl_covid" in scored.columns or "covid_pnl_usd" in rec.result.metrics
