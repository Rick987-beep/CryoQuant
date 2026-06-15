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
        assert ("yahoo:SPY", "1d") in pairs
        assert ("yahoo:SPY", "1h") in pairs

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
