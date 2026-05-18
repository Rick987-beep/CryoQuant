"""Binance perpetual contract feeds: funding rate (and OI later).

Public REST endpoints, no auth:
    GET https://fapi.binance.com/fapi/v1/fundingRate
        symbol, startTime, endTime, limit (max 1000)

Funding is published every 8 hours at 00:00, 08:00, 16:00 UTC. The rate for
period [t-8h, t] becomes public at t — release_lag_seconds = 0 for backtests
that act at next-bar open after t.

Open interest history (`/futures/data/openInterestHist`) is intentionally
NOT fetched here: Binance only serves the past 30 days through that endpoint,
which is too short for our backtest window. Park OI for a later feed adapter
that uses a paid/archival source if a candidate motivates it.

Cache layout:
    pineforge/data/feeds/binance_perp_funding_{SYMBOL}.parquet
        columns: funding_time (ts UTC), funding_rate (float), mark_price (float)
    + sidecar pineforge/data/feeds/binance_perp_funding_{SYMBOL}.meta.json
        rendered FeedSnapshot.

attach_funding(df) is the read API: merge_asof aligns the most recent
published funding rate to each bar's *close* timestamp, never look-ahead.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

from ..schemas import FeedSnapshot, FeedSpec

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "feeds"
BASE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
LIMIT = 1000


def _parquet_path(symbol: str) -> Path:
    return DATA_DIR / f"binance_perp_funding_{symbol}.parquet"


def _meta_path(symbol: str) -> Path:
    return DATA_DIR / f"binance_perp_funding_{symbol}.meta.json"


def _to_ms(ts: pd.Timestamp | str | int) -> int:
    if isinstance(ts, (int, float)):
        return int(ts)
    return int(pd.Timestamp(ts, tz="UTC").timestamp() * 1000)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_funding(
    symbol: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    *,
    sleep_s: float = 0.25,
    session: requests.Session | None = None,
    max_retries: int = 6,
) -> pd.DataFrame:
    """Fetch funding rate history from Binance Futures.

    Returns a DataFrame indexed by `funding_time` (UTC) with columns
    `funding_rate` (float) and `mark_price` (float).
    """
    sess = session or requests.Session()
    cursor = _to_ms(start)
    end_ms = _to_ms(end) if end is not None else int(time.time() * 1000)

    rows: list[dict] = []
    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": LIMIT,
        }
        delay = 1.0
        last_err: Exception | None = None
        for _ in range(max_retries):
            try:
                r = sess.get(BASE_URL, params=params, timeout=15)
                r.raise_for_status()
                batch = r.json()
                last_err = None
                break
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(delay)
                delay *= 2
        else:
            raise RuntimeError(f"fundingRate fetch failed: {last_err}")

        if not batch:
            break

        for rec in batch:
            mp = rec.get("markPrice", "")
            try:
                mp_f = float(mp) if mp not in ("", None) else float("nan")
            except (TypeError, ValueError):
                mp_f = float("nan")
            rows.append(
                dict(
                    funding_time=int(rec["fundingTime"]),
                    funding_rate=float(rec["fundingRate"]),
                    mark_price=mp_f,
                )
            )

        # advance: 1 ms past the last fundingTime in this batch
        last_t = batch[-1]["fundingTime"]
        if len(batch) < LIMIT:
            break
        cursor = int(last_t) + 1
        time.sleep(sleep_s)

    if not rows:
        return pd.DataFrame(
            columns=["funding_rate", "mark_price"],
            index=pd.DatetimeIndex([], tz="UTC", name="funding_time"),
        )

    df = pd.DataFrame(rows)
    df["funding_time"] = pd.to_datetime(df["funding_time"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["funding_time"]).sort_values("funding_time")
    return df.set_index("funding_time")[["funding_rate", "mark_price"]]


# ---------------------------------------------------------------------------
# Cache update + load
# ---------------------------------------------------------------------------

def update_funding_cache(
    symbol: str = "BTCUSDT",
    *,
    full: bool = False,
    history_start: str = "2019-09-08",
) -> Path:
    """Refresh the cached parquet. Incremental by default."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _parquet_path(symbol)

    if full or not path.exists():
        new = fetch_funding(symbol, history_start)
        merged = new
    else:
        existing = pd.read_parquet(path)
        last_ts = existing.index.max()
        # 1ms past the last cached row
        start_ts = last_ts + pd.Timedelta(milliseconds=1)
        new = fetch_funding(symbol, start_ts)
        if len(new) == 0:
            merged = existing
        else:
            merged = pd.concat([existing, new]).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]

    merged.to_parquet(path)

    # write sidecar FeedSnapshot
    spec = FeedSpec(
        name="binance.perp.funding",
        source_url=BASE_URL,
        columns={"funding_rate": "float64", "mark_price": "float64"},
        cadence="8h",
        release_lag_seconds=0,
        history_start=history_start,
        history_end=None,
    )
    snap = FeedSnapshot(
        spec=spec,
        parquet_path=str(path.relative_to(path.parents[3])),  # workspace-relative
        rows=int(len(merged)),
        last_refreshed=pd.Timestamp.now(tz="UTC").to_pydatetime(),
    )
    _meta_path(symbol).write_text(snap.model_dump_json(indent=2))
    return path


