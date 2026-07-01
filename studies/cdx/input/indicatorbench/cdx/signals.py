"""
signals.py — CDX NA IG entry/exit signal generators.
All functions take a spread pd.Series (DatetimeIndex, ascending) and return
a positions pd.Series of the same index:
  +1 = long spread (buy protection, profit if spread widens)
  -1 = short spread (sell protection, profit if spread compresses)
   0 = flat

Timing convention: pos[t] is determined using information available at close
of bar t. The backtester applies it to the return from t→t+1 (next close).
"""
from __future__ import annotations
import numpy as np
import pandas as pd


# ── Building-block indicators ─────────────────────────────────────────────────

def zscore(s: pd.Series, window: int) -> pd.Series:
    mu  = s.rolling(window).mean()
    sig = s.rolling(window).std()
    return (s - mu) / sig.replace(0, np.nan)


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta    = s.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def bb(s: pd.Series, period: int = 20, mult: float = 2.0):
    mid   = s.rolling(period).mean()
    sigma = s.rolling(period).std()
    return mid + mult * sigma, mid, mid - mult * sigma


# ── Strategy A — Z-score spike fade (short after confirmed spike) ─────────────

def sig_zscore_fade(
    s: pd.Series,
    *,
    z_window: int   = 63,
    z_enter: float  = 2.5,
    z_exit: float   = 0.5,
    z_stop: float   = 4.5,
    confirm: int    = 2,
) -> pd.Series:
    """
    Short spread when rolling z-score has been ≥ z_enter for `confirm` consecutive
    days (avoids catching the very first day of a spike).
    Exit: z-score drops below z_exit (mean reversion achieved).
    Stop: z-score exceeds z_stop (runaway stress — cut).
    """
    z   = zscore(s, z_window)
    z_v = z.values
    n   = len(s)
    pos = np.zeros(n, dtype=np.float64)

    in_trade = False
    for i in range(confirm, n - 1):
        if np.isnan(z_v[i]):
            continue
        if not in_trade:
            # all last `confirm` bars must be >= z_enter
            if all(
                not np.isnan(z_v[i - k]) and z_v[i - k] >= z_enter
                for k in range(confirm)
            ):
                pos[i]   = -1
                in_trade = True
        else:
            pos[i] = -1
            if z_v[i] <= z_exit or z_v[i] >= z_stop:
                pos[i]   = 0
                in_trade = False

    return pd.Series(pos, index=s.index, name="zscore_fade")


# ── Strategy A2 — Peak-detect fade (enter short on z-score peak) ──────────────

def sig_zscore_peak_fade(
    s: pd.Series,
    *,
    z_window: int   = 63,
    z_enter: float  = 2.5,
    z_exit: float   = 0.5,
    z_stop: float   = 4.5,
) -> pd.Series:
    """
    Enter short when z-score was above z_enter yesterday but has started falling
    today (peak detection — better timing than confirmation-delay approach).
    Exit same as A.
    """
    z   = zscore(s, z_window)
    z_v = z.values
    n   = len(s)
    pos = np.zeros(n, dtype=np.float64)

    in_trade = False
    for i in range(1, n - 1):
        if np.isnan(z_v[i]) or np.isnan(z_v[i - 1]):
            continue
        if not in_trade:
            # previous bar was above threshold AND today z is lower (turning down)
            if z_v[i - 1] >= z_enter and z_v[i] < z_v[i - 1]:
                pos[i]   = -1
                in_trade = True
        else:
            pos[i] = -1
            if z_v[i] <= z_exit or z_v[i] >= z_stop:
                pos[i]   = 0
                in_trade = False

    return pd.Series(pos, index=s.index, name="zscore_peak_fade")


# ── Strategy B — Spike onset momentum (long after large single-day move) ──────

