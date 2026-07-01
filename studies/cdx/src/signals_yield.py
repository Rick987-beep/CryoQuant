"""Overlay 2 — CDX.NA.IG yield book strategies (Y1–Y14).

Each function returns a position series:
  -1  = short protection (collect carry)
   0  = flat
 fractional values allowed (Y9 partial notional)

See PLAN.md § Yield strategy backlog for definitions.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .yield_gates import (
    apply_tail_mutex,
    calm_allowed,
    consecutive_true,
    is_local_peak,
    pct_chg_n,
)

_INDICATORBENCH = Path(__file__).resolve().parents[1] / "input" / "indicatorbench" / "cdx"
if str(_INDICATORBENCH) not in sys.path:
    sys.path.insert(0, str(_INDICATORBENCH))

from signals import sig_zscore_fade  # noqa: E402

YieldFn = Callable[..., pd.Series]


def _align_features(
    spread_bps: pd.Series,
    features: pd.DataFrame | None,
) -> pd.DataFrame:
    if features is not None:
        return features.reindex(spread_bps.index)
    return pd.DataFrame(index=spread_bps.index)


def _gate_kwargs(
    spread_bps: pd.Series,
    features: pd.DataFrame | None,
    *,
    stress_bps: float,
    require_velocity_low: bool,
    tail_position: pd.Series | None,
    skip_roll: bool,
    extra_block: pd.Series | None = None,
) -> dict:
    feat = _align_features(spread_bps, features)
    skip = feat["is_roll_window"] if skip_roll and "is_roll_window" in feat.columns else None
    velocity = feat["regime_velocity"] if "regime_velocity" in feat.columns else None
    return {
        "stress_bps": stress_bps,
        "regime_velocity": velocity,
        "require_velocity_low": require_velocity_low,
        "skip_roll": skip,
        "tail_position": tail_position,
        "extra_block": extra_block,
    }


def _state_machine_short(
    spread_bps: pd.Series,
    allowed: pd.Series,
    *,
    entry_signal: pd.Series,
    exit_signal: pd.Series,
    min_hold_days: int = 0,
    position_value: float = -1.0,
    name: str = "yield",
) -> pd.Series:
    """Generic short state machine with gate-forced exit."""
    n = len(spread_bps)
    pos = np.zeros(n, dtype=np.float64)
    in_trade = False
    entry_i = 0
    ent = entry_signal.fillna(False).values
    ext = exit_signal.fillna(False).values
    allow = allowed.fillna(False).values

    for i in range(n):
        if not allow[i]:
            in_trade = False
            continue
        if not in_trade:
            if ent[i]:
                pos[i] = position_value
                in_trade = True
                entry_i = i
        else:
            pos[i] = position_value
            held = i - entry_i
            if held >= min_hold_days and ext[i]:
                in_trade = False

    return pd.Series(pos, index=spread_bps.index, name=name)


# ── Y1: Calm underwriter (benchmark) ─────────────────────────────────────────

def yield_calm_underwriter(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y1 — short whenever universal calm gates pass (stateless daily)."""
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
        ),
    )
    pos = pd.Series(np.where(allowed, -1.0, 0.0), index=spread_bps.index)
    return pos.rename("Y1_calm_underwriter")


# ── Y2: Band trader ───────────────────────────────────────────────────────────

def yield_band_trader(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    band_lo: float = 52.0,
    band_hi: float = 78.0,
    entry_bps: float = 72.0,
    exit_bps: float = 62.0,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y2 — short above entry_bps inside band; cover below exit_bps."""
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
        ),
    )
    in_band = spread_bps.between(band_lo, band_hi, inclusive="both")
    allowed &= in_band.fillna(False)

    entry = spread_bps >= entry_bps
    exit_sig = spread_bps <= exit_bps
    return _state_machine_short(
        spread_bps, allowed,
        entry_signal=entry,
        exit_signal=exit_sig,
        name="Y2_band_trader",
    )


# ── Y3: Compression rider ─────────────────────────────────────────────────────

def yield_compression_rider(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    lookback_days: int = 3,
    consecutive_days: int = 2,
    min_hold_days: int = 3,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y3 — short while multi-day spread momentum is negative (tightening)."""
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
        ),
    )
    chg = pct_chg_n(spread_bps, lookback_days)
    tightening = consecutive_true(chg < 0, consecutive_days)
    widening = chg > 0

    return _state_machine_short(
        spread_bps, allowed,
        entry_signal=tightening,
        exit_signal=widening,
        min_hold_days=min_hold_days,
        name="Y3_compression_rider",
    )


