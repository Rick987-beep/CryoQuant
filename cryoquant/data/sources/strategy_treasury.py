"""Strategy Inc (MSTR) BTC treasury — official purchase disclosures.

Source: https://www.strategy.com/purchases (__NEXT_DATA__ JSON).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests

from cryoquant.data.sources.sosovalue import mstr_available_utc

log = logging.getLogger(__name__)

_mstr_avail_cache: dict[date, datetime] = {}


def _mstr_available(event_date: date) -> datetime:
    if event_date not in _mstr_avail_cache:
        _mstr_avail_cache[event_date] = mstr_available_utc(event_date)
    return _mstr_avail_cache[event_date]

_PURCHASES_URL = "https://www.strategy.com/purchases"
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _fetch_bitcoin_data(*, session: requests.Session) -> list[dict[str, Any]]:
    r = session.get(_PURCHASES_URL, headers=_DEFAULT_HEADERS, timeout=90)
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, re.S)
    if not m:
        raise ValueError("Strategy.com __NEXT_DATA__ not found")
    payload = json.loads(m.group(1))
    data = payload.get("props", {}).get("pageProps", {}).get("bitcoinData")
    if not data:
        raise ValueError("Strategy.com bitcoinData missing from page")
    return sorted(data, key=lambda x: x["date_of_purchase"])


def _acq_cost_usd(item: dict[str, Any]) -> float:
    raw = item.get("total_purchase_price")
    if raw is None:
        raw = item.get("total_acquisition_cost")
    if raw is None:
        return float("nan")
    val = float(raw)
    # total_purchase_price is USD; total_acquisition_cost on recent rows is USD thousands in UI
    if item.get("total_purchase_price") is None and val < 1_000_000:
        return val * 1_000.0
    return val


def fetch_mstr_purchases(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """MSTR BTC acquisition events (sparse). btc_acq = holdings delta."""
    sess = session or requests.Session()
    end_d = end or date.today()
    events = _fetch_bitcoin_data(session=sess)

    prev_holdings = 0.0
    rows: list[dict] = []
    for item in events:
        event_date = date.fromisoformat(str(item["date_of_purchase"])[:10])
        holdings = float(item.get("btc_holdings") or 0.0)
        if event_date < start:
            prev_holdings = holdings
            continue
        if event_date > end_d:
            break
        btc_acq = holdings - prev_holdings
        prev_holdings = holdings
        rows.append(
            {
                "event_date": event_date,
                "btc_acq": btc_acq,
                "acq_cost": _acq_cost_usd(item),
                "avg_price": float(item.get("purchase_price") or float("nan")),
                "available_utc": _mstr_available(event_date),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["btc_acq", "acq_cost", "avg_price", "available_utc"])

    df = pd.DataFrame(rows).set_index("event_date").sort_index()
    df.index = pd.DatetimeIndex(df.index, tz="UTC")
    df.index.name = "timestamp"
    return df


def fetch_mstr_holdings(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """MSTR BTC holdings level (step function at each disclosure)."""
    sess = session or requests.Session()
    end_d = end or date.today()
    events = _fetch_bitcoin_data(session=sess)

    rows: list[dict] = []
    for item in events:
        event_date = date.fromisoformat(str(item["date_of_purchase"])[:10])
        holdings = float(item.get("btc_holdings") or 0.0)
        if event_date < start:
            continue
        if event_date > end_d:
            break
        rows.append(
            {
                "event_date": event_date,
                "btc_holding": holdings,
                "available_utc": _mstr_available(event_date),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["btc_holding", "available_utc"])

    df = pd.DataFrame(rows).set_index("event_date").sort_index()
    df.index = pd.DatetimeIndex(df.index, tz="UTC")
    df.index.name = "timestamp"
    return df
