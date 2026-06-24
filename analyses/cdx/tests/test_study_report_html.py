"""Tests for self-contained study report HTML."""
from __future__ import annotations

from pathlib import Path

from src.study_report_html import build_study_report_html, write_study_report


def test_build_study_report_html_contains_key_sections() -> None:
    html = build_study_report_html()
    assert "CDX.NA.IG Multi-Overlay Portfolio" in html
    assert "Executive summary" in html
    assert "2011-09-09" in html
    assert "2026-03-15" in html
    assert "mutex" in html.lower()
    assert "Y8" in html
    assert "<svg" in html


def test_write_study_report_creates_file(tmp_path: Path) -> None:
    out = write_study_report(tmp_path / "study.html")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert len(text) > 10_000
    assert "COVID" in text