def sig_spike_onset(
    s: pd.Series,
    *,
    move_thresh: float = 6.0,
    hold_days: int     = 5,
    vol_filter: bool   = True,
    calm_mult: float   = 1.5,
) -> pd.Series:
    """
    Long spread (buy protection) on the day a large daily move occurs.
    Optional vol_filter: only fire if prior 10-day vol is calm (< calm_mult × long-run vol).
    Hold for exactly hold_days bars then close.
    """
    pct      = s.pct_change() * 100
    pct_v    = pct.values
    roll_vol = pct.rolling(10).std().values
    long_vol = pct.rolling(63).std().values
    n        = len(s)
    pos      = np.zeros(n, dtype=np.float64)

    hold_left = 0
    for i in range(1, n - 1):
        if hold_left > 0:
            pos[i]     = 1
            hold_left -= 1
        elif not np.isnan(pct_v[i]):
            calm = True
            if vol_filter and not np.isnan(roll_vol[i]) and not np.isnan(long_vol[i]):
                calm = roll_vol[i] < calm_mult * long_vol[i]
            if pct_v[i] >= move_thresh and calm:
                pos[i]    = 1
                hold_left = hold_days - 1

    return pd.Series(pos, index=s.index, name="spike_onset")


# ── Strategy C — Bollinger Band fade (short above upper, long below lower) ────

def sig_bb_fade(
    s: pd.Series,
    *,
    period: int   = 20,
    mult: float   = 2.0,
    fade_only: bool = True,
) -> pd.Series:
    """
    Short when spread closes above BB upper band.
    If fade_only=True: only short (no long below lower band).
    Exit when spread returns to mid-band.
    """
    upper, mid, lower = bb(s, period, mult)
    n   = len(s)
    pos = np.zeros(n, dtype=np.float64)
    sv  = s.values
    uv  = upper.values
    mv  = mid.values
    lv  = lower.values

    in_trade = 0  # 0=flat, 1=long, -1=short
    for i in range(period, n - 1):
        if np.isnan(uv[i]):
            continue
        if in_trade == 0:
            if sv[i] > uv[i]:
                pos[i]   = -1
                in_trade = -1
            elif not fade_only and sv[i] < lv[i]:
                pos[i]   = 1
                in_trade = 1
        elif in_trade == -1:
            if sv[i] < mv[i]:
                pos[i]   = 0
                in_trade = 0
            else:
                pos[i] = -1
        elif in_trade == 1:
            if sv[i] > mv[i]:
                pos[i]   = 0
                in_trade = 0
            else:
                pos[i] = 1

    return pd.Series(pos, index=s.index, name="bb_fade")


# ── Strategy D — RSI fade (short when RSI overbought) ────────────────────────

def sig_rsi_fade(
    s: pd.Series,
    *,
    period: int       = 14,
    rsi_enter: float  = 70.0,
    rsi_exit: float   = 50.0,
) -> pd.Series:
    """
    Short spread when RSI ≥ rsi_enter (spread overbought = about to compress).
    Exit when RSI drops below rsi_exit.
    """
    r   = rsi(s, period)
    rv  = r.values
    n   = len(s)
    pos = np.zeros(n, dtype=np.float64)

    in_trade = False
    for i in range(period, n - 1):
        if np.isnan(rv[i]):
            continue
        if not in_trade:
            if rv[i] >= rsi_enter:
                pos[i]   = -1
                in_trade = True
        else:
            pos[i] = -1
            if rv[i] <= rsi_exit:
                pos[i]   = 0
                in_trade = False

    return pd.Series(pos, index=s.index, name="rsi_fade")


# ── Strategy E — OU continuous (always positioned by z-score sign) ────────────

def sig_ou_continuous(
    s: pd.Series,
    *,
    z_window: int    = 63,
    z_thresh: float  = 1.5,
) -> pd.Series:
    """
    Always carry a position proportional to z-score:
      z >  z_thresh → short (above equilibrium, mean-revert down)
      z < -z_thresh → long  (below equilibrium, mean-revert up)
      |z| < z_thresh → flat
    """
    z   = zscore(s, z_window)
    pos = pd.Series(0.0, index=s.index, name="ou_continuous")
    pos[z >  z_thresh] = -1
    pos[z < -z_thresh] =  1
    return pos


# ── Strategy G — Z-score fade with max-hold cap ──────────────────────────────

