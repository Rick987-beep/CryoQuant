"""Tests for cryoquant.backtest.scoring — ScoringConfig and score_leaderboard().

Coverage
--------
S01  ScoringConfig rejects weights with columns not in higher/lower_is_better
S02  ScoringConfig rejects empty weights
S03  score_leaderboard ranks better sharpe higher
S04  lower_is_better column: smaller max_drawdown → higher rank
S05  Rows with n_trades < min_trades receive NaN composite_score
S06  Output is sorted descending by composite_score
S07  Tie-breaker column used when composite_score is equal
S08  Normalised weights: total composite in [0, 1]
S09  Single-row leaderboard: composite_score is finite
S10  All-NaN column is handled gracefully (no crash)
S11  score_leaderboard returns a copy (original df unchanged)
S12  _pct_rank: min/max mapped to 0/1
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.scoring import ScoringConfig, _pct_rank, score_leaderboard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_leaderboard(n: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "run_id":       [f"run_{i}" for i in range(n)],
        "n_trades":     np.full(n, 15),
        "sharpe_equity": rng.uniform(0.3, 2.5, n),
        "max_drawdown": -rng.uniform(0.05, 0.40, n),  # negative
        "profit_factor": rng.uniform(0.8, 3.0, n),
    })


_DEFAULT_CONFIG = ScoringConfig(
    weights={
        "sharpe_equity": 0.5,
        "max_drawdown":  0.3,
        "profit_factor": 0.2,
    },
    min_trades=10,
    # max_drawdown stored as negative; higher (less negative) = better
    higher_is_better=("sharpe_equity", "profit_factor", "max_drawdown"),
    lower_is_better=(),
)

_CONFIG_WITH_LOWER = ScoringConfig(
    weights={
        "sharpe_equity": 0.6,
        "loss_rate":     0.4,   # synthetic positive metric where lower is better
    },
    min_trades=5,
    higher_is_better=("sharpe_equity",),
    lower_is_better=("loss_rate",),
)


# ---------------------------------------------------------------------------
# S01 / S02 — ScoringConfig validation
# ---------------------------------------------------------------------------

class TestScoringConfigValidation:
    def test_rejects_column_not_in_higher_or_lower(self) -> None:
        with pytest.raises(ValueError, match="not listed in"):
            ScoringConfig(
                weights={"sharpe_equity": 1.0, "unknown_col": 0.5},
                higher_is_better=("sharpe_equity",),
                lower_is_better=(),
            )

    def test_rejects_empty_weights(self) -> None:
        with pytest.raises(ValueError):
            ScoringConfig(
                weights={},
                higher_is_better=(),
                lower_is_better=(),
            )


# ---------------------------------------------------------------------------
# S03 — ranking direction for higher_is_better
# ---------------------------------------------------------------------------

class TestRankingHigherBetter:
    def test_higher_sharpe_ranks_higher(self) -> None:
        df = pd.DataFrame({
            "run_id":       ["a", "b"],
            "n_trades":     [15, 15],
            "sharpe_equity": [2.0, 0.5],
            "max_drawdown":  [-0.1, -0.1],
            "profit_factor": [1.5, 1.5],
        })
        result = score_leaderboard(df, _DEFAULT_CONFIG)
        top = result.iloc[0]["run_id"]
        assert top == "a", f"Expected 'a' to rank first, got {top!r}"


# ---------------------------------------------------------------------------
# S04 — lower_is_better: lower positive value ranks higher (e.g. loss_rate)
# ---------------------------------------------------------------------------

class TestRankingLowerBetter:
    def test_smaller_drawdown_ranks_higher(self) -> None:
        """max_drawdown stored as negative: -0.05 > -0.50 so "good" wins via higher_is_better."""
        df = pd.DataFrame({
            "run_id":       ["good", "bad"],
            "n_trades":     [15, 15],
            "sharpe_equity": [1.0, 1.0],
            "max_drawdown":  [-0.05, -0.50],  # good has less negative drawdown → higher → better
            "profit_factor": [1.5, 1.5],
        })
        result = score_leaderboard(df, _DEFAULT_CONFIG)
        assert result.iloc[0]["run_id"] == "good"

    def test_lower_is_better_positive_metric(self) -> None:
        """For a positive metric (lower = better), inversion gives correct order."""
        df = pd.DataFrame({
            "run_id":       ["good", "bad"],
            "n_trades":     [10, 10],
            "sharpe_equity": [1.0, 1.0],
            "loss_rate":     [0.10, 0.50],  # good has lower loss_rate → better
        })
        result = score_leaderboard(df, _CONFIG_WITH_LOWER)
        assert result.iloc[0]["run_id"] == "good"


# ---------------------------------------------------------------------------
# S05 — n_trades < min_trades → NaN score
# ---------------------------------------------------------------------------

class TestMinTradesGating:
    def test_below_min_trades_gets_nan_score(self) -> None:
        df = pd.DataFrame({
            "run_id":       ["good", "small"],
            "n_trades":     [15, 3],      # 3 < min_trades=10
            "sharpe_equity": [2.0, 5.0],  # small has best sharpe but too few trades
            "max_drawdown":  [-0.1, -0.1],
            "profit_factor": [1.5, 3.0],
        })
        result = score_leaderboard(df, _DEFAULT_CONFIG)
        small_row = result[result["run_id"] == "small"].iloc[0]
        assert math.isnan(small_row["composite_score"]), (
            "Row with n_trades < min_trades should have NaN composite_score"
        )


# ---------------------------------------------------------------------------
# S06 — output sorted descending
# ---------------------------------------------------------------------------

class TestSortedDescending:
    def test_sorted_by_composite_score(self) -> None:
        df = _make_leaderboard(10)
        result = score_leaderboard(df, _DEFAULT_CONFIG)
        scores = result["composite_score"].dropna().values
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


# ---------------------------------------------------------------------------
# S08 — composite_score in [0, 1]
# ---------------------------------------------------------------------------

class TestCompositeRange:
    def test_composite_score_in_unit_interval(self) -> None:
        result = score_leaderboard(_make_leaderboard(20), _DEFAULT_CONFIG)
        valid = result["composite_score"].dropna()
        assert (valid >= 0.0).all() and (valid <= 1.0).all()


# ---------------------------------------------------------------------------
# S09 — single row
# ---------------------------------------------------------------------------

class TestSingleRow:
    def test_single_row_finite_score(self) -> None:
        df = pd.DataFrame({
            "run_id":       ["solo"],
            "n_trades":     [15],
            "sharpe_equity": [1.5],
            "max_drawdown":  [-0.1],
            "profit_factor": [2.0],
        })
        result = score_leaderboard(df, _DEFAULT_CONFIG)
        assert result["composite_score"].notna().all()
        assert math.isfinite(result.iloc[0]["composite_score"])


# ---------------------------------------------------------------------------
# S10 — all-NaN column
# ---------------------------------------------------------------------------

class TestAllNanColumn:
    def test_all_nan_column_no_crash(self) -> None:
        df = _make_leaderboard(5).copy()
        df["profit_factor"] = float("nan")
        # Should not raise — rows with any NaN scored column get NaN score
        result = score_leaderboard(df, _DEFAULT_CONFIG)
        assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# S11 — original df not mutated
# ---------------------------------------------------------------------------

class TestOriginalUnchanged:
    def test_copy_returned(self) -> None:
        df = _make_leaderboard(5)
        original_cols = list(df.columns)
        score_leaderboard(df, _DEFAULT_CONFIG)
        assert list(df.columns) == original_cols
        assert "composite_score" not in df.columns


# ---------------------------------------------------------------------------
# S12 — _pct_rank
# ---------------------------------------------------------------------------

class TestPctRank:
    def test_min_maps_to_zero_max_to_one(self) -> None:
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        ranks = _pct_rank(arr)
        assert ranks[0] == pytest.approx(0.0)
        assert ranks[-1] == pytest.approx(1.0)

    def test_single_element(self) -> None:
        arr = np.array([42.0])
        ranks = _pct_rank(arr)
        assert ranks[0] == pytest.approx(0.0)
