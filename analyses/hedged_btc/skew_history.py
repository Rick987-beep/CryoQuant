"""1a — Daily skew term structure from local Deribit option chains."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from cryoquant.data.sources import deribit_options as deribit

from ._utils import (
    TENOR_BUCKETS,
    chain_daily_snapshot,
    expiry_dte,
    iv_at_strike,
    nearest_strike,
    pick_expiry_for_bucket,
)

log = logging.getLogger(__name__)


def _skew_for_bucket(snap: pd.DataFrame, spot: float, as_of: date, bucket: str) -> dict | None:
    expiries = snap["expiry"].astype(str).unique().tolist()
    expiry = pick_expiry_for_bucket(expiries, as_of, bucket)
    if expiry is None:
        return None

    sub = snap[snap["expiry"] == expiry]
    if sub.empty:
        return None

    put_target = spot * 0.90
    call_target = spot * 1.10
    atm_target = spot

    put_strike = nearest_strike(sub[sub["is_call"] == False]["strike"], put_target)
    call_strike = nearest_strike(sub[sub["is_call"] == True]["strike"], call_target)
    atm_strike = nearest_strike(sub["strike"].drop_duplicates(), atm_target)

    put_iv = iv_at_strike(sub, expiry=expiry, strike=put_strike, is_call=False)
    call_iv = iv_at_strike(sub, expiry=expiry, strike=call_strike, is_call=True)
    atm_iv = iv_at_strike(sub, expiry=expiry, strike=atm_strike, is_call=True)
    if put_iv is None or call_iv is None:
        return None

    return {
        "expiry": expiry,
        "dte": expiry_dte(expiry, as_of),
        "put_iv_10otm": put_iv,
        "call_iv_10otm": call_iv,
        "skew_10otm": put_iv - call_iv,
        "atm_iv": atm_iv,
        "put_strike": put_strike,
        "call_strike": call_strike,
    }


def compute_skew_history(
    dates: list[date] | None = None,
    *,
    sample_every: int = 1,
) -> pd.DataFrame:
    """Build daily skew metrics for front / mid / back tenor buckets."""
    dates = dates or deribit.list_dates()
    if sample_every > 1:
        dates = dates[::sample_every]

    rows: list[dict] = []
    for i, d in enumerate(dates):
        if i % 50 == 0:
            log.info("skew: %d / %d (%s)", i, len(dates), d)
        try:
            chain = deribit.load_chain(d)
        except FileNotFoundError:
            continue
        snap = chain_daily_snapshot(chain)
        if snap.empty:
            continue
        spot = float(snap["underlying_price"].median())
        if spot <= 0:
            continue

        row: dict = {"date": d, "spot": spot}
        for bucket in TENOR_BUCKETS:
            metrics = _skew_for_bucket(snap, spot, d, bucket)
            if metrics is None:
                continue
            for k, v in metrics.items():
                row[f"{bucket}_{k}"] = v

        if "front_skew_10otm" in row and "back_skew_10otm" in row:
            row["skew_spread_front_minus_back"] = (
                row["front_skew_10otm"] - row["back_skew_10otm"]
            )
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def summarise_skew(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n_days": 0}
    spread = df["skew_spread_front_minus_back"].dropna()
    return {
        "n_days": len(df),
        "date_start": str(df["date"].min()),
        "date_end": str(df["date"].max()),
        "skew_spread_mean_pp": float(spread.mean()) if len(spread) else None,
        "skew_spread_median_pp": float(spread.median()) if len(spread) else None,
        "skew_spread_p25_pp": float(spread.quantile(0.25)) if len(spread) else None,
        "skew_spread_p75_pp": float(spread.quantile(0.75)) if len(spread) else None,
        "pct_days_spread_gt_5pp": float((spread > 5).mean() * 100) if len(spread) else None,
        "pct_days_spread_gt_10pp": float((spread > 10).mean() * 100) if len(spread) else None,
        "front_skew_mean_pp": float(df["front_skew_10otm"].mean()),
        "back_skew_mean_pp": float(df["back_skew_10otm"].mean()),
    }


def run(out_dir: Path) -> tuple[pd.DataFrame, dict]:
    df = compute_skew_history()
    summary = summarise_skew(df)
    out_path = out_dir / "skew_history.csv"
    df.to_csv(out_path, index=False)
    log.info("Wrote %s (%d rows)", out_path, len(df))
    return df, summary