# ── Y4: Tail/yield mutex (wrapper) ────────────────────────────────────────────

def yield_with_tail_mutex(
    position: pd.Series,
    tail_position: pd.Series,
) -> pd.Series:
    """Y4 — force flat when tail holds long protection."""
    return apply_tail_mutex(position, tail_position).rename("Y4_tail_mutex")


# ── Y5: Time-boxed carry scalp ────────────────────────────────────────────────

def yield_timeboxed_scalp(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    hold_days: int = 10,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y5 — enter short when gates pass; exit after fixed hold_days."""
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
        ),
    )
    n = len(spread_bps)
    pos = np.zeros(n, dtype=np.float64)
    in_trade = False
    entry_i = 0
    allow = allowed.fillna(False).values

    for i in range(n):
        if not allow[i]:
            in_trade = False
            continue
        if not in_trade:
            pos[i] = -1.0
            in_trade = True
            entry_i = i
        else:
            pos[i] = -1.0
            if i - entry_i >= hold_days - 1:
                in_trade = False

    return pd.Series(pos, index=spread_bps.index, name="Y5_timeboxed_scalp")


# ── Y6: Peak-confirmed fade ───────────────────────────────────────────────────

def yield_peak_confirmed_fade(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    peak_window: int = 20,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y6 — short after local peak AND 3d change turns negative."""
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
        ),
    )
    had_peak = is_local_peak(spread_bps, window=peak_window)
    # Peak must have occurred within last `peak_window` bars (causal)
    recent_peak = had_peak.rolling(peak_window, min_periods=1).max().astype(bool)
    chg3 = pct_chg_n(spread_bps, 3)
    entry = recent_peak & (chg3 < 0)
    exit_sig = chg3 >= 0

    return _state_machine_short(
        spread_bps, allowed,
        entry_signal=entry,
        exit_signal=exit_sig,
        name="Y6_peak_fade",
    )


# ── Y7: Fade the rip ──────────────────────────────────────────────────────────

