"""CBOE VIX daily OHLC load + light QA.

``load_track(Symbol("cboe", "VIX"), ...)`` returns close only. Strategy work
needs the four macro_store series written by ``ingest_macro`` / ``fetch_vix``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from cryoquant.data import macro_store

from src.paths import ANALYSIS_ROOT, load_config


def _shift_years(dt: datetime, years: int) -> datetime:
    """Calendar shift by ``years`` (negative = back). Handles Feb 29."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def parse_window(cfg: dict[str, Any] | None = None) -> tuple[datetime, datetime]:
    """Research / backtest window.

    Default study policy (``config.yaml``): **exact trailing 10 calendar years**
    ending on the last complete UTC day (yesterday). Override only when the
    user asks for a different range explicitly.
    """
    cfg = cfg or load_config()
    window = cfg["window"]
    mode = str(window.get("mode") or "fixed").lower()

    end_raw = window.get("end")
    if end_raw:
        end = datetime.strptime(str(end_raw), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        # Last complete UTC day — avoids a partial "today" bar.
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end = today - timedelta(days=1)

    if mode in ("trailing_years", "trailing"):
        years = int(window.get("years", 10))
        start = _shift_years(end, -years)
    else:
        start = datetime.strptime(str(window["start"]), "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    if end < start:
        raise ValueError(f"window end {end.date()} precedes start {start.date()}")
    return start, end


def ingest_start(cfg: dict[str, Any] | None = None) -> datetime:
    cfg = cfg or load_config()
    raw = cfg.get("data", {}).get("ingest_start", "2010-01-01")
    return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def load_vix_ohlc(
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load daily VIX OHLC from macro_store as a UTC-indexed DataFrame."""
    if start is None or end is None:
        w_start, w_end = parse_window()
        start = start or w_start
        end = end or w_end

    parts: dict[str, pd.Series] = {}
    for col in ("open", "high", "low", "close"):
        sid = f"VIX_{col.upper()}"
        parts[col] = macro_store.load_series("cboe", sid, start, end)

    df = pd.DataFrame(parts).sort_index()
    df.index.name = "timestamp"
    return df.astype("float64")


def ohlc_parquet_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    rel = cfg.get("data", {}).get("ohlc_parquet", "data/vix_daily_ohlc.parquet")
    return ANALYSIS_ROOT / rel


def write_ohlc_parquet(df: pd.DataFrame, path: Path | None = None) -> Path:
    path = path or ohlc_parquet_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return path


def qa_report(df: pd.DataFrame) -> dict[str, Any]:
    """Lightweight integrity checks for daily VIX OHLC."""
    if df.empty:
        return {"n": 0, "empty": True}

    nulls = {c: int(df[c].isna().sum()) for c in df.columns}
    bad_hl = int((df["high"] < df["low"]).sum())
    outside = int(
        (
            (df["open"] > df["high"])
            | (df["open"] < df["low"])
            | (df["close"] > df["high"])
            | (df["close"] < df["low"])
        ).sum()
    )
    deltas = df.index.to_series().diff().dt.days.iloc[1:]
    large_gaps = int((deltas >= 5).sum())
    ret = df["close"].pct_change()
    return {
        "n": int(len(df)),
        "start": str(df.index.min().date()),
        "end": str(df.index.max().date()),
        "nulls": nulls,
        "duplicate_index": int(df.index.duplicated().sum()),
        "high_lt_low": bad_hl,
        "open_close_outside_range": outside,
        "gaps_ge_5d": large_gaps,
        "max_gap_days": int(deltas.max()) if len(deltas) else 0,
        "ret_abs_gt_30pct": int((ret.abs() > 0.30).sum()),
        "close_min": float(df["close"].min()),
        "close_max": float(df["close"].max()),
    }
