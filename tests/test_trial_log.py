"""Tests for cryoquant.backtest.trial_log."""
from __future__ import annotations

from pathlib import Path

from cryoquant.backtest.trial_log import append_trial, count_trials, trial_log_path


def test_append_and_count(tmp_path: Path) -> None:
    path = trial_log_path(tmp_path)
    assert count_trials(path) == 0
    tid = append_trial(path, {"phase": "test", "run_id": "r1"})
    assert tid == 1
    assert count_trials(path) == 1
    tid2 = append_trial(path, {"phase": "test", "run_id": "r2"})
    assert tid2 == 2
