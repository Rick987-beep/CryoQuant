"""Tests for cryoquant.reporting.manifest."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from cryoquant.reporting.manifest import (
    build_manifest,
    bundle_status,
    relative_report_href,
    write_manifest,
)


def _fake_bundle(path: Path, meta: dict, lb_rows: list[dict] | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if lb_rows:
        pd.DataFrame(lb_rows).to_parquet(path / "leaderboard.parquet", index=False)
    (path / "report.html").write_text("<html></html>", encoding="utf-8")


def test_bundle_status_missing(tmp_path: Path) -> None:
    assert bundle_status(tmp_path / "nope")["status"] == "missing"


def test_bundle_status_ok(tmp_path: Path) -> None:
    bundle = tmp_path / "sweep"
    _fake_bundle(bundle, {"study": "test", "n_runs": 2}, [{"run_id": "a", "nav_end": 1.5}])
    reports_root = tmp_path / "reports"
    status = bundle_status(bundle, reports_root=reports_root)
    assert status["status"] == "ok"
    assert status["top_run_id"] == "a"
    assert status["report_html"].endswith("sweep/report.html")


def test_relative_report_href_fallback(tmp_path: Path) -> None:
    bundle = tmp_path / "outside" / "bundle"
    bundle.mkdir(parents=True)
    href = relative_report_href(bundle, tmp_path / "reports")
    assert href == "bundle/report.html"


def test_build_and_write_manifest(tmp_path: Path) -> None:
    manifest = build_manifest(
        study="demo",
        sample={"start": "2020-01-01", "end": "2021-01-01", "n_bars": 252, "label": "2020"},
        highlights={"sharpe": 1.2},
        bundles={"main": {"status": "ok"}},
    )
    assert manifest["study"] == "demo"
    assert manifest["bundle_version"] == "1"
    assert "created_at" in manifest

    out = write_manifest(tmp_path / "manifest.json", manifest)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["highlights"]["sharpe"] == 1.2
