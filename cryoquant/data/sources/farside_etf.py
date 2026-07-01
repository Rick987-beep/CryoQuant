"""Farside Investors — US spot Bitcoin ETF daily flows (US$m).

Canonical public table: https://farside.co.uk/bitcoin-etf-flow-all-data/
Optional fallback: Parse.bot Farside wrapper (PARSE_API_KEY) when Cloudflare blocks scrape.

Public interface::

    fetch_aggregate_flows(start, end, *, session) -> pd.DataFrame
    fetch_ticker_flows(start, end, tickers, *, session) -> pd.DataFrame
    fetch_all_ticker_flows(start, end, *, session) -> pd.DataFrame

Frames include ``value`` (USD) and ``available_utc`` (ETF flow publication lag).
Persist via ``macro_store.write_frame("farside", series_id, df)``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from cryoquant import config
from cryoquant.data.sources.sosovalue import etf_available_utc

log = logging.getLogger(__name__)

_FARSIDE_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
_PARSE_ALL_URL = (
    "https://api.parse.bot/scraper/942741c9-1857-4cca-89fd-31c80c2c6ea4/get_bitcoin_etf_flows_all"
)
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_DATE_FMT = "%d %b %Y"
_MILLIONS_TO_USD = 1_000_000.0
_avail_cache: dict[date, datetime] = {}


def _available_for(trade_date: date) -> datetime:
    if trade_date not in _avail_cache:
        _avail_cache[trade_date] = etf_available_utc(trade_date)
    return _avail_cache[trade_date]


def _parse_flow_value(raw: str) -> float:
    text = raw.strip().replace(",", "")
    if not text or text in {"-", "—"}:
        return float("nan")
    neg = text.startswith("(") and text.endswith(")")
    if neg:
        text = text[1:-1]
    val = float(text)
    return -val if neg else val


def _rows_from_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="etf")
    if table is None:
        raise ValueError("Farside ETF table not found in HTML (Cloudflare block?)")

    header_cells = table.find("thead").find_all("th")
    tickers = [c.get_text(strip=True) for c in header_cells[1:]]
    rows: list[dict[str, Any]] = []

    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        date_str = cells[0].get_text(strip=True)
        if not date_str or date_str.lower() == "total":
            continue
        try:
            trade_date = datetime.strptime(date_str, _DATE_FMT).date()
        except ValueError:
            log.debug("Skipping unparseable Farside date %r", date_str)
            continue

        rec: dict[str, Any] = {"trade_date": trade_date}
        for ticker, cell in zip(tickers, cells[1:], strict=False):
            rec[ticker] = _parse_flow_value(cell.get_text(strip=True))
        rows.append(rec)

    if not rows:
        raise ValueError("Farside ETF table parsed zero data rows")
    return rows


def _rows_from_parse_payload(payload: dict) -> list[dict[str, Any]]:
    data_block = payload.get("data") or {}
    if isinstance(data_block, dict) and "data" in data_block:
        data_block = data_block["data"]
    if isinstance(data_block, dict) and "data" in data_block:
        items = data_block["data"]
    elif isinstance(data_block, list):
        items = data_block
    else:
        raise ValueError(f"Unexpected Parse.bot payload shape: {list(payload.keys())}")

    rows: list[dict[str, Any]] = []
    for item in items:
        date_str = item.get("Date") or item.get("date")
        if not date_str:
            continue
        trade_date = datetime.strptime(str(date_str).strip(), _DATE_FMT).date()
        rec: dict[str, Any] = {"trade_date": trade_date}
        for key, val in item.items():
            if key in {"Date", "date"}:
                continue
            if val is None or val == "-":
                rec[key] = float("nan")
            else:
                rec[key] = float(val)
        rows.append(rec)
    return rows


_rows_cache: list[dict[str, Any]] | None = None


def fetch_raw_rows(*, session: requests.Session | None = None, use_cache: bool = True) -> list[dict[str, Any]]:
    """Fetch full Farside BTC ETF flow table (direct scrape, Parse.bot fallback)."""
    global _rows_cache
    if use_cache and _rows_cache is not None:
        return _rows_cache

    sess = session or requests.Session()

    r = sess.get(_FARSIDE_URL, headers=_DEFAULT_HEADERS, timeout=90)
    if r.status_code == 200 and "table class=\"etf\"" in r.text:
        try:
            rows = _rows_from_html(r.text)
            log.info("Farside: scraped %d rows from HTML", len(rows))
            if use_cache:
                _rows_cache = rows
            return rows
        except ValueError as exc:
            log.warning("Farside HTML parse failed: %s", exc)

    if config.PARSE_API_KEY:
        log.info("Farside: falling back to Parse.bot API")
        pr = sess.get(
            _PARSE_ALL_URL,
            headers={"X-API-Key": config.PARSE_API_KEY, "Accept": "application/json"},
            timeout=120,
        )
        pr.raise_for_status()
        rows = _rows_from_parse_payload(pr.json())
        log.info("Farside: Parse.bot returned %d rows", len(rows))
        if use_cache:
            _rows_cache = rows
        return rows

    raise RuntimeError(
        "Farside scrape blocked and PARSE_API_KEY not set — cannot fetch ETF history"
    )


def clear_rows_cache() -> None:
    """Drop cached scrape (for tests)."""
    global _rows_cache
    _rows_cache = None


def _filter_rows(rows: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [r for r in rows if start <= r["trade_date"] <= end]


def fetch_all_ticker_flows(
    tickers: list[str],
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> dict[str, pd.DataFrame]:
    """Per-ticker flows from a single Farside scrape."""
    end_d = end or date.today()
    rows = _filter_rows(fetch_raw_rows(session=session), start, end_d)
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        ticker = ticker.upper()
        series_rows: list[dict] = []
        for rec in rows:
            if ticker not in rec:
                continue
            flow = rec[ticker]
            if flow is None or (isinstance(flow, float) and pd.isna(flow)):
                continue
            trade_date = rec["trade_date"]
            series_rows.append(
                {
                    "trade_date": trade_date,
                    "value": float(flow) * _MILLIONS_TO_USD,
                    "available_utc": _available_for(trade_date),
                }
            )
        out[ticker] = _rows_to_frame(series_rows)
    return out


def fetch_aggregate_flows(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Daily aggregate US spot BTC ETF net flow (USD, not millions)."""
    end_d = end or date.today()
    rows = _filter_rows(fetch_raw_rows(session=session), start, end_d)
    out: list[dict] = []
    for rec in rows:
        total = rec.get("Total")
        if total is None or (isinstance(total, float) and pd.isna(total)):
            continue
        trade_date = rec["trade_date"]
        out.append(
            {
                "trade_date": trade_date,
                "value": float(total) * _MILLIONS_TO_USD,
                "available_utc": _available_for(trade_date),
            }
        )
    return _rows_to_frame(out)


def fetch_ticker_flows(
    ticker: str,
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Per-ticker daily net flow (USD)."""
    end_d = end or date.today()
    ticker = ticker.upper()
    rows = _filter_rows(fetch_raw_rows(session=session), start, end_d)
    out: list[dict] = []
    for rec in rows:
        if ticker not in rec:
            continue
        flow = rec[ticker]
        if flow is None or (isinstance(flow, float) and pd.isna(flow)):
            continue
        trade_date = rec["trade_date"]
        out.append(
            {
                "trade_date": trade_date,
                "value": float(flow) * _MILLIONS_TO_USD,
                "available_utc": _available_for(trade_date),
            }
        )
    return _rows_to_frame(out)


def _rows_to_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["value", "available_utc"])

    df = (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["trade_date"], keep="last")
        .set_index("trade_date")
        .sort_index()
    )
    df.index = pd.DatetimeIndex(df.index, tz="UTC")
    df.index.name = "timestamp"
    return df
