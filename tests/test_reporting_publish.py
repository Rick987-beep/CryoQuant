"""Tests for cryoquant.reporting.publish."""
from __future__ import annotations

import json
from pathlib import Path

from cryoquant.reporting.publish import publish_study


def test_publish_study_no_config_returns_empty(tmp_path: Path) -> None:
    assert publish_study(tmp_path) == {}


def test_publish_study_writes_manifest_and_index(tmp_path: Path) -> None:
    manifest = {
        "study": "demo",
        "created_at": "2026-01-01T00:00:00Z",
        "sample": {"label": "2020", "n_bars": 10},
        "highlights": {},
        "bundles": {},
        "reports": {"index": "index.html"},
    }
    written = publish_study(
        tmp_path,
        config={"reporting": {"index": True}},
        manifest=manifest,
        sections=[{"name": "S", "description": "d", "href": None, "status": "ok"}],
    )
    assert "manifest" in written
    assert "index" in written
    assert json.loads((tmp_path / "reports" / "manifest.json").read_text())["study"] == "demo"
    assert (tmp_path / "reports" / "index.html").exists()


def test_publish_study_from_yaml_config(tmp_path: Path) -> None:
    bundle = tmp_path / "bundles" / "main"
    bundle.mkdir(parents=True)
    (bundle / "meta.json").write_text('{"study": "x", "n_runs": 1}', encoding="utf-8")
    (bundle / "report.html").write_text("<html></html>", encoding="utf-8")

    (tmp_path / "config.yaml").write_text(
        """
reporting:
  study: yaml_study
  index: true
  sample:
    start: "2020-01-01"
    end: "2021-01-01"
    n_bars: 100
    label: "2020"
  bundles:
    main: bundles/main
""".strip(),
        encoding="utf-8",
    )
    written = publish_study(tmp_path)
    assert "manifest" in written
    manifest = json.loads((tmp_path / "reports" / "manifest.json").read_text())
    assert manifest["study"] == "yaml_study"
    assert manifest["bundles"]["main"]["status"] == "ok"
