"""Load frozen v5 reference inputs from ``input/v5_reference/``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.paths import load_config, v5_reference_dir


def _data_dir() -> Path:
    return v5_reference_dir() / "data"


def load_yields_daily() -> pd.DataFrame:
    """CNBC FR10Y / DE10Y daily closes and spread (bp)."""
    path = _data_dir() / "yields_daily.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df.sort_index()


def load_yields_weekly() -> pd.DataFrame:
    path = _data_dir() / "yields_weekly.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df.sort_index()


def load_eurex_settles() -> pd.DataFrame:
    """FOAT / FGBL front and next settlements (v5 calibration window)."""
    path = _data_dir() / "eurex_settles.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    return df


def load_stocks_daily() -> pd.DataFrame:
    path = _data_dir() / "stocks_daily.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df


def load_stocks_weekly() -> pd.DataFrame:
    path = _data_dir() / "stocks_weekly.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df


def load_fred_monthly() -> pd.DataFrame:
    path = _data_dir() / "fred_10y_monthly.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    df.index = idx.normalize()
    df.index.name = "date"
    return df.sort_index()


def load_eurex_snapshot(stamp: str | None = None) -> dict[str, Any]:
    """Live Eurex chains + CNBC quote snapshot from the v5 stamp."""
    cfg_stamp = stamp or load_config()["reference"]["stamp"]
    path = _data_dir() / f"eurex_{cfg_stamp}.json"
    return json.loads(path.read_text())
