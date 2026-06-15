"""Unit tests for cryoquant.data.sources.twelvedata (no network)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cryocore.instruments import Symbol, td_ticker_info, should_use_twelvedata
from cryoquant.data.sources import twelvedata as td


class TestTdTickerInfo:
    def test_fx_direct_mapping(self):
        sym = Symbol("yahoo", "EURUSD=X")
        ticker, invert = td_ticker_info(sym)
        assert ticker == "EUR/USD"
        assert invert is False

    def test_fx_inverted_mapping(self):
        sym = Symbol("yahoo", "JPY=X")
        ticker, invert = td_ticker_info(sym)
        assert ticker == "USD/JPY"
        assert invert is True

    def test_equity_defaults_to_yahoo_ticker(self):
        sym = Symbol("yahoo", "SPY")
        ticker, invert = td_ticker_info(sym)
        assert ticker == "SPY"
        assert invert is False


class TestShouldUseTwelvedata:
    def test_hourly_spy_uses_td_when_key_set(self, monkeypatch):
        monkeypatch.setattr("cryoquant.config.TWELVEDATA_API_KEY", "test-key")
        assert should_use_twelvedata(Symbol("yahoo", "SPY"), "1h") is True

    def test_daily_spy_uses_yahoo(self, monkeypatch):
        monkeypatch.setattr("cryoquant.config.TWELVEDATA_API_KEY", "test-key")
        assert should_use_twelvedata(Symbol("yahoo", "SPY"), "1d") is False

    def test_futures_excluded(self, monkeypatch):
        monkeypatch.setattr("cryoquant.config.TWELVEDATA_API_KEY", "test-key")
        assert should_use_twelvedata(Symbol("yahoo", "CL=F"), "1h") is False

    def test_no_key_returns_false(self, monkeypatch):
        monkeypatch.setattr("cryoquant.config.TWELVEDATA_API_KEY", None)
        assert should_use_twelvedata(Symbol("yahoo", "SPY"), "1h") is False


class TestParseValues:
    def test_parses_and_floors_hourly(self):
        values = [
            {"datetime": "2024-06-01 10:00:01", "open": "100", "high": "101",
             "low": "99", "close": "100.5", "volume": "1000"},
        ]
        df = td._parse_values(values, "1h", invert=False)
        assert len(df) == 1
        assert df.index[0] == pd.Timestamp("2024-06-01 10:00:00", tz="UTC")
        assert df["close"].iloc[0] == pytest.approx(100.5)

    def test_inverts_fx_prices(self):
        values = [
            {"datetime": "2024-06-01 10:00:00", "open": "156.0", "high": "157.0",
             "low": "155.0", "close": "156.5", "volume": "0"},
        ]
        df = td._parse_values(values, "1h", invert=True)
        assert df["close"].iloc[0] == pytest.approx(1.0 / 156.5)
        assert df["high"].iloc[0] == pytest.approx(1.0 / 155.0)
        assert df["low"].iloc[0] == pytest.approx(1.0 / 157.0)

    def test_daily_skips_intraday_floor(self):
        values = [
            {"datetime": "2024-06-01 00:00:00", "open": "100", "high": "101",
             "low": "99", "close": "100", "volume": "1000"},
        ]
        df = td._parse_values(values, "1d", invert=False)
        assert df.index[0] == pd.Timestamp("2024-06-01 00:00:00", tz="UTC")

    def test_exchange_local_converted_to_utc(self):
        """US ETF bars from TD default API arrive in exchange local time."""
        values = [
            {"datetime": "2024-11-06 15:00:00", "open": "591", "high": "592",
             "low": "590", "close": "591.04", "volume": "1000"},
        ]
        df = td._parse_values(values, "1h", invert=False, source_tz="America/New_York")
        # 15:00 EST (Nov) = 20:00 UTC
        assert df.index[0] == pd.Timestamp("2024-11-06 20:00:00", tz="UTC")
        assert df["close"].iloc[0] == pytest.approx(591.04)


class TestFetchBarsPagination:
    def test_requests_timezone_utc(self, monkeypatch):
        monkeypatch.setattr("cryoquant.config.TWELVEDATA_API_KEY", "test-key")
        td._rate_limiter.reset()
        captured: dict = {}

        def fake_get(url, params=None, timeout=None):
            captured["params"] = params
            return MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"values": [], "status": "ok"}),
            )

        with patch("cryoquant.data.sources.twelvedata.requests.get", side_effect=fake_get):
            td.fetch_bars(
                Symbol("yahoo", "SPY"), "1h",
                start=pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
                end=pd.Timestamp("2024-01-02", tz="UTC").to_pydatetime(),
            )
        assert captured["params"]["timezone"] == "UTC"

    def test_raises_on_http_error(self, monkeypatch):
        import requests
        monkeypatch.setattr("cryoquant.config.TWELVEDATA_API_KEY", "test-key")
        td._rate_limiter.reset()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.RequestException("timeout")
        with patch("cryoquant.data.sources.twelvedata.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP error"):
                td.fetch_bars(
                    Symbol("yahoo", "SPY"), "1h",
                    start=pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
                    end=pd.Timestamp("2024-01-02", tz="UTC").to_pydatetime(),
                )
