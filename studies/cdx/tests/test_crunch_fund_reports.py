"""Tests for Crunch Fund HTML reports."""
from __future__ import annotations

from pathlib import Path

from src.crunch_fund_pitch_html import build_crunch_fund_pitch_html, write_crunch_fund_pitch
from src.crunch_fund_report_html import build_crunch_fund_report_html, write_crunch_fund_report


def test_build_crunch_fund_report_html_contains_key_sections() -> None:
    html = build_crunch_fund_report_html()
    assert "Executive summary" in html
    assert "Pyramid" in html
    assert "crisis_nav_peak" not in html  # user-facing, not raw column names
    assert "10×" in html


def test_build_crunch_fund_pitch_html_contains_key_sections() -> None:
    html = build_crunch_fund_pitch_html()
    assert "The Credit Crunch Fund" in html
    assert "Ackman" in html
    assert "Pershing Square" in html
    assert "per month" in html.lower() or "per quarter" in html.lower()
    assert "pyramid" in html.lower()
    assert "crunch_fund_study_report" not in html
    assert 'href="' not in html


def test_write_crunch_fund_reports(tmp_path: Path) -> None:
    study = write_crunch_fund_report(tmp_path / "study.html")
    pitch = write_crunch_fund_pitch(tmp_path / "pitch.html")
    assert study.exists() and study.stat().st_size > 5000
    assert pitch.exists() and pitch.stat().st_size > 8000
