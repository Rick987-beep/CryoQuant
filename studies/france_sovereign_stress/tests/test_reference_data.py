"""Tests for v5 reference loaders and QA (no network)."""

from __future__ import annotations

from src.data.qa import qa_report
from src.data.reference import (
    load_eurex_settles,
    load_eurex_snapshot,
    load_fred_monthly,
    load_stocks_daily,
    load_yields_daily,
)
from src.paths import load_config


def test_yields_daily_shape_and_last_spread() -> None:
    df = load_yields_daily()
    assert {"oat10", "bund10", "spread_bp"} <= set(df.columns)
    assert len(df) > 100
    # v5 daily file ends 2026-10-08 with spread ≈ 139.3 bp
    assert str(df.index[-1].date()) == "2026-10-08"
    assert abs(float(df["spread_bp"].iloc[-1]) - 139.34) < 0.05


def test_eurex_settles_window() -> None:
    df = load_eurex_settles()
    assert len(df) == 20
    assert str(df.index[0].date()) == "2026-09-11"
    assert str(df.index[-1].date()) == "2026-10-08"
    assert abs(float(df["FOAT_front"].iloc[-1]) - 108.66) < 0.01
    assert abs(float(df["FGBL_front"].iloc[-1]) - 120.67) < 0.01


def test_snapshot_yields_match_handover() -> None:
    snap = load_eurex_snapshot()
    y = snap["yields"]
    assert abs(float(y["oat10"]) - 4.8493) < 1e-4
    assert abs(float(y["bund10"]) - 3.4693) < 1e-4
    spread = (float(y["oat10"]) - float(y["bund10"])) * 100
    assert abs(spread - 138.0) < 0.05


def test_qa_report_ok() -> None:
    qa = qa_report(
        load_yields_daily(),
        load_eurex_settles(),
        load_stocks_daily(),
        load_fred_monthly(),
    )
    assert qa["ok"] is True
    assert qa["spot_checks"]["settles_last_date"] == "2026-10-08"


def test_config_stamp() -> None:
    assert load_config()["reference"]["stamp"] == "2026-10-09T1456"
