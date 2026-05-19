"""Phase 6 acceptance tests — cryocore API surface snapshot.

These tests lock in the public contract of ``cryocore`` so that accidental
removals or renames are caught immediately.  They also exercise the basic
runtime behaviour of each exported symbol.
"""
from __future__ import annotations

import importlib

import pytest


# ---------------------------------------------------------------------------
# Expected public API — edit this if the API intentionally changes
# ---------------------------------------------------------------------------

_EXPECTED_ALL = frozenset([
    # Instruments
    "Symbol",
    "Instrument",
    "parse_symbol",
    # Time helpers
    "utcnow",
    "floor_to_tf",
    "tf_to_seconds",
    "tf_to_pandas_freq",
    "bar_open",
    "bar_close",
    # Schemas / emit types
    "OHLCVBars",
    "BoolEmit",
    "StateEmit",
    "ProbEmit",
    # Calendars
    "Calendar",
    "get_calendar",
])


class TestCryocoreAPISnapshot:
    """Lock in the cryocore public surface so accidental removals are caught."""

    def test_all_symbols_present(self):
        """Every expected symbol must appear in cryocore.__all__."""
        import cryocore
        actual = frozenset(cryocore.__all__)
        missing = _EXPECTED_ALL - actual
        assert not missing, f"cryocore.__all__ is missing: {sorted(missing)}"

    def test_no_surprise_additions(self):
        """No undocumented symbol should appear in __all__ (update _EXPECTED_ALL if deliberate)."""
        import cryocore
        actual = frozenset(cryocore.__all__)
        unexpected = actual - _EXPECTED_ALL
        assert not unexpected, f"New symbol in cryocore.__all__ (update snapshot): {sorted(unexpected)}"

    def test_all_symbols_importable(self):
        """Every symbol in __all__ must be importable from the top-level package."""
        import cryocore
        for name in cryocore.__all__:
            assert hasattr(cryocore, name), f"cryocore.{name} not accessible after import"

    def test_version_is_semver(self):
        """cryocore.__version__ must be a non-empty semver-ish string."""
        import cryocore
        v = cryocore.__version__
        assert isinstance(v, str) and len(v) > 0
        parts = v.split(".")
        assert len(parts) >= 2, f"Expected semver, got {v!r}"


class TestCryocoreInstruments:
    def test_symbol_roundtrip(self):
        from cryocore import Symbol, parse_symbol
        sym = Symbol("binance.spot", "BTCUSDT")
        assert str(sym) == "binance.spot:BTCUSDT"
        assert parse_symbol("binance.spot:BTCUSDT") == sym

    def test_symbol_hashable(self):
        from cryocore import Symbol
        s = {Symbol("a", "b"), Symbol("a", "b"), Symbol("c", "d")}
        assert len(s) == 2

    def test_instrument_creation(self):
        from cryocore import Symbol, Instrument
        sym = Symbol("nyse", "AAPL")
        inst = Instrument(sym, asset_class="equity", quote_ccy="USD", calendar_id="nyse")
        assert inst.symbol == sym
        assert inst.asset_class == "equity"


class TestCryocoreTime:
    def test_utcnow_is_utc(self):
        from cryocore import utcnow
        from datetime import timezone
        now = utcnow()
        assert now.tzinfo is not None
        assert now.utcoffset().total_seconds() == 0

    def test_tf_to_seconds(self):
        from cryocore import tf_to_seconds
        assert tf_to_seconds("1h") == 3600
        assert tf_to_seconds("4h") == 14400
        assert tf_to_seconds("1d") == 86400

    def test_tf_to_pandas_freq(self):
        from cryocore import tf_to_pandas_freq
        assert tf_to_pandas_freq("1h") == "1h"
        assert tf_to_pandas_freq("1d") == "1D"

    def test_floor_to_tf(self):
        import pandas as pd
        from cryocore import floor_to_tf
        ts = pd.Timestamp("2024-03-15 14:37:00", tz="UTC")
        floored = floor_to_tf(ts, "1h")
        assert floored == pd.Timestamp("2024-03-15 14:00:00", tz="UTC")

    def test_bar_open_close(self):
        import pandas as pd
        from cryocore import bar_open, bar_close
        ts = pd.Timestamp("2024-01-01 03:45:00", tz="UTC")
        assert bar_open(ts, "1h") == pd.Timestamp("2024-01-01 03:00:00", tz="UTC")
        assert bar_close(ts, "1h") == pd.Timestamp("2024-01-01 04:00:00", tz="UTC")


class TestCryocoreSchemas:
    def test_ohlcvbars_validates_good_df(self):
        import pandas as pd
        from cryocore import OHLCVBars
        idx = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {"open": 100., "high": 105., "low": 95., "close": 102., "volume": 1.},
            index=idx,
        )
        result = OHLCVBars.validate_df(df)
        assert result is df

    def test_ohlcvbars_rejects_missing_column(self):
        import pandas as pd
        from cryocore import OHLCVBars
        idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        df = pd.DataFrame({"open": 1., "close": 1.}, index=idx)
        with pytest.raises(ValueError, match="missing columns"):
            OHLCVBars.validate_df(df)

    def test_bool_emit_roundtrip(self):
        from datetime import datetime, timezone
        from cryocore import BoolEmit
        e = BoolEmit(
            ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
            signal_id="test_signal",
            symbol_str="binance.spot:BTCUSDT",
            value=True,
        )
        assert e.value is True
        assert e.signal_id == "test_signal"

    def test_prob_emit_validates_range(self):
        from datetime import datetime, timezone
        from cryocore import ProbEmit
        with pytest.raises(Exception):
            ProbEmit(
                ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
                signal_id="s",
                symbol_str="x:y",
                prob=1.5,  # out of range
                direction="up",
                horizon_hours=24,
                threshold_used=0.6,
            )


class TestCryocoreCalendars:
    def test_get_calendar_crypto(self):
        from cryocore import get_calendar
        cal = get_calendar("crypto_24_7")
        import pandas as pd
        assert cal.is_open(pd.Timestamp("2024-01-01 00:00:00", tz="UTC")) is True

    def test_get_calendar_unknown_raises(self):
        from cryocore import get_calendar
        with pytest.raises(KeyError):
            get_calendar("nonexistent_calendar")

    def test_calendar_protocol(self):
        from cryocore import Calendar, get_calendar
        cal = get_calendar("crypto_24_7")
        assert isinstance(cal, Calendar)
