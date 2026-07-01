"""Tests for Phase 5 manifest, index, and primary bundle."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.portfolio_backtest import PortfolioSpec, run_portfolio
from src.primary_bundle import export_primary_bundle
from src.report_manifest import (
    build_manifest,
    bundle_status,
    primary_status,
    render_index_html,
    write_manifest,
)


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return pd.bdate_range("2016-01-01", "2018-12-31", tz="UTC")


@pytest.fixture
def spread(idx: pd.DatetimeIndex) -> pd.Series:
    rng = np.random.default_rng(0)
    vals = 58.0 + rng.normal(0, 0.2, len(idx)).cumsum()
    return pd.Series(np.clip(vals, 50, 85), index=idx)


def _features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"regime_velocity": "moderate", "is_roll_window": False},
        index=idx,
    )


def _fake_sweep_bundle(path: Path, study: str, rows: list[dict]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    meta = {"study": study, "n_runs": len(rows), "data_end": "2018-12-31"}
    (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    pd.DataFrame(rows).to_parquet(path / "leaderboard.parquet", index=False)
    (path / "report.html").write_text("<html><body>sweep</body></html>", encoding="utf-8")


class TestPrimaryBundle:
    def test_export_primary_bundle_files(self, spread: pd.Series, tmp_path: Path) -> None:
        feat = _features(spread.index)
        result = run_portfolio(
            spread, feat,
            spec=PortfolioSpec(name="tail_y8_mutex", apply_mutex=True),
        )
        out = export_primary_bundle(
            result, spread, tmp_path / "primary",
            meta_extra={"data_end": "2018-12-31"},
        )
        assert (out / "meta.json").exists()
        assert (out / "equity_daily.parquet").exists()
        assert (out / "attribution_daily.parquet").exists()
        assert (out / "report.html").exists()

        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        assert meta["name"] == "tail_y8_mutex"
        assert meta["study"] == "cdx_primary_portfolio"

        eq = pd.read_parquet(out / "equity_daily.parquet")
        assert {"date", "equity", "nav_usd"}.issubset(eq.columns)
        assert len(eq) == len(spread)

        attr = pd.read_parquet(out / "attribution_daily.parquet")
        assert "pnl_tail" in attr.columns
        assert "pnl_yield" in attr.columns
        assert "total" in attr.columns

        html = (out / "report.html").read_text(encoding="utf-8")
        assert "tail_y8_mutex" in html

    def test_primary_status(self, spread: pd.Series, tmp_path: Path) -> None:
        feat = _features(spread.index)
        result = run_portfolio(spread, feat, spec=PortfolioSpec(name="p"))
        export_primary_bundle(result, spread, tmp_path / "primary")
        status = primary_status(tmp_path / "primary")
        assert status["status"] == "ok"
        assert status["name"] == "p"
        assert status["nav_end"] == pytest.approx(result.metrics["nav_end"])


class TestManifest:
    def test_build_manifest_with_fake_bundles(self, spread: pd.Series, tmp_path: Path) -> None:
        p3 = tmp_path / "phase3"
        p4 = tmp_path / "phase4"
        primary = tmp_path / "primary"
        _fake_sweep_bundle(p3, "cdx_phase3_overlay_sweep", [
            {"run_id": "Y8_velocity_filter", "nav_end": 5.4, "composite_score": 0.9},
        ])
        _fake_sweep_bundle(p4, "cdx_phase4_portfolio", [
            {"run_id": "tail_y8_mutex", "nav_end": 1.94, "composite_score": 0.8},
        ])
        feat = _features(spread.index)
        result = run_portfolio(spread, feat, spec=PortfolioSpec(name="tail_y8_mutex"))
        export_primary_bundle(result, spread, primary)

        manifest = build_manifest(
            data_start="2016-01-01",
            data_end="2018-12-31",
            n_bars=len(spread),
            primary_name="tail_y8_mutex",
            phase3_dir=p3,
            phase4_dir=p4,
            primary_dir=primary,
            walk_forward={"spec": "tail_y8_mutex", "metrics": {"n_blocks": 2, "nav_end": 1.5}, "blocks": []},
        )
        assert manifest["study"] == "CDX.NA.IG"
        assert manifest["bundles"]["phase3_overlay_sweep"]["status"] == "ok"
        assert manifest["highlights"]["top_yield_run"] == "Y8_velocity_filter"
        assert manifest["highlights"]["primary_nav_end"] == pytest.approx(result.metrics["nav_end"])

    def test_bundle_status_missing(self, tmp_path: Path) -> None:
        assert bundle_status(tmp_path / "nope")["status"] == "missing"

    def test_write_manifest_and_index(self, spread: pd.Series, tmp_path: Path) -> None:
        primary = tmp_path / "primary"
        feat = _features(spread.index)
        result = run_portfolio(spread, feat, spec=PortfolioSpec(name="tail_y8_mutex"))
        export_primary_bundle(result, spread, primary)

        manifest = build_manifest(
            data_start="2016-01-01",
            data_end="2018-12-31",
            n_bars=len(spread),
            primary_name="tail_y8_mutex",
            phase3_dir=tmp_path / "missing3",
            phase4_dir=tmp_path / "missing4",
            primary_dir=primary,
        )
        manifest_path = write_manifest(tmp_path / "manifest.json", manifest)
        index_path = render_index_html(tmp_path / "report.html", manifest)

        assert manifest_path.exists()
        assert index_path.exists()
        html = index_path.read_text(encoding="utf-8")
        assert "CDX.NA.IG" in html
        assert "Primary" in html
        assert "missing" in html.lower() or "Open report" in html
