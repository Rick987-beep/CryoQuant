"""Coverage gate — verify a candidate catches the trend episodes in trend_tests.yaml.

Public API
----------
load_trend_tests(path)
    Parse trend_tests.yaml → list[TrendTest].

check_test(state_series, test, tf_minutes)
    Score one TrendTest against a state Series → CoverageResult.

run_coverage_gate(state_series, tests, tf_minutes,
                  min_coverage_pct, max_lag_pct)
    Score all tests → CoverageReport.

DEFAULT_TESTS_PATH
    Workspace-relative path to trend_tests.yaml (used when path is not supplied).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd
import yaml

from .schemas import CoverageReport, CoverageResult, TrendTest

# Path relative to this file's package root (pineforge/pineforge/../trend_tests.yaml)
DEFAULT_TESTS_PATH = Path(__file__).resolve().parents[1] / "trend_tests.yaml"

# Gate defaults — tunable per-test in the YAML via min_coverage_pct / max_lag_pct
DEFAULT_MIN_COVERAGE_PCT: float = 60.0   # ≥60% of window bars must agree
DEFAULT_MAX_LAG_PCT: float = 33.0        # first agreement ≤ 33% into the window


def load_trend_tests(path: Path | str | None = None) -> list[TrendTest]:
    """Load trend_tests.yaml and return a list of TrendTest objects."""
    p = Path(path) if path else DEFAULT_TESTS_PATH
    raw = yaml.safe_load(p.read_text())
    return [TrendTest(**t) for t in raw["trend_tests"]]


def check_test(
    state: pd.Series,
    test: TrendTest,
    tf_minutes: int,
    *,
    min_coverage_pct: float = DEFAULT_MIN_COVERAGE_PCT,
    max_lag_pct: float = DEFAULT_MAX_LAG_PCT,
) -> CoverageResult:
    """Score a single TrendTest against a state Series.

    Parameters
    ----------
    state:
        Integer Series of {-1, 0, +1} with a tz-aware UTC DatetimeIndex,
        as produced by Candidate.classify()["state"].
    test:
        The trend test to evaluate.
    tf_minutes:
        Bar duration in minutes (e.g. 60 for 1h, 15 for 15m). Used to
        compute lag_pct and for human-readable lag display.
    min_coverage_pct, max_lag_pct:
        Default gate thresholds; overridden by per-test values in the YAML.
    """
    expected_dir = 1 if test.direction == "up" else -1

    # Per-test threshold overrides
    cov_thresh = test.min_coverage_pct if test.min_coverage_pct is not None else min_coverage_pct
    lag_thresh = test.max_lag_pct if test.max_lag_pct is not None else max_lag_pct

    entry_ts = pd.Timestamp(test.entry_bar).tz_localize("UTC") if pd.Timestamp(test.entry_bar).tzinfo is None else pd.Timestamp(test.entry_bar)
    exit_ts  = pd.Timestamp(test.exit_bar).tz_localize("UTC")  if pd.Timestamp(test.exit_bar).tzinfo is None  else pd.Timestamp(test.exit_bar)

    window = state.loc[entry_ts:exit_ts]
    n_bars = len(window)

    if n_bars == 0:
        return CoverageResult(
            test_id=test.id,
            direction=test.direction,
            expected_dir=expected_dir,
            n_bars=0,
            correct_bars=0,
            coverage_pct=0.0,
            lag_bars=None,
            lag_pct=None,
            min_coverage_pct=cov_thresh,
            max_lag_pct=lag_thresh,
            passed=False,
        )

    correct_bars = int((window == expected_dir).sum())
    coverage_pct = correct_bars / n_bars * 100.0

    # First bar where signal agrees
    agrees = window[window == expected_dir]
    if len(agrees):
        first_agree_ts = agrees.index[0]
        lag_bars = int((first_agree_ts - entry_ts) / pd.Timedelta(minutes=tf_minutes))
        lag_pct = lag_bars / n_bars * 100.0
    else:
        lag_bars = None
        lag_pct = None

    # Gate logic
    coverage_ok = coverage_pct >= cov_thresh
    lag_ok = (lag_pct is not None) and (lag_pct <= lag_thresh)
    passed = coverage_ok and lag_ok

    return CoverageResult(
        test_id=test.id,
        direction=test.direction,
        expected_dir=expected_dir,
        n_bars=n_bars,
        correct_bars=correct_bars,
        coverage_pct=round(coverage_pct, 1),
        lag_bars=lag_bars,
        lag_pct=round(lag_pct, 1) if lag_pct is not None else None,
        min_coverage_pct=cov_thresh,
        max_lag_pct=lag_thresh,
        passed=passed,
    )


def run_coverage_gate(
    state: pd.Series,
    tests: Sequence[TrendTest],
    tf_minutes: int,
    *,
    min_coverage_pct: float = DEFAULT_MIN_COVERAGE_PCT,
    max_lag_pct: float = DEFAULT_MAX_LAG_PCT,
) -> CoverageReport:
    """Run all trend tests and return a CoverageReport.

    A candidate passes the gate only if every individual test passes.
    """
    results = [
        check_test(state, t, tf_minutes,
                   min_coverage_pct=min_coverage_pct,
                   max_lag_pct=max_lag_pct)
        for t in tests
    ]
    n_passed = sum(r.passed for r in results)
    n_total = len(results)
    passed = n_passed == n_total

    failed_ids = [r.test_id for r in results if not r.passed]
    if passed:
        summary = f"PASS — all {n_total} trend tests covered"
    else:
        summary = f"FAIL — {n_total - n_passed}/{n_total} tests failed: {', '.join(failed_ids)}"

    return CoverageReport(
        tests=results,
        n_passed=n_passed,
        n_total=n_total,
        passed=passed,
        summary=summary,
    )


def tf_minutes_from_str(tf: str) -> int:
    """Convert a timeframe string like '1h', '15m', '4h' to minutes."""
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 1440
    raise ValueError(f"unsupported timeframe string {tf!r}")


def print_coverage_report(report: CoverageReport, tf_minutes: int) -> None:
    """Print a human-readable summary of a CoverageReport to stdout."""
    status = "✓ PASS" if report.passed else "✗ FAIL"
    print(f"\nCoverage gate: {status}  ({report.n_passed}/{report.n_total} tests passed)")
    print(f"  {report.summary}")
    header = f"  {'test_id':<30} {'dir':>5} {'bars':>5} {'cov%':>6} {'lag_bars':>9} {'lag%':>6} {'result':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in report.tests:
        result_str = "PASS" if r.passed else "FAIL"
        lag_b = str(r.lag_bars) if r.lag_bars is not None else "—"
        lag_p = f"{r.lag_pct:.0f}%" if r.lag_pct is not None else "—"
        print(
            f"  {r.test_id:<30} {'↓' if r.direction == 'down' else '↑':>5} "
            f"{r.n_bars:>5} {r.coverage_pct:>5.1f}% {lag_b:>9} {lag_p:>6}  {result_str:>6}"
        )
    print()
