"""Unit tests for crypto / alt-data sources (mocked HTTP, no network)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cryoquant.data.sources import (
    coinmetrics,
    defillama,
    deribit_indices,
    farside_etf,
    fear_greed,
    fomc_calendar,
    strategy_treasury,
)


_FARSIDE_HTML = """
<table class="etf"><thead><tr>
<th>Date</th><th>IBIT</th><th>FBTC</th><th>Total</th>
</tr></thead><tbody>
<tr><td>11 Jan 2024</td><td>111.7</td><td>227.0</td><td>655.3</td></tr>
<tr><td>12 Jan 2024</td><td>(50.0)</td><td>-</td><td>(50.0)</td></tr>
</tbody></table>
"""

_STRATEGY_JSON = {
    "props": {
        "pageProps": {
            "bitcoinData": [
                {
                    "date_of_purchase": "2020-08-10",
                    "btc_holdings": 21454,
                    "purchase_price": 11652.84,
                    "total_purchase_price": 250000000,
                },
                {
                    "date_of_purchase": "2020-09-14",
                    "btc_holdings": 38250,
                    "purchase_price": 10419.15,
                    "total_purchase_price": 175000000,
                },
            ]
        }
    }
}


class TestFearGreed:
    def test_fetch_series_parses_values(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"timestamp": "1704067200", "value": "25"},
                {"timestamp": "1704153600", "value": "30"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        df = fear_greed.fetch_series(date(2024, 1, 1), date(2024, 1, 10), session=mock_sess)
        assert len(df) == 2
        assert df["value"].between(0, 100).all()
        assert df.index.tz is not None


class TestDefiLlama:
    def test_stablecoin_supply_parses(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"date": "1704067200", "totalCirculatingUSD": {"peggedUSD": 100_000_000.0}},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        df = defillama.fetch_stablecoin_supply(date(2024, 1, 1), date(2024, 1, 5), session=mock_sess)
        assert len(df) == 1
        assert df["value"].iloc[0] == 100_000_000.0

    def test_empty_response(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        df = defillama.fetch_stablecoin_supply(date(2024, 1, 1), session=mock_sess)
        assert df.empty


class TestCoinMetrics:
    def test_available_utc_is_chain_date_plus_one(self):
        chain_d = date(2024, 6, 1)
        avail = coinmetrics.chain_date_to_available_utc(chain_d)
        assert avail == datetime(2024, 6, 2, 0, 0, tzinfo=timezone.utc)

    def test_fetch_asset_metric(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"time": "2024-06-01T00:00:00Z", "HashRate": "500000000"}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        with patch("cryoquant.data.sources.coinmetrics.time.sleep"):
            df = coinmetrics.fetch_asset_metric("btc", "HashRate", date(2024, 6, 1), session=mock_sess)

        assert len(df) == 1
        assert df["available_utc"].iloc[0].date() == date(2024, 6, 2)


class TestFOMC:
    def test_decision_flag_not_before_available(self):
        d = date(2024, 3, 20)
        avail = fomc_calendar.decision_available_utc(d)
        assert avail.date() >= d

    def test_fetch_fomc_includes_static_dates(self):
        df = fomc_calendar.fetch_fomc_decision_days(date(2024, 1, 1), date(2024, 12, 31))
        assert not df.empty
        assert (df["is_fomc_decision_day"] == 1.0).all()

    def test_build_calendar_features(self):
        index = pd.date_range("2024-03-18", periods=5, freq="D", tz="UTC")
        feat = fomc_calendar.build_fomc_calendar_features(index)
        assert "is_fomc_decision_day" in feat.columns
        assert feat.loc[pd.Timestamp("2024-03-20", tz="UTC"), "is_fomc_decision_day"] == 1.0


class TestDeribitDVOL:
    def test_fetch_dvol_monotonic(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "data": [
                    [1704067200000, 50, 55, 45, 52],
                    [1704153600000, 52, 56, 48, 54],
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        df = deribit_indices.fetch_dvol("BTC", date(2024, 1, 1), date(2024, 1, 10), session=mock_sess)
        assert len(df) == 2
        assert df.index.is_monotonic_increasing


class TestFarsideETF:
    def test_parse_aggregate_flows(self):
        with patch("cryoquant.data.sources.farside_etf.fetch_raw_rows") as mock_rows:
            mock_rows.return_value = [
                {"trade_date": date(2024, 1, 11), "Total": 655.3, "IBIT": 111.7},
                {"trade_date": date(2024, 1, 12), "Total": -50.0, "IBIT": -50.0},
            ]
            df = farside_etf.fetch_aggregate_flows(date(2024, 1, 1), date(2024, 1, 31))
        assert len(df) == 2
        assert df["value"].iloc[0] == pytest.approx(655.3e6)
        assert df["value"].iloc[1] == pytest.approx(-50.0e6)
        assert df["available_utc"].iloc[0].tzinfo is not None

    def test_parse_html_table(self):
        rows = farside_etf._rows_from_html(_FARSIDE_HTML)
        assert len(rows) == 2
        assert rows[0]["trade_date"] == date(2024, 1, 11)
        assert rows[1]["IBIT"] == pytest.approx(-50.0)


class TestStrategyTreasury:
    def test_fetch_mstr_purchases(self):
        mock_resp = MagicMock()
        mock_resp.text = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(_STRATEGY_JSON)
            + "</script>"
        )
        mock_resp.raise_for_status = MagicMock()
        mock_sess = MagicMock()
        mock_sess.get.return_value = mock_resp

        df = strategy_treasury.fetch_mstr_purchases(date(2020, 8, 1), session=mock_sess)
        assert len(df) == 2
        assert df["btc_acq"].iloc[0] == pytest.approx(21454)
        assert df["btc_acq"].iloc[1] == pytest.approx(16796)
        assert df["acq_cost"].iloc[0] == pytest.approx(250_000_000)
