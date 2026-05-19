"""Phase 1 unit tests: cryocore.time, calendars, instruments, catalog, loader, schema."""
from __future__ import annotations

from datetime import datetime, timezone, date
from pathlib import Path

import pandas as pd
import pytest

from cryocore.time import (
    floor_to_tf, bar_open, bar_close, tf_to_seconds, utcnow, tf_to_pandas_freq,
)
from cryocore.calendars import get_calendar, Crypto24_7, NYSE
from cryocore.instruments import Symbol, Instrument, parse_symbol
from cryocore.schemas import OHLCVBars, BoolEmit, ProbEmit, StateEmit


# ---------------------------------------------------------------------------
# time.py
# ---------------------------------------------------------------------------

class TestFloorToTf:
    def test_1h_exact(self):
        ts = pd.Timestamp("2024-03-15 14:00:00", tz="UTC")
        assert floor_to_tf(ts, "1h") == ts

    def test_1h_floors(self):
        ts = pd.Timestamp("2024-03-15 14:37:22", tz="UTC")
        assert floor_to_tf(ts, "1h") == pd.Timestamp("2024-03-15 14:00:00", tz="UTC")

    def test_4h(self):
        ts = pd.Timestamp("2024-03-15 15:00:00", tz="UTC")
        assert floor_to_tf(ts, "4h") == pd.Timestamp("2024-03-15 12:00:00", tz="UTC")

    def test_1d(self):
        ts = pd.Timestamp("2024-03-15 14:37:00", tz="UTC")
        assert floor_to_tf(ts, "1d") == pd.Timestamp("2024-03-15 00:00:00", tz="UTC")

    def test_all_tfs_idempotent(self):
        """floor_to_tf(floor_to_tf(ts, tf), tf) == floor_to_tf(ts, tf)."""
        ts = pd.Timestamp("2024-06-22 13:22:45", tz="UTC")
        for tf in ("1m", "5m", "15m", "1h", "4h", "1d"):
            floored = floor_to_tf(ts, tf)
            assert floor_to_tf(floored, tf) == floored

    def test_invalid_tf(self):
        with pytest.raises(ValueError):
            floor_to_tf(pd.Timestamp("2024-01-01", tz="UTC"), "3h")

    def test_bar_open_matches_floor(self):
        ts = pd.Timestamp("2024-03-15 14:37:22", tz="UTC")
        assert bar_open(ts, "1h") == floor_to_tf(ts, "1h")

    def test_bar_close(self):
        ts = pd.Timestamp("2024-03-15 14:37:22", tz="UTC")
        assert bar_close(ts, "1h") == pd.Timestamp("2024-03-15 15:00:00", tz="UTC")

    def test_tf_to_seconds(self):
        assert tf_to_seconds("1h") == 3600
        assert tf_to_seconds("4h") == 14400
        assert tf_to_seconds("1d") == 86400

    def test_utcnow_is_aware(self):
        now = utcnow()
        assert now.tzinfo is not None


# ---------------------------------------------------------------------------
# calendars.py
# ---------------------------------------------------------------------------

class TestCrypto24_7:
    def test_always_open(self):
        cal = get_calendar("crypto_24_7")
        for ts in [
            pd.Timestamp("2024-01-01 00:00:00", tz="UTC"),   # New Year's Day
            pd.Timestamp("2024-12-25 12:00:00", tz="UTC"),   # Christmas
            pd.Timestamp("2024-07-06 10:00:00", tz="UTC"),   # Saturday
        ]:
            assert cal.is_open(ts) is True

    def test_session_label(self):
        cal = get_calendar("crypto_24_7")
        assert cal.session_label(pd.Timestamp("2024-06-01", tz="UTC")) == "crypto"


class TestNYSE:
    def test_closed_on_saturday(self):
        cal = get_calendar("nyse")
        # 2024-06-08 is a Saturday
        ts = pd.Timestamp("2024-06-08 14:00:00", tz="UTC")
        assert cal.is_open(ts) is False

    def test_open_on_weekday(self):
        cal = get_calendar("nyse")
        # 2024-06-10 is a Monday
        ts = pd.Timestamp("2024-06-10 14:00:00", tz="UTC")
        assert cal.is_open(ts) is True

    def test_known_holiday(self):
        """2024-12-25 Christmas — NYSE closed."""
        cal = get_calendar("nyse")
        ts = pd.Timestamp("2024-12-25 14:00:00", tz="UTC")
        assert cal.is_open(ts) is False


class TestCalendarRegistry:
    def test_unknown_raises(self):
        with pytest.raises(KeyError):
            get_calendar("nonexistent_calendar")

    def test_all_registered(self):
        for name in ("crypto_24_7", "nyse", "cme_futures", "fx_eur"):
            assert get_calendar(name) is not None


# ---------------------------------------------------------------------------
# instruments.py
# ---------------------------------------------------------------------------

class TestSymbol:
    def test_str(self):
        s = Symbol("binance.spot", "BTCUSDT")
        assert str(s) == "binance.spot:BTCUSDT"

    def test_frozen(self):
        s = Symbol("binance.spot", "BTCUSDT")
        with pytest.raises((AttributeError, TypeError)):
            s.ticker = "ETHUSDT"  # type: ignore

    def test_hashable(self):
        s1 = Symbol("binance.spot", "BTCUSDT")
        s2 = Symbol("binance.spot", "BTCUSDT")
        assert s1 == s2
        assert hash(s1) == hash(s2)
        assert {s1, s2} == {s1}

    def test_different_venues(self):
        s1 = Symbol("binance.spot", "BTCUSDT")
        s2 = Symbol("binance.perp", "BTCUSDT")
        assert s1 != s2

    def test_parse_roundtrip(self):
        s = Symbol("binance.spot", "BTCUSDT")
        assert parse_symbol(str(s)) == s

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            parse_symbol("no-colon-here")


