"""Cross-validation utilities for time-series data.

purged_kfold   — embargo-aware K-fold (López de Prado purged CV).
walk_forward   — fixed-window walk-forward split.

Both yield (train_idx, test_idx) as integer-position arrays so they work with
iloc-based DataFrame slicing.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np


def purged_kfold(
    n: int,
    n_splits: int = 5,
    embargo_bars: int = 0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Time-series K-fold with purging and embargo.

    Splits the index [0, n) into ``n_splits`` contiguous test folds.  For each
    fold the training set excludes the test range **plus** ``embargo_bars`` rows
    immediately following it (to prevent label leakage when forward-return
    labels overlap the test period).

    Args:
        n:             Total number of samples.
        n_splits:      Number of folds.
        embargo_bars:  Bars to exclude from training after each test fold.

    Yields:
        (train_idx, test_idx) integer-position arrays.
    """
    if n_splits < 2:
        raise ValueError(f"n_splits must be >= 2, got {n_splits}")
    indices = np.arange(n)
    fold_size = n // n_splits

    for k in range(n_splits):
        test_start = k * fold_size
        test_end = test_start + fold_size if k < n_splits - 1 else n
        test_idx = indices[test_start:test_end]

        embargo_end = min(test_end + embargo_bars, n)
        train_idx = np.concatenate([
            indices[:test_start],
            indices[embargo_end:],
        ])
        if len(train_idx) == 0 or len(test_idx) == 0:
            continue
        yield train_idx, test_idx


def walk_forward(
    n: int,
    train_window: int,
    test_window: int,
    step: int | None = None,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Fixed-window walk-forward cross-validation.

    Each iteration advances by ``step`` bars (default = ``test_window``).

    Args:
        n:             Total number of samples.
        train_window:  Bars in each training window.
        test_window:   Bars in each test window.
        step:          How many bars to advance each iteration.
                       Defaults to test_window (non-overlapping test folds).

    Yields:
        (train_idx, test_idx) integer-position arrays.
    """
    if train_window < 1 or test_window < 1:
        raise ValueError("train_window and test_window must be >= 1")
    if step is None:
        step = test_window

    indices = np.arange(n)
    start = 0
    while True:
        train_end = start + train_window
        test_end = train_end + test_window
        if test_end > n:
            break
        yield indices[start:train_end], indices[train_end:test_end]
        start += step