def sig_zscore_fade_capped(
    s: pd.Series,
    *,
    z_window: int   = 63,
    z_enter: float  = 2.5,
    z_exit: float   = 0.5,
    z_stop: float   = 4.5,
    confirm: int    = 2,
    max_hold: int   = 40,
) -> pd.Series:
    """
    Like sig_zscore_fade but caps max hold at max_hold bars — limits drawdown
    when mean reversion takes too long (avoids riding stress episodes to infinity).
    """
    z   = zscore(s, z_window)
    z_v = z.values
    n   = len(s)
    pos = np.zeros(n, dtype=np.float64)

    in_trade    = False
    bars_held   = 0
    for i in range(confirm, n - 1):
        if np.isnan(z_v[i]):
            continue
        if not in_trade:
            if all(
                not np.isnan(z_v[i - k]) and z_v[i - k] >= z_enter
                for k in range(confirm)
            ):
                pos[i]    = -1
                in_trade  = True
                bars_held = 1
        else:
            bars_held += 1
            pos[i] = -1
            if z_v[i] <= z_exit or z_v[i] >= z_stop or bars_held >= max_hold:
                pos[i]   = 0
                in_trade = False

    return pd.Series(pos, index=s.index, name="zscore_fade_capped")


# ── Strategy H — Two-phase: onset long → peak fade short ─────────────────────

def sig_two_phase(
    s: pd.Series,
    *,
    # onset params
    move_thresh: float = 8.0,
    onset_hold: int    = 5,
    # fade params
    z_window: int      = 63,
    z_enter: float     = 2.0,
    fade_hold: int     = 30,
    z_exit: float      = 0.5,
    z_stop: float      = 4.5,
) -> pd.Series:
    """
    Phase 1 (onset): Long spread when daily move ≥ move_thresh%.
                     Hold for onset_hold bars.
    Phase 2 (fade):  After phase-1 unwinds, short if z-score ≥ z_enter.
                     Hold up to fade_hold bars or until z reverts.
    Phases are non-overlapping; onset takes priority.
    """
    pct  = s.pct_change() * 100
    z    = zscore(s, z_window)
    pv   = pct.values
    zv   = z.values
    n    = len(s)
    pos  = np.zeros(n, dtype=np.float64)

    phase       = 0   # 0=flat, 1=onset-long, 2=fade-short
    bars_held   = 0

    for i in range(max(z_window, 1), n - 1):
        if phase == 0:
            # Check onset trigger first
            if not np.isnan(pv[i]) and pv[i] >= move_thresh:
                pos[i]    = 1
                phase     = 1
                bars_held = 1
            # Then check fade trigger
            elif not np.isnan(zv[i]) and zv[i] >= z_enter:
                pos[i]    = -1
                phase     = 2
                bars_held = 1
        elif phase == 1:
            bars_held += 1
            pos[i] = 1
            if bars_held >= onset_hold:
                pos[i] = 0
                phase  = 0
        elif phase == 2:
            bars_held += 1
            pos[i] = -1
            if zv[i] <= z_exit or zv[i] >= z_stop or bars_held >= fade_hold:
                pos[i] = 0
                phase  = 0

    return pd.Series(pos, index=s.index, name="two_phase")


# ── Strategy I — Regime-filtered spike fade ───────────────────────────────────

def sig_regime_fade(
    s: pd.Series,
    *,
    z_window: int   = 63,
    z_enter: float  = 2.0,
    z_exit: float   = 0.5,
    z_stop: float   = 4.5,
    confirm: int    = 1,
    min_level: float = 65.0,
) -> pd.Series:
    """
    Short only when spread is in an Elevated/Stress regime (level ≥ min_level)
    AND z-score is elevated — avoids false signals in tight markets.
    """
    z   = zscore(s, z_window)
    z_v = z.values
    sv  = s.values
    n   = len(s)
    pos = np.zeros(n, dtype=np.float64)

    in_trade = False
    for i in range(confirm, n - 1):
        if np.isnan(z_v[i]):
            continue
        if not in_trade:
            if sv[i] >= min_level and all(
                not np.isnan(z_v[i - k]) and z_v[i - k] >= z_enter
                for k in range(confirm)
            ):
                pos[i]   = -1
                in_trade = True
        else:
            pos[i] = -1
            if z_v[i] <= z_exit or z_v[i] >= z_stop:
                pos[i]   = 0
                in_trade = False

    return pd.Series(pos, index=s.index, name="regime_fade")


# ── Strategy F — Pctrank fade (short when 1-year rank > threshold) ────────────

