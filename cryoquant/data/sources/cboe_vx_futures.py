"""Cboe VX (standard VIX) futures — free daily CSVs → continuous front month.

Source (official CFE historical)::

    https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/VX_{YYYY-MM-DD}.csv

Raw contract CSVs are cached under ``STORE_ROOT/macro/cboe/_raw/vx/`` so re-runs
are cheap. Front-month stitch is written to ``macro_store`` as ``VX_FRONT``
(frame) plus scalar ``VX_FRONT_{OPEN,HIGH,LOW,CLOSE,SETTLE,VOLUME}``.

Public interface::

    vx_expiration_for_contract_month(year, month) -> date
    fetch_vx_contract(expiration, *, force=False) -> pd.DataFrame
    build_vx_front_month(start, end, ...) -> pd.DataFrame
    ingest_vx_front(start, end, *, force=False) -> pd.DataFrame
"""
from __future__ import annotations

import calendar
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from cryoquant import config

log = logging.getLogger(__name__)

_CDN_VX = (
    "https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/VX_{exp}.csv"
)
_TIMEOUT = 45
_HEADERS = {"User-Agent": "CryoQuant/1.0 (+research; VX front-month ingest)"}
_RAW_DIR = config.STORE_ROOT / "macro" / "cboe" / "_raw" / "vx"
_MAX_WORKERS = 8
# Cboe CDN historical CSVs for VX begin around early 2013 (pre-2013 → 403).
_CDN_START = date(2013, 1, 1)


def third_friday(year: int, month: int) -> date:
    cal = calendar.Calendar(firstweekday=calendar.SUNDAY)
    fridays = [
        d for d in cal.itermonthdates(year, month) if d.month == month and d.weekday() == 4
    ]
    return fridays[2]


def vx_expiration_for_contract_month(year: int, month: int) -> date:
    """Textbook VX final-settlement Wednesday for calendar month ``month``.

    Wednesday 30 days prior to the third Friday of the *following* month.
    Holiday shifts are handled at download time (try prior business day).
    """
    if month == 12:
        ny, nm = year + 1, 1
    else:
        ny, nm = year, month + 1
    exp = third_friday(ny, nm) - timedelta(days=30)
    while exp.weekday() != 2:
        exp -= timedelta(days=1)
    return exp


def _month_slots(start: date, end: date) -> list[tuple[int, int]]:
    s = max(start, _CDN_START)
    y, m = s.year, s.month
    for _ in range(2):
        m -= 1
        if m < 1:
            m, y = 12, y - 1
    if date(y, m, 1) < _CDN_START.replace(day=1):
        y, m = _CDN_START.year, _CDN_START.month
    slots: list[tuple[int, int]] = []
    while date(y, m, 1) <= end + timedelta(days=60):
        slots.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return slots


def _cache_path(expiration: date) -> Path:
    return _RAW_DIR / f"VX_{expiration.isoformat()}.csv"


def _http_get(url: str, sess: requests.Session) -> requests.Response:
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = sess.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            if r.status_code == 403 and attempt < 2:
                time.sleep(0.35 * (attempt + 1))
                continue
            return r
        except Exception as exc:
            last = exc
            time.sleep(0.35 * (attempt + 1))
    raise RuntimeError(f"GET failed {url}") from last


