"""Twelve Data OHLCV source (free tier).

Rate limits (free): 8 requests/minute, 800 requests/day.
Historical depth: ETFs from ~2020-02-10, FX from ~2020-01-30 (vs yfinance ~730 days).

Public interface::

    fetch_bars(symbol, tf, start, end) -> pd.DataFrame   # UTC bar-open, OHLCV float64
    td_ticker(yahoo_ticker) -> str                        # convert yahoo ticker to TD ticker

Symbol mapping (yahoo venue → Twelve Data):
  - Equity/ETF tickers (SPY, GLD, …): same ticker, no transformation.
  - Direct FX (EURUSD=X → EUR/USD, GBPUSD=X → GBP/USD, AUDUSD=X → AUD/USD):
    same quote convention; just reformat.
  - Inverted FX (JPY=X → USD/JPY, CAD=X → USD/CAD):
    Yahoo returns USD per unit of foreign (~0.0064 for JPY=X); TD returns the standard
    market quote (USD/JPY ~156). We invert the OHLC prices after fetching so the stored
    values match the Yahoo convention that downstream code already expects.

Pagination:
    TD returns at most 5 000 bars per request. For full history (2020 → present) we
    paginate backward from *end* to *start*: each page's end_date is set to just before
    the earliest bar returned by the previous page.  This minimises requests.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from cryocore.instruments import Symbol
from cryocore.time import floor_to_tf, tf_to_seconds
from cryoquant import config

log = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com"
_PAGE_SIZE = 5000          # TD free tier maximum bars per request
_REQUEST_GAP = 7.6         # seconds between calls (8 req/min = 7.5 s; add buffer)
_TIMEOUT = 30              # HTTP timeout per call

# ---------------------------------------------------------------------------
# Interval mapping (CryoQuant tf → Twelve Data interval string)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Yahoo ticker → Twelve Data ticker
# (ticker, needs_inversion)
# "needs_inversion": TD returns standard market quote (JPY/USD = 156); Yahoo
# stores the reciprocal (USD/JPY = 0.0064). We invert OHLC after fetching.
# ---------------------------------------------------------------------------

_YAHOO_TO_TD: dict[str, tuple[str, bool]] = {
    # Direct FX (same quote convention — just strip the =X suffix and add /)
    "EURUSD=X": ("EUR/USD", False),
    "GBPUSD=X": ("GBP/USD", False),
    "AUDUSD=X": ("AUD/USD", False),
    "NZDUSD=X": ("NZD/USD", False),
    # Inverted FX (Yahoo: USD per foreign unit; TD: foreign per USD → invert)
    "JPY=X":    ("USD/JPY", True),
    "CAD=X":    ("USD/CAD", True),
    "CHF=X":    ("USD/CHF", True),
}


def td_ticker(yahoo_ticker: str) -> tuple[str, bool]:
    """Return (twelvedata_ticker, needs_inversion) for a Yahoo ticker.

    For tickers not in the explicit mapping, the Yahoo ticker is used as-is
    (works for US stocks and ETFs).
    """
    if yahoo_ticker in _YAHOO_TO_TD:
        return _YAHOO_TO_TD[yahoo_ticker]
    # ETFs / stocks: same ticker; no inversion needed
    return yahoo_ticker, False


# ---------------------------------------------------------------------------
# Rate limiter — module-level state
# ---------------------------------------------------------------------------

_last_request_at: float = 0.0


def _rate_limit() -> None:
    """Block until the minimum inter-request gap has elapsed."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _REQUEST_GAP:
        sleep_for = _REQUEST_GAP - elapsed
        log.debug("TD rate limit: sleeping %.2fs", sleep_for)
        time.sleep(sleep_for)
    _last_request_at = time.monotonic()


# ---------------------------------------------------------------------------
# Core fetcher
# ---------------------------------------------------------------------------

