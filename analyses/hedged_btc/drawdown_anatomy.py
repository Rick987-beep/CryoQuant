"""1d — BTC drawdown anatomy (24/7 markets — no overnight/weekend gap framing)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.data.loader import load

log = logging.getLogger(__name__)


def load_btc_daily(start_year: int = 2019) -> pd.DataFrame:
    sym = Symbol("binance.spot", "BTCUSDT")
    start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    return load(sym, "1d", start, end)


def load_btc_hourly(start: datetime, end: datetime) -> pd.DataFrame:
    sym = Symbol("binance.spot", "BTCUSDT")
    return load(sym, "1h", start, end)


def rolling_drawdown(close: pd.Series) -> pd.Series:
    peak = close.cummax()
    return (close - peak) / peak * 100


def period_drawdowns(close: pd.Series, freq: str) -> pd.Series:
    dd = rolling_drawdown(close)
    return dd.groupby(pd.Grouper(freq=freq)).min()


def intraday_excursion(df: pd.DataFrame) -> pd.Series:
    """Within-bar range as % of close (24/7 daily bar, not an 'overnight' concept)."""
    return (df["high"] - df["low"]) / df["close"] * 100


def summarise_drawdowns(df: pd.DataFrame, hourly: pd.DataFrame | None = None) -> dict:
    close = df["close"]
    dd = rolling_drawdown(close)
    monthly = period_drawdowns(close, "ME")
    quarterly = period_drawdowns(close, "QE")
    daily_ret = close.pct_change() * 100
    excursion = intraday_excursion(df)

    out = {
        "n_days": len(df),
        "date_start": str(close.index[0].date()),
        "date_end": str(close.index[-1].date()),
        "max_drawdown_pct": float(dd.min()),
        "max_drawdown_date": str(dd.idxmin().date()),
        "pct_days_dd_worse_than_5pct": float((dd < -5).mean() * 100),
        "pct_days_dd_worse_than_10pct": float((dd < -10).mean() * 100),
        "pct_days_dd_worse_than_20pct": float((dd < -20).mean() * 100),
        "monthly_dd_median_pct": float(monthly.median()),
        "monthly_dd_p10_pct": float(monthly.quantile(0.10)),
        "monthly_dd_worst_pct": float(monthly.min()),
        "quarterly_dd_median_pct": float(quarterly.median()),
        "quarterly_dd_p10_pct": float(quarterly.quantile(0.10)),
        "quarterly_dd_worst_pct": float(quarterly.min()),
        "daily_close_return_worst_pct": float(daily_ret.min()),
        "daily_close_return_best_pct": float(daily_ret.max()),
        "pct_days_close_down_gt_5pct": float((daily_ret < -5).mean() * 100),
        "pct_days_close_down_gt_10pct": float((daily_ret < -10).mean() * 100),
        "daily_range_median_pct": float(excursion.median()),
        "daily_range_p95_pct": float(excursion.quantile(0.95)),
        "daily_range_worst_pct": float(excursion.max()),
    }

    if hourly is not None and not hourly.empty:
        h_close = hourly["close"]
        h_ret = h_close.pct_change() * 100
        roll_24h = h_close.pct_change(24) * 100
        out.update({
            "worst_1h_return_pct": float(h_ret.min()),
            "worst_24h_return_pct": float(roll_24h.min()),
            "pct_hours_down_gt_2pct": float((h_ret < -2).mean() * 100),
        })

    return out


def run(out_dir: Path, start_year: int = 2019) -> tuple[pd.DataFrame, dict]:
    df = load_btc_daily(start_year)
    close = df["close"]

    # Hourly stats for last ~2 years (lighter than full history)
    hourly_start = datetime(max(start_year, close.index[-1].year - 2), 1, 1, tzinfo=timezone.utc)
    try:
        hourly = load_btc_hourly(hourly_start, datetime.now(timezone.utc))
    except Exception as exc:
        log.warning("Hourly load failed: %s", exc)
        hourly = None

    out = pd.DataFrame({
        "date": close.index,
        "close": close.values,
        "drawdown_pct": rolling_drawdown(close).values,
        "daily_close_return_pct": close.pct_change().values * 100,
        "daily_range_pct": intraday_excursion(df).values,
    })
    out_path = out_dir / "drawdown_daily.csv"
    out.to_csv(out_path, index=False)
    log.info("Wrote %s (%d rows)", out_path, len(out))

    monthly = period_drawdowns(close, "ME").reset_index()
    monthly.columns = ["period_end", "max_drawdown_pct"]
    monthly.to_csv(out_dir / "drawdown_monthly.csv", index=False)

    summary = summarise_drawdowns(df, hourly)
    return out, summary
