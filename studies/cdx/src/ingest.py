"""Ingest CDX.NA.IG spread series and align proxy/macro data."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.data import loader
from cryoquant.data import macro_store

from .paths import cdx_clean_csv_path, data_dir, load_config

log = logging.getLogger(__name__)


def load_cdx_clean_csv(path: Path | None = None) -> pd.DataFrame:
    """Load canonical CDX.NA.IG clean CSV from input."""
    path = path or cdx_clean_csv_path()
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.rename(columns={"cdx_na_ig": "spread_bps"})
    return df


def cdx_to_macro_series(df: pd.DataFrame) -> pd.Series:
    """Convert clean frame to UTC macro_store series."""
    idx = pd.DatetimeIndex(df["date"]).tz_localize("UTC")
    return pd.Series(df["spread_bps"].values, index=idx, name="CDX_NA_IG_5Y", dtype=float)


def ingest_cdx(*, force: bool = False) -> pd.Series:
    """Write CDX.NA.IG to macro_store and local parquet."""
    cfg = load_config()
    df = load_cdx_clean_csv()
    series = cdx_to_macro_series(df)

    source = cfg["instrument"]["macro_source"]
    series_id = cfg["instrument"]["series_id"]
    macro_store.write_series(source, series_id, series, force=force)

    out = data_dir() / "cdx_na_ig_clean.parquet"
    df.to_parquet(out, index=False)
    log.info("Wrote %s (%d rows)", out, len(df))
    return series


def load_proxy_close(ticker: str, start: datetime, end: datetime) -> pd.Series:
    """Load daily close for a Yahoo proxy."""
    sym = Symbol(venue="yahoo", ticker=ticker)
    bars = loader.load(sym, "1d", start, end)
    s = bars["close"].copy()
    s.index = pd.DatetimeIndex(s.index).tz_convert("UTC")
    s.name = ticker
    return s


def load_vix(start: datetime, end: datetime) -> pd.Series:
    return macro_store.load_series("cboe", "VIX_CLOSE", start, end)


def build_aligned_panel(*, force_cdx: bool = False) -> pd.DataFrame:
    """CDX.NA.IG + proxy closes on a common daily index."""
    ingest_cdx(force=force_cdx)
    df = load_cdx_clean_csv()
    idx = pd.DatetimeIndex(df["date"]).tz_localize("UTC")
    panel = pd.DataFrame({"spread_bps": df["spread_bps"].values}, index=idx)

    start = idx.min().to_pydatetime()
    end = idx.max().to_pydatetime()

    for spec in load_config()["data"]["proxies"]:
        ticker = spec["ticker"]
        try:
            panel[ticker] = load_proxy_close(ticker, start, end)
        except FileNotFoundError:
            log.warning("Proxy %s not on disk — run cryoquant ingest for yahoo/%s", ticker, ticker)

    try:
        panel["VIX"] = load_vix(start, end)
    except FileNotFoundError:
        log.warning("VIX not on disk — run macro ingest for cboe/VIX_CLOSE")

    panel = panel.sort_index().ffill()
    out = data_dir() / "panel_daily.parquet"
    panel.to_parquet(out)
    log.info("Wrote aligned panel %s [%s → %s]", out, panel.index.min().date(), panel.index.max().date())
    return panel


def qa_report(df: pd.DataFrame) -> dict:
    """Basic data quality checks."""
    dupes = int(df["date"].duplicated().sum()) if "date" in df.columns else int(df.index.duplicated().sum())
    gaps = int((df["gap_days"] > 4).sum()) if "gap_days" in df.columns else 0
    return {
        "n_rows": len(df),
        "start": str(df["date"].iloc[0]) if "date" in df.columns else str(df.index[0].date()),
        "end": str(df["date"].iloc[-1]) if "date" in df.columns else str(df.index[-1].date()),
        "spread_min": float(df["spread_bps"].min()),
        "spread_max": float(df["spread_bps"].max()),
        "duplicate_dates": dupes,
        "gaps_gt_4d": gaps,
    }
