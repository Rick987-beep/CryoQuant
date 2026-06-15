"""CBOE VIX data source — fetches VIX history from CBOE public CSV.

CBOE publishes the full VIX history (daily, from 1990-01-02) as a free CSV:
    https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv

Fallback: FRED VIXCLS series (updated with a 1-day lag; missing some dates).

Public interface::

    fetch_vix(start, end) -> pd.DataFrame   # daily, UTC-indexed, OHLC float64
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import StringIO

import pandas as pd
import requests

log = logging.getLogger(__name__)

_CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
_FRED_VIX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_TIMEOUT = 60


def fetch_vix(
    start: datetime,
    end: datetime | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch CBOE VIX daily history.

    Returns a DataFrame with UTC DatetimeIndex and float64 columns:
        open, high, low, close
    (CBOE publishes OHLC for VIX; volume is not available — omitted.)

    Falls back to FRED VIXCLS (close only) if CBOE CSV is unavailable.
    """
    end_dt = end or datetime.now(timezone.utc)
    sess = session or requests.Session()

    try:
        return _fetch_cboe(start, end_dt, sess)
    except Exception as exc:
        log.warning("CBOE VIX fetch failed; falling back to FRED: %s", exc)
        return _fetch_fred_fallback(start, end_dt, sess)


def _fetch_cboe(start: datetime, end: datetime, sess: requests.Session) -> pd.DataFrame:
    r = sess.get(_CBOE_VIX_URL, timeout=_TIMEOUT)
    r.raise_for_status()

    df = pd.read_csv(StringIO(r.text))
    df.columns = [c.strip().lower() for c in df.columns]

    # CBOE header: DATE, OPEN, HIGH, LOW, CLOSE
    df = df.rename(columns={"date": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()

    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"CBOE VIX CSV missing column {col!r}")

    df = df[["open", "high", "low", "close"]].astype(float)

    start_ts = pd.Timestamp(start).tz_convert("UTC") if start.tzinfo else pd.Timestamp(start, tz="UTC")
    end_ts   = pd.Timestamp(end).tz_convert("UTC")   if end.tzinfo   else pd.Timestamp(end,   tz="UTC")
    df = df.loc[start_ts:end_ts]

    log.info("CBOE VIX: %d daily bars [%s → %s]", len(df),
             df.index.min().date() if not df.empty else "n/a",
             df.index.max().date() if not df.empty else "n/a")
    return df


def _fetch_fred_fallback(start: datetime, end: datetime, sess: requests.Session) -> pd.DataFrame:
    """Return VIX close-only as a DataFrame (open/high/low = NaN)."""
    params = {
        "id": "VIXCLS",
        "vintage_date": end.strftime("%Y-%m-%d"),
    }
    r = sess.get(_FRED_VIX_URL, params=params, timeout=_TIMEOUT)
    r.raise_for_status()

    raw = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
    raw = raw.rename(columns={"DATE": "timestamp", "VIXCLS": "close"})
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    raw = raw.set_index("timestamp").sort_index()
    raw["close"] = pd.to_numeric(raw["close"], errors="coerce")

    # Pad missing OHLC columns
    for col in ("open", "high", "low"):
        raw[col] = float("nan")

    df = raw[["open", "high", "low", "close"]].astype(float)

    start_ts = pd.Timestamp(start).tz_convert("UTC") if start.tzinfo else pd.Timestamp(start, tz="UTC")
    end_ts   = pd.Timestamp(end).tz_convert("UTC")   if end.tzinfo   else pd.Timestamp(end,   tz="UTC")
    df = df.loc[start_ts:end_ts]

    log.info("FRED VIX fallback: %d bars [%s → %s]", len(df),
             df.index.min().date() if not df.empty else "n/a",
             df.index.max().date() if not df.empty else "n/a")
    return df
