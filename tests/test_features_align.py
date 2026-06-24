"""Tests for cryoquant.features.align."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryoquant.features.align import (
    align_frame_column,
    align_many,
    align_series,
    join_features,
)


def _idx(n: int = 5, start: str = "2024-01-01", freq: str = "1D") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=freq, tz="UTC")


class TestAlignSeriesAsof:
    def test_asof_aligns_backward(self) -> None:
        target = _idx(5)
        src = pd.Series(
            [10.0, 20.0, 30.0],
            index=pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-05"], utc=True),
            name="vix",
        )
        out = align_series(target, src, method="asof")
        assert out.iloc[0] == 10.0
        assert out.iloc[1] == 10.0
        assert out.iloc[2] == 20.0
        assert out.iloc[4] == 30.0

    def test_empty_series_returns_nan(self) -> None:
        target = _idx(3)
        out = align_series(target, pd.Series(dtype=float))
        assert out.isna().all()

    def test_ffill_limit_staleness(self) -> None:
        target = _idx(3, start="2024-06-01")
        src = pd.Series(
            [1.0],
            index=pd.to_datetime(["2024-01-01"], utc=True),
        )
        out = align_series(target, src, method="asof", ffill_limit=35)
        assert pd.isna(out.iloc[-1])

    def test_ffill_limit_none_keeps_stale(self) -> None:
        target = _idx(3, start="2024-06-01")
        src = pd.Series([1.0], index=pd.to_datetime(["2024-01-01"], utc=True))
        out = align_series(target, src, method="asof", ffill_limit=None)
        assert out.iloc[-1] == 1.0

    def test_tz_naive_source_normalized(self) -> None:
        target = _idx(2)
        src = pd.Series(
            [5.0, 6.0],
            index=pd.date_range("2024-01-01", periods=2, freq="1D"),
        )
        out = align_series(target, src, method="asof")
        assert out.iloc[0] == 5.0


class TestAlignSeriesFfill:
    def test_ffill_method(self) -> None:
        target = _idx(4)
        src = pd.Series(
            [1.0, 2.0],
            index=pd.to_datetime(["2024-01-01", "2024-01-03"], utc=True),
        )
        out = align_series(target, src, method="ffill")
        assert out.iloc[1] == 1.0
        assert out.iloc[2] == 2.0


class TestAlignHelpers:
    def test_align_frame_column(self) -> None:
        target = _idx(3)
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=target)
        out = align_frame_column(target, df)
        assert list(out) == [1.0, 2.0, 3.0]

    def test_align_many(self) -> None:
        target = _idx(3)
        a = pd.Series([1.0, 2.0, 3.0], index=target, name="a")
        b = pd.Series([4.0, 5.0, 6.0], index=target, name="b")
        df = align_many(target, {"x": a, "y": b}, prefix="m_")
        assert "m_x" in df.columns and "m_y" in df.columns

    def test_join_features_rejects_duplicate_cols(self) -> None:
        idx = _idx(3)
        left = pd.DataFrame({"a": [1, 2, 3]}, index=idx)
        right = pd.DataFrame({"a": [4, 5, 6]}, index=idx)
        with pytest.raises(ValueError, match="duplicate"):
            join_features(left, right)

    def test_join_features_inner(self) -> None:
        idx = _idx(3)
        left = pd.DataFrame({"a": [1, 2, 3]}, index=idx)
        right = pd.DataFrame({"b": [4, 5, 6]}, index=idx)
        out = join_features(left, right)
        assert list(out.columns) == ["a", "b"]