def sig_pctrank_fade(
    s: pd.Series,
    *,
    rank_window: int    = 252,
    rank_enter: float   = 85.0,
    rank_exit: float    = 60.0,
) -> pd.Series:
    """
    Short when 1-year rolling percentile rank ≥ rank_enter.
    Exit when rank drops below rank_exit.
    """
    prank = s.rolling(rank_window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100, raw=False
    )
    pv  = prank.values
    n   = len(s)
    pos = np.zeros(n, dtype=np.float64)

    in_trade = False
    for i in range(rank_window, n - 1):
        if np.isnan(pv[i]):
            continue
        if not in_trade:
            if pv[i] >= rank_enter:
                pos[i]   = -1
                in_trade = True
        else:
            pos[i] = -1
            if pv[i] <= rank_exit:
                pos[i]   = 0
                in_trade = False

    return pd.Series(pos, index=s.index, name="pctrank_fade")


# ── Strategy J — Tail hold (spike entry + trailing stop from peak) ────────────

def sig_tail_hold(
    s: pd.Series,
    *,
    move_thresh: float = 10.0,
    trail_pct: float   = 0.25,
    max_hold: int      = 60,
    vol_filter: bool   = True,
    calm_mult: float   = 2.0,
    max_level: float   = 9999.0,
) -> pd.Series:
    """
    Long on large daily spike, then trail a stop from the rolling spread peak.
    Exit when spread retraces trail_pct below peak, or max_hold bars elapse.
    max_level: only fire when spread < max_level (buy cheap insurance).

    Unlike sig_spike_onset (fixed hold), this lets winners run:
    the 2020 trade with trail_pct=0.25 would ride the spread from ~53 up toward
    the crisis peak before exiting, capturing far more than a 3-day hold.
    """
    pct      = s.pct_change() * 100
    roll_vol = pct.rolling(10).std()
    long_vol = pct.rolling(63).std()
    pos      = pd.Series(0.0, index=s.index, name="tail_hold")
    vals     = s.values
    pct_v    = pct.values
    rv       = roll_vol.values
    lv       = long_vol.values
    n        = len(vals)
    i        = 0

    while i < n - 1:
        mv = pct_v[i]
        if np.isnan(mv) or vals[i] >= max_level:
            i += 1
            continue
        calm = True
        if vol_filter and not np.isnan(rv[i]) and not np.isnan(lv[i]):
            calm = rv[i] < calm_mult * lv[i]
        if mv >= move_thresh and calm:
            peak  = vals[i]
            j     = i + 1
            end   = min(i + max_hold, n - 1)
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


# ── Strategy K — Crisis ride (spike entry + hold entire episode) ──────────────

def sig_crisis_ride(
    s: pd.Series,
    *,
    move_thresh: float  = 8.0,
    vol_filter: bool    = True,
    calm_mult: float    = 2.0,
    max_hold: int       = 180,
    revert_mult: float  = 1.10,
    max_level: float    = 9999.0,
) -> pd.Series:
    """
    Long on large spike, hold until spread falls back to revert_mult × entry_level
    (or max_hold days).  revert_mult=1.10 → exit when spread is ≤10% above entry.
    max_level: only fire when spread < max_level.

    "Big Short" framing: enter cheap insurance on the first tremor, hold through
    the entire crisis episode, exit only when the episode has resolved.
    By default allows re-entry after exit (independent episodes).
    """
    pct      = s.pct_change() * 100
    roll_vol = pct.rolling(10).std()
    long_vol = pct.rolling(63).std()
    pos      = pd.Series(0.0, index=s.index, name="crisis_ride")
    vals     = s.values
    pct_v    = pct.values
    rv       = roll_vol.values
    lv       = long_vol.values
    n        = len(vals)
    i        = 0

    while i < n - 1:
        mv = pct_v[i]
        if np.isnan(mv) or vals[i] >= max_level:
            i += 1
            continue
        calm = True
        if vol_filter and not np.isnan(rv[i]) and not np.isnan(lv[i]):
            calm = rv[i] < calm_mult * lv[i]
        if mv >= move_thresh and calm:
            entry = vals[i]
            j     = i + 1
            end   = min(i + max_hold, n - 1)
            while j <= end:
                pos.iloc[j] = 1.0
                if vals[j] <= entry * revert_mult:
                    break
                j += 1
            i = j + 1
        else:
            i += 1

    return pos
