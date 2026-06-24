"""Tests for optional reporting adapters."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


def test_export_notebook_import_error_without_nbconvert(tmp_path: Path) -> None:
    if importlib.util.find_spec("nbconvert") is not None:
        pytest.skip("nbconvert installed")

    from cryoquant.reporting.notebook_export import export_notebook

    nb = tmp_path / "x.ipynb"
    nb.write_text('{"cells":[],"metadata":{},"nbformat":4,"nbformat_minor":5}', encoding="utf-8")

    with pytest.raises(ImportError, match=r"cryoquant\[reports\]"):
        export_notebook(nb, tmp_path / "out.html")


def test_render_tearsheet_import_error_without_quantstats(tmp_path: Path) -> None:
    if importlib.util.find_spec("quantstats") is not None:
        pytest.skip("quantstats installed")

    from cryoquant.reporting.tearsheet import render_tearsheet

    returns = pd.Series([0.01, -0.005], index=pd.date_range("2020-01-01", periods=2))

    with pytest.raises(ImportError, match=r"cryoquant\[reports\]"):
        render_tearsheet(returns, tmp_path / "tearsheet.html")
