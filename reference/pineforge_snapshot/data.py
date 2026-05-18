"""Klines loading + resampling.

Source data is Binance spot BTCUSDT, stored as parquet with a tz-aware UTC
DatetimeIndex named 'timestamp' and columns: open, high, low, close, volume.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_TF_TO_PANDAS = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1D",
}


def load(symbol: str = "BTCUSDT", tf: str = "1h") -> pd.DataFrame:
    """Load a klines parquet. Returns OHLCV with a UTC DatetimeIndex."""
    path = DATA_DIR / f"{symbol}_{tf}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Available: {[p.name for p in DATA_DIR.glob('*.parquet')]}"
        )
    df = pd.read_parquet(path)
    if df.index.name != "timestamp":
        raise ValueError(f"expected index 'timestamp', got {df.index.name}")
    expected = ["open", "high", "low", "close", "volume"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns {missing}; have {list(df.columns)}")
    return df[expected].sort_index()


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample OHLCV to a new timeframe.

    Uses label='left', closed='left' to match TradingView's convention where
    a bar is labelled by its open time and closes at open + tf.
    """
    if tf not in _TF_TO_PANDAS:
        raise ValueError(f"unsupported tf {tf!r}; choose from {list(_TF_TO_PANDAS)}")
    rule = _TF_TO_PANDAS[tf]
    out = df.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"])


# ---------------------------------------------------------------------------
# Multi-timeframe context (closed-bar safe)
# ---------------------------------------------------------------------------

def htf_align(base_df: pd.DataFrame, htf_series: pd.Series, *, htf: str) -> pd.Series:
    """Forward-fill an HTF series onto a base-TF DataFrame, no look-ahead.

    Mirrors Pine's `request.security(..., lookahead=barmerge.lookahead_off)`:
    on a base bar with open ts T_base, the HTF value used is the most recent
    HTF bar that has *closed* by T_base (i.e. HTF bar with open ts <= T_base
    minus one HTF step is the last fully-closed one; if T_base coincides with
    an HTF open, the HTF bar that just closed at that instant is allowed).

    Implementation:
        - HTF series is indexed by HTF bar OPEN ts. The bar closes at
          open + htf_step. We shift the series forward by one HTF step so
          that each value is labelled by its CLOSE ts.
        - Then merge_asof(direction='backward') onto base_df.index.

    Args:
        base_df:    OHLCV at the base TF, DatetimeIndex (UTC, open-ts labelled).
        htf_series: any series indexed at the HTF (open-ts labelled).
        htf:        HTF tf-string (e.g. "4h", "1d") — needed to compute the step.

    Returns:
        pd.Series aligned to base_df.index with the same dtype as htf_series.
    """
    if htf not in _TF_TO_PANDAS:
        raise ValueError(f"unsupported htf {htf!r}; choose from {list(_TF_TO_PANDAS)}")
    if not isinstance(base_df.index, pd.DatetimeIndex):
        raise ValueError("base_df must have a DatetimeIndex")
    if not isinstance(htf_series.index, pd.DatetimeIndex):
        raise ValueError("htf_series must have a DatetimeIndex")

    step = pd.tseries.frequencies.to_offset(_TF_TO_PANDAS[htf])
    # Each HTF value becomes available at HTF_open + step (= HTF close).
    htf_close_ts = htf_series.index + step
    feed = pd.DataFrame({"close_ts": htf_close_ts, "value": htf_series.to_numpy()})
    feed = feed.sort_values("close_ts").reset_index(drop=True)

    base = pd.DataFrame({"base_ts": base_df.index})
    base = base.sort_values("base_ts").reset_index(drop=True)

    joined = pd.merge_asof(
        base, feed, left_on="base_ts", right_on="close_ts", direction="backward"
    )
    return pd.Series(
        joined["value"].to_numpy(), index=base_df.index, name=htf_series.name
    )