def fetch_bars(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV bars from Twelve Data.

    Paginates backward from *end* → *start* so that the first request captures
    the most recent data (useful for incremental updates).

    Args:
        symbol: Must have venue ``"yahoo"``; the ticker is translated to a TD symbol.
        tf:     Timeframe string (e.g. ``"1h"``, ``"1d"``).
        start:  First bar open (inclusive), tz-aware UTC.
        end:    Last bar open (exclusive). Defaults to now.

    Returns:
        DataFrame with UTC DatetimeIndex ``"timestamp"`` and float64 columns
        ``open``, ``high``, ``low``, ``close``, ``volume``.
        Empty DataFrame (correct schema) when no data is available.
    """
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

    td_sym, invert = td_ticker(symbol.ticker)
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

    while True:
        params = {
            "symbol":     td_sym,
            "interval":   td_interval,
            "outputsize": _PAGE_SIZE,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date":   page_end.strftime("%Y-%m-%d %H:%M:%S"),
            "apikey":     api_key,
            "format":     "JSON",
        }

        _rate_limit()

        try:
            resp = requests.get(
                f"{_BASE_URL}/time_series", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("TD HTTP error for %s %s: %s", td_sym, tf, exc)
            break

        data = resp.json()

        if data.get("status") == "error":
            log.warning(
                "TD API error for %s %s: %s", td_sym, tf,
                data.get("message", data)
            )
            break

        values = data.get("values", [])
        if not values:
            break

        page_df = _parse_values(values, invert)
        pages.append(page_df)

        earliest_in_page = page_df.index.min()
        log.debug(
            "  TD page: %d bars [%s → %s] for %s",
            len(page_df), earliest_in_page.date(), page_df.index.max().date(), td_sym,
        )

        # Stop conditions
        if len(values) < _PAGE_SIZE:
            # Fewer bars than page size → reached the beginning of available data
            break
        ts_start = pd.Timestamp(start)
        if ts_start.tzinfo is None:
            ts_start = ts_start.tz_localize("UTC")
        if earliest_in_page <= ts_start:
            break

        # Advance page_end to just before the earliest bar of this page
        bar_secs = tf_to_seconds(tf) if tf != "1wk" else 604_800
        page_end = (earliest_in_page - pd.Timedelta(seconds=bar_secs)).to_pydatetime()

    if not pages:
        log.info("TwelveData: no data for %s %s [%s → %s]",
                 td_sym, tf, start.date(), end_dt.date())
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        empty.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
        return empty

    df = pd.concat(pages)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    # Clip to requested range
    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end_dt)
    df = df.loc[ts_start:ts_end]

    # Drop in-progress bar
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


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_values(values: list[dict], invert: bool) -> pd.DataFrame:
    """Convert the ``values`` list from a TD response to a canonical DataFrame.

    ``values`` is sorted newest-first by TD; we reverse to get oldest-first.
    If ``invert`` is True, OHLC prices are reciprocated to match Yahoo's inverted
    FX quote convention (e.g. JPY=X stores USD per JPY, not JPY per USD).
    """
    records = []
    for v in reversed(values):          # TD returns newest-first
        ts = pd.Timestamp(v["datetime"]).tz_localize("UTC")
        records.append({
            "timestamp": ts,
            "open":   float(v["open"]),
            "high":   float(v["high"]),
            "low":    float(v["low"]),
            "close":  float(v["close"]),
            "volume": float(v.get("volume", 0) or 0),
        })

    df = pd.DataFrame(records).set_index("timestamp")
    df = df.astype({"open": "float64", "high": "float64",
                    "low": "float64", "close": "float64", "volume": "float64"})

    if invert:
        # Reciprocate to match Yahoo's inverted convention:
        # Yahoo JPY=X ≈ 0.0064  (USD per JPY)  ←→  TD USD/JPY ≈ 156 (JPY per USD)
        # Reciprocal flips direction: new_high = 1/old_low, new_low = 1/old_high
        df["open"]  = 1.0 / df["open"]
        df["close"] = 1.0 / df["close"]
        old_high = df["high"].copy()
        df["high"] = 1.0 / df["low"]
        df["low"]  = 1.0 / old_high

    # Floor timestamps to bar-open boundary (TD sometimes drifts slightly)
    try:
        df.index = pd.DatetimeIndex(
            [floor_to_tf(ts, "1h") for ts in df.index], name="timestamp"
        )
    except Exception:
        pass

    return df
