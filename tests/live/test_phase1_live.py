"""Phase 1 live tests — require network; run with: pytest tests/ -m live"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cryocore.instruments import Symbol
from cryocore.schemas import OHLCVBars

_ARTEFACTS = Path(__file__).parent.parent / "_artefacts" / "phase1"
pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def clean_artefacts():
    shutil.rmtree(_ARTEFACTS, ignore_errors=True)
    _ARTEFACTS.mkdir(parents=True, exist_ok=True)


def test_loader_roundtrip_binance(tmp_store, monkeypatch):
    """Sign-off: fetch BTC 1h from Binance, cache, reload from disk without network."""
    import requests as _requests
    from cryoquant.data.loader import load
    from cryoquant.data import catalog as cat

    sym = Symbol("binance.spot", "BTCUSDT")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)

    # First call — goes to network
    df = load(sym, "1h", start, end)
    assert len(df) >= 24 * 29, f"Expected ≥696 rows, got {len(df)}"
    assert df.index.tz is not None
    assert df.index.is_monotonic_increasing
    # No gaps > 2 bars (7200s)
    max_gap = df.index.to_series().diff().max()
    assert max_gap <= pd.Timedelta(hours=2), f"Gap too large: {max_gap}"
    # Latest bar within 2h of now
    assert df.index[-1] >= pd.Timestamp(end - timedelta(hours=2))
    OHLCVBars.validate_df(df)

    # Monkeypatch requests.Session.get to count calls on second load
    call_count = {"n": 0}
    orig_get = _requests.Session.get
    def counting_get(self, *args, **kwargs):
        call_count["n"] += 1
        return orig_get(self, *args, **kwargs)
    monkeypatch.setattr(_requests.Session, "get", counting_get)

    # Second call — must serve from disk
    df2 = load(sym, "1h", start, end)
    assert call_count["n"] == 0, f"Expected 0 network calls on second load, got {call_count['n']}"
    assert df2.equals(df)

    # Catalog has an entry
    row = cat.lookup(sym, "1h")
    assert row is not None

    # Write sign-off artefact
    summary = {
        "row_count": len(df),
        "ts_min": str(df.index.min()),
        "ts_max": str(df.index.max()),
    }
    (_ARTEFACTS / "summary.json").write_text(json.dumps(summary, indent=2))


def test_deribit_options_read(cryobt_data_dir):
    """Read most recent option chain; assert structure."""
    from cryoquant.data.sources.deribit_options import list_dates, load_chain, load_spot

    dates = list_dates()
    assert len(dates) > 0, "No options parquets found"

    latest = dates[-1]
    chain = load_chain(latest)
    assert len(chain) > 100, f"Expected >100 rows in chain, got {len(chain)}"

    required_cols = {"instrument_name", "strike", "option_type"}
    missing = required_cols - set(chain.columns)
    assert not missing, f"Missing columns: {missing}"


def test_fred_dxy_smoke():
    """Fetch 1 year of DXY; two code paths (fredapi / CSV fallback)."""
    from cryoquant.data.sources.fred import fetch_series

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365)
    series = fetch_series("DXY", start, end)

    assert len(series.dropna()) >= 200, f"Expected ≥200 points, got {len(series.dropna())}"
    assert series.dtype == float
    assert series.index.tz is not None
