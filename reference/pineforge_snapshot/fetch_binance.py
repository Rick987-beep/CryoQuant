"""Fetch Binance spot klines for pineforge.

Binance public REST endpoint, no auth required:
    https://api.binance.com/api/v3/klines

We pull a single symbol/interval, paginated by 1000-bar chunks, and write a
parquet under pineforge/data/{SYMBOL}_{INTERVAL}.parquet with a tz-aware UTC
DatetimeIndex named 'timestamp' and columns: open, high, low, close, volume.

Usage:
    python -m pineforge.fetch_binance --symbol BTCUSDT --interval 1h \
        --start 2020-01-01 [--end 2026-04-30]

A second resampling-friendly default: --interval 1m for the master file (slow
but only needs to run once). Resamples to other timeframes are produced on
demand from `data.py`.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BASE_URL = "https://api.binance.com/api/v3/klines"
LIMIT = 1000  # Binance max per request

# Map our names to milliseconds per bar.
_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _to_ms(ts: str) -> int:
    return int(pd.Timestamp(ts, tz="UTC").timestamp() * 1000)


def fetch(
    symbol: str,
    interval: str,
    start: str,
    end: str | None = None,
    *,
    sleep_s: float = 0.25,
    session: requests.Session | None = None,
    max_retries: int = 8,
) -> pd.DataFrame:
    """Fetch klines [start, end) inclusive of start, exclusive of end-bar.

    Returns a DataFrame with UTC DatetimeIndex 'timestamp' (open time) and
    columns: open, high, low, close, volume (all float).

    Resilient to transient network errors: each request retries up to
    ``max_retries`` times with exponential backoff (1s, 2s, 4s, ...).
    """
    if interval not in _INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    sess = session or requests.Session()
    start_ms = _to_ms(start)
    end_ms = _to_ms(end) if end else int(time.time() * 1000)
    bar_ms = _INTERVAL_MS[interval]

    rows: list[list] = []
    cursor = start_ms
    n_calls = 0
    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": LIMIT,
        }
        chunk = None
        for attempt in range(max_retries):
            try:
                r = sess.get(BASE_URL, params=params, timeout=30)
                r.raise_for_status()
                chunk = r.json()
                break
            except (requests.exceptions.RequestException, ValueError) as exc:
                wait = min(60.0, 2 ** attempt)
                ts = pd.Timestamp(cursor, unit="ms", tz="UTC")
                print(
                    f"  ! request failed at cursor={ts} (attempt {attempt+1}/{max_retries}): "
                    f"{type(exc).__name__}: {exc}. Sleeping {wait:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
        if chunk is None:
            raise RuntimeError(f"giving up after {max_retries} retries at cursor {cursor}")
        n_calls += 1
        if not chunk:
            break
        rows.extend(chunk)
        last_open = chunk[-1][0]
        next_cursor = last_open + bar_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if n_calls % 10 == 0:
            ts = pd.Timestamp(cursor, unit="ms", tz="UTC")
            print(f"  ...{n_calls} calls, cursor={ts}, rows={len(rows)}", file=sys.stderr)
        if len(chunk) < LIMIT:
            break  # caught up
        time.sleep(sleep_s)

    if not rows:
        raise RuntimeError("no klines returned")

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
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch Binance spot klines to parquet")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1h", choices=list(_INTERVAL_MS))
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default=None, help="default: now")
    p.add_argument("--out", default=None, help="default: data/{SYMBOL}_{INTERVAL}.parquet")
    p.add_argument(
        "--resume",
        action="store_true",
        help="if --out exists, start at last_timestamp + 1 bar instead of --start",
    )
    args = p.parse_args(argv)

    out = Path(args.out) if args.out else DATA_DIR / f"{args.symbol}_{args.interval}.parquet"
    start = args.start
    existing: pd.DataFrame | None = None
    if args.resume and out.exists():
        existing = pd.read_parquet(out)
        last_ts = existing.index[-1]
        bar_ms = _INTERVAL_MS[args.interval]
        next_ts = last_ts + pd.Timedelta(milliseconds=bar_ms)
        start = next_ts.isoformat()
        print(f"Resuming: existing parquet has {len(existing):,} bars up to {last_ts}; new start={start}")

    print(f"Fetching {args.symbol} {args.interval} from {start} to {args.end or 'now'}...")
    df = fetch(args.symbol, args.interval, start, args.end)
    print(f"Got {len(df):,} new bars [{df.index[0]} .. {df.index[-1]}]")

    if existing is not None and len(existing) > 0:
        df = pd.concat([existing, df])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        print(f"Merged: {len(df):,} total bars [{df.index[0]} .. {df.index[-1]}]")

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
