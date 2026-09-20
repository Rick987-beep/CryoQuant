"""Tests for StudyPaths and html_brand helpers."""
from __future__ import annotations

from pathlib import Path

import yaml

from cryoquant.study_paths import StudyPaths


def test_study_paths_layout(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("study_id: demo\n", encoding="utf-8")
    sp = StudyPaths(tmp_path)
    assert sp.config_path() == tmp_path / "config.yaml"
    assert sp.data_dir() == tmp_path / "data"
    assert sp.reports_dir().is_dir()
    assert sp.bundles_dir().is_dir()
    assert sp.bundles_dir(under_reports=True) == tmp_path / "reports" / "bundles"
    assert sp.load_config()["study_id"] == "demo"


def test_study_paths_variant_dirs(tmp_path: Path) -> None:
    sp = StudyPaths(tmp_path)
    assert sp.variant_data_dir("london_us") == tmp_path / "data" / "london_us"
    assert sp.variant_reports_dir("london_us").is_dir()


def test_html_brand_escape() -> None:
    from cryoquant.reporting.html_brand import escape_html, html_document

    assert escape_html("<x>") == "&lt;x&gt;"
    doc = html_document(title="T", body="<p>hi</p>", brand="cryo-dark")
    assert "<title>T</title>" in doc
    assert "<p>hi</p>" in doc
