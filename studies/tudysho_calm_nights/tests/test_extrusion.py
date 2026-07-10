"""Tests for extrusion metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

STUDY_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(STUDY_SRC))

from extrusion import (  # noqa: E402
    normalize_extrusion,
    path_extrusion,
    quiet_tertile_flags,
    range_extrusion,
    slice_bars,
)


def _bars(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(prices), freq="15min", tz="UTC")
    return pd.DataFrame(
        {"open": prices, "high": [p * 1.01 for p in prices], "low": [p * 0.99 for p in prices], "close": prices},
        index=idx,
    )


def test_range_extrusion_flat():
    bars = _bars([100.0] * 5)
    r = range_extrusion(bars)
    assert abs(r - 0.02) < 1e-6


def test_path_extrusion_zero_drift():
    bars = _bars([100.0] * 5)
    assert path_extrusion(bars) == 0.0


def test_slice_bars_half_open():
    bars = _bars([100.0 + i for i in range(10)])
    start = bars.index[2]
    end = bars.index[5]
    sub = slice_bars(bars, start, end)
    assert len(sub) == 3


def test_quiet_tertile_flags():
    s = pd.Series(np.linspace(0.5, 2.0, 80))
    norm = normalize_extrusion(s, rolling=20)
    flags = quiet_tertile_flags(norm, q=0.33)
    assert flags.sum() > 0
    assert flags.sum() < len(flags)
