"""Twelve Data OHLCV source (free tier).

Rate limits (free): 8 requests/minute, 800 requests/day.
Historical depth: ETFs from ~2020-02-10, FX from ~2020-01-30 (vs yfinance ~730 days).

Public interface::

    fetch_bars(symbol, tf, start, end) -> pd.DataFrame   # UTC bar-open, OHLCV float64

Ticker mapping and inversion flags live in ``Instrument.meta`` (see
``cryocore.instruments.td_ticker_info``).  Pagination fetches backward from
*end* → *start* in pages of 5 000 bars.

Timezone: all API requests pass ``timezone=UTC`` so bar opens are true UTC
(US equities would otherwise arrive in exchange-local wall clock).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from cryocore.instruments import Symbol, td_ticker_info
from cryocore.time import floor_to_tf, tf_to_seconds
from cryoquant import config

log = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com"
_PAGE_SIZE = 5000
_REQUEST_GAP = 7.6
_TIMEOUT = 30

_TF_TO_TD: dict[str, str] = {
    "1m":  "1min",
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "1h":  "1h",
    "2h":  "2h",
    "4h":  "4h",
    "1d":  "1day",
    "1wk": "1week",
}


class _RateLimiter:
    """Simple inter-request gap limiter (Twelve Data free tier: 8 req/min)."""

    def __init__(self, gap_s: float) -> None:
        self.gap_s = gap_s
        self._last_at = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_at
        if elapsed < self.gap_s:
            sleep_for = self.gap_s - elapsed
            log.debug("TD rate limit: sleeping %.2fs", sleep_for)
            time.sleep(sleep_for)
        self._last_at = time.monotonic()

    def reset(self) -> None:
        """Reset state — for tests only."""
        self._last_at = 0.0


_rate_limiter = _RateLimiter(_REQUEST_GAP)


def _empty_ohlcv() -> pd.DataFrame:
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    empty.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return empty


def fetch_bars(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV bars from Twelve Data with backward pagination."""
    api_key = config.TWELVEDATA_API_KEY
    if not api_key:
        raise RuntimeError(
            "TWELVEDATA_API_KEY is not set. Add it to .env or export it as an env var."
        )

    if symbol.venue != "yahoo":
        raise ValueError(
            f"twelvedata source only handles yahoo-venue symbols; got {symbol.venue!r}"
        )

    if tf not in _TF_TO_TD:
        raise ValueError(f"unsupported tf {tf!r}; supported: {sorted(_TF_TO_TD)}")

    td_sym, invert = td_ticker_info(symbol)
    td_interval = _TF_TO_TD[tf]
    end_dt = end or datetime.now(timezone.utc)

    log.info(
        "TwelveData fetch: %s (%s) %s  [%s → %s]%s",
        symbol.ticker, td_sym, tf,
        start.date(), end_dt.date(),
        "  [INVERT]" if invert else "",
    )

    pages: list[pd.DataFrame] = []
    page_end = end_dt
    ts_start = pd.Timestamp(start)
    if ts_start.tzinfo is None:
        ts_start = ts_start.tz_localize("UTC")

    while True:
        params = {
            "symbol":     td_sym,
            "interval":   td_interval,
            "outputsize": _PAGE_SIZE,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date":   page_end.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone":   "UTC",
            "apikey":     api_key,
            "format":     "JSON",
        }

        _rate_limiter.wait()

        try:
            resp = requests.get(
                f"{_BASE_URL}/time_series", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Twelve Data HTTP error for {td_sym} {tf}: {exc}"
            ) from exc

        data = resp.json()

        if data.get("status") == "error":
            msg = data.get("message", data)
            raise RuntimeError(f"Twelve Data API error for {td_sym} {tf}: {msg}")

        values = data.get("values", [])
        if not values:
            break

        page_df = _parse_values(values, tf, invert)
        pages.append(page_df)

        earliest_in_page = page_df.index.min()
        log.debug(
            "  TD page: %d bars [%s → %s] for %s",
            len(page_df), earliest_in_page.date(), page_df.index.max().date(), td_sym,
        )

        if len(values) < _PAGE_SIZE:
            break
        if earliest_in_page <= ts_start:
            break

        bar_secs = tf_to_seconds(tf) if tf != "1wk" else 604_800
        page_end = (earliest_in_page - pd.Timedelta(seconds=bar_secs)).to_pydatetime()

    if not pages:
        log.info(
            "TwelveData: no data for %s %s [%s → %s]",
            td_sym, tf, start.date(), end_dt.date(),
        )
        return _empty_ohlcv()

    df = pd.concat(pages)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.loc[ts_start:pd.Timestamp(end_dt)]

    bar_secs = tf_to_seconds(tf) if tf != "1wk" else 604_800
    cutoff = pd.Timestamp(datetime.now(timezone.utc)) - pd.Timedelta(seconds=bar_secs)
    df = df[df.index <= cutoff]

    log.info(
        "TwelveData: %s %s → %d bars [%s → %s]",
        td_sym, tf, len(df),
        df.index.min().date() if not df.empty else "n/a",
        df.index.max().date() if not df.empty else "n/a",
    )
    return df


def _utc_timestamp(dt_str: str, source_tz: str | None = None) -> pd.Timestamp:
    """Parse a TD ``datetime`` string into a UTC bar-open timestamp.

    When ``timezone=UTC`` is set on the API request, *source_tz* is omitted and
    the string is already UTC.  For defence-in-depth (or tests), pass
    ``source_tz='America/New_York'`` to convert exchange-local datetimes.
    """
    ts = pd.Timestamp(dt_str)
    if ts.tzinfo is not None:
        return ts.tz_convert("UTC")
    if source_tz and source_tz not in ("UTC", "Exchange"):
        return ts.tz_localize(source_tz).tz_convert("UTC")
    return ts.tz_localize("UTC")


def _parse_values(
    values: list[dict],
    tf: str,
    invert: bool,
    *,
    source_tz: str | None = None,
) -> pd.DataFrame:
    """Convert TD ``values`` (newest-first) to canonical OHLCV DataFrame."""
    records = []
    for v in reversed(values):
        ts = _utc_timestamp(v["datetime"], source_tz)
        records.append({
            "timestamp": ts,
            "open":   float(v["open"]),
            "high":   float(v["high"]),
            "low":    float(v["low"]),
            "close":  float(v["close"]),
            "volume": float(v.get("volume", 0) or 0),
        })

    df = pd.DataFrame(records).set_index("timestamp")
    df = df.astype({
        "open": "float64", "high": "float64",
        "low": "float64", "close": "float64", "volume": "float64",
    })

    if invert:
        # Match Yahoo's inverted FX convention (USD per unit of foreign).
        df["open"] = 1.0 / df["open"]
        df["close"] = 1.0 / df["close"]
        old_high = df["high"].copy()
        df["high"] = 1.0 / df["low"]
        df["low"] = 1.0 / old_high

    if tf not in ("1d", "1wk"):
        df.index = pd.DatetimeIndex(
            [floor_to_tf(ts, tf) for ts in df.index], name="timestamp"
        )

    return df
