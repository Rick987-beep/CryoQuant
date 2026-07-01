"""Shared regime gates for CDX.NA.IG yield overlay strategies.

Timing convention (matches IndicatorBench / backtest_cds):
  position[t] is decided using information available at the close of bar t.
  PnL for bar t uses position[t] against spread[t] and d_spread[t].

All gate inputs must be known at or before t — never use future rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .paths import load_config


def stress_spread_bps(cfg: dict | None = None) -> float:
    cfg = cfg or load_config()
    return float(cfg["regimes"]["level"]["normal"])


def calm_allowed(
    spread_bps: pd.Series,
    *,
    stress_bps: float | None = None,
    regime_velocity: pd.Series | None = None,
    require_velocity_low: bool = True,
    skip_roll: pd.Series | None = None,
    tail_position: pd.Series | None = None,
    extra_block: pd.Series | None = None,
) -> pd.Series:
    """
    Boolean mask: True when yield short is permitted by universal gates.

    Conservative defaults: unknown spread or unknown velocity → blocked.
    """
    stress = stress_bps if stress_bps is not None else stress_spread_bps()
    allowed = spread_bps.notna() & (spread_bps < stress)

    if require_velocity_low:
        if regime_velocity is None:
            allowed &= False
        else:
            # "Calm velocity" = not in high-stress bucket (low or moderate)
            allowed &= regime_velocity.notna() & regime_velocity.isin(["low", "moderate"])

    if skip_roll is not None:
        allowed &= ~skip_roll.reindex(spread_bps.index).fillna(False).astype(bool)

    if tail_position is not None:
        allowed &= tail_position.reindex(spread_bps.index).fillna(0.0) == 0.0

    if extra_block is not None:
        allowed &= ~extra_block.reindex(spread_bps.index).fillna(False).astype(bool)

    return allowed.rename("calm_allowed")


def apply_tail_mutex(
    position: pd.Series,
    tail_position: pd.Series | None,
) -> pd.Series:
    """Force flat whenever tail overlay holds long protection."""
    if tail_position is None:
        return position
    blocked = tail_position.reindex(position.index).fillna(0.0) != 0.0
    out = position.where(~blocked, 0.0)
    return out.fillna(0.0)


def pct_chg_n(spread_bps: pd.Series, n: int) -> pd.Series:
    """n-day percent change in spread (%), causal at each bar."""
    return spread_bps.pct_change(n) * 100.0


def consecutive_true(mask: pd.Series, n: int) -> pd.Series:
    """True when the last n observations (inclusive) are all True."""
    if n <= 1:
        return mask.fillna(False).astype(bool)
    arr = mask.fillna(False).astype(bool).values
    out = np.zeros(len(arr), dtype=bool)
    for i in range(n - 1, len(arr)):
        out[i] = bool(arr[i - n + 1 : i + 1].all())
    return pd.Series(out, index=mask.index)


def past_rolling_max(series: pd.Series, window: int) -> pd.Series:
    """Rolling max over the prior `window` bars including current (causal at close t)."""
    return series.rolling(window, min_periods=window).max()


def is_local_peak(spread_bps: pd.Series, *, window: int = 20) -> pd.Series:
    """
    True at t when spread[t] equals the rolling max over [t-window+1, t].

  Requires a full window of history; early bars are False.
    """
    rmax = past_rolling_max(spread_bps, window)
    return (spread_bps >= rmax) & spread_bps.notna() & rmax.notna()
