"""Tests for cryoquant.data.resolve."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from cryocore.instruments import Symbol
from cryoquant.data import resolve


START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 1, 10, tzinfo=timezone.utc)


class TestIsOhlcvSymbol:
    def test_binance_is_ohlcv(self) -> None:
        assert resolve.is_ohlcv_symbol(Symbol("binance.spot", "BTCUSDT")) is True

    def test_fred_is_macro(self) -> None:
        assert resolve.is_ohlcv_symbol(Symbol("fred", "DGS10")) is False

    def test_manual_is_macro(self) -> None:
        assert resolve.is_ohlcv_symbol(Symbol("manual", "CDX_NA_IG_5Y")) is False

    def test_cboe_is_macro(self) -> None:
        assert resolve.is_ohlcv_symbol(Symbol("cboe", "VIX")) is False

    def test_yahoo_is_ohlcv(self) -> None:
        assert resolve.is_ohlcv_symbol(Symbol("yahoo", "SPY")) is True


class TestMacroSourceAndId:
    def test_cboe_vix_maps_to_vix_close(self) -> None:
        assert resolve.macro_source_and_id(Symbol("cboe", "VIX")) == ("cboe", "VIX_CLOSE")


class TestLoadTrack:
    def test_load_track_ohlcv_delegates_to_loader(self, monkeypatch) -> None:
        sym = Symbol("binance.spot", "BTCUSDT")
        idx = pd.date_range(START, periods=5, freq="1h", tz="UTC")
        fake = pd.DataFrame(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
            index=idx,
        )

        def _fake_load(symbol, tf, start, end):
            return fake

        monkeypatch.setattr(resolve.loader, "load", _fake_load)
        out = resolve.load_track(sym, "1h", START, END)
        assert isinstance(out, pd.DataFrame)
        assert "close" in out.columns

    def test_load_track_macro_delegates_to_macro_store(self, monkeypatch) -> None:
        sym = Symbol("fred", "DGS10")
        idx = pd.date_range(START, periods=5, freq="1D", tz="UTC")
        fake = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx, name="DGS10")

        def _fake_series(source, series_id, start, end):
            assert source == "fred"
            assert series_id == "DGS10"
            return fake

        monkeypatch.setattr(resolve.macro_store, "load_series", _fake_series)
        out = resolve.load_track(sym, "1d", START, END)
        assert isinstance(out, pd.Series)

    def test_load_tracks_mixed(self, monkeypatch) -> None:
        idx = pd.date_range(START, periods=3, freq="1D", tz="UTC")
        bars = pd.DataFrame(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0},
            index=idx,
        )
        macro = pd.Series([20.0, 21.0, 22.0], index=idx)

        monkeypatch.setattr(
            resolve.loader,
            "load",
            lambda s, tf, start, end: bars,
        )
        monkeypatch.setattr(
            resolve.macro_store,
            "load_series",
            lambda source, sid, start, end: macro,
        )

        specs = [
            (Symbol("yahoo", "SPY"), "1d"),
            (Symbol("fred", "VIX"), "1d"),
        ]
        tracks = resolve.load_tracks(specs, START, END)
        assert "yahoo:SPY@1d" in tracks
        assert "fred:VIX" in tracks
