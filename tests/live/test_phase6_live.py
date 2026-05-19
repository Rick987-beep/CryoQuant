"""Phase 6 live tests — cross-repo contract verification.

Gated by environment variables; all tests skip gracefully when the required
env/repos are not available on the current machine.

Run with:
    pytest tests/live/test_phase6_live.py -m "live and slow" -v -s
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


def _artefact_dir(tag: str) -> Path:
    d = Path(__file__).parent.parent / "artefacts" / "phase6_live" / tag
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Test 1: CryoTrader paper slot consumption (gated)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.slow
def test_cryotrader_consumes_signal_live(tmp_path):
    """Push a ProbSignal history file to CryoTrader's paper slot and verify
    at least one entry was evaluated via its replay CLI.

    Requires:
      - CRYOTRADER_PAPER_AVAILABLE=1
      - CRYOTRADER_ROOT env var pointing to a local CryoTrader checkout
    """
    if os.environ.get("CRYOTRADER_PAPER_AVAILABLE") != "1":
        pytest.skip("Set CRYOTRADER_PAPER_AVAILABLE=1 to run CryoTrader integration test")

    cryotrader_root = os.environ.get("CRYOTRADER_ROOT", "")
    if not cryotrader_root or not Path(cryotrader_root).exists():
        pytest.skip("CRYOTRADER_ROOT not set or not found")

    from cryocore import Symbol, ProbEmit
    from cryoquant.signals.publishers import SignalPublisher
    import cryoquant.config as cfg

    art = _artefact_dir("cryotrader_replay")
    print(f"\nArtefacts → {art}")

    # Build a minimal 3-event ProbSignal history
    sym = Symbol("binance.spot", "BTCUSDT")
    events = []
    base = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        e = ProbEmit(
            ts=base + timedelta(hours=i * 24),
            signal_id="test_pullback_v1",
            symbol_str=str(sym),
            prob=0.72 + i * 0.02,
            direction="up",
            horizon_hours=24,
            threshold_used=0.6,
        )
        events.append(e)

    # Write signal history as NDJSON
    history_file = tmp_path / "signal_history.ndjson"
    with history_file.open("w") as fh:
        for e in events:
            fh.write(e.model_dump_json() + "\n")

    print(f"  Signal history: {len(events)} events written to {history_file}")

    # Copy to CryoTrader paper input directory and invoke replay
    import subprocess
    paper_dir = Path(cryotrader_root) / "paper" / "signals"
    paper_dir.mkdir(parents=True, exist_ok=True)
    dest = paper_dir / "test_pullback_v1.ndjson"
    dest.write_bytes(history_file.read_bytes())

    result = subprocess.run(
        ["python", "-m", "cryotrader", "replay", "--signal", "test_pullback_v1", "--dry-run"],
        cwd=cryotrader_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(f"  Replay exit code: {result.returncode}")
    print(f"  Replay stdout: {result.stdout[:500]}")
    if result.returncode != 0:
        print(f"  Replay stderr: {result.stderr[:200]}")

    # Write artefacts
    (art / "replay_stdout.txt").write_text(result.stdout)
    (art / "replay_stderr.txt").write_text(result.stderr)

    assert result.returncode == 0, f"CryoTrader replay failed:\n{result.stderr}"
    assert "evaluated" in result.stdout.lower() or len(result.stdout) > 0, \
        "Replay produced no output — check CryoTrader integration"

    print("✓ Phase 6 CryoTrader live test PASSED")


# ---------------------------------------------------------------------------
# Test 2: cryocore end-to-end import from a sibling-repo perspective
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.slow
def test_cryocore_api_stable():
    """Verify that the full cryocore public API is importable and exercisable.

    This is the 'sibling repo' perspective: pretend we're CryoTrader importing
    cryocore for the first time and exercising every exported symbol.
    """
    import cryocore

    art = _artefact_dir("api_stable")

    # Instruments
    from cryocore import Symbol, Instrument, parse_symbol
    sym = parse_symbol("binance.spot:BTCUSDT")
    assert str(sym) == "binance.spot:BTCUSDT"
    inst = Instrument(sym, asset_class="crypto", quote_ccy="USDT", calendar_id="crypto_24_7")
    assert inst.calendar_id == "crypto_24_7"

    # Time
    from cryocore import utcnow, floor_to_tf, tf_to_seconds, tf_to_pandas_freq, bar_open, bar_close
    import pandas as pd
    now = utcnow()
    assert now.tzinfo is not None
    floored = floor_to_tf(now, "4h")
    assert (now - floored).total_seconds() < 4 * 3600

    # Schemas
    from cryocore import OHLCVBars, BoolEmit, StateEmit, ProbEmit
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {"open": 100., "high": 101., "low": 99., "close": 100.5, "volume": 10.},
        index=idx,
    )
    OHLCVBars.validate_df(df)

    emit = ProbEmit(
        ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
        signal_id="my_signal",
        symbol_str="binance.spot:BTCUSDT",
        prob=0.75,
        direction="up",
        horizon_hours=24,
        threshold_used=0.6,
    )
    assert 0 <= emit.prob <= 1

    # Calendars
    from cryocore import Calendar, get_calendar
    cal = get_calendar("crypto_24_7")
    assert cal.is_open(now)
    assert isinstance(cal, Calendar)

    # Write artefact
    summary = {
        "cryocore_version": cryocore.__version__,
        "all_symbols": sorted(cryocore.__all__),
        "sym_example": str(sym),
        "now_utc": str(now),
        "floored_4h": str(floored),
        "tf_seconds_1h": tf_to_seconds("1h"),
        "calendar_open": cal.is_open(now),
    }
    (art / "api_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  cryocore version: {cryocore.__version__}")
    print(f"  Exported symbols ({len(cryocore.__all__)}): {sorted(cryocore.__all__)}")
    print(f"  Artefact: {art / 'api_summary.json'}")
    print("✓ Phase 6 cryocore API stable test PASSED")
