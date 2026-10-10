"""Eurex overall-statistics API — FOAT / FGBL daily settlements.

Unofficial public endpoint (same as v5)::

    https://www.eurex.com/api/v1/overallstatistics/{product_id}?filtertype=overview
    &busdate=YYYYMMDD

Eurex typically exposes ~20 recent settlement days. Same-day rows can be missing;
callers should treat the series as T+1.

Public interface::

    fetch_settles() -> pd.DataFrame
    ingest_settles(*, force) -> pd.DataFrame
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

log = logging.getLogger(__name__)

_STATS_URL = "https://www.eurex.com/api/v1/overallstatistics/{pid}?filtertype=overview"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TIMEOUT = 30

# Eurex product ids (overall statistics)
FUTURES: dict[str, int] = {
    "FOAT": 34684,
    "FGBL": 34656,
}

SERIES_ID = "FOAT_FGBL_SETTLES"


def fetch_settles(*, session: requests.Session | None = None) -> pd.DataFrame:
    """Daily front/next settlements for FOAT and FGBL over Eurex's recent window.

    Returns a UTC-indexed DataFrame with columns::

        FOAT_front, FOAT_next, FOAT_front_month,
        FGBL_front, FGBL_next, FGBL_front_month
    """
    sess = session or requests.Session()
    header = _get(FUTURES["FOAT"], sess=sess)
    trading_dates = header.get("header", {}).get("tradingDates") or []
    if not trading_dates:
        raise RuntimeError("Eurex FOAT statistics returned no tradingDates")

    dates = [pd.to_datetime(x[:10], format="%d-%m-%Y", utc=True) for x in trading_dates]
    rows: list[dict[str, Any]] = []
    for dt in dates:
        row: dict[str, Any] = {"timestamp": dt}
        bus = dt.strftime("%Y%m%d")
        for code, pid in FUTURES.items():
            payload = _get(pid, busdate=bus, sess=sess)
            months = sorted(payload.get("dataRows") or [], key=lambda m: m["date"])
            months = [m for m in months if m.get("dSettle") not in (None, "")]
            if len(months) >= 2:
                row[f"{code}_front"] = float(months[0]["dSettle"])
                row[f"{code}_next"] = float(months[1]["dSettle"])
                row[f"{code}_front_month"] = int(months[0]["date"])
        rows.append(row)

    df = pd.DataFrame(rows).set_index("timestamp").sort_index()
    df = df.dropna(subset=["FOAT_front", "FGBL_front"])
    # month codes stay as float if mixed; cast where present
    for col in ("FOAT_front_month", "FGBL_front_month"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def ingest_settles(*, force: bool = False, session: requests.Session | None = None) -> pd.DataFrame:
    """Fetch FOAT/FGBL settlements and persist the frame to ``macro_store``."""
    from cryoquant.data import macro_store

    df = fetch_settles(session=session)
    macro_store.write_frame("eurex", SERIES_ID, df, force=force)
    log.info(
        "eurex settles %s → %s (%d rows)",
        df.index[0].date(),
        df.index[-1].date(),
        len(df),
    )
    return df


def _get(
    pid: int,
    *,
    busdate: str = "",
    sess: requests.Session,
) -> dict[str, Any]:
    url = _STATS_URL.format(pid=pid)
    if busdate:
        url = f"{url}&busdate={busdate}"
    r = sess.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()
