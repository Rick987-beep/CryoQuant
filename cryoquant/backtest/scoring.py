"""Percentile-composite scoring for backtest leaderboards.

Analysis-specific weights live in the analysis package (e.g.
``analyses/quickwintrend/scoring_config.py``).  This module only provides
the generic engine.

Public interface::

    ScoringConfig     — frozen dataclass: weights, gates, column names
    score_leaderboard(df, config) -> pd.DataFrame
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoringConfig:
    """Configuration for percentile-composite scoring.

    Parameters
    ----------
    weights:
        Mapping of leaderboard column name to weight.  Weights are
        normalised internally, so they only need to represent relative
        importance.
    min_trades:
        Rows with ``n_trades < min_trades`` are excluded from ranking
        (assigned score 0) but **not** dropped from the returned DataFrame.
    higher_is_better:
        Tuple of column names where a higher value is better (e.g.
        ``"sharpe_equity"``, ``"profit_factor"``).
    lower_is_better:
        Tuple of column names where a lower value is better (e.g.
        ``"max_drawdown"`` which is typically negative).
    rank_column:
        Name of the output composite score column.
    tie_breaker:
        Column used to break ties in sorting.  Must appear in ``weights``.
    """

    weights: dict[str, float]
    min_trades: int = 10
    higher_is_better: tuple[str, ...] = ()
    lower_is_better: tuple[str, ...] = ()
    rank_column: str = "composite_score"
    tie_breaker: str = "sharpe_equity"

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("ScoringConfig.weights must not be empty")
        all_columns = set(self.higher_is_better) | set(self.lower_is_better)
        missing = set(self.weights) - all_columns
        if missing:
            raise ValueError(
                f"ScoringConfig: columns in weights not listed in "
                f"higher_is_better or lower_is_better: {missing}"
            )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def score_leaderboard(df: pd.DataFrame, config: ScoringConfig) -> pd.DataFrame:
    """Score and rank a leaderboard DataFrame using percentile composition.

    Algorithm
    ---------
    1. For each column in ``config.weights``, compute the percentile rank
       across *eligible* rows (``n_trades >= config.min_trades`` and column
       is finite).
    2. Invert the percentile for ``lower_is_better`` columns so that
       *better* always maps to a higher rank.
    3. Multiply each ranked column by its normalised weight and sum to
       produce ``config.rank_column``.
    4. Ineligible rows receive a score of ``NaN`` and sort to the bottom.

    Parameters
    ----------
    df:
        Leaderboard DataFrame; must contain ``n_trades`` and all columns
        referenced in ``config.weights``.
    config:
        Scoring parameters.

    Returns
    -------
    A copy of ``df`` with ``config.rank_column`` appended, sorted
    descending by score then by ``config.tie_breaker``.
    """
    result = df.copy()
    result[config.rank_column] = float("nan")

    if "n_trades" not in result.columns:
        result["n_trades"] = 0

    eligible_mask = result["n_trades"] >= config.min_trades

    # Normalise weights
    total_weight = sum(config.weights.values())
    if total_weight <= 0:
        raise ValueError("ScoringConfig: total weight must be positive")
    norm_weights = {col: w / total_weight for col, w in config.weights.items()}

    # Percentile ranks for eligible rows
    composite = np.zeros(len(result), dtype=float)
    composite[:] = float("nan")

    eligible_idx = result.index[eligible_mask]
    if len(eligible_idx) == 0:
        result[config.rank_column] = float("nan")
        return result

    # Only score rows where all weighted columns are finite
    valid_mask = eligible_mask.copy()
    for col in config.weights:
        if col not in result.columns:
            valid_mask &= False
            break
        valid_mask &= result[col].notna() & np.isfinite(result[col])

    valid_idx = result.index[valid_mask]
    if len(valid_idx) == 0:
        result[config.rank_column] = float("nan")
        return result

    composite_scores = np.zeros(len(valid_idx), dtype=float)

    for col, weight in norm_weights.items():
        vals = result.loc[valid_idx, col].to_numpy(dtype=float)
        # Percentile rank within the valid set (0..1)
        ranks = _pct_rank(vals)
        # Invert for lower_is_better
        if col in config.lower_is_better:
            ranks = 1.0 - ranks
        composite_scores += ranks * weight

    result.loc[valid_idx, config.rank_column] = composite_scores

    # Sort: valid rows by composite score desc, then tie_breaker desc
    sort_cols = [config.rank_column]
    if config.tie_breaker in result.columns and config.tie_breaker != config.rank_column:
        sort_cols.append(config.tie_breaker)

    result = result.sort_values(sort_cols, ascending=False, na_position="last")
    result = result.reset_index(drop=True)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct_rank(arr: np.ndarray) -> np.ndarray:
    """Return percentile ranks in [0, 1] using the average-rank method.

    Tied values receive the same rank (average of their ordinal positions).
    The minimum value maps to 0.0 and the maximum to 1.0 when there are no ties.
    Single-element arrays map to 0.0.
    """
    n = len(arr)
    if n == 0:
        return arr.copy()
    if n == 1:
        return np.array([0.0])

    order = np.argsort(arr, kind="stable")
    ranks = np.empty(n, dtype=float)

    i = 0
    while i < n:
        j = i + 1
        while j < n and arr[order[j]] == arr[order[i]]:
            j += 1
        # all positions i..j-1 are tied; assign average of their ordinal ranks
        avg_ordinal = (i + j - 1) / 2.0
        normalised  = avg_ordinal / max(n - 1, 1)
        for k in range(i, j):
            ranks[order[k]] = normalised
        i = j

    return ranks
