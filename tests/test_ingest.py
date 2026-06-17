"""Unit tests for cryoquant.data.ingest and loader.delete_partitions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from cryocore.instruments import Symbol
from cryoquant.data import ingest
from cryoquant.data import loader as ldr


@pytest.fixture
def sample_universe(tmp_path: Path) -> Path:
    data = {
        "equities": {
            "timeframes": ["1d", "1h"],
            "symbols": ["yahoo:SPY"],
        },
        "macro_fred": {
            "timeframes": ["1d"],
            "symbols": ["fred:US10Y"],
        },
    }
    path = tmp_path / "universe.yaml"
    path.write_text(yaml.dump(data))
    return path


class TestIngestUniverse:
    def test_load_universe(self, sample_universe: Path):
        u = ingest.load_universe(sample_universe)
        assert "equities" in u
        assert "macro_fred" in u

    def test_iter_ohlcv_symbols(self, sample_universe: Path):
        u = ingest.load_universe(sample_universe)
        pairs = ingest.iter_ohlcv_symbols(u)
        assert ("yahoo:SPY", "1d", u["equities"]) in pairs
        assert ("yahoo:SPY", "1h", u["equities"]) in pairs

    def test_iter_ohlcv_with_crypto_and_group_starts(self, tmp_path: Path):
        data = {
            "crypto": {
                "timeframes": ["1d", "1h"],
                "start_daily": "2017-08-01",
                "start_hourly": "2020-01-01",
                "symbols": ["binance.spot:BTCUSDT", "binance.spot:ETHUSDT"],
            },
        }
        path = tmp_path / "universe.yaml"
        path.write_text(yaml.dump(data))
        u = ingest.load_universe(path)
        pairs = ingest.iter_ohlcv_symbols(u)
        assert len(pairs) == 4
        assert ("binance.spot:ETHUSDT", "1h", u["crypto"]) in pairs

    def test_group_start_for_tf(self):
        group = {"start_daily": "2017-08-01", "start_hourly": "2020-01-01"}
        d = ingest._start_for_tf(
            "1d", start_override=None,
            daily_start="2010-01-01", hourly_start="2020-01-01", group=group,
        )
        h = ingest._start_for_tf(
            "1h", start_override=None,
            daily_start="2010-01-01", hourly_start="2020-01-01", group=group,
        )
        assert d.year == 2017 and d.month == 8
        assert h.year == 2020

    def test_cli_start_overrides_group(self):
        group = {"start_daily": "2017-08-01"}
        d = ingest._start_for_tf(
            "1d", start_override="2015-01-01",
            daily_start="2010-01-01", hourly_start="2020-01-01", group=group,
        )
        assert d.year == 2015

    def test_iter_macro_symbols(self, sample_universe: Path):
        u = ingest.load_universe(sample_universe)
        syms = ingest.iter_macro_symbols(u)
        assert syms == ["fred:US10Y"]

    def test_ingest_result_exit_codes(self):
        assert ingest.IngestResult(ok=5, failed=0).exit_code() == 0
        assert ingest.IngestResult(ok=3, failed=2).exit_code() == 1
        assert ingest.IngestResult(ok=0, failed=3).exit_code() == 2


class TestDeletePartitions:
    def test_delete_partitions_removes_parquet_and_sentinel(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cryoquant.config.STORE_ROOT", tmp_path)
        sym = Symbol("yahoo", "SPY")
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 2, 1, tzinfo=timezone.utc)

        parquet = ldr._partition_path(sym, "1d", 2024, 1)
        sentinel = ldr._sentinel_path(sym, "1d", 2024, 1)
        parquet.parent.mkdir(parents=True)
        parquet.write_text("x")
        sentinel.touch()

        removed = ldr.delete_partitions(sym, "1d", start, end)
        assert removed == 2
        assert not parquet.exists()
        assert not sentinel.exists()
