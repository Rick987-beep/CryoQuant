"""Unit tests for new cryoquant data sources."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cryoquant.data.sources import binance_perp


class TestBinancePerpOI:
    def test_fetch_open_interest_parses(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"timestamp": 1704067200000, "sumOpenInterest": "12345.67"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        sym = __import__("cryocore.instruments", fromlist=["Symbol"]).Symbol("binance.perp", "BTCUSDT")
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = binance_perp.fetch_open_interest(sym, start, session=mock_sess)
        assert len(df) == 1
        assert df["open_interest"].iloc[0] == pytest.approx(12345.67)
