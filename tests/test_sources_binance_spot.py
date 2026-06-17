"""Unit tests for cryoquant.data.sources.binance_spot (no network)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cryocore.instruments import Symbol
from cryoquant.data.sources import binance_spot as bs


def _kline(open_ms: int, o: str, h: str, l: str, c: str, v: str) -> list:
    """Minimal Binance kline array (open_time … ignore)."""
    close_ms = open_ms + 3_600_000 - 1
    return [
        open_ms, o, h, l, c, v,
        close_ms, "0", 0, "0", "0", "0",
    ]


class TestFetchKlines:
    def test_parses_utc_bar_open(self, monkeypatch):
        open_ms = int(pd.Timestamp("2024-06-01 10:00:00", tz="UTC").timestamp() * 1000)
        chunk = [_kline(open_ms, "3500", "3510", "3490", "3505", "100")]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = chunk

        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        sym = Symbol("binance.spot", "ETHUSDT")
        start = pd.Timestamp("2024-06-01", tz="UTC").to_pydatetime()
        end = pd.Timestamp("2024-06-02", tz="UTC").to_pydatetime()

        with patch("cryoquant.data.sources.binance_spot.requests.Session", return_value=mock_sess):
            df = bs.fetch_klines(sym, "1h", start, end, sleep_s=0)

        assert len(df) == 1
        assert df.index[0] == pd.Timestamp("2024-06-01 10:00:00", tz="UTC")
        assert df["close"].iloc[0] == pytest.approx(3505.0)
        assert df.index.tz is not None

    def test_rejects_non_binance_venue(self):
        sym = Symbol("yahoo", "ETHUSDT")
        start = pd.Timestamp("2024-06-01", tz="UTC").to_pydatetime()
        with pytest.raises(ValueError, match="binance"):
            bs.fetch_klines(sym, "1h", start)
