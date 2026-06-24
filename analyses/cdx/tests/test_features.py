"""Tests for feature engineering."""
from __future__ import annotations

import pandas as pd

from src.features import velocity_regime


def test_velocity_regime_uses_1d_sigma() -> None:
    idx = pd.date_range("2015-01-01", periods=500, freq="B", tz="UTC")
    chg1 = pd.Series(0.1, index=idx)
    chg1.iloc[400:420] = 8.0
    regime = velocity_regime(chg1)
    assert (regime == "moderate").any() or (regime == "low").any()
    assert (regime == "high").any()
