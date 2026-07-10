"""Tests for contingency lift logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

STUDY_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(STUDY_SRC))

from contingency import contingency_lift, spearman_matrix  # noqa: E402


def _synthetic_daily(n: int = 120, correlation: float = 0.8) -> pd.DataFrame:
    """Morning quiet strongly predicts hold quiet when correlation high."""
    rows = []
    for i in range(n):
        morning_quiet = i % 3 == 0
        if correlation > 0.5:
            hold_quiet = morning_quiet if i % 10 != 7 else False
        else:
            hold_quiet = i % 2 == 0
        rows.append(
            {
                "entry_date": f"2025-01-{1 + i % 28:02d}",
                "us_morning_range": 0.01 if morning_quiet else 0.05,
                "us_afternoon_range": 0.012 if morning_quiet else 0.04,
                "hold_night_range": 0.015 if hold_quiet else 0.06,
                "us_morning_quiet": morning_quiet,
                "hold_night_quiet": hold_quiet,
            }
        )
    return pd.DataFrame(rows)


def test_contingency_lift_passes_on_correlated_data():
    daily = _synthetic_daily(120, correlation=0.9)
    daily["predictor_quiet"] = daily["us_morning_quiet"]
    r = contingency_lift(daily, "hold_night_quiet", min_sample_days=100)
    assert r.lift > 1.5
    assert r.passed


def test_contingency_lift_fails_on_independent_data():
    daily = _synthetic_daily(120, correlation=0.0)
    daily["predictor_quiet"] = daily["us_morning_quiet"]
    r = contingency_lift(daily, "hold_night_quiet", min_sample_days=100)
    assert not r.passed


def test_spearman_matrix_keys():
    daily = _synthetic_daily(50)
    daily["predictor_range"] = daily["us_morning_range"]
    daily["hold_from_1200_range"] = daily["hold_night_range"]
    daily["hold_from_1400_range"] = daily["hold_night_range"]
    daily["us_afternoon_range"] = daily["hold_night_range"]
    m = spearman_matrix(daily)
    assert "predictor_range__hold_night_range" in m
