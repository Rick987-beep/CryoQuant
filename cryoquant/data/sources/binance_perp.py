"""Binance perpetual futures source: klines and funding rate.

Public API — no authentication required.

Public interface::

    fetch_klines(symbol, tf, start, end)   -> pd.DataFrame   # same shape as binance_spot
    fetch_funding(symbol, start, end)      -> pd.DataFrame   # funding rate time series
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from cryocore.instruments import Symbol
from cryoquant import config
from cryoquant.data.sources.binance_spot import fetch_klines as _spot_klines

log = logging.getLogger(__name__)

_FUNDING_ENDPOINT = "/fapi/v1/fundingRate"
_FUNDING_LIMIT = 1000


def fetch_klines(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Fetch perpetual futures klines. Same signature and return shape as binance_spot."""
    if symbol.venue != "binance.perp":
        raise ValueError(f"binance_perp source requires venue binance.perp; got {symbol.venue!r}")
    # Perp klines use the futures base URL
    import cryoquant.config as cfg
    orig = cfg.BINANCE_REST_BASE
    cfg.BINANCE_REST_BASE = "https://fapi.binance.com"
    try:
        return _spot_klines(symbol, tf, start, end, **kwargs)
    finally:
        cfg.BINANCE_REST_BASE = orig


def fetch_funding(
    symbol: Symbol,
    start: datetime,
    end: datetime | None = None,
    *,
    session: requests.Session | None = None,
    max_retries: int = 8,
) -> pd.DataFrame:
    """Fetch perpetual funding rate history.

    Returns:
        DataFrame indexed by tz-aware UTC timestamp with column "funding_rate" (float).
    """
    if symbol.venue != "binance.perp":
        raise ValueError(f"binance_perp source requires venue binance.perp; got {symbol.venue!r}")

    start_ms = int(start.timestamp() * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000) if end else now_ms

    sess = session or requests.Session()
    url = f"https://fapi.binance.com{_FUNDING_ENDPOINT}"

    rows: list[dict] = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol":    symbol.ticker,
            "startTime": cursor,
            "endTime":   end_ms,
            "limit":     _FUNDING_LIMIT,
        }
        chunk = None
        for attempt in range(max_retries):
            try:
                r = sess.get(url, params=params, timeout=30)
                r.raise_for_status()
                chunk = r.json()
                break
            except (requests.exceptions.RequestException, ValueError) as exc:
                wait = min(60.0, 2 ** attempt)
                log.warning("Funding request failed (attempt %d/%d): %s", attempt + 1, max_retries, exc)
                time.sleep(wait)

        if chunk is None:
            raise RuntimeError(f"Giving up after {max_retries} retries fetching funding at cursor {cursor}")
        if not chunk:
            break

        rows.extend(chunk)
        last_ts = int(chunk[-1]["fundingTime"])
        cursor = last_ts + 1

        if len(chunk) < _FUNDING_LIMIT:
            break

    if not rows:
        return pd.DataFrame(
            {"funding_rate": pd.Series(dtype=float)},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    idx = pd.to_datetime([r["fundingTime"] for r in rows], unit="ms", utc=True)
    rates = [float(r["fundingRate"]) for r in rows]
    out = pd.DataFrame({"funding_rate": rates}, index=idx)
    out.index.name = "timestamp"
    return out.sort_index().loc[~out.index.duplicated(keep="last")]


_OI_ENDPOINT = "/futures/data/openInterestHist"
_OI_PERIOD = "1d"
_OI_LIMIT = 500
_OI_MAX_HISTORY_DAYS = 30  # Binance API rolling window


def fetch_open_interest(
    symbol: Symbol,
    start: datetime,
    end: datetime | None = None,
    *,
    session: requests.Session | None = None,
    max_retries: int = 4,
) -> pd.DataFrame:
    """Fetch perpetual open-interest history (Binance rolling window, ~30 days max).

    Requests older than ~30 days are clamped — Binance returns HTTP 400 otherwise.

    Returns:
        DataFrame indexed by tz-aware UTC timestamp with column ``open_interest`` (float).
    """
    if symbol.venue != "binance.perp":
        raise ValueError(f"binance_perp source requires venue binance.perp; got {symbol.venue!r}")

    end_dt = end or datetime.now(timezone.utc)
    window_start = end_dt - timedelta(days=_OI_MAX_HISTORY_DAYS)
    effective_start = max(start, window_start)
    if effective_start > start:
        log.info(
            "OI %s: clamping start %s → %s (Binance ~%dd window)",
            symbol.ticker, start.date(), effective_start.date(), _OI_MAX_HISTORY_DAYS,
        )

    start_ms = int(effective_start.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    sess = session or requests.Session()
    url = f"https://fapi.binance.com{_OI_ENDPOINT}"

    rows: list[dict] = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol.ticker,
            "period": _OI_PERIOD,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": _OI_LIMIT,
        }
        chunk = None
        for attempt in range(max_retries):
            try:
                r = sess.get(url, params=params, timeout=30)
                if r.status_code == 400:
                    log.warning("OI 400 for %s at cursor %s — stopping", symbol.ticker, cursor)
                    chunk = []
                    break
                r.raise_for_status()
                chunk = r.json()
                break
            except (requests.exceptions.RequestException, ValueError) as exc:
                wait = min(30.0, 2 ** attempt)
                log.warning("OI request failed (attempt %d/%d): %s", attempt + 1, max_retries, exc)
                time.sleep(wait)

        if chunk is None:
            raise RuntimeError(f"Giving up after {max_retries} retries fetching OI at cursor {cursor}")
        if not chunk:
            break

        rows.extend(chunk)
        last_ts = int(chunk[-1]["timestamp"])
        cursor = last_ts + 1

        if len(chunk) < _OI_LIMIT:
            break

    if not rows:
        return pd.DataFrame(
            {"open_interest": pd.Series(dtype=float)},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    idx = pd.to_datetime([r["timestamp"] for r in rows], unit="ms", utc=True)
    oi = [float(r["sumOpenInterest"]) for r in rows]
    out = pd.DataFrame({"open_interest": oi}, index=idx)
    out.index.name = "timestamp"
    return out.sort_index().loc[~out.index.duplicated(keep="last")]


def funding_to_daily(funding: pd.DataFrame) -> pd.Series:
    """Aggregate 8h funding rates to UTC daily (last observation per calendar day)."""
    if funding.empty:
        return pd.Series(dtype=float, name="funding_rate")
    s = funding["funding_rate"].sort_index()
    daily = s.groupby(s.index.floor("D")).last()
    daily.index = pd.DatetimeIndex(daily.index, tz="UTC")
    daily.name = "funding_rate"
    return daily
