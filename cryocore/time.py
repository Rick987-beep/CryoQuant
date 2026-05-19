"""UTC time helpers and bar-convention utilities.

All functions work in UTC. Bar timestamps follow the **bar-open** convention:
a bar labelled 2024-01-15 14:00 UTC covers [14:00, 15:00) on a 1h timeframe.

Supported tf strings: 1m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 1w
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

_TF_SECONDS: dict[str, int] = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "30m": 1_800,
    "1h":  3_600,
    "2h":  7_200,
    "4h":  14_400,
    "6h":  21_600,
    "8h":  28_800,
    "12h": 43_200,
    "1d":  86_400,
    "1w":  604_800,
}

_TF_PANDAS: dict[str, str] = {
    "1m":  "1min",
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "1h":  "1h",
    "2h":  "2h",
    "4h":  "4h",
    "6h":  "6h",
    "8h":  "8h",
    "12h": "12h",
    "1d":  "1D",
    "1w":  "1W",
}


def utcnow() -> datetime:
    """Return current time as a tz-aware UTC datetime."""
    return datetime.now(timezone.utc)


def tf_to_seconds(tf: str) -> int:
    """Return the number of seconds in one bar of *tf*."""
    if tf not in _TF_SECONDS:
        raise ValueError(f"unsupported tf {tf!r}; valid: {sorted(_TF_SECONDS)}")
    return _TF_SECONDS[tf]


def tf_to_pandas_freq(tf: str) -> str:
    """Return the pandas frequency alias for *tf*."""
    if tf not in _TF_PANDAS:
        raise ValueError(f"unsupported tf {tf!r}; valid: {sorted(_TF_PANDAS)}")
    return _TF_PANDAS[tf]


def floor_to_tf(ts: pd.Timestamp | datetime, tf: str) -> pd.Timestamp:
    """Floor *ts* to the nearest bar-open boundary for *tf*.

    Works for all supported tfs including 1w (Monday boundary).
    """
    secs = tf_to_seconds(tf)
    if isinstance(ts, datetime):
        ts = pd.Timestamp(ts)
    ts_utc = ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
    epoch_s = int(ts_utc.timestamp())
    floored_s = (epoch_s // secs) * secs
    return pd.Timestamp(floored_s, unit="s", tz="UTC")


def bar_open(ts: pd.Timestamp | datetime, tf: str) -> pd.Timestamp:
    """Return the open timestamp of the bar containing *ts*."""
    return floor_to_tf(ts, tf)


def bar_close(ts: pd.Timestamp | datetime, tf: str) -> pd.Timestamp:
    """Return the close (exclusive) timestamp of the bar containing *ts*."""
    secs = tf_to_seconds(tf)
    return floor_to_tf(ts, tf) + pd.Timedelta(seconds=secs)
