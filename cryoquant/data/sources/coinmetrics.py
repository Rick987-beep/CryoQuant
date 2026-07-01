"""Coin Metrics Community API — on-chain asset metrics.

Public interface::

    chain_date_to_available_utc(chain_date) -> datetime
    fetch_asset_metric(asset, metric, start, end, *, session) -> pd.DataFrame

Frames include ``value``, ``available_utc``, ``chain_date``.
Persist via ``macro_store.write_frame("coinmetrics", f"{asset}_{metric}", df)``.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

log = logging.getLogger(__name__)

_BASE_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
_MIN_INTERVAL_S = 0.65  # 10 req / 6s rate limit


def chain_date_to_available_utc(chain_date: date) -> datetime:
    """§G.3: chain day D available at D+1 00:00 UTC."""
    return datetime.combine(chain_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


def fetch_asset_metric(
    asset: str,
    metric: str,
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch one Coin Metrics community metric.

    Returns DataFrame indexed by ``chain_date`` (UTC midnight) with columns:
    ``value``, ``available_utc``.
    """
    sess = session or requests.Session()
    end_d = end or date.today()
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_d + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    params = {
        "assets": asset.lower(),
        "metrics": metric,
        "frequency": "1d",
        "start_time": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "page_size": 10000,
    }

    r = sess.get(_BASE_URL, params=params, timeout=60)
    r.raise_for_status()
    data = r.json().get("data") or []
    time.sleep(_MIN_INTERVAL_S)

    if not data:
        return pd.DataFrame(
            columns=["value", "available_utc", "chain_date"],
        )

    records = []
    for row in data:
        chain_ts = pd.Timestamp(row["time"])
        if chain_ts.tzinfo is None:
            chain_ts = chain_ts.tz_localize("UTC")
        else:
            chain_ts = chain_ts.tz_convert("UTC")
        chain_d = chain_ts.date()
        val = row.get(metric)
        if val is None:
            continue
        avail = chain_date_to_available_utc(chain_d)
        records.append(
            {
                "chain_date": pd.Timestamp(chain_d, tz="UTC"),
                "value": float(val),
                "available_utc": avail,
            }
        )

    if not records:
        return pd.DataFrame(columns=["value", "available_utc", "chain_date"])

    df = pd.DataFrame(records).set_index("chain_date").sort_index()
    df.index.name = "timestamp"
    return df