def yield_fade_the_rip(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    panel: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    rip_bps: float = 6.0,
    vix_jump_pct: float = 20.0,
    hold_days: int = 10,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y7 — short after large 1d widening if VIX did not spike same day."""
    feat = _align_features(spread_bps, features)
    pan = panel.reindex(spread_bps.index) if panel is not None else pd.DataFrame(index=spread_bps.index)

    vix_block = pd.Series(False, index=spread_bps.index)
    if "VIX" in pan.columns:
        vix_chg = pan["VIX"].pct_change() * 100.0
        vix_block = vix_chg >= vix_jump_pct

    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
            extra_block=vix_block,
        ),
    )
    d1 = spread_bps.diff()
    rip = d1 >= rip_bps

    n = len(spread_bps)
    pos = np.zeros(n, dtype=np.float64)
    in_trade = False
    entry_i = 0
    allow = allowed.fillna(False).values
    rip_v = rip.fillna(False).values

    for i in range(n):
        if not allow[i]:
            in_trade = False
            continue
        if not in_trade:
            if rip_v[i]:
                pos[i] = -1.0
                in_trade = True
                entry_i = i
        else:
            pos[i] = -1.0
            if i - entry_i >= hold_days - 1:
                in_trade = False

    return pd.Series(pos, index=spread_bps.index, name="Y7_fade_rip")


# ── Y8: Velocity filter on underwriter ──────────────────────────────────────────

def yield_velocity_filtered_underwriter(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    grind_days: int = 3,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y8 — Y1 plus block when 3d % change > 0 for grind_days consecutive days."""
    chg3 = pct_chg_n(spread_bps, 3)
    grind = consecutive_true(chg3 > 0, grind_days)
    base = yield_calm_underwriter(
        spread_bps,
        features=features,
        tail_position=tail_position,
        stress_bps=stress_bps,
        require_velocity_low=require_velocity_low,
        skip_roll=skip_roll,
    )
    out = base.where(~grind.fillna(False), 0.0)
    return out.fillna(0.0).rename("Y8_velocity_filter")


# ── Y9: Partial notional yield ────────────────────────────────────────────────

def yield_partial_notional(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    tight_bps: float = 55.0,
    scale_tight: float = 0.5,
    scale_normal: float = 1.0,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y9 — scaled short size: lighter in very tight spreads, full in normal calm."""
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
        ),
    )
    scale = np.where(spread_bps < tight_bps, scale_tight, scale_normal)
    pos = np.where(allowed, -1.0 * scale, 0.0)
    return pd.Series(pos, index=spread_bps.index, name="Y9_partial_notional")


# ── Y10–Y12: Cross-asset conditional ─────────────────────────────────────────

def _qqq_return(spread_bps: pd.Series, panel: pd.DataFrame | None, window: int) -> pd.Series:
    if panel is None or "QQQ" not in panel.columns:
        return pd.Series(np.nan, index=spread_bps.index)
    px = panel["QQQ"].reindex(spread_bps.index)
    return px.pct_change(window) * 100.0


def _vix_below_median(spread_bps: pd.Series, panel: pd.DataFrame | None, window: int) -> pd.Series:
    if panel is None or "VIX" not in panel.columns:
        return pd.Series(False, index=spread_bps.index)
    vix = panel["VIX"].reindex(spread_bps.index)
    med = vix.rolling(window, min_periods=window).median()
    return (vix < med) & vix.notna() & med.notna()


def yield_risk_on_underwriter(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    panel: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    qqq_window: int = 20,
    vix_window: int = 20,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y10 — short when QQQ up, VIX below its median, and calm gates pass."""
    qqq_ret = _qqq_return(spread_bps, panel, qqq_window)
    risk_on = (qqq_ret > 0) & _vix_below_median(spread_bps, panel, vix_window)
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
            extra_block=~risk_on.fillna(False),
        ),
    )
    pos = pd.Series(np.where(allowed, -1.0, 0.0), index=spread_bps.index)
    return pos.rename("Y10_risk_on")


def yield_equity_credit_divergence(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    panel: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    window: int = 20,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y11 — short when QQQ at window high but spread above window low."""
    if panel is None or "QQQ" not in panel.columns:
        return pd.Series(0.0, index=spread_bps.index, name="Y11_divergence")

    pan = panel.reindex(spread_bps.index)
    qqq = pan["QQQ"]
    qqq_high = qqq >= qqq.rolling(window, min_periods=window).max()
    spread_low = spread_bps <= spread_bps.rolling(window, min_periods=window).min()
    divergence = qqq_high.fillna(False) & (~spread_low.fillna(True))

    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
            extra_block=~divergence,
        ),
    )
    pos = pd.Series(np.where(allowed, -1.0, 0.0), index=spread_bps.index)
    return pos.rename("Y11_divergence")


def yield_rates_aware(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    panel: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    spread_lo: float = 65.0,
    spread_hi: float = 78.0,
    tlt_window: int = 5,
    tlt_shock_pct: float = -2.0,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y12 — short when TLT rising and spread in upper calm band; block on TLT shock."""
    tlt_block = pd.Series(False, index=spread_bps.index)
    tlt_rising = pd.Series(False, index=spread_bps.index)
    if panel is not None and "TLT" in panel.columns:
        tlt = panel["TLT"].reindex(spread_bps.index)
        tlt_ret = tlt.pct_change(tlt_window) * 100.0
        tlt_rising = tlt_ret > 0
        tlt_block = tlt.pct_change() * 100.0 <= tlt_shock_pct

    in_band = spread_bps.between(spread_lo, spread_hi, inclusive="both")
    signal = in_band.fillna(False) & tlt_rising.fillna(False)

    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=tail_position,
            skip_roll=skip_roll,
            extra_block=tlt_block,
        ),
    )
    pos = pd.Series(np.where(allowed & signal, -1.0, 0.0), index=spread_bps.index)
    return pos.rename("Y12_rates_aware")


# ── Y13–Y14: Calendar / coordination ──────────────────────────────────────────

def yield_roll_season_carry(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    require_velocity_low: bool = True,
) -> pd.Series:
    """Y13 — Y1 but flat during IMM roll windows."""
    return yield_calm_underwriter(
        spread_bps,
        features=features,
        tail_position=tail_position,
        stress_bps=stress_bps,
        require_velocity_low=require_velocity_low,
        skip_roll=True,
    ).rename("Y13_roll_season")


