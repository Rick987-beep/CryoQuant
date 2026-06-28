"""SoSoValue OpenAPI — US BTC ETF flows and MSTR treasury events."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from cryoquant import config

log = logging.getLogger(__name__)

_BASE_URL = "https://openapi.sosovalue.com/openapi/v1"
_ET = timezone(timedelta(hours=-5))  # fallback; NYSE calendar used in alignment helpers


def _headers() -> dict[str, str]:
    key = config.SOSOVALUE_API_KEY
    if not key:
        raise RuntimeError("SOSOVALUE_API_KEY not set — skip institutional ingest or set env var")
    return {"x-soso-api-key": key, "Accept": "application/json"}


def _next_us_business_day(d: date) -> date:
    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(start_date=d, end_date=d + timedelta(days=14))
        open_days = [ts.date() for ts in schedule.index]
        for cand in open_days:
            if cand > d:
                return cand
    except Exception:
        pass
    # Fallback: skip weekends only
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def etf_available_utc(trade_date: date) -> datetime:
    """§E.1: next US business day @ 18:00 America/New_York."""
    try:
        from zoneinfo import ZoneInfo

        biz = _next_us_business_day(trade_date)
        local = datetime.combine(biz, time(18, 0), tzinfo=ZoneInfo("America/New_York"))
        return local.astimezone(timezone.utc)
    except Exception:
        biz = _next_us_business_day(trade_date)
        return datetime.combine(biz, time(23, 0), tzinfo=timezone.utc)


def mstr_available_utc(event_date: date) -> datetime:
    """§E.1: next US business day @ 14:00 America/New_York."""
    try:
        from zoneinfo import ZoneInfo

        biz = _next_us_business_day(event_date)
        local = datetime.combine(biz, time(14, 0), tzinfo=ZoneInfo("America/New_York"))
        return local.astimezone(timezone.utc)
    except Exception:
        biz = _next_us_business_day(event_date)
        return datetime.combine(biz, time(19, 0), tzinfo=timezone.utc)


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        last = date(cur.year, cur.month, monthrange(cur.year, cur.month)[1])
        w_start = max(start, cur)
        w_end = min(end, last)
        windows.append((w_start, w_end))
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return windows


def _get_json(path: str, params: dict[str, Any], *, session: requests.Session, retries: int = 5) -> dict:
    import time

    for attempt in range(retries):
        r = session.get(f"{_BASE_URL}{path}", params=params, headers=_headers(), timeout=60)
        if r.status_code == 429:
            wait = min(60.0, 2 ** attempt * 2)
            log.warning("SoSoValue 429 — sleeping %.0fs", wait)
            time.sleep(wait)
            continue
        if r.status_code == 403:
            payload = r.json() if r.content else {}
            msg = payload.get("message", r.text)
            raise PermissionError(f"SoSoValue 403: {msg}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"SoSoValue rate limit after {retries} retries: {path}")


def _etf_window(start: date, end: date) -> tuple[date, date]:
    """Free tier allows only the last 30 calendar days for ETF endpoints."""
    from datetime import timedelta

    plan_limit = date.today() - timedelta(days=29)
    if start < plan_limit:
        log.warning(
            "SoSoValue ETF free tier: clamping start %s → %s (30-day limit; forward collection only)",
            start,
            plan_limit,
        )
        start = plan_limit
    return start, end


def fetch_etf_aggregate_flows(
    start: date,
    end: date | None = None,
    *,
    symbol: str = "BTC",
    country_code: str = "US",
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Aggregate US spot ETF daily net flow (USD)."""
    sess = session or requests.Session()
    end_d = end or date.today()
    eff_start, eff_end = _etf_window(start, end_d)

    payload = _get_json(
        "/etfs/summary-history",
        {
            "symbol": symbol,
            "country_code": country_code,
            "start_date": eff_start.isoformat(),
            "end_date": eff_end.isoformat(),
        },
        session=sess,
    )
    rows: list[dict] = []
    for item in payload.get("data") or []:
        trade_date = date.fromisoformat(str(item["date"])[:10])
        flow = float(
            item.get("total_net_inflow")
            or item.get("totalNetInflow")
            or item.get("net_inflow")
            or item.get("netInflow")
            or 0.0
        )
        rows.append(
            {
                "trade_date": trade_date,
                "value": flow,
                "available_utc": etf_available_utc(trade_date),
            }
        )

    return _rows_to_frame(rows, index_col="trade_date")


