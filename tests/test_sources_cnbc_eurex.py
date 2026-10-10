"""Unit tests for CNBC / Eurex source modules (mocked network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from cryoquant.data.sources import cnbc_yields, eurex_futures


def test_cnbc_fetch_yield_parses_bars() -> None:
    payload = {
        "barData": {
            "priceBars": [
                {"tradeTime": "20261007T000000", "close": "4.8696"},
                {"tradeTime": "20261008T000000", "close": "4.8873"},
            ]
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    sess = MagicMock()
    sess.get.return_value = mock_resp

    s = cnbc_yields.fetch_yield("OAT10", "1Y", session=sess)
    assert len(s) == 2
    assert float(s.iloc[-1]) == 4.8873
    assert s.index.tz is not None


def test_eurex_fetch_settles_parses_window() -> None:
    header = {
        "header": {"tradingDates": ["08-10-2026", "07-10-2026"]},
        "dataRows": [],
    }
    day = {
        "dataRows": [
            {"date": 20261208, "dSettle": "108.66"},
            {"date": 20270308, "dSettle": "107.90"},
        ]
    }

    def _json_for_url(url: str, **_kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "busdate=" in url:
            resp.json.return_value = day
        else:
            resp.json.return_value = header
        return resp

    sess = MagicMock()
    sess.get.side_effect = _json_for_url

    df = eurex_futures.fetch_settles(session=sess)
    assert len(df) == 2
    assert abs(float(df["FOAT_front"].iloc[-1]) - 108.66) < 1e-9
    assert "FGBL_front" in df.columns


def test_fred_euro_aliases_present() -> None:
    from cryoquant.data.sources.fred import list_aliases

    aliases = list_aliases()
    assert aliases["FR10Y_LT"] == "IRLTLT01FRM156N"
    assert aliases["DE10Y_LT"] == "IRLTLT01DEM156N"
    assert aliases["IT10Y_LT"] == "IRLTLT01ITM156N"
