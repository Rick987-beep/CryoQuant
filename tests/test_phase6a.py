"""Phase 6A acceptance tests — framework closure hygiene.

See ``docs/archive/quant_spec.md`` § Phase 6A.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestDependencyHygiene:
    def test_pyproject_declares_yfinance(self):
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "yfinance" in text

    def test_yfinance_importable(self):
        pytest.importorskip("yfinance")


class TestExportHygiene:
    def test_score_signal_exported(self):
        import cryoquant.signals as sig

        assert "ScoreSignal" in sig.__all__
        from cryoquant.signals import ScoreSignal  # noqa: F401

        assert ScoreSignal is sig.ScoreSignal


class TestCLISurface:
    def test_catalog_list(self, tmp_path, monkeypatch):
        import cryoquant.config as cfg

        monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "cat.duckdb")
        from cryoquant.cli import main

        assert main(["catalog", "list"]) == 0

    def test_models_list(self, tmp_path, monkeypatch):
        import cryoquant.config as cfg

        monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "cat.duckdb")
        from cryoquant.cli import main

        assert main(["models", "list"]) == 0

    @pytest.mark.parametrize(
        "argv",
        [
            ["backtest", "spot", "--signal", "x"],
            ["backtest", "options", "--signal", "x"],
            ["signals", "publish", "x", "--out", "/tmp/out.parquet"],
        ],
    )
    def test_legacy_subcommands_remain_stubs(self, argv, capsys):
        """backtest / signals publish kept for CLI users; return 0 with library hint."""
        from cryoquant.cli import main

        assert main(argv) == 0
        out = capsys.readouterr().out
        assert "how_to_use" in out.lower() or "cryoquant" in out.lower()

    def test_backtest_no_subcommand_returns_one(self):
        from cryoquant.cli import main

        assert main(["backtest"]) == 1


class TestDocumentation:
    def test_how_to_build_a_study_exists(self):
        path = REPO_ROOT / "docs" / "how_to_build_a_study.md"
        assert path.is_file()
        assert len(path.read_text(encoding="utf-8").strip()) > 500

    def test_framework_status_documents_phase6(self):
        text = (REPO_ROOT / "docs" / "archive" / "FRAMEWORK_STATUS.md").read_text(encoding="utf-8")
        assert "6A" in text or "Phase 6" in text
        assert "postponed" in text.lower() or "6B" in text

    def test_quant_spec_phase6_split(self):
        text = (REPO_ROOT / "docs" / "archive" / "quant_spec.md").read_text(encoding="utf-8")
        assert "Phase 6A" in text
        assert "Phase 6B" in text

    def test_quant_plan_post_v1_extensions(self):
        text = (REPO_ROOT / "docs" / "archive" / "quant_plan.md").read_text(encoding="utf-8")
        assert "7.1" in text or "Post-v1" in text


class TestDroppedSpecItems:
    def test_no_features_catalog_yaml(self):
        assert not (REPO_ROOT / "cryoquant" / "features" / "catalog.yaml").exists()

    def test_no_experiments_tree(self):
        assert not (REPO_ROOT / "cryoquant" / "experiments").exists()