def yield_handoff_to_tail(
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    stress_bps: float = 80.0,
    tight_entry_bps: float = 55.0,
    handoff_bps: float = 60.0,
    require_velocity_low: bool = True,
    skip_roll: bool = False,
) -> pd.Series:
    """Y14 — aggressive short below tight_entry; cover at handoff or when tail enters."""
    allowed = calm_allowed(
        spread_bps,
        **_gate_kwargs(
            spread_bps, features,
            stress_bps=stress_bps,
            require_velocity_low=require_velocity_low,
            tail_position=None,  # manage tail exit inside loop
            skip_roll=skip_roll,
        ),
    )
    tail = (
        tail_position.reindex(spread_bps.index).fillna(0.0)
        if tail_position is not None
        else pd.Series(0.0, index=spread_bps.index)
    )
    n = len(spread_bps)
    pos = np.zeros(n, dtype=np.float64)
    in_trade = False
    vals = spread_bps.values
    allow = allowed.values
    tail_v = tail.values

    for i in range(n):
        if np.isnan(vals[i]) or not allow[i] or tail_v[i] != 0:
            in_trade = False
            continue
        if not in_trade:
            if vals[i] < tight_entry_bps:
                pos[i] = -1.0
                in_trade = True
        else:
            pos[i] = -1.0
            if vals[i] >= handoff_bps:
                in_trade = False

    return pd.Series(pos, index=spread_bps.index, name="Y14_handoff")


# ── Legacy v1 baseline ────────────────────────────────────────────────────────

def yield_zscore_fade(
    spread_bps: pd.Series,
    *,
    disable_above_bps: float = 80.0,
    z_window: int = 63,
    z_enter: float = 2.5,
    z_exit: float = 0.5,
    z_stop: float = 4.5,
    confirm: int = 2,
) -> pd.Series:
    """Phase 3 v1 baseline — IndicatorBench z-score fade + stress gate."""
    raw = sig_zscore_fade(
        spread_bps,
        z_window=z_window,
        z_enter=z_enter,
        z_exit=z_exit,
        z_stop=z_stop,
        confirm=confirm,
    )
    stressed = spread_bps >= disable_above_bps
    return raw.where(~stressed, 0.0).fillna(0.0).rename("yield_zscore_fade")


# ── Registry ──────────────────────────────────────────────────────────────────

YIELD_STRATEGY_REGISTRY: dict[str, YieldFn] = {
    "Y1_calm_underwriter": yield_calm_underwriter,
    "Y2_band_trader": yield_band_trader,
    "Y3_compression_rider": yield_compression_rider,
    "Y5_timeboxed_scalp": yield_timeboxed_scalp,
    "Y6_peak_fade": yield_peak_confirmed_fade,
    "Y7_fade_rip": yield_fade_the_rip,
    "Y8_velocity_filter": yield_velocity_filtered_underwriter,
    "Y9_partial_notional": yield_partial_notional,
    "Y10_risk_on": yield_risk_on_underwriter,
    "Y11_divergence": yield_equity_credit_divergence,
    "Y12_rates_aware": yield_rates_aware,
    "Y13_roll_season": yield_roll_season_carry,
    "Y14_handoff": yield_handoff_to_tail,
    "yield_zscore_fade": yield_zscore_fade,
}


def run_yield_strategy(
    name: str,
    spread_bps: pd.Series,
    *,
    features: pd.DataFrame | None = None,
    panel: pd.DataFrame | None = None,
    tail_position: pd.Series | None = None,
    **kwargs,
) -> pd.Series:
    """Dispatch a registered yield strategy by name."""
    if name not in YIELD_STRATEGY_REGISTRY:
        raise KeyError(f"Unknown yield strategy: {name}")
    fn = YIELD_STRATEGY_REGISTRY[name]
    candidates = {
        "spread_bps": spread_bps,
        "features": features,
        "panel": panel,
        "tail_position": tail_position,
        **kwargs,
    }
    params = inspect.signature(fn).parameters
    filtered = {k: v for k, v in candidates.items() if k in params}
    return fn(**filtered)