def _parse_vx_csv(text: str, expiration: date) -> pd.DataFrame:
    text = text.lstrip("\ufeff")
    if "Trade Date" not in text.splitlines()[0]:
        raise ValueError(f"bad VX header for {expiration}: {text[:60]!r}")
    raw = pd.read_csv(StringIO(text))
    raw.columns = [c.strip() for c in raw.columns]
    raw = raw.rename(
        columns={
            "Trade Date": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Settle": "settle",
            "Total Volume": "volume",
            "Open Interest": "open_interest",
            "Futures": "futures",
        }
    )
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    for col in ("open", "high", "low", "close", "settle", "volume", "open_interest"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce").astype("float64")
    df = raw.set_index("timestamp").sort_index()
    df["expiration"] = pd.Timestamp(expiration, tz="UTC")
    # Settlement day often has OHLC=0 — use settle as the mark.
    zero = df["close"].fillna(0.0) <= 0.0
    df.loc[zero, "close"] = df.loc[zero, "settle"]
    for col in ("open", "high", "low"):
        bad = df[col].fillna(0.0) <= 0.0
        df.loc[bad, col] = df.loc[bad, "settle"]
    return df[
        [
            "open",
            "high",
            "low",
            "close",
            "settle",
            "volume",
            "open_interest",
            "futures",
            "expiration",
        ]
    ]


def _download_one(
    year: int,
    month: int,
    *,
    force: bool,
    sess: requests.Session,
) -> tuple[date, pd.DataFrame] | None:
    """Try textbook expiry then prior day (holiday shift). Return parsed frame."""
    guess = vx_expiration_for_contract_month(year, month)
    candidates = [guess, guess - timedelta(days=1), guess + timedelta(days=1)]
    for exp in candidates:
        path = _cache_path(exp)
        if path.exists() and not force:
            return exp, _parse_vx_csv(path.read_text(encoding="utf-8"), exp)
        url = _CDN_VX.format(exp=exp.isoformat())
        r = _http_get(url, sess)
        if r.status_code != 200:
            continue
        text = r.text
        if "Trade Date" not in text.lstrip("\ufeff")[:40]:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return exp, _parse_vx_csv(text, exp)
    log.warning("VX %04d-%02d: no CDN file near %s", year, month, guess)
    return None


def fetch_vx_contracts(
    start: date | datetime,
    end: date | datetime,
    *,
    force: bool = False,
    max_workers: int = _MAX_WORKERS,
) -> list[pd.DataFrame]:
    """Download (or load-cache) all monthly VX contracts covering ``[start, end]``."""
    s = start.date() if isinstance(start, datetime) else start
    e = end.date() if isinstance(end, datetime) else end
    slots = _month_slots(s, e)
    sess = requests.Session()
    out: list[pd.DataFrame] = []
    # Parallel downloads; each worker uses its own Session for thread safety
    def _job(ym: tuple[int, int]) -> tuple[date, pd.DataFrame] | None:
        y, m = ym
        return _download_one(y, m, force=force, sess=requests.Session())

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_job, slot): slot for slot in slots}
        for fut in as_completed(futs):
            slot = futs[fut]
            try:
                res = fut.result()
            except Exception as exc:
                log.warning("VX %04d-%02d worker failed: %s", slot[0], slot[1], exc)
                continue
            if res is None:
                continue
            exp, df = res
            out.append(df)
            log.debug("VX %s: %d bars", exp, len(df))

    log.info("VX contracts ready: %d / %d month slots", len(out), len(slots))
    return out


def build_vx_front_month(
    start: datetime | date,
    end: datetime | date | None = None,
    *,
    roll_days_before_expiry: int = 0,
    force: bool = False,
    max_workers: int = _MAX_WORKERS,
) -> pd.DataFrame:
    """Continuous front-month VX daily series (UTC index).

    Columns: open, high, low, close, settle, volume, open_interest,
    contract_expiration, futures.
    """
    end_dt = end or datetime.now(timezone.utc)
    s = (
        start
        if isinstance(start, datetime)
        else datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    )
    e = (
        end_dt
        if isinstance(end_dt, datetime)
        else datetime(end_dt.year, end_dt.month, end_dt.day, tzinfo=timezone.utc)
    )
    if s.tzinfo is None:
        s = s.replace(tzinfo=timezone.utc)
    if e.tzinfo is None:
        e = e.replace(tzinfo=timezone.utc)

    parts = fetch_vx_contracts(s, e, force=force, max_workers=max_workers)
    if not parts:
        raise RuntimeError("No VX contracts downloaded")

    stacked = pd.concat(parts, axis=0).reset_index()
    roll = int(roll_days_before_expiry)
    rows: list[dict] = []
    for ts, g in stacked.groupby("timestamp", sort=True):
        ts_d = pd.Timestamp(ts).tz_convert("UTC").normalize()
        g = g.copy()
        g["exp_d"] = pd.to_datetime(g["expiration"], utc=True).dt.normalize()
        cand = g.loc[g["exp_d"] >= (ts_d + pd.Timedelta(days=roll))]
        if cand.empty:
            continue
        front = cand.sort_values("exp_d").iloc[0]
        rows.append(
            {
                "timestamp": ts_d,
                "open": float(front["open"]),
                "high": float(front["high"]),
                "low": float(front["low"]),
                "close": float(front["close"]),
                "settle": float(front["settle"]),
                "volume": float(front["volume"]) if pd.notna(front["volume"]) else float("nan"),
                "open_interest": float(front["open_interest"])
                if pd.notna(front["open_interest"])
                else float("nan"),
                "contract_expiration": front["exp_d"].date().isoformat(),
                "futures": str(front["futures"]),
            }
        )

    out = pd.DataFrame(rows).set_index("timestamp").sort_index()
    out = out.loc[
        pd.Timestamp(s).tz_convert("UTC").normalize() : pd.Timestamp(e).tz_convert("UTC").normalize()
    ]
    out = out[out["settle"].fillna(0.0) > 0.0]
    log.info(
        "VX front month: %d bars [%s → %s]",
        len(out),
        out.index.min().date() if len(out) else "n/a",
        out.index.max().date() if len(out) else "n/a",
    )
    return out


def ingest_vx_front(
    start: datetime | date,
    end: datetime | date | None = None,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """Build front month and write to ``macro_store`` (frame + scalars)."""
    from cryoquant.data import macro_store

    front = build_vx_front_month(start, end, force=force)
    macro_store.write_frame("cboe", "VX_FRONT", front, force=True)
    for col in ("open", "high", "low", "close", "settle", "volume"):
        macro_store.write_series(
            "cboe", f"VX_FRONT_{col.upper()}", front[col].astype(float), force=True
        )
    return front
