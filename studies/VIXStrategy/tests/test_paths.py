"""Smoke tests for VIXStrategy scaffolding."""

from __future__ import annotations

from datetime import datetime, timezone

from src.paths import ANALYSIS_ROOT, config_path, load_config, reports_dir
from src.vix_data import parse_window, qa_report
import pandas as pd


def test_analysis_root_layout() -> None:
    assert (ANALYSIS_ROOT / "config.yaml").is_file()
    assert (ANALYSIS_ROOT / "universe.yaml").is_file()
    assert (ANALYSIS_ROOT / "PLAN.md").is_file()
    assert (ANALYSIS_ROOT / "run_phase0_data.py").is_file()


def test_load_config() -> None:
    cfg = load_config()
    assert cfg["study_id"] == "vix_strategy"
    assert cfg["primary"]["symbol"] == "cboe:VIX"


def test_parse_window_trailing_10y() -> None:
    from datetime import timedelta

    start, end = parse_window()
    assert end.tzinfo == timezone.utc
    assert start.tzinfo == timezone.utc
    assert end > start
    # Exact trailing 10 calendar years ending yesterday UTC
    assert start.year == end.year - 10
    assert (start.month, start.day) == (end.month, end.day)
    today = datetime.now(timezone.utc).date()
    assert end.date() == today - timedelta(days=1)


def test_paths_create_reports_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.paths.ANALYSIS_ROOT", tmp_path)
    load_config.cache_clear()
    out = reports_dir()
    assert out == tmp_path / "reports"
    assert out.is_dir()
    assert config_path() == tmp_path / "config.yaml"


def test_qa_report_empty() -> None:
    assert qa_report(pd.DataFrame(columns=["open", "high", "low", "close"]))["empty"] is True


def test_qa_report_clean_bar() -> None:
    idx = pd.DatetimeIndex(["2020-03-16"], tz="UTC", name="timestamp")
    df = pd.DataFrame(
        {"open": [57.83], "high": [83.56], "low": [57.83], "close": [82.69]},
        index=idx,
    )
    qa = qa_report(df)
    assert qa["n"] == 1
    assert qa["high_lt_low"] == 0
    assert qa["open_close_outside_range"] == 0
