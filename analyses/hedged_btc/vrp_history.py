"""1b — Vol risk premium: chain-implied ATM IV vs realised vol."""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.data.loader import load
from cryoquant.features.primitives import realised_vol

from ._utils import chain_daily_snapshot, pick_expiry_for_bucket

log = logging.getLogger(__name__)


def _atm_iv_from_chain(chain: pd.DataFrame, as_of: date) -> float | None:
    snap = chain_daily_snapshot(chain)
    if snap.empty:
        return None
    spot = float(snap["underlying_price"].median())
    expiries = snap["expiry"].astype(str).unique().tolist()
    expiry = pick_expiry_for_bucket(expiries, as_of, "mid")
    if expiry is None:
        return None
    sub = snap[(snap["expiry"] == expiry) & (snap["is_call"] == True)]
    if sub.empty:
        return None
    idx = (sub["strike"] - spot).abs().idxmin()
    iv = float(sub.loc[idx, "mark_iv"])
    return iv if 0 < iv < 200 else None


def chain_vrp_series(
    iv_by_date: pd.Series,
    rv_daily: pd.Series,
) -> pd.DataFrame:
    """Align chain IV (mid tenor) with trailing 30d realised vol on daily bars."""
    rv = rv_daily.reindex(iv_by_date.index, method="ffill")
    vrp = iv_by_date - rv
    return pd.DataFrame({"iv_mid": iv_by_date, "rv_30d": rv, "vrp": vrp}).dropna()


def fetch_dvol_history(
    start: datetime,
    end: datetime | None = None,
    *,
    resolution: str = "1D",
) -> pd.DataFrame:
    """Fetch Deribit DVOL index history (public API)."""
    end = end or datetime.now(timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    url = (
        "https://www.deribit.com/api/v2/public/get_volatility_index_data"
        f"?currency=BTC&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution={resolution}"
    )
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.load(resp)
    data = payload.get("result", {}).get("data", [])
    if not data:
        return pd.DataFrame(columns=["dvol", "rv_30d", "vrp"])

    rows = []
    for row in data:
        # [timestamp_ms, open, high, low, close]
        ts = pd.Timestamp(row[0], unit="ms", tz="UTC")
        rows.append({"date": ts.date(), "dvol": float(row[4])})
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
    return df.reset_index(drop=True)


def compute_vrp_from_chains(dates: list[date]) -> pd.DataFrame:
    from cryoquant.data.sources import deribit_options as deribit

    rows = []
    for d in dates:
        try:
            chain = deribit.load_chain(d)
        except FileNotFoundError:
            continue
        iv = _atm_iv_from_chain(chain, d)
        if iv is not None:
            rows.append({"date": d, "iv_mid_atm": iv})
    return pd.DataFrame(rows)


def compute_vrp_full(
    chain_start: date,
    chain_end: date,
) -> tuple[pd.DataFrame, dict]:
    """Combine chain IV, DVOL, and Binance realised vol."""
    sym = Symbol("binance.spot", "BTCUSDT")
    start_dt = datetime(chain_start.year, chain_start.month, chain_start.day, tzinfo=timezone.utc)
    end_dt = datetime(chain_end.year, chain_end.month, chain_end.day, tzinfo=timezone.utc)
    load_start = start_dt - pd.Timedelta(days=60)
    if hasattr(load_start, "to_pydatetime"):
        load_start = load_start.to_pydatetime()
    bars = load(sym, "1d", load_start, end_dt)
    rv30 = realised_vol(bars["close"], n=30, annualise_factor=365)

    from cryoquant.data.sources import deribit_options as deribit
    chain_dates = [d for d in deribit.list_dates() if chain_start <= d <= chain_end]
    chain_iv = compute_vrp_from_chains(chain_dates)
    rv30d = rv30.copy()
    rv30d.index = pd.to_datetime(rv30d.index).tz_localize(None).normalize()

    if not chain_iv.empty:
        chain_iv["date"] = pd.to_datetime(chain_iv["date"]).dt.normalize()
        chain_iv = chain_iv.set_index("date").sort_index()
        rv_aligned = rv30d.reindex(chain_iv.index, method="nearest", tolerance=pd.Timedelta("2d"))
        chain_iv["rv_30d"] = rv_aligned.values
        chain_iv["vrp_chain"] = chain_iv["iv_mid_atm"] - chain_iv["rv_30d"]

    dvol = fetch_dvol_history(datetime(2023, 1, 1, tzinfo=timezone.utc))
    if not dvol.empty:
        dvol["date"] = pd.to_datetime(dvol["date"]).dt.normalize()
        dvol = dvol.set_index("date").sort_index()
        rv_on_dvol = rv30d.reindex(dvol.index, method="nearest", tolerance=pd.Timedelta("2d"))
        dvol["rv_30d"] = rv_on_dvol.values
        dvol["vrp_dvol"] = dvol["dvol"] - dvol["rv_30d"]

    summary = _summarise_vrp(chain_iv if not chain_iv.empty else None, dvol)
    return _merge_outputs(chain_iv, dvol), summary


def _merge_outputs(chain_iv: pd.DataFrame | None, dvol: pd.DataFrame) -> pd.DataFrame:
    out = dvol.copy() if not dvol.empty else pd.DataFrame()
    if chain_iv is not None and not chain_iv.empty:
        if out.empty:
            out = chain_iv.reset_index()
        else:
            out = out.reset_index().merge(
                chain_iv.reset_index(), on="date", how="outer", suffixes=("", "_chain")
            )
    return out.sort_values("date").reset_index(drop=True) if not out.empty else out


def _summarise_vrp(chain_iv: pd.DataFrame | None, dvol: pd.DataFrame) -> dict:
    summary: dict = {}
    if not dvol.empty and "vrp_dvol" in dvol.columns:
        v = dvol["vrp_dvol"].dropna()
        summary.update({
            "dvol_n_days": len(v),
            "dvol_vrp_mean_pp": float(v.mean()),
            "dvol_vrp_median_pp": float(v.median()),
            "dvol_pct_positive_vrp": float((v > 0).mean() * 100),
            "dvol_pct_vrp_gt_5pp": float((v > 5).mean() * 100),
        })
    if chain_iv is not None and not chain_iv.empty and "vrp_chain" in chain_iv.columns:
        v = chain_iv["vrp_chain"].dropna()
        summary.update({
            "chain_n_days": len(v),
            "chain_vrp_mean_pp": float(v.mean()),
            "chain_vrp_median_pp": float(v.median()),
            "chain_pct_positive_vrp": float((v > 0).mean() * 100),
        })
    return summary


def run(out_dir: Path, chain_start: date, chain_end: date) -> tuple[pd.DataFrame, dict]:
    df, summary = compute_vrp_full(chain_start, chain_end)
    out_path = out_dir / "vrp_history.csv"
    df.to_csv(out_path, index=False)
    log.info("Wrote %s (%d rows)", out_path, len(df))
    return df, summary
