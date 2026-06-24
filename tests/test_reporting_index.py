"""Tests for cryoquant.reporting.index_html."""
from __future__ import annotations

from pathlib import Path

from cryoquant.reporting.index_html import render_index_from_manifest, render_index_html


def test_render_index_html_sections(tmp_path: Path) -> None:
    out = render_index_html(
        tmp_path / "index.html",
        title="Demo Study",
        generated_at="2026-01-01T00:00:00Z",
        sample_label="2020 → 2021",
        n_bars=252,
        highlights=[{"label": "Sharpe", "value": "1.20"}],
        sections=[
            {
                "name": "Main sweep",
                "description": "Parameter grid",
                "href": "bundles/main/report.html",
                "status": "ok",
            }
        ],
    )
    html = out.read_text(encoding="utf-8")
    assert "Demo Study" in html
    assert "Sharpe" in html
    assert "Main sweep" in html
    assert "bundles/main/report.html" in html


def test_render_index_from_manifest(tmp_path: Path) -> None:
    manifest = {
        "study": "ema_cross",
        "created_at": "2026-01-01T00:00:00Z",
        "sample": {"label": "2020", "n_bars": 100},
    }
    out = render_index_from_manifest(
        tmp_path / "index.html",
        manifest,
        sections=[{"name": "Run", "description": "d", "href": None, "status": "missing"}],
    )
    assert "ema_cross" in out.read_text(encoding="utf-8")
