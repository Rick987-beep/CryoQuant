"""Binance spot klines source.

Public API — no authentication required.

Public interface::

    fetch_klines(symbol, tf, start, end) -> pd.DataFrame   # UTC OHLCV, bar-open indexed
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from cryocore.instruments import Symbol
from cryoquant import config

log = logging.getLogger(__name__)

_LIMIT = 1000  # Binance max bars per request

_TF_MS: dict[str, int] = {
    "1m":  60_000,
    "5m":  300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h":  3_600_000,
    "2h":  7_200_000,
    "4h":  14_400_000,
    "6h":  21_600_000,
    "8h":  28_800_000,
    "12h": 43_200_000,
    "1d":  86_400_000,
    "1w":  604_800_000,
}

_KLINES_ENDPOINT = "/api/v3/klines"


def fetch_klines(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime | None = None,
    *,
    session: requests.Session | None = None,
    sleep_s: float = 0.25,
    max_retries: int = 8,
) -> pd.DataFrame:
    """Fetch closed klines from Binance REST.

    Args:
        symbol: Must be a binance.spot or binance.perp Symbol.
        tf:     Timeframe string (e.g. "1h", "4h", "1d").
        start:  First bar open time (inclusive), tz-aware UTC.
        end:    Last bar open time (exclusive). Defaults to now.

    Returns:
        DataFrame with tz-aware UTC DatetimeIndex named "timestamp" (bar open)
        and float64 columns: open, high, low, close, volume.
        The in-progress bar is dropped — only closed bars are returned.
    """
    if tf not in _TF_MS:
        raise ValueError(f"unsupported tf {tf!r}")
    if symbol.venue not in ("binance.spot", "binance.perp"):
        raise ValueError(f"binance_spot source requires venue binance.spot/binance.perp; got {symbol.venue!r}")

    bar_ms = _TF_MS[tf]
    start_ms = int(start.timestamp() * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000) if end else now_ms

    sess = session or requests.Session()
    base = config.BINANCE_REST_BASE.rstrip("/")
    url = base + _KLINES_ENDPOINT

    rows: list[list] = []
    cursor = start_ms
    n_calls = 0

    while cursor < end_ms:
        params = {
            "symbol":    symbol.ticker,
            "interval":  tf,
            "startTime": cursor,
            "endTime":   end_ms - 1,   # Binance end is inclusive
            "limit":     _LIMIT,
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
                log.warning(
                    "Binance request failed (attempt %d/%d): %s. Sleeping %.1fs",
                    attempt + 1, max_retries, exc, wait,
                )
                time.sleep(wait)

        if chunk is None:
            raise RuntimeError(f"Giving up after {max_retries} retries at cursor {cursor}")

        n_calls += 1
        if not chunk:
            break

        rows.extend(chunk)
        last_open_ms = chunk[-1][0]
        cursor = last_open_ms + bar_ms

        if n_calls % 10 == 0:
            log.info("Binance fetch: %d calls, %d rows", n_calls, len(rows))

        if len(chunk) < _LIMIT:
            break  # caught up

        time.sleep(sleep_s)

    if not rows:
        raise RuntimeError(f"No klines returned for {symbol} {tf} starting {start.isoformat()}")

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time")

    idx = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    out = pd.DataFrame(
        {
            "open":   df["open"].astype(float).values,
            "high":   df["high"].astype(float).values,
            "low":    df["low"].astype(float).values,
            "close":  df["close"].astype(float).values,
            "volume": df["volume"].astype(float).values,
        },
        index=idx,
    )
    out.index.name = "timestamp"

    # Drop the in-progress (not yet closed) bar
    latest_closed_open = now_ms - bar_ms
    out = out[out.index <= pd.Timestamp(latest_closed_open, unit="ms", tz="UTC")]

    return out