def load_funding(symbol: str = "BTCUSDT") -> pd.DataFrame:
    path = _parquet_path(symbol)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing. Run: python -m pineforge.feeds.binance_perp --update {symbol}"
        )
    df = pd.read_parquet(path)
    return df.sort_index()


# ---------------------------------------------------------------------------
# Closed-bar-safe attach
# ---------------------------------------------------------------------------

def attach_funding(
    df: pd.DataFrame,
    *,
    symbol: str = "BTCUSDT",
    z_window_bars: int = 240,
) -> pd.DataFrame:
    """Add `funding_rate` and `funding_z` columns to an OHLCV DataFrame.

    Closed-bar safe: at bar with close timestamp T (which is the next bar's
    open ts under TradingView labeling — index labels are open ts), we use
    the most recent funding event with `funding_time <= bar_close`.

    The bar close for a row labelled at index `t_open` is `t_open + tf`. We
    compute it from the index spacing. If the spacing is irregular (raw 1m
    can be) we fall back to the last delta.

    `funding_z`: rolling z-score of funding_rate over `z_window_bars` 8h
    funding events (default 240 ≈ 80 days).
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df must have a DatetimeIndex")
    if df.index.tz is None:
        df = df.tz_localize("UTC")

    funding = load_funding(symbol).copy()
    # Normalize precision so merge_asof keys match the OHLCV index.
    funding.index = funding.index.astype("datetime64[ns, UTC]")
    # rolling z over funding events themselves (not bars)
    fr = funding["funding_rate"]
    mu = fr.rolling(z_window_bars, min_periods=z_window_bars // 4).mean()
    sd = fr.rolling(z_window_bars, min_periods=z_window_bars // 4).std()
    funding["funding_z"] = (fr - mu) / sd
    funding = funding.reset_index().rename(columns={"funding_time": "ts"})

    # bar close = next index step; for irregular last bar use median delta
    deltas = df.index.to_series().diff().dropna()
    tf_ns = int(deltas.median().value) if len(deltas) > 0 else 0
    bar_close = df.index + pd.to_timedelta(tf_ns, unit="ns")

    bars = pd.DataFrame({"bar_open": df.index, "bar_close": bar_close})
    bars = bars.sort_values("bar_close")

    # merge_asof: for each bar, take latest funding event with ts <= bar_close
    joined = pd.merge_asof(
        bars,
        funding[["ts", "funding_rate", "funding_z"]],
        left_on="bar_close",
        right_on="ts",
        direction="backward",
    )
    joined = joined.set_index("bar_open").reindex(df.index)

    out = df.copy()
    out["funding_rate"] = joined["funding_rate"].values
    out["funding_z"] = joined["funding_z"].values
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--full", action="store_true", help="refetch from history_start")
    p.add_argument("--history-start", default="2019-09-08")
    args = p.parse_args(argv)

    path = update_funding_cache(args.symbol, full=args.full, history_start=args.history_start)
    df = load_funding(args.symbol)
    print(f"wrote {path}")
    print(f"  rows: {len(df):,}")
    print(f"  span: {df.index.min()} .. {df.index.max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
