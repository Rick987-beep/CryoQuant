"""Overlay 1 — CDX.NA.IG tail insurance signals."""
from __future__ import annotations

import numpy as np
import pandas as pd


def standing_tail_insurance(
    spread_bps: pd.Series,
    *,
    entry_max_bps: float = 65.0,
    exit_bps: float = 100.0,
    max_hold_days: int | None = None,
    skip_roll: pd.Series | None = None,
) -> pd.Series:
    """
    Standing long protection when spread is compressed; exit on stress normalization.

    Enter long (+1) when flat and spread < entry_max_bps.
    Exit when spread >= exit_bps or max_hold_days elapsed.
    """
    vals = spread_bps.values
    skip = skip_roll.values if skip_roll is not None else np.zeros(len(spread_bps), dtype=bool)
    n = len(vals)
    pos = np.zeros(n, dtype=np.float64)
    in_trade = False
    entry_i = 0

    for i in range(n):
        if np.isnan(vals[i]):
            continue
        if not in_trade:
            if vals[i] < entry_max_bps and not skip[i]:
                pos[i] = 1.0
                in_trade = True
                entry_i = i
        else:
            pos[i] = 1.0
            held = i - entry_i
            if vals[i] >= exit_bps:
                in_trade = False
            elif max_hold_days is not None and held >= max_hold_days:
                in_trade = False

    return pd.Series(pos, index=spread_bps.index, name="standing_tail")


def pyramid_tail_insurance(
    spread_bps: pd.Series,
    *,
    entry_max_bps: float = 60.0,
    base_exit_bps: float = 9_999.0,
    addon_entry_bps: float = 100.0,
    addon_retreat_bps: float = 90.0,
    addon_hold_days: int = 30,
    skip_roll: pd.Series | None = None,
) -> pd.Series:
    """
    Standing base leg + stress add-on pyramid.

    Position units: 0 (flat), 1 (base only), 2 (base + add-on). Each unit scales
    ``notional_usd`` in the backtester.

    Base: enter when spread < entry_max_bps; exit when spread >= base_exit_bps.
    Add-on: enter when spread >= addon_entry_bps; exit when spread <= addon_retreat_bps
    or addon_hold_days elapsed.
    """
    vals = spread_bps.values
    skip = skip_roll.values if skip_roll is not None else np.zeros(len(spread_bps), dtype=bool)
    n = len(vals)
    pos = np.zeros(n, dtype=np.float64)
    base_in = False
    addon_in = False
    addon_entry_i = 0

    for i in range(n):
        if np.isnan(vals[i]):
            continue

        if not base_in:
            if vals[i] < entry_max_bps and not skip[i]:
                base_in = True
        elif vals[i] >= base_exit_bps:
            base_in = False

        if not addon_in:
            if vals[i] >= addon_entry_bps:
                addon_in = True
                addon_entry_i = i
        else:
            held = i - addon_entry_i
            if vals[i] <= addon_retreat_bps or held >= addon_hold_days:
                addon_in = False

        pos[i] = (1.0 if base_in else 0.0) + (1.0 if addon_in else 0.0)

    return pd.Series(pos, index=spread_bps.index, name="pyramid_tail")


def tail_hold_on_spike(
    spread_bps: pd.Series,
    *,
    move_thresh: float = 10.0,
    trail_pct: float = 0.25,
    max_hold: int = 60,
    max_level: float = 70.0,
) -> pd.Series:
    """Reactive tail hold (IndicatorBench J-style) for comparison."""
    pct = spread_bps.pct_change() * 100
    vals = spread_bps.values
    pct_v = pct.values
    pos = pd.Series(0.0, index=spread_bps.index, name="tail_hold")
    n = len(vals)
    i = 0
    while i < n - 1:
        mv = pct_v[i]
        if np.isnan(mv) or vals[i] >= max_level:
            i += 1
            continue
        if mv >= move_thresh:
            peak = vals[i]
            j = i + 1
            end = min(i + max_hold, n - 1)
            while j <= end:
                pos.iloc[j] = 1.0
                if vals[j] > peak:
                    peak = vals[j]
                if vals[j] < peak * (1.0 - trail_pct):
                    break
                j += 1
            i = j + 1
        else:
            i += 1
    return pos
