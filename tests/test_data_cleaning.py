"""Unit tests for cryoquant.data.cleaning.

Tests are pure (no I/O, no network) — all DataFrames are constructed in-memory.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from cryoquant.data.cleaning import (
    AuditWarning,
    audit_bars,
    clean_ohlcv,
    normalize_ohlcv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daily(
    dates: list[str],
    open_: float = 100.0,
    high_: float = 105.0,
    low_: float = 95.0,
    close_: float = 102.0,
    volume: float = 1_000_000.0,
    tz: str | None = "UTC",
) -> pd.DataFrame:
    idx = pd.DatetimeIndex(dates, tz=tz, name="timestamp")
    return pd.DataFrame(
        {
            "open":   open_,
            "high":   high_,
            "low":    low_,
            "close":  close_,
            "volume": volume,
        },
        index=idx,
    )


def _make_hourly(n: int = 48, start: str = "2024-01-01 00:00", tz: str = "UTC") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="1h", tz=tz, name="timestamp")
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500.0},
        index=idx,
    )


# ---------------------------------------------------------------------------
# normalize_ohlcv
# ---------------------------------------------------------------------------

class TestNormalizeOHLCV:
    def test_basic_passthrough(self):
        df = _make_daily(["2024-01-02", "2024-01-03"])
        out = normalize_ohlcv(df, "1d")
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]
        assert out.index.tz is not None
        assert str(out.index.tz) == "UTC"
        assert out.index.name == "timestamp"
        assert len(out) == 2

    def test_tz_naive_index_gets_utc(self):
        df = _make_daily(["2024-01-02"], tz=None)
        out = normalize_ohlcv(df, "1d")
        assert out.index.tz is not None

    def test_non_utc_converted(self):
        df = _make_daily(["2024-01-02 09:30:00"], tz="US/Eastern")
        out = normalize_ohlcv(df, "1d")
        assert str(out.index.tz) == "UTC"

    def test_missing_volume_defaults_to_zero(self):
        df = _make_daily(["2024-01-02"])
        df = df.drop(columns=["volume"])
        out = normalize_ohlcv(df, "1d")
        assert (out["volume"] == 0.0).all()

    def test_missing_ohlc_raises(self):
        df = _make_daily(["2024-01-02"])
        df = df.drop(columns=["close"])
        with pytest.raises(ValueError, match="missing required column"):
            normalize_ohlcv(df, "1d")

    def test_deduplicate_keeps_first(self):
        df = _make_daily(["2024-01-02", "2024-01-02"])
        assert len(df) == 2
        out = normalize_ohlcv(df, "1d")
        assert len(out) == 1

    def test_sorted_output(self):
        df = _make_daily(["2024-01-04", "2024-01-02", "2024-01-03"])
        out = normalize_ohlcv(df, "1d")
        assert out.index.is_monotonic_increasing

    def test_dtypes_float64(self):
        df = _make_daily(["2024-01-02"])
        df["open"] = "100.5"   # string input
        out = normalize_ohlcv(df, "1d")
        for col in ("open", "high", "low", "close", "volume"):
            assert out[col].dtype == float

    def test_hourly_floor_to_bar_open(self):
        """Timestamps slightly off should be floored to the hour."""
        idx = pd.DatetimeIndex(["2024-01-01 10:00:01+00:00"], name="timestamp")
        df = pd.DataFrame(
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100.0},
            index=idx,
        )
        out = normalize_ohlcv(df, "1h")
        assert out.index[0] == pd.Timestamp("2024-01-01 10:00:00+00:00")


# ---------------------------------------------------------------------------
# clean_ohlcv
# ---------------------------------------------------------------------------

class TestCleanOHLCV:
    def test_drops_nan_ohlc(self):
        df = _make_daily(["2024-01-02", "2024-01-03"])
        df.loc[df.index[0], "close"] = float("nan")
        out = clean_ohlcv(df, "1d")
        assert len(out) == 1

    def test_drops_zero_ohlc(self):
        df = _make_daily(["2024-01-02", "2024-01-03"])
        df.loc[df.index[1], "open"] = 0.0
        out = clean_ohlcv(df, "1d")
        assert len(out) == 1

    def test_drops_inverted_ohlc(self):
        df = _make_daily(["2024-01-02", "2024-01-03"])
        df.loc[df.index[0], "low"] = 200.0   # low > high
        out = clean_ohlcv(df, "1d")
        assert len(out) == 1

    def test_drops_negative_price(self):
        df = _make_daily(["2024-01-02", "2024-01-03"])
        df.loc[df.index[0], "close"] = -1.0
        out = clean_ohlcv(df, "1d")
        assert len(out) == 1

    def test_drops_negative_volume(self):
        df = _make_daily(["2024-01-02", "2024-01-03"])
        df.loc[df.index[1], "volume"] = -500.0
        out = clean_ohlcv(df, "1d")
        assert len(out) == 1

    def test_drops_fx_saturday_daily(self):
        # 2024-01-06 is Saturday
        df = _make_daily(["2024-01-05", "2024-01-06", "2024-01-07"])
        out = clean_ohlcv(df, "1d", calendar_id="fx_24_5")
        assert pd.Timestamp("2024-01-06", tz="UTC") not in out.index

    def test_drops_fx_sunday_before_open_daily(self):
        # 2024-01-07 is Sunday — both Saturday and Sunday should be dropped with daily tf
        df = _make_daily(["2024-01-05", "2024-01-06", "2024-01-07"])
        out = clean_ohlcv(df, "1d", calendar_id="fx_24_5")
        assert pd.Timestamp("2024-01-07", tz="UTC") not in out.index

    def test_keeps_weekday_fx(self):
        df = _make_daily(["2024-01-08", "2024-01-09", "2024-01-10"])  # Mon/Tue/Wed
        out = clean_ohlcv(df, "1d", calendar_id="fx_24_5")
        assert len(out) == 3

    def test_clean_passes_good_data(self):
        df = _make_hourly(n=100)
        out = clean_ohlcv(df, "1h", calendar_id="nyse")
        assert len(out) > 0
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# audit_bars
# ---------------------------------------------------------------------------

class TestAuditBars:
    def test_no_warnings_for_clean_data(self):
        df = _make_hourly(n=48)
        warns = audit_bars(df, "1h", "nyse")
        errors = [w for w in warns if w.level == "error"]
        assert errors == [], [str(w) for w in errors]

    def test_detects_empty_df(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        warns = audit_bars(df, "1d")
        assert any(w.code == "EMPTY" for w in warns)

    def test_detects_duplicate_timestamps(self):
        df = _make_daily(["2024-01-02", "2024-01-02"])
        warns = audit_bars(df, "1d")
        assert any(w.code == "DUPLICATE_TS" for w in warns)

    def test_detects_nan_close(self):
        df = _make_daily(["2024-01-02", "2024-01-03"])
        df.loc[df.index[0], "close"] = float("nan")
        warns = audit_bars(df, "1d")
        assert any(w.code == "NAN_CLOSE" for w in warns)

    def test_detects_inverted_ohlc(self):
        df = _make_daily(["2024-01-02"])
        df.loc[df.index[0], "low"] = 200.0
        warns = audit_bars(df, "1d")
        assert any(w.code == "INVERTED_OHLC" for w in warns)

    def test_detects_price_spike(self):
        # Build a 30-bar series with a huge spike at bar 15
        idx = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC", name="timestamp")
        closes = [100.0] * 30
        closes[15] = 200.0   # 100% jump
        df = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1e6},
            index=idx,
        )
        warns = audit_bars(df, "1d")
        assert any(w.code == "PRICE_SPIKE" for w in warns)

    def test_commodity_etf_tolerates_moderate_spike(self):
        """Commodity ETFs (USO, etc.) use 35% spike threshold even on NYSE calendar."""
        idx = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC", name="timestamp")
        closes = [100.0] * 30
        closes[15] = 125.0   # 25% jump — below 35% commodity threshold
        df = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1e6},
            index=idx,
        )
        warns = audit_bars(df, "1d", "nyse", asset_class="commodity")
        assert not any(w.code == "PRICE_SPIKE" for w in warns)

    def test_commodity_etf_flags_large_spike(self):
        idx = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC", name="timestamp")
        closes = [100.0] * 30
        closes[15] = 140.0   # 40% jump — above 35% commodity threshold
        df = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1e6},
            index=idx,
        )
        warns = audit_bars(df, "1d", "nyse", asset_class="commodity")
        assert any(w.code == "PRICE_SPIKE" for w in warns)

    def test_detects_gap(self):
        # Two bars 30 days apart — large gap
        df = _make_daily(["2024-01-02", "2024-02-02"])
        warns = audit_bars(df, "1d", "nyse")
        assert any(w.code == "GAPS" for w in warns)

    def test_detects_stale_close(self):
        # 6 consecutive bars with same close
        idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC", name="timestamp")
        closes = [100.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 102.0, 103.0, 104.0]
        df = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1e6},
            index=idx,
        )
        warns = audit_bars(df, "1d")
        assert any(w.code == "STALE_CLOSE" for w in warns)

    def test_audit_warning_str(self):
        w = AuditWarning("warning", "TEST", "a test warning", affected_rows=3)
        assert "TEST" in str(w)
        assert "3" in str(w)


# ---------------------------------------------------------------------------
# fx_24_5 calendar
# ---------------------------------------------------------------------------

class TestFX24_5Calendar:
    def setup_method(self):
        from cryocore.calendars import get_calendar
        self.cal = get_calendar("fx_24_5")

    def test_monday_is_open(self):
        ts = pd.Timestamp("2024-01-08 12:00:00", tz="UTC")  # Monday
        assert self.cal.is_open(ts) is True

    def test_saturday_is_closed(self):
        ts = pd.Timestamp("2024-01-06 12:00:00", tz="UTC")  # Saturday
        assert self.cal.is_open(ts) is False

    def test_sunday_before_open_closed(self):
        ts = pd.Timestamp("2024-01-07 20:00:00", tz="UTC")  # Sunday 20:00 UTC
        assert self.cal.is_open(ts) is False

    def test_sunday_after_open(self):
        ts = pd.Timestamp("2024-01-07 21:30:00", tz="UTC")  # Sunday 21:30 UTC
        assert self.cal.is_open(ts) is True

    def test_friday_during_session(self):
        ts = pd.Timestamp("2024-01-05 15:00:00", tz="UTC")  # Friday 15:00 UTC
        assert self.cal.is_open(ts) is True

    def test_friday_after_close(self):
        ts = pd.Timestamp("2024-01-05 21:30:00", tz="UTC")  # Friday 21:30 UTC
        assert self.cal.is_open(ts) is False

    def test_fx_eur_alias(self):
        from cryocore.calendars import get_calendar
        cal2 = get_calendar("fx_eur")
        ts = pd.Timestamp("2024-01-08 12:00:00", tz="UTC")
        assert cal2.is_open(ts) == self.cal.is_open(ts)


# ---------------------------------------------------------------------------
# Instrument registry
# ---------------------------------------------------------------------------

class TestInstrumentRegistry:
    def test_yahoo_spy_registered(self):
        from cryocore.instruments import Symbol, get_instrument
        sym = Symbol("yahoo", "SPY")
        instr = get_instrument(sym)
        assert instr is not None
        assert instr.asset_class == "equity"
        assert instr.calendar_id == "nyse"

    def test_fx_eurusd_registered(self):
        from cryocore.instruments import Symbol, get_instrument
        sym = Symbol("yahoo", "EURUSD=X")
        instr = get_instrument(sym)
        assert instr is not None
        assert instr.asset_class == "fx"
        assert instr.calendar_id == "fx_24_5"
        assert instr.meta.get("quote_convention") == "direct"

    def test_fx_jpy_inverted(self):
        from cryocore.instruments import Symbol, get_instrument
        sym = Symbol("yahoo", "JPY=X")
        instr = get_instrument(sym)
        assert instr is not None
        assert instr.meta.get("quote_convention") == "inverted"

    def test_td_ticker_metadata_on_fx(self):
        from cryocore.instruments import Symbol, td_ticker_info
        ticker, invert = td_ticker_info(Symbol("yahoo", "EURUSD=X"))
        assert ticker == "EUR/USD"
        assert invert is False
        ticker2, invert2 = td_ticker_info(Symbol("yahoo", "JPY=X"))
        assert ticker2 == "USD/JPY"
        assert invert2 is True

    def test_cboe_vix_registered(self):
        from cryocore.instruments import Symbol, get_instrument
        sym = Symbol("cboe", "VIX")
        instr = get_instrument(sym)
        assert instr is not None
        assert instr.asset_class == "volatility"
