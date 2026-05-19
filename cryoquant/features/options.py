"""Options-derived features (Tier-2).

Input: per-day chain DataFrames from deribit_options.load_chain().
Output: time series of option market structure metrics.

All functions accept a list of (date, chain_df) pairs or a concatenated
chain with a "date" column, and return a pd.Series or pd.DataFrame indexed
by UTC date.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _to_date_series(dates: list[date], values: list[float], name: str) -> pd.Series:
    idx = pd.DatetimeIndex([datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d in dates], name="date")
    return pd.Series(values, index=idx, name=name, dtype=float)


def atm_iv(chains: list[tuple[date, pd.DataFrame]], dte_target: int = 30) -> pd.Series:
    """ATM IV (mark_iv) for the nearest expiry to dte_target days.

    Args:
        chains: List of (date, chain_df) where chain_df has columns
                instrument_name, expiry, strike, option_type, mark_iv.
        dte_target: Target DTE in days.

    Returns:
        pd.Series indexed by UTC date.
    """
    dates, ivs = [], []
    for d, df in chains:
        try:
            iv = _atm_iv_single(d, df, dte_target)
        except Exception as e:
            log.debug("atm_iv failed for %s: %s", d, e)
            iv = float("nan")
        dates.append(d)
        ivs.append(iv)
    return _to_date_series(dates, ivs, f"atm_iv_dte{dte_target}")


def _atm_iv_single(d: date, df: pd.DataFrame, dte_target: int) -> float:
    """Extract ATM IV from one day's chain snapshot."""
    # Normalise column names to lowercase
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    required = {"expiry", "strike", "option_type", "mark_iv"}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing columns: {required - set(df.columns)}")

    # Parse expiry to date
    if not pd.api.types.is_datetime64_any_dtype(df["expiry"]):
        df["expiry"] = pd.to_datetime(df["expiry"])
    df["dte"] = (df["expiry"].dt.date.apply(lambda e: (e - d).days))

    # Select nearest expiry to dte_target
    df = df[df["dte"] > 0]
    if df.empty:
        return float("nan")
    expiry_dtes = df["dte"].unique()
    nearest_dte = expiry_dtes[np.argmin(np.abs(expiry_dtes - dte_target))]
    subset = df[df["dte"] == nearest_dte]

    # Find spot price as the strike where call IV ≈ put IV (ATM)
    # Simpler: pick the strike with the minimum absolute difference between
    # call and put mark_iv, then take the average of the two
    calls = subset[subset["option_type"].str.lower() == "call"].set_index("strike")["mark_iv"]
    puts  = subset[subset["option_type"].str.lower() == "put"].set_index("strike")["mark_iv"]
    common = calls.index.intersection(puts.index)
    if common.empty:
        return float(subset["mark_iv"].median())

    diff = (calls.loc[common] - puts.loc[common]).abs()
    atm_strike = diff.idxmin()
    return float((calls.loc[atm_strike] + puts.loc[atm_strike]) / 2)


def iv_minus_rv(
    atm_iv_series: pd.Series,
    rv_series: pd.Series,
) -> pd.Series:
    """IV richness: ATM IV minus realised vol, on a common daily index.

    Both inputs must be percentage (annualised) values.
    """
    joined = pd.concat([atm_iv_series.rename("iv"), rv_series.rename("rv")], axis=1)
    joined = joined.ffill().dropna()
    result = joined["iv"] - joined["rv"]
    result.name = "iv_minus_rv"
    return result


def term_slope(chains: list[tuple[date, pd.DataFrame]]) -> pd.Series:
    """Front/back ATM IV ratio (term structure slope).

    Computes ATM IV at 30d and 90d, returns the 90d/30d ratio.
    > 1 => normal contango (back > front); < 1 => backwardation.
    """
    dates, slopes = [], []
    for d, df in chains:
        iv_front = _atm_iv_single(d, df, dte_target=30)
        iv_back  = _atm_iv_single(d, df, dte_target=90)
        slope = iv_back / iv_front if iv_front and iv_front > 0 else float("nan")
        dates.append(d)
        slopes.append(slope)
    return _to_date_series(dates, slopes, "term_slope")


def risk_reversal_25d(chains: list[tuple[date, pd.DataFrame]]) -> pd.Series:
    """25-delta risk reversal: call_iv_25d - put_iv_25d.

    Positive => calls bid up vs puts (bullish skew).
    Reads mark_iv for strikes near 25-delta; approximated as nearest
    OTM call / OTM put at ±25% from ATM strike.
    """
    dates, rrs = [], []
    for d, df in chains:
        try:
            rr = _rr_25d_single(d, df)
        except Exception:
            rr = float("nan")
        dates.append(d)
        rrs.append(rr)
    return _to_date_series(dates, rrs, "risk_reversal_25d")


def _rr_25d_single(d: date, df: pd.DataFrame) -> float:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if not pd.api.types.is_datetime64_any_dtype(df.get("expiry", pd.Series())):
        df["expiry"] = pd.to_datetime(df["expiry"])
    df["dte"] = df["expiry"].dt.date.apply(lambda e: (e - d).days)
    df = df[df["dte"] > 0]
    expiry_dtes = df["dte"].unique()
    nearest_dte = expiry_dtes[np.argmin(np.abs(expiry_dtes - 30))]
    subset = df[df["dte"] == nearest_dte]
    calls = subset[subset["option_type"].str.lower() == "call"].sort_values("strike")
    puts  = subset[subset["option_type"].str.lower() == "put"].sort_values("strike")
    if calls.empty or puts.empty:
        return float("nan")
    # ATM ≈ mid of strikes range
    atm = (calls["strike"].median() + puts["strike"].median()) / 2
    # 25d OTM call: first call above ATM * 1.15 (rough 25d proxy)
    otm_call = calls[calls["strike"] > atm * 1.05]
    otm_put  = puts[puts["strike"] < atm * 0.95]
    if otm_call.empty or otm_put.empty:
        return float("nan")
    return float(otm_call.iloc[0]["mark_iv"] - otm_put.iloc[-1]["mark_iv"])


def vol_of_vol(atm_iv_series: pd.Series, n: int = 21) -> pd.Series:
    """Rolling std of ATM IV (vol-of-vol)."""
    result = atm_iv_series.rolling(n, min_periods=n // 2).std()
    result.name = f"vol_of_vol_{n}"
    return result
