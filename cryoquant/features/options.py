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


def _normalize_chain_df(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase columns and map Deribit ingest schema to options feature helpers."""
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    if "option_type" not in out.columns and "is_call" in out.columns:
        out["option_type"] = np.where(out["is_call"].astype(bool), "call", "put")
    return out


def _atm_iv_single(d: date, df: pd.DataFrame, dte_target: int) -> float:
    """Extract ATM IV from one day's chain snapshot."""
    df = _normalize_chain_df(df)

    required = {"expiry", "strike", "option_type", "mark_iv"}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing columns: {required - set(df.columns)}")

    # Parse expiry to date
    if not pd.api.types.is_datetime64_any_dtype(df["expiry"]):
        df["expiry"] = pd.to_datetime(df["expiry"], format="%d%b%y", errors="coerce")
        if df["expiry"].isna().all():
            df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce")
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
    call_iv = float(calls.loc[atm_strike].iloc[0] if isinstance(calls.loc[atm_strike], pd.Series) else calls.loc[atm_strike])
    put_iv = float(puts.loc[atm_strike].iloc[0] if isinstance(puts.loc[atm_strike], pd.Series) else puts.loc[atm_strike])
    return (call_iv + put_iv) / 2


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
    df = _normalize_chain_df(df)
    if not pd.api.types.is_datetime64_any_dtype(df.get("expiry", pd.Series())):
        df["expiry"] = pd.to_datetime(df["expiry"], format="%d%b%y", errors="coerce")
        if df["expiry"].isna().all():
            df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce")
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
    result.name = "vol_of_vol"
    return result


def dvol_rank(dvol: pd.Series, lookback: int = 252) -> pd.Series:
    """Rolling percentile rank of DVOL (IV percentile), same scale as ``rv_rank`` (0–1)."""
    s = _ensure_utc(dvol)
    return s.rolling(lookback, min_periods=lookback // 2).rank(pct=True)


def dvol_features(
    dvol: pd.Series,
    rv: pd.Series,
    *,
    vol_of_vol_window: int = 21,
    rank_lookback_252: int = 252,
    rank_lookback_90: int = 90,
    prefix: str = "",
) -> pd.DataFrame:
    """DVOL-based options features (FEATURE_CATALOG Layer F — dev-trainable).

    Lag: same as ``dvol_30d`` — asof calendar date ``T``, no extra ``shift(1)``.
    ``dvol_rank_*`` uses only DVOL observations ≤ ``T`` in each rolling window.
    """
    dvol_a = _ensure_utc(dvol)
    rv_a = _ensure_utc(rv)
    joined = pd.concat([dvol_a.rename("dvol"), rv_a.rename("rv")], axis=1, sort=True).sort_index()
    joined = joined.dropna(how="all")
    iv_rv = joined["dvol"] - joined["rv"]
    vov = vol_of_vol(joined["dvol"], n=vol_of_vol_window)
    rank_252 = dvol_rank(joined["dvol"], lookback=rank_lookback_252)
    rank_90 = dvol_rank(joined["dvol"], lookback=rank_lookback_90)
    chg_7d = joined["dvol"].pct_change(7) * 100.0
    return pd.DataFrame(
        {
            f"{prefix}dvol_30d": joined["dvol"],
            f"{prefix}iv_minus_rv": iv_rv,
            f"{prefix}dvol_rank_252": rank_252,
            f"{prefix}dvol_rank_90": rank_90,
            f"{prefix}dvol_chg_7d": chg_7d,
            f"{prefix}vol_of_vol": vov,
        }
    )


def build_chain_feature_frame(
    chains: list[tuple[date, pd.DataFrame]],
    *,
    prefix: str = "",
) -> pd.DataFrame:
    """Chain IV/skew/term features indexed by UTC date (single pass over chains)."""
    empty_cols = [f"{prefix}atm_iv_30d", f"{prefix}term_slope", f"{prefix}risk_reversal_25d"]
    if not chains:
        return pd.DataFrame(columns=empty_cols)

    dates: list[date] = []
    atm_vals: list[float] = []
    slope_vals: list[float] = []
    rr_vals: list[float] = []

    for d, df in chains:
        dates.append(d)
        try:
            iv30 = _atm_iv_single(d, df, dte_target=30)
            iv90 = _atm_iv_single(d, df, dte_target=90)
            slope = iv90 / iv30 if iv30 and iv30 > 0 else float("nan")
            rr = _rr_25d_single(d, df)
        except Exception as exc:
            log.debug("chain features failed for %s: %s", d, exc)
            iv30, slope, rr = float("nan"), float("nan"), float("nan")
        atm_vals.append(iv30)
        slope_vals.append(slope)
        rr_vals.append(rr)

    idx = pd.DatetimeIndex(
        [datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d in dates],
        tz="UTC",
    )
    return pd.DataFrame(
        {
            f"{prefix}atm_iv_30d": atm_vals,
            f"{prefix}term_slope": slope_vals,
            f"{prefix}risk_reversal_25d": rr_vals,
        },
        index=idx,
    ).sort_index()


def _ensure_utc(s: pd.Series) -> pd.Series:
    out = s.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out.sort_index()
