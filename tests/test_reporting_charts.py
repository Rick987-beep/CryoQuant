"""Tests for cryoquant.reporting.charts."""
from __future__ import annotations

import pandas as pd

from cryoquant.reporting.charts import svg_bars, svg_line_chart


def test_svg_line_chart_nonempty() -> None:
    series = pd.Series([1.0, 1.1, 1.05, 1.2], index=pd.date_range("2020-01-01", periods=4))
    html = svg_line_chart(series, y_label="NAV")
    assert "<svg" in html
    assert "NAV" in html


def test_svg_line_chart_empty() -> None:
    assert "No series data" in svg_line_chart(pd.Series(dtype=float))


def test_svg_bars() -> None:
    html = svg_bars(["A", "B"], [1.2, 0.9])
    assert "<svg" in html
    assert "A" in html