def fetch_etf_ticker_flows(
    ticker: str,
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Per-ticker US spot ETF daily net flow."""
    import time

    sess = session or requests.Session()
    end_d = end or date.today()
    eff_start, eff_end = _etf_window(start, end_d)
    payload = _get_json(
        f"/etfs/{ticker}/history",
        {"start_date": eff_start.isoformat(), "end_date": eff_end.isoformat()},
        session=sess,
    )
    time.sleep(1.0)  # rate limit courtesy between tickers
    rows: list[dict] = []
    for item in payload.get("data") or []:
        trade_date = date.fromisoformat(str(item["date"])[:10])
        flow = float(
            item.get("net_inflow")
            or item.get("netInflow")
            or item.get("total_net_inflow")
            or item.get("totalNetInflow")
            or 0.0
        )
        rows.append(
            {
                "trade_date": trade_date,
                "value": flow,
                "available_utc": etf_available_utc(trade_date),
            }
        )

    return _rows_to_frame(rows, index_col="trade_date")


def fetch_mstr_purchases(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """MSTR BTC acquisition events (sparse)."""
    sess = session or requests.Session()
    end_d = end or date.today()
    payload = _get_json("/btc-treasuries/MSTR/purchase-history", {}, session=sess)
    rows: list[dict] = []
    for item in payload.get("data") or []:
        event_date = date.fromisoformat(str(item["date"])[:10])
        if event_date < start or event_date > end_d:
            continue
        btc = float(item.get("btcAmount") or item.get("btc_acq") or item.get("btcHoldingDelta") or 0.0)
        cost = float(item.get("cost") or item.get("acqCost") or 0.0)
        rows.append(
            {
                "event_date": event_date,
                "btc_acq": btc,
                "acq_cost": cost,
                "available_utc": mstr_available_utc(event_date),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["btc_acq", "acq_cost", "available_utc", "event_date"])

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
    """MSTR BTC holdings level (step function from purchase history)."""
    events = fetch_mstr_purchases(start, end, session=session)
    if events.empty:
        return pd.DataFrame(columns=["btc_holding", "available_utc"])

    sess = session or requests.Session()
    payload = _get_json("/btc-treasuries/MSTR/purchase-history", {}, session=sess)
    holdings = 0.0
    rows: list[dict] = []
    for item in sorted(payload.get("data") or [], key=lambda x: x["date"]):
        event_date = date.fromisoformat(str(item["date"])[:10])
        if event_date < start:
            delta = float(item.get("btcAmount") or item.get("btcHoldingDelta") or 0.0)
            holdings += delta
            continue
        delta = float(item.get("btcAmount") or item.get("btcHoldingDelta") or 0.0)
        holdings = float(item.get("btcHolding") or (holdings + delta))
        avail = mstr_available_utc(event_date)
        rows.append({"event_date": event_date, "btc_holding": holdings, "available_utc": avail})

    if not rows:
        return pd.DataFrame(columns=["btc_holding", "available_utc"])

    df = pd.DataFrame(rows).set_index("event_date").sort_index()
    df.index = pd.DatetimeIndex(df.index, tz="UTC")
    df.index.name = "timestamp"
    return df


def _rows_to_frame(rows: list[dict], *, index_col: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["value", "available_utc", index_col])

    df = pd.DataFrame(rows).drop_duplicates(subset=[index_col], keep="last").set_index(index_col).sort_index()
    df.index = pd.DatetimeIndex(df.index, tz="UTC")
    df.index.name = "timestamp"
    return df
