"""Unit tests for cryoquant.data.sources.fred (no network)."""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cryoquant.data.sources import fred


_CSV_SAMPLE = """DATE,DGS10
2024-01-02,3.95
2024-01-03,3.99
2024-01-04,.
"""


class TestFredCsvFallback:
    def test_fetch_series_csv_parses_values(self, monkeypatch):
        monkeypatch.setattr("cryoquant.config.FRED_API_KEY", None)

        mock_resp = MagicMock()
        mock_resp.text = _CSV_SAMPLE
        mock_resp.raise_for_status = MagicMock()

        with patch("cryoquant.data.sources.fred.requests.Session") as mock_sess_cls:
            mock_sess = MagicMock()
            mock_sess.get.return_value = mock_resp
            mock_sess_cls.return_value = mock_sess

            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            end = datetime(2024, 1, 10, tzinfo=timezone.utc)
            s = fred.fetch_series("US10Y", start, end, session=mock_sess)

        assert len(s) == 3
        assert s.name == "US10Y"
        assert s.index.tz is not None
        assert pd.isna(s.iloc[2])  # "." → NaN

    def test_list_aliases_includes_dff_mapping(self):
        aliases = fred.list_aliases()
        assert aliases["FEDFUNDS"] == "DFF"
        assert aliases["NFCI"] == "NFCI"

    def test_unexpected_csv_format_raises(self, monkeypatch):
        monkeypatch.setattr("cryoquant.config.FRED_API_KEY", None)
        mock_resp = MagicMock()
        mock_resp.text = "not,a,valid,fred,csv\n1,2,3,4,5"
        mock_resp.raise_for_status = MagicMock()

        with patch("cryoquant.data.sources.fred.requests.Session") as mock_sess_cls:
            mock_sess = MagicMock()
            mock_sess.get.return_value = mock_resp
            mock_sess_cls.return_value = mock_sess

            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            with pytest.raises(RuntimeError, match="unexpected format"):
                fred.fetch_series("US10Y", start, session=mock_sess)
