"""Shared test fixtures for all phases."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from cryocore.instruments import Symbol


@pytest.fixture
def artefact_dir(request, tmp_path) -> Path:
    """Return a cleaned artefact directory for the current test.

    For live tests that write sign-off artefacts to a stable location,
    use the explicit path construction instead.
    """
    name = request.node.name.replace("/", "_").replace(" ", "_")
    d = Path(__file__).parent / "_artefacts" / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def tmp_store(tmp_path, monkeypatch) -> Path:
    """Override STORE_ROOT and CATALOG_DB to a tmp directory."""
    import cryoquant.config as cfg
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(cfg, "STORE_ROOT", store)
    monkeypatch.setattr(cfg, "CATALOG_DB", store / "catalog.duckdb")
    return store


@pytest.fixture
def cryobt_data_dir() -> Path:
    from cryoquant import config
    d = config.CRYOBACKTESTER_DATA_DIR
    if not d.exists():
        pytest.skip(f"CryoBacktester data dir not found: {d}")
    return d


@pytest.fixture(autouse=True)
def requires_network(request):
    """Skip live-marked tests when CRYOQUANT_OFFLINE is set."""
    if request.node.get_closest_marker("live"):
        if os.environ.get("CRYOQUANT_OFFLINE"):
            pytest.skip("CRYOQUANT_OFFLINE set — skipping live test")


def make_ohlcv(n: int = 100, start: str = "2024-01-01", freq: str = "1h") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame for testing."""
    import numpy as np
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    close = 30_000 + rng.standard_normal(n).cumsum() * 50
    close = np.clip(close, 100, None)
    high = close + rng.uniform(0, 100, n)
    low = close - rng.uniform(0, 100, n)
    low = np.clip(low, 1, None)
    df = pd.DataFrame(
        {
            "open":   close,
            "high":   high,
            "low":    low,
            "close":  close,
            "volume": rng.uniform(1, 1000, n),
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df
