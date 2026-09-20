"""Offline tests for VIX OHLC helpers (no network)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from src.vix_data import load_vix_ohlc, write_ohlc_parquet


def test_load_vix_ohlc_assembles_columns(monkeypatch) -> None:
    idx = pd.DatetimeIndex(
        ["2024-01-02", "2024-01-03"], tz="UTC", name="timestamp"
    )

    def fake_load(source, series_id, start, end):
        assert source == "cboe"
        values = {"VIX_OPEN": [13.0, 14.0], "VIX_HIGH": [14.0, 15.0],
                  "VIX_LOW": [12.0, 13.0], "VIX_CLOSE": [13.5, 14.5]}[series_id]
        return pd.Series(values, index=idx, name=series_id, dtype="float64")

    monkeypatch.setattr("src.vix_data.macro_store.load_series", fake_load)
    df = load_vix_ohlc(
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 1, 5, tzinfo=timezone.utc),
    )
    assert list(df.columns) == ["open", "high", "low", "close"]
    assert len(df) == 2
    assert df.loc[idx[0], "close"] == 13.5


def test_write_ohlc_parquet(tmp_path) -> None:
    idx = pd.DatetimeIndex(["2024-01-02"], tz="UTC", name="timestamp")
    df = pd.DataFrame(
        {"open": [13.0], "high": [14.0], "low": [12.0], "close": [13.5]},
        index=idx,
    )
    path = write_ohlc_parquet(df, tmp_path / "vix.parquet")
    loaded = pd.read_parquet(path)
    assert list(loaded.columns) == ["open", "high", "low", "close"]
    assert len(loaded) == 1
