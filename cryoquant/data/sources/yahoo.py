"""Yahoo Finance OHLCV source via yfinance.

Public interface::

    fetch_bars(symbol, tf, start, end) -> pd.DataFrame   # UTC bar-open, OHLCV float64

Normalisation applied here (raw → canonical schema):
  - Flatten MultiIndex columns produced by yf.download for a single ticker
  - Lowercase column names
  - DatetimeIndex named "timestamp", UTC tz-aware, bar-open convention
  - float64 OHLCV
  - Drop the in-progress (not yet closed) bar
  - FX inverted pairs (JPY=X, CAD=X): prices left as-is; cleaning.py flips sign convention

Supported tf strings: 1m 5m 15m 30m 1h 2h 4h 1d 1wk
Note: yfinance hard limits — 1h bars go back ~730 days; sub-hourly ~60 days.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd

from cryocore.instruments import Symbol
from cryocore.time import tf_to_seconds, floor_to_tf

log = logging.getLogger(__name__)

# yfinance interval strings
_TF_TO_YF: dict[str, str] = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "2h":  "2h",
    "4h":  "4h",
    "1d":  "1d",
    "1wk": "1wk",
}

# Yahoo Finance hard limits on historical depth for intraday intervals
# (days of history available from today).  Requests starting beyond these
# limits will be silently empty.
_MAX_HISTORY_DAYS: dict[str, int] = {
    "1m":  7,
    "5m":  60,
    "15m": 60,
    "30m": 60,
    "1h":  729,   # ~730 days; use 729 to stay safely inside
    "2h":  729,
    "4h":  729,
}

_MAX_RETRIES = 4


def fetch_bars(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime | None = None,
    *,
    auto_adjust: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV bars from Yahoo Finance.

    Args:
        symbol:       Must be a ``yahoo`` venue Symbol; ticker is the yfinance ticker.
        tf:           Timeframe string (e.g. "1h", "1d").
        start:        First bar open (inclusive), tz-aware UTC.
        end:          Last bar open (exclusive). Defaults to now.
        auto_adjust:  Apply split/dividend adjustment (True for equities/ETFs; False for FX).

    Returns:
        DataFrame with UTC bar-open DatetimeIndex "timestamp" and
        float64 columns: open, high, low, close, volume.
        The in-progress bar is dropped.
    """
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:
        raise ImportError("yfinance is required: pip install yfinance") from exc

    if symbol.venue != "yahoo":
        raise ValueError(f"yahoo source requires venue 'yahoo'; got {symbol.venue!r}")
    if tf not in _TF_TO_YF:
        raise ValueError(f"unsupported tf {tf!r}; supported: {sorted(_TF_TO_YF)}")

    yf_interval = _TF_TO_YF[tf]
    end_dt = end or datetime.now(timezone.utc)
    ticker = symbol.ticker

    # Clamp start to within Yahoo's historical limit for intraday data
    if tf in _MAX_HISTORY_DAYS:
        earliest_allowed = datetime.now(timezone.utc) - pd.Timedelta(days=_MAX_HISTORY_DAYS[tf])
        earliest_allowed = earliest_allowed.replace(tzinfo=timezone.utc)
        if start < earliest_allowed:
            log.info(
                "Yahoo 1h/intraday limit: clamping start %s → %s for %s",
                start.date(), earliest_allowed.date(), ticker,
            )
            start = earliest_allowed

    df = None
    for attempt in range(_MAX_RETRIES):
        try:
            raw = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end_dt.strftime("%Y-%m-%d"),
                interval=yf_interval,
                auto_adjust=auto_adjust,
                progress=False,
                repair=True,
                multi_level_index=False,
            )
            if raw is not None and not raw.empty:
                df = raw
                break
        except Exception as exc:
            wait = min(30.0, 2 ** attempt)
            log.warning(
                "yfinance download failed for %s (attempt %d/%d): %s — sleeping %.1fs",
                ticker, attempt + 1, _MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)

    if df is None or df.empty:
        # Return empty DataFrame with correct schema rather than raising.
        # Callers (e.g. loader) treat empty returns as "no data for this range"
        # (common for pre-inception dates).
        log.info("Yahoo: no data for %s %s [%s → %s] — returning empty",
                 ticker, tf, start.date(), end_dt.date())
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        empty.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
        return empty

    df = _normalise(df, tf)

    # Drop in-progress bar
    bar_secs = tf_to_seconds(tf) if tf != "1wk" else 604_800
    cutoff = pd.Timestamp(datetime.now(timezone.utc)) - pd.Timedelta(seconds=bar_secs)
    df = df[df.index <= cutoff]

    log.info("Yahoo fetch: %s %s → %d bars [%s → %s]",
             ticker, tf, len(df),
             df.index.min().date() if not df.empty else "n/a",
             df.index.max().date() if not df.empty else "n/a")
    return df


def _normalise(raw: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Convert raw yfinance output to canonical OHLCV schema."""
    df = raw.copy()

    # Flatten MultiIndex if present (yfinance sometimes returns one)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(str(c) for c in col).strip() for col in df.columns]

    # Lowercase column names; handle yfinance capitalised variants
    df.columns = [c.lower() for c in df.columns]

    # yfinance may return "adj close" instead of "close" when auto_adjust=False
    if "adj close" in df.columns and "close" not in df.columns:
        df = df.rename(columns={"adj close": "close"})

    # Keep only canonical columns; add volume=0 if missing (index symbols have none)
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"yfinance response missing required column {col!r}")
    if "volume" not in df.columns:
        df["volume"] = 0.0

    df = df[["open", "high", "low", "close", "volume"]].astype(float)

    # Ensure UTC tz-aware DatetimeIndex
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    df.index = idx
    df.index.name = "timestamp"

    # Floor to bar-open boundary (yfinance occasionally returns slightly off timestamps)
    if tf not in ("1d", "1wk"):
        try:
            df.index = pd.DatetimeIndex(
                [floor_to_tf(ts, tf) for ts in df.index], name="timestamp"
            )
        except Exception:
            pass  # non-standard tf (e.g. "1wk") — leave as-is

    df = df.sort_index()
    return df
