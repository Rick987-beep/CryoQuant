"""Phase 3 integration tests (P3-T06–T07)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from src.config_models import load_study_config
from src.label_build import build_study_labels, validate_label_keys
from src.paths import ANALYSIS_ROOT


class TestP3T06LongFormatKeys:
    """P3-T06: unique (timestamp, asset, horizon_id, label_name)."""

    def test_validate_label_keys_passes_on_build(self):
        cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
        end = datetime(2024, 3, 1, tzinfo=timezone.utc)
        df = build_study_labels(cfg, end=end)
        validate_label_keys(df)
        assert {"timestamp", "asset", "horizon_id", "label_name", "value"}.issubset(df.columns)

    def test_duplicate_keys_rejected(self):
        df = pd.DataFrame(
            [
                {
                    "timestamp": pd.Timestamp("2024-01-01", tz="UTC"),
                    "asset": "BTC",
                    "horizon_id": "T+1d",
                    "label_name": "log_return_h1",
                    "value": 0.01,
                },
                {
                    "timestamp": pd.Timestamp("2024-01-01", tz="UTC"),
                    "asset": "BTC",
                    "horizon_id": "T+1d",
                    "label_name": "log_return_h1",
                    "value": 0.02,
                },
            ]
        )
        with pytest.raises(ValueError, match="Duplicate label keys"):
            validate_label_keys(df)


class TestP3T07FeaturesExcludeLabels:
    """P3-T07: feature panel never includes labels."""

    def test_include_labels_false_by_default(self):
        from src.panel_build import build_study_features

        cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
        end = datetime(2024, 2, 1, tzinfo=timezone.utc)
        df = build_study_features(cfg, end=end)
        label_like = [c for c in df.columns if "win_t" in c or c.startswith("exceedance_")]
        assert label_like == []

    def test_include_labels_true_raises(self):
        from src.panel_build import build_study_features

        cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
        with pytest.raises(ValueError, match="include_labels must be False"):
            build_study_features(cfg, include_labels=True)


class TestP3AssetScope:
    def test_sol_has_no_options_labels(self):
        cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
        end = datetime(2024, 6, 1, tzinfo=timezone.utc)
        df = build_study_labels(cfg, end=end)
        sol = df[df.asset == "SOL"]
        bad = sol[sol.label_name.str.startswith(("exceedance_", "vrp_realized_"))]
        assert bad.empty

    def test_no_labels_in_trailing_horizon_window(self):
        from cryocore.instruments import Symbol
        from cryoquant.data.resolve import load_track

        cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
        end = datetime(2024, 6, 1, tzinfo=timezone.utc)
        df = build_study_labels(cfg, end=end)
        start = datetime.combine(cfg.splits.dev_start, datetime.min.time(), tzinfo=timezone.utc)
        bars = load_track(Symbol("binance.spot", "BTCUSDT"), "1d", start, end)
        tail = set(pd.DatetimeIndex(bars.index)[-14:])
        leaked = df[
            (df.asset == "BTC")
            & (df.horizon_id == "T+10-21d")
            & (df.timestamp.isin(tail))
        ]
        assert leaked.empty


class TestP3QA:
    def test_phase3_qa_passes_on_disk(self):
        from src.paths import data_dir
        from src.phase3_qa import run_phase3_qa

        labels = data_dir() / "labels.parquet"
        if not labels.is_file():
            pytest.skip("labels.parquet not built")
        report = run_phase3_qa(labels, data_dir() / "labels_schema.json", data_dir() / "features.parquet")
        assert report.errors == 0