# ---------------------------------------------------------------------------
# schemas.py — OHLCVBars
# ---------------------------------------------------------------------------

class TestOHLCVBars:
    def test_valid(self, conftest_ohlcv):
        df = conftest_ohlcv
        OHLCVBars.validate_df(df)  # should not raise

    def test_rejects_nan_ohlc(self, conftest_ohlcv):
        df = conftest_ohlcv.copy()
        df.iloc[5, df.columns.get_loc("close")] = float("nan")
        with pytest.raises(ValueError, match="NaN"):
            OHLCVBars.validate_df(df)

    def test_rejects_negative_volume(self, conftest_ohlcv):
        df = conftest_ohlcv.copy()
        df.iloc[3, df.columns.get_loc("volume")] = -1.0
        with pytest.raises(ValueError, match="volume"):
            OHLCVBars.validate_df(df)

    def test_rejects_non_utc_index(self, conftest_ohlcv):
        df = conftest_ohlcv.copy()
        df.index = df.index.tz_localize(None)
        with pytest.raises(ValueError, match="tz-aware"):
            OHLCVBars.validate_df(df)

    def test_rejects_non_datetimeindex(self, conftest_ohlcv):
        df = conftest_ohlcv.copy()
        df.index = range(len(df))
        with pytest.raises(ValueError, match="DatetimeIndex"):
            OHLCVBars.validate_df(df)

    def test_rejects_missing_columns(self, conftest_ohlcv):
        df = conftest_ohlcv.drop(columns=["volume"])
        with pytest.raises(ValueError, match="missing"):
            OHLCVBars.validate_df(df)


# Fixture used by TestOHLCVBars — attach to conftest via conftest.py
@pytest.fixture
def conftest_ohlcv():
    from tests.conftest import make_ohlcv
    return make_ohlcv()


# ---------------------------------------------------------------------------
# catalog.py
# ---------------------------------------------------------------------------

class TestCatalog:
    def test_register_and_lookup(self, tmp_path):
        from cryoquant.data.catalog import register, lookup
        sym = Symbol("binance.spot", "BTCUSDT")
        now = datetime(2024, 6, 1, tzinfo=timezone.utc)
        register(
            source="binance_spot", symbol=sym, tf="1h",
            path=tmp_path, row_count=100,
            ts_min=now, ts_max=now,
            db_path=tmp_path / "cat.duckdb",
        )
        row = lookup(sym, "1h", db_path=tmp_path / "cat.duckdb")
        assert row is not None
        assert row["ticker"] == "BTCUSDT"
        assert row["row_count"] == 100

    def test_upsert_updates_not_duplicates(self, tmp_path):
        from cryoquant.data.catalog import register, list_datasets
        sym = Symbol("binance.spot", "BTCUSDT")
        db = tmp_path / "cat.duckdb"
        now = datetime(2024, 6, 1, tzinfo=timezone.utc)
        for rc in [100, 200]:
            register("binance_spot", sym, "1h", tmp_path, rc, now, now, db_path=db)
        df = list_datasets(db_path=db)
        assert len(df) == 1
        assert df.iloc[0]["row_count"] == 200

    def test_lookup_missing_returns_none(self, tmp_path):
        from cryoquant.data.catalog import lookup
        sym = Symbol("binance.spot", "MISSING")
        result = lookup(sym, "1h", db_path=tmp_path / "cat.duckdb")
        assert result is None

    def test_list_datasets_multiple(self, tmp_path):
        from cryoquant.data.catalog import register, list_datasets
        db = tmp_path / "cat.duckdb"
        now = datetime(2024, 6, 1, tzinfo=timezone.utc)
        for ticker, tf in [("BTCUSDT", "1h"), ("ETHUSDT", "1d")]:
            register("binance_spot", Symbol("binance.spot", ticker), tf,
                     tmp_path, 100, now, now, db_path=db)
        df = list_datasets(db_path=db)
        assert len(df) == 2


# ---------------------------------------------------------------------------
# loader (offline — pre-populated parquet)
# ---------------------------------------------------------------------------

class TestLoaderOffline:
    def test_load_from_existing_parquet(self, tmp_store):
        """With pre-populated partition, load() returns the expected slice."""
        from cryoquant.data.loader import load, _partition_path
        import cryoquant.config as cfg

        sym = Symbol("binance.spot", "BTCUSDT")
        from tests.conftest import make_ohlcv
        df = make_ohlcv(n=200, start="2024-03-01", freq="1h")

        path = _partition_path(sym, "1h", 2024, 3)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)

        # monkeypatch catalog DB to tmp location too
        result = load(
            sym, "1h",
            start=datetime(2024, 3, 1, tzinfo=timezone.utc),
            end=datetime(2024, 3, 31, 23, 59, tzinfo=timezone.utc),
        )
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.tz is not None
        assert set(result.columns) >= {"open", "high", "low", "close", "volume"}
        assert len(result) > 0
