"""Phase 1 integration tests — study ingest router (framework sources tested in tests/test_sources_crypto.py)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from cryocore.instruments import Symbol, get_instrument
from cryoquant.data.sources import binance_perp


class TestSOLRegistration:
    def test_solusdt_registered(self):
        sym = Symbol("binance.spot", "SOLUSDT")
        instr = get_instrument(sym)
        assert instr is not None
        assert instr.calendar_id == "crypto_24_7"


class TestFundingDaily:
    def test_funding_to_daily_last_per_day(self):
        idx = pd.DatetimeIndex(
            ["2024-01-01 08:00", "2024-01-01 16:00", "2024-01-02 00:00"],
            tz="UTC",
        )
        funding = pd.DataFrame({"funding_rate": [0.0001, 0.0002, 0.0003]}, index=idx)
        daily = binance_perp.funding_to_daily(funding)
        assert len(daily) == 2
        assert daily.iloc[0] == pytest.approx(0.0002)
        assert daily.iloc[1] == pytest.approx(0.0003)


class TestIngestDryRun:
    def test_dry_run_manifest(self, tmp_path):
        from src.ingest import run_btcpredict_ingest, write_manifest
        from src.paths import ANALYSIS_ROOT

        manifest = run_btcpredict_ingest(
            ANALYSIS_ROOT / "universe.yaml",
            dry_run=True,
            skip_optional=True,
        )
        assert manifest.ok > 0
        assert manifest.failed == 0
        out = tmp_path / "manifest.json"
        write_manifest(manifest, out)
        assert out.exists()
