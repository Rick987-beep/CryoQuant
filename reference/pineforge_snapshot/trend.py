"""Trend candidates and the indicator output contract.

State convention:
    +1 = uptrend
     0 = no_trend
    -1 = downtrend

Every candidate exposes the CryoTrader-compatible shape:

    Candidate.classify(df, **params) -> DataFrame
        columns: state (int8), flip_up, flip_down, flip_to_flat

    Candidate.latest_signal(df, **params) -> dict | None
        last fully-closed bar's row as a plain dict, or None during warmup.

The raw `fn` returning a state Series is the implementation detail; the
DataFrame and dict above are the public contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import ta


# -----------------------------------------------------------------------------
# Output contract helpers
# -----------------------------------------------------------------------------

CONTRACT_COLUMNS = ("state", "flip_up", "flip_down", "flip_to_flat")


def state_to_contract(state: pd.Series) -> pd.DataFrame:
    """Materialize the (state, flip_up, flip_down, flip_to_flat) DataFrame.

    Flip semantics (mirrors `~/CryoTrader/indicators/supertrend.py`):
        flip_up      : prev_state <= 0 AND state == +1
        flip_down    : prev_state >= 0 AND state == -1
        flip_to_flat : prev_state != 0 AND state ==  0
    First bar has all flips False (no prior state to compare).
    """
    s = state.to_numpy()
    n = len(s)
    flip_up = np.zeros(n, dtype=bool)
    flip_down = np.zeros(n, dtype=bool)
    flip_to_flat = np.zeros(n, dtype=bool)
    if n > 1:
        prev = s[:-1]
        cur = s[1:]
        flip_up[1:] = (prev <= 0) & (cur == 1)
        flip_down[1:] = (prev >= 0) & (cur == -1)
        flip_to_flat[1:] = (prev != 0) & (cur == 0)
    return pd.DataFrame(
        {
            "state": pd.Series(s, index=state.index, dtype="int8"),
            "flip_up": pd.Series(flip_up, index=state.index),
            "flip_down": pd.Series(flip_down, index=state.index),
            "flip_to_flat": pd.Series(flip_to_flat, index=state.index),
        }
    )


def as_state_series(
    state_or_frame: "pd.Series | pd.DataFrame",
) -> pd.Series:
    """Accept either the legacy state Series or a contract DataFrame and
    return the state Series. Used by eval/report to be tolerant during the
    refactor."""
    if isinstance(state_or_frame, pd.DataFrame):
        return state_or_frame["state"]
    return state_or_frame


# -----------------------------------------------------------------------------
# Candidate A — ADX-gated EMA slope
# -----------------------------------------------------------------------------

def candidate_a_adx_ema(
    df: pd.DataFrame,
    *,
    ema_len: int = 50,
    slope_lookback: int = 5,
    adx_len: int = 14,
    adx_enter: float = 25.0,
    adx_exit: float = 18.0,
    dwell: int = 2,
) -> pd.Series:
    """ADX-gated EMA slope classifier with hysteresis + dwell.

    Logic:
        direction = sign( EMA(close, ema_len) - EMA(close, ema_len)[slope_lookback] )
        - Enter a trend state when ADX > adx_enter AND direction is non-zero.
        - Stay in the trend state while ADX > adx_exit.
        - Drop to no_trend when ADX <= adx_exit OR direction flips.
        - Apply minimum-dwell smoothing (a state must persist `dwell` bars
          before being reported; otherwise the previous reported state holds).
    """
    if dwell < 1:
        raise ValueError("dwell must be >= 1")

    close = df["close"]
    ema = ta.ema(close, ema_len)
    slope = ema - ema.shift(slope_lookback)
    direction = np.sign(slope.to_numpy())  # NaN-safe: NaN -> NaN

    adx = ta.dmi(df["high"], df["low"], df["close"], adx_len)["adx"].to_numpy()

    n = len(df)
    raw = np.zeros(n, dtype=np.int8)  # pre-hysteresis state
    state = 0
    for i in range(n):
        d = direction[i]
        a = adx[i]
        if np.isnan(d) or np.isnan(a):
            raw[i] = 0
            state = 0
            continue
        if state == 0:
            if a > adx_enter and d != 0:
                state = int(d)
        else:
            # in a trend state: exit if adx weakens or direction flips
            if a <= adx_exit or (d != 0 and int(d) != state):
                state = 0
        raw[i] = state

    # Dwell smoothing: only commit a transition once the new state has
    # persisted for `dwell` consecutive bars. The reported series therefore
    # lags by up to (dwell-1) bars but flips less.
    if dwell == 1:
        out = raw
    else:
        out = np.zeros(n, dtype=np.int8)
        reported = 0
        run_state = raw[0] if n else 0
        run_len = 1
        for i in range(n):
            if raw[i] == run_state:
                run_len += 1
            else:
                run_state = raw[i]
                run_len = 1
            if run_len >= dwell:
                reported = run_state
            out[i] = reported

    return pd.Series(out, index=df.index, name="state").astype("int8")


# -----------------------------------------------------------------------------
# Candidate registry
# -----------------------------------------------------------------------------

@dataclass
class Candidate:
    name: str
    fn: Callable[..., pd.Series]
    defaults: dict[str, Any]
    grid: dict[str, list] = field(default_factory=dict)

    def state(self, df: pd.DataFrame, **overrides) -> pd.Series:
        """Raw state Series — implementation detail, used by composers/tests."""
        params = {**self.defaults, **overrides}
        return self.fn(df, **params)

    def classify(self, df: pd.DataFrame, **overrides) -> pd.DataFrame:
        """Public contract: state + flip_up + flip_down + flip_to_flat."""
        return state_to_contract(self.state(df, **overrides))

    def latest_signal(self, df: pd.DataFrame, **overrides) -> "dict | None":
        """Last fully-closed bar's signal as a plain dict, or None if df
        has too few bars to evaluate (any required warmup window).

        Returns None when the last bar's state is masked (NaN-equivalent
        cannot occur for int8, so we use the convention: if every state
        value is 0 the indicator hasn't warmed up yet — return None).
        """
        if df is None or len(df) == 0:
            return None
        out = self.classify(df, **overrides)
        # Heuristic warmup guard: if the entire run is flat, treat as not
        # ready. Real candidates have transient flat periods, but a fully
        # flat history means warmup hasn't completed.
        if int((out["state"] != 0).sum()) == 0:
            return None
        last = out.iloc[-1]
        return {
            "bar_ts": out.index[-1],
            "state": int(last["state"]),
            "flip_up": bool(last["flip_up"]),
            "flip_down": bool(last["flip_down"]),
            "flip_to_flat": bool(last["flip_to_flat"]),
        }


CANDIDATES: dict[str, Candidate] = {
    "A": Candidate(
        name="ADX-gated EMA slope",
        fn=candidate_a_adx_ema,
        defaults=dict(
            ema_len=50,
            slope_lookback=5,
            adx_len=14,
            adx_enter=25.0,
            adx_exit=18.0,
            dwell=2,
        ),
        grid=dict(
            ema_len=[21, 34, 50, 89],
            slope_lookback=[3, 5, 8],
            adx_enter=[20.0, 25.0, 30.0],
            adx_exit=[15.0, 18.0, 22.0],
            dwell=[1, 2, 3],
        ),
    ),
}


# -----------------------------------------------------------------------------
# Candidate A_v2 \u2014 same behavior as A, but assembled via the compose DSL.
# Lives here so it shows up in the candidate registry alongside A.
# -----------------------------------------------------------------------------

def _candidate_a_v2_state(
    df: pd.DataFrame,
    *,
    ema_len: int = 50,
    slope_lookback: int = 5,
    adx_len: int = 14,
    adx_enter: float = 25.0,
    adx_exit: float = 18.0,
    dwell: int = 2,
) -> pd.Series:
    """Composed twin of `candidate_a_adx_ema`.

    Must produce a byte-equal state Series for the same parameters.
    """
    from . import compose as _compose  # local import avoids cycle on module load

    def _direction(d: pd.DataFrame) -> pd.Series:
        ema = ta.ema(d["close"], ema_len)
        return np.sign(ema - ema.shift(slope_lookback))

    def _enter(d: pd.DataFrame) -> pd.Series:
        adx = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        return adx > adx_enter

    def _exit(d: pd.DataFrame) -> pd.Series:
        adx = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        return adx <= adx_exit

    recipe = (
        _compose.compose()
        .direction(_direction)
        .gate(enter=_enter, exit=_exit)
        .dwell(dwell)
        .build()
    )
    return recipe(df)["state"]


CANDIDATES["A_v2"] = Candidate(
    name="ADX-gated EMA slope (composed)",
    fn=_candidate_a_v2_state,
    defaults=dict(CANDIDATES["A"].defaults),
    grid=dict(CANDIDATES["A"].grid),
)


# -----------------------------------------------------------------------------
# Phase 5 — funding-aware variants of A_v2.
#
# Both consume the `funding_rate` and `funding_z` columns produced by
# `pineforge.feeds.binance_perp.attach_funding`. They are pure additions to
# the gate logic; the direction primitive (EMA slope) is unchanged.
# -----------------------------------------------------------------------------

def _require_funding_cols(df: pd.DataFrame) -> None:
    missing = [c for c in ("funding_rate", "funding_z") if c not in df.columns]
    if missing:
        raise KeyError(
            f"candidate requires {missing}; attach the binance.perp.funding feed "
            "before calling classify() (or set RunSpec.feeds=['binance.perp.funding'])."
        )


def _candidate_a_v2_funding_veto_state(
    df: pd.DataFrame,
    *,
    ema_len: int = 50,
    slope_lookback: int = 5,
    adx_len: int = 14,
    adx_enter: float = 25.0,
    adx_exit: float = 18.0,
    dwell: int = 2,
) -> pd.Series:
    """A_v2 + funding-sign agreement gate.

    Same direction (EMA slope) and same ADX gate as A_v2, but additionally:
    the entry signal must agree with the prevailing funding regime — long
    entries require funding_rate > 0, short entries require funding_rate < 0.
    Bars where funding == 0 (or NaN warmup) cannot enter; existing trends
    exit on the standard ADX rule.
    """
    from . import compose as _compose

    _require_funding_cols(df)

    def _direction(d: pd.DataFrame) -> pd.Series:
        ema = ta.ema(d["close"], ema_len)
        return np.sign(ema - ema.shift(slope_lookback))

    def _enter(d: pd.DataFrame) -> pd.Series:
        adx = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        ema = ta.ema(d["close"], ema_len)
        dir_sign = np.sign(ema - ema.shift(slope_lookback))
        f_sign = np.sign(d["funding_rate"])
        # entry permitted only when funding sign matches direction (or
        # direction is zero, in which case A_v2 won't enter anyway).
        agree = (dir_sign * f_sign) > 0
        return (adx > adx_enter) & agree

    def _exit(d: pd.DataFrame) -> pd.Series:
        adx = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        return adx <= adx_exit

    recipe = (
        _compose.compose()
        .direction(_direction)
        .gate(enter=_enter, exit=_exit)
        .dwell(dwell)
        .build()
    )
    return recipe(df)["state"]


def _candidate_a_v2_funding_z_brake_state(
    df: pd.DataFrame,
    *,
    ema_len: int = 50,
    slope_lookback: int = 5,
    adx_len: int = 14,
    adx_enter: float = 25.0,
    adx_exit: float = 18.0,
    z_max: float = 2.5,
    dwell: int = 2,
) -> pd.Series:
    """A_v2, but extreme funding z-scores brake entries and force exits.

    Hypothesis: when funding gets extreme, the trend often whipsaws. Block
    new entries when |funding_z| >= z_max, and exit existing trends when
    |funding_z| crosses the same threshold. Otherwise identical to A_v2.
    """
    from . import compose as _compose

    _require_funding_cols(df)

    def _direction(d: pd.DataFrame) -> pd.Series:
        ema = ta.ema(d["close"], ema_len)
        return np.sign(ema - ema.shift(slope_lookback))

    def _enter(d: pd.DataFrame) -> pd.Series:
        adx = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        z_ok = d["funding_z"].abs() < z_max
        return (adx > adx_enter) & z_ok

    def _exit(d: pd.DataFrame) -> pd.Series:
        adx = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        z_extreme = d["funding_z"].abs() >= z_max
        return (adx <= adx_exit) | z_extreme

    recipe = (
        _compose.compose()
        .direction(_direction)
        .gate(enter=_enter, exit=_exit)
        .dwell(dwell)
        .build()
    )
    return recipe(df)["state"]


CANDIDATES["A_v2_funding_veto"] = Candidate(
    name="A_v2 + funding-sign veto",
    fn=_candidate_a_v2_funding_veto_state,
    defaults=dict(CANDIDATES["A"].defaults),
    grid=dict(CANDIDATES["A"].grid),
)

CANDIDATES["A_v2_funding_z_brake"] = Candidate(
    name="A_v2 + funding-z extreme brake",
    fn=_candidate_a_v2_funding_z_brake_state,
    defaults={**CANDIDATES["A"].defaults, "z_max": 2.5},
    grid={**CANDIDATES["A"].grid, "z_max": [1.5, 2.0, 2.5, 3.0]},
)


# -----------------------------------------------------------------------------
# Phase 6 candidates
# -----------------------------------------------------------------------------

def _candidate_b_supertrend_state(
    df: pd.DataFrame,
    *,
    factor: float = 3.0,
    atr_len: int = 10,
    dwell: int = 1,
) -> pd.Series:
    """Candidate B — Pine-faithful Supertrend.

    Direction sign is the only signal; no ADX gate. Dwell smoothing is the
    only knob added on top of Pine's ta.supertrend so we can compare to
    A_v2 on equal terms (A_v2 uses dwell=2 by default).

    State convention:
        +1 = uptrend (Supertrend below price, Pine direction=-1)
         0 = (never; Supertrend is always either uptrend or downtrend after warmup)
        -1 = downtrend
    """
    st = ta.supertrend(df["high"], df["low"], df["close"], factor=factor, atr_len=atr_len)
    raw = st["trend"].fillna(0).astype(np.int8).to_numpy()
    if dwell <= 1:
        out = raw
    else:
        n = len(raw)
        out = np.zeros(n, dtype=np.int8)
        reported = 0
        run_state = raw[0] if n else 0
        run_len = 1
        for i in range(n):
            if raw[i] == run_state:
                run_len += 1
            else:
                run_state = raw[i]
                run_len = 1
            if run_len >= dwell:
                reported = run_state
            out[i] = reported
    return pd.Series(out, index=df.index, name="state").astype("int8")


def _candidate_c_a_v2_htf_confirm_state(
    df: pd.DataFrame,
    *,
    ema_len: int = 50,
    slope_lookback: int = 5,
    adx_len: int = 14,
    adx_enter: float = 25.0,
    adx_exit: float = 18.0,
    htf: str = "4h",
    htf_ema_len: int = 50,
    dwell: int = 2,
) -> pd.Series:
    """Candidate C — A_v2 with higher-timeframe trend confirmation.

    Direction must agree with the HTF EMA slope (signed). Closed-bar safe via
    `data.htf_align`: each bar's HTF context is the most recent fully-closed
    HTF bar.

    Caller does not need to pre-attach anything: the helper resamples
    `df` itself to the requested HTF, computes the HTF EMA slope sign, and
    aligns it back. (No external feed; pure derivation from OHLCV.)
    """
    from . import compose as _compose
    from . import data as _data

    base = df

    htf_df = _data.resample(base, htf)
    htf_ema = ta.ema(htf_df["close"], htf_ema_len)
    htf_slope_sign = np.sign(htf_ema - htf_ema.shift(1))
    htf_slope_sign.name = "htf_slope_sign"
    htf_aligned = _data.htf_align(base, htf_slope_sign, htf=htf)

    def _direction(d: pd.DataFrame) -> pd.Series:
        ema_v = ta.ema(d["close"], ema_len)
        base_sign = np.sign(ema_v - ema_v.shift(slope_lookback))
        # only emit a direction when both timeframes agree
        agree = (base_sign * htf_aligned) > 0
        return base_sign.where(agree, 0.0)

    def _enter(d: pd.DataFrame) -> pd.Series:
        a = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        return a > adx_enter

    def _exit(d: pd.DataFrame) -> pd.Series:
        a = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        return a <= adx_exit

    recipe = (
        _compose.compose()
        .direction(_direction)
        .gate(enter=_enter, exit=_exit)
        .dwell(dwell)
        .build()
    )
    return recipe(base)["state"]


def _candidate_d_a_v2_squeeze_release_state(
    df: pd.DataFrame,
    *,
    ema_len: int = 50,
    slope_lookback: int = 5,
    adx_len: int = 14,
    adx_enter: float = 25.0,
    adx_exit: float = 18.0,
    bbw_len: int = 20,
    bbw_mult: float = 2.0,
    bbw_pct_lookback: int = 252,
    bbw_release_pct: float = 0.30,
    dwell: int = 2,
) -> pd.Series:
    """Candidate D — A_v2 with squeeze-release entry filter.

    Same direction (EMA slope) and ADX gate as A_v2, but additionally an
    entry only fires when BBW percentile is *rising through* `bbw_release_pct`
    — i.e. the current bar's percentile is above the threshold AND the
    previous bar's was below. Existing trends exit on the standard ADX rule.
    """
    from . import compose as _compose

    bbw_p = ta.bbw_pct(df["close"], n=bbw_len, mult=bbw_mult, lookback=bbw_pct_lookback)
    release = (bbw_p > bbw_release_pct) & (bbw_p.shift(1) <= bbw_release_pct)

    def _direction(d: pd.DataFrame) -> pd.Series:
        ema_v = ta.ema(d["close"], ema_len)
        return np.sign(ema_v - ema_v.shift(slope_lookback))

    def _enter(d: pd.DataFrame) -> pd.Series:
        a = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        return (a > adx_enter) & release

    def _exit(d: pd.DataFrame) -> pd.Series:
        a = ta.dmi(d["high"], d["low"], d["close"], adx_len)["adx"]
        return a <= adx_exit

    recipe = (
        _compose.compose()
        .direction(_direction)
        .gate(enter=_enter, exit=_exit)
        .dwell(dwell)
        .build()
    )
    return recipe(df)["state"]


CANDIDATES["B_supertrend"] = Candidate(
    name="Pine Supertrend (3, 10) + dwell",
    fn=_candidate_b_supertrend_state,
    defaults=dict(factor=3.0, atr_len=10, dwell=1),
    grid=dict(factor=[2.0, 3.0, 4.0], atr_len=[7, 10, 14], dwell=[1, 2, 3]),
)

CANDIDATES["C_htf_confirm"] = Candidate(
    name="A_v2 + 4h trend confirmation",
    fn=_candidate_c_a_v2_htf_confirm_state,
    defaults={**CANDIDATES["A"].defaults, "htf": "4h", "htf_ema_len": 50},
    grid={
        **CANDIDATES["A"].grid,
        "htf": ["4h", "1d"],
        "htf_ema_len": [21, 50, 89],
    },
)

CANDIDATES["D_squeeze_release"] = Candidate(
    name="A_v2 + BBW-percentile squeeze release",
    fn=_candidate_d_a_v2_squeeze_release_state,
    defaults={
        **CANDIDATES["A"].defaults,
        "bbw_len": 20, "bbw_mult": 2.0,
        "bbw_pct_lookback": 252, "bbw_release_pct": 0.30,
    },
    grid={
        **CANDIDATES["A"].grid,
        "bbw_release_pct": [0.20, 0.30, 0.50],
        "bbw_pct_lookback": [126, 252, 500],
    },
)


# -----------------------------------------------------------------------------
# Candidate E — US-session opening-range breakout (post-ETF era)
#
# Hypothesis: BTCUSD frequently breaks out around US cash-equity open
# (NYSE 13:30/14:30 UTC depending on DST), trends for 1–3 hours, then
# settles. We try to catch the early direction and exit when the move
# fades (BBW% drops back) or the session window closes.
#
# Entry rules (15m bars):
#   - bar timestamp falls inside [entry_hour_start, entry_hour_end) UTC
#   - bar's UTC date is a NYSE trading day
#   - close breaks the prior `consolidation_bars` high/low
#   - sign of breakout agrees with sign of EMA slope (no chase)
#   - ADX > adx_enter (trend-quality) and BBW% > bbw_release_pct (vol expansion)
#
# Exit rules (any of):
#   - bar's UTC hour >= exit_hour
#   - max_hold_bars elapsed since entry
#   - BBW% drops back below bbw_release_pct (settling)
#   - opposite breakout: close crosses the OPPOSITE side of the OR
# -----------------------------------------------------------------------------

def _candidate_e_us_session_breakout_state(
    df: pd.DataFrame,
    *,
    ema_len: int = 20,
    consolidation_bars: int = 8,
    adx_len: int = 14,
    adx_enter: float = 22.0,
    bbw_len: int = 20,
    bbw_mult: float = 2.0,
    bbw_pct_lookback: int = 252,
    bbw_release_pct: float = 0.40,
    entry_hour_start: int = 13,
    entry_hour_end: int = 15,
    exit_hour: int = 19,
    max_hold_bars: int = 12,
    require_us_calendar: bool = True,
) -> pd.Series:
    """Candidate E — US-session ORB on BTCUSDT.

    Signals only between `entry_hour_start` and `entry_hour_end` UTC on
    NYSE trading days. Closed-bar safe — every input is shifted or
    rolling-window-only, no peeking.
    """
    from . import calendars as _cal

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    ema_v = ta.ema(df["close"], ema_len)
    base_sign = np.sign(ema_v - ema_v.shift(1)).fillna(0).to_numpy()

    adx_v = ta.dmi(df["high"], df["low"], df["close"], adx_len)["adx"].to_numpy()

    bbw_p = ta.bbw_pct(
        df["close"], n=bbw_len, mult=bbw_mult, lookback=bbw_pct_lookback,
    ).to_numpy()

    or_df = ta.opening_range(df["high"], df["low"], consolidation_bars)
    or_high = or_df["or_high"].to_numpy()
    or_low = or_df["or_low"].to_numpy()

    in_session = _cal.in_us_session(
        df.index,
        start_hour=entry_hour_start,
        end_hour=entry_hour_end,
        require_trading_day=require_us_calendar,
    ).to_numpy()

    utc_hour = df.index.tz_convert("UTC").hour.to_numpy()

    n = len(df)
    state = np.zeros(n, dtype=np.int8)
    pos = 0
    hold = 0
    entry_or_high = np.nan
    entry_or_low = np.nan

    for i in range(n):
        # default: carry previous state forward; we'll override on entry/exit.
        if pos != 0:
            hold += 1
            forced_exit = False
            # 1. Time-of-day exit
            if utc_hour[i] >= exit_hour:
                forced_exit = True
            # 2. Max hold
            elif hold >= max_hold_bars:
                forced_exit = True
            # 3. BBW collapse
            elif not np.isnan(bbw_p[i]) and bbw_p[i] < bbw_release_pct:
                forced_exit = True
            # 4. Opposite breakout (against entry's OR boundary)
            elif pos == 1 and not np.isnan(entry_or_low) and close[i] < entry_or_low:
                forced_exit = True
            elif pos == -1 and not np.isnan(entry_or_high) and close[i] > entry_or_high:
                forced_exit = True
            if forced_exit:
                pos = 0
                hold = 0
                entry_or_high = np.nan
                entry_or_low = np.nan

        # Entry: only inside the window, and only if currently flat
        if pos == 0 and in_session[i]:
            if (np.isnan(or_high[i]) or np.isnan(or_low[i])
                    or np.isnan(adx_v[i]) or np.isnan(bbw_p[i])):
                pass
            elif adx_v[i] > adx_enter and bbw_p[i] > bbw_release_pct:
                broke_up = close[i] > or_high[i]
                broke_dn = close[i] < or_low[i]
                if broke_up and base_sign[i] > 0:
                    pos = 1
                    hold = 0
                    entry_or_high = or_high[i]
                    entry_or_low = or_low[i]
                elif broke_dn and base_sign[i] < 0:
                    pos = -1
                    hold = 0
                    entry_or_high = or_high[i]
                    entry_or_low = or_low[i]

        state[i] = pos

    return pd.Series(state, index=df.index, name="state").astype("int8")


CANDIDATES["E_us_session_breakout"] = Candidate(
    name="US-session opening-range breakout (post-ETF era)",
    fn=_candidate_e_us_session_breakout_state,
    defaults=dict(
        ema_len=20,
        consolidation_bars=8,
        adx_len=14,
        adx_enter=22.0,
        bbw_len=20,
        bbw_mult=2.0,
        bbw_pct_lookback=252,
        bbw_release_pct=0.40,
        entry_hour_start=13,
        entry_hour_end=15,
        exit_hour=19,
        max_hold_bars=12,
        require_us_calendar=True,
    ),
    grid=dict(
        consolidation_bars=[4, 8, 12],
        adx_enter=[18.0, 22.0, 26.0],
        bbw_release_pct=[0.30, 0.40, 0.55],
        max_hold_bars=[8, 12, 16],
    ),
)


# -----------------------------------------------------------------------------
# Candidate F — KAMA slope + R² + Donchian breakout + RSI + HTF confirm
#
# Hypothesis: the dominant failure mode of C_htf_confirm is *entry lag* —
# ADX(14) is Wilder-smoothed and fires 9+ bars after the direction primitive
# already agreed. By replacing every slow-smoothed component with faster
# equivalents from the new primitive library, we aim to catch 4–18 bar
# intraday trends that C currently enters too late or misses entirely.
#
# Architecture (all new primitives, no ADX):
#
#   Direction  : KAMA(kama_n) slope over kama_lookback bars.
#                KAMA naturally self-adapts via its embedded Efficiency Ratio —
#                it accelerates in trends and freezes in chop, so its slope
#                is already a joint direction+regime signal.
#                Gated by HTF EMA(htf_ema_len) slope agreement (closed-bar safe).
#
#   Enter gate : ALL of the following must be true —
#                1. linreg_r2(r2_len) > r2_enter   — price is moving in a
#                   straight line (explicit fit quality, ~1-bar lag)
#                2. atr_percentile(atr_n, atr_pct_lookback) > atr_pct_min —
#                   not a dead-vol flatline (prevents false signals in squeezes)
#                3. donchian_breakout(dc_n) agrees with direction —
#                   price left a range in the signal's direction
#                   (fires immediately when close crosses the prior N-bar high/low)
#                4. RSI(rsi_n) agrees with direction —
#                   RSI > 50 for longs, RSI < 50 for shorts
#                   (cheap momentum sanity check; vetoes counter-trend momentum)
#
#   Exit gate  : linreg_r2 drops below r2_exit  — the linear structure has
#                broken down. Direction flips (via KAMA slope) also trigger
#                exit automatically via the compose state machine.
#
# None of the four enter conditions use Wilder smoothing. The expected entry
# lag is 1–3 bars vs C's measured 9-bar median.
# -----------------------------------------------------------------------------

def _candidate_f_kama_r2_state(
    df: pd.DataFrame,
    *,
    kama_n: int = 10,
    kama_fast: int = 2,
    kama_slow: int = 30,
    kama_lookback: int = 2,
    r2_len: int = 20,
    r2_enter: float = 0.5,
    r2_exit: float = 0.35,
    atr_n: int = 14,
    atr_pct_lookback: int = 126,
    atr_pct_min: float = 0.35,
    dc_n: int = 20,
    rsi_n: int = 14,
    htf: str = "4h",
    htf_ema_len: int = 21,
    dwell: int = 2,
) -> pd.Series:
    """Candidate F — KAMA slope + R² regime gate + Donchian trigger + RSI confirm.

    See module-level comment block above for full architecture description.
    """
    from . import compose as _compose
    from . import data as _data

    # --- Pre-compute all signals (closed-bar safe; no lookahead) ---
    kama_v = ta.kama(df["close"], kama_n, fast=kama_fast, slow=kama_slow)
    kama_slope = np.sign(kama_v - kama_v.shift(kama_lookback))

    r2 = ta.linreg_r2(df["close"], r2_len)
    atr_pct = ta.atr_percentile(
        df["high"], df["low"], df["close"], atr_n, atr_pct_lookback
    )
    dc_break = ta.donchian_breakout(df["high"], df["low"], df["close"], dc_n)
    rsi_v = ta.rsi(df["close"], rsi_n)

    # HTF confirm: resample to htf, compute EMA slope sign, align back closed-bar safe
    htf_df = _data.resample(df, htf)
    htf_ema = ta.ema(htf_df["close"], htf_ema_len)
    htf_slope_sign = np.sign(htf_ema - htf_ema.shift(1))
    htf_slope_sign.name = "htf_slope_sign"
    htf_aligned = _data.htf_align(df, htf_slope_sign, htf=htf)

    def _direction(d: pd.DataFrame) -> pd.Series:
        # KAMA slope, zeroed where base and HTF disagree
        agree = (kama_slope * htf_aligned) > 0
        return kama_slope.where(agree, 0.0)

    def _enter(d: pd.DataFrame) -> pd.Series:
        # Effective direction at this bar (same logic as _direction)
        dir_sig = kama_slope.where((kama_slope * htf_aligned) > 0, 0.0)

        # 1. R² — price is actually trending in a straight line
        r2_ok = r2 > r2_enter

        # 2. ATR percentile — not a dead-vol environment
        atr_ok = atr_pct > atr_pct_min

        # 3. Donchian breakout — price left the prior range in the signal direction
        dc_agree = (dc_break != 0) & (dc_break == dir_sig)

        # 4. RSI momentum sanity — RSI > 50 for longs, < 50 for shorts
        rsi_ok = ((dir_sig > 0) & (rsi_v > 50)) | ((dir_sig < 0) & (rsi_v < 50))

        return r2_ok & atr_ok & dc_agree & rsi_ok

    def _exit(d: pd.DataFrame) -> pd.Series:
        # Exit when the linear structure breaks down
        return r2 < r2_exit

    recipe = (
        _compose.compose()
        .direction(_direction)
        .gate(enter=_enter, exit=_exit)
        .dwell(dwell)
        .build()
    )
    return recipe(df)["state"]


CANDIDATES["F_kama_r2"] = Candidate(
    name="KAMA slope + R² gate + Donchian trigger + RSI confirm + HTF",
    fn=_candidate_f_kama_r2_state,
    defaults=dict(
        kama_n=10,
        kama_fast=2,
        kama_slow=30,
        kama_lookback=2,
        r2_len=20,
        r2_enter=0.5,
        r2_exit=0.35,
        atr_n=14,
        atr_pct_lookback=126,
        atr_pct_min=0.35,
        dc_n=20,
        rsi_n=14,
        htf="4h",
        htf_ema_len=21,
        dwell=2,
    ),
    grid=dict(
        kama_n=[10, 14, 20],
        kama_lookback=[2, 3, 5],
        r2_len=[14, 20, 30],
        r2_enter=[0.4, 0.5, 0.6],
        r2_exit=[0.25, 0.35, 0.45],
        atr_pct_min=[0.25, 0.35, 0.50],
        dc_n=[14, 20, 30],
        htf_ema_len=[21, 34, 50],
        dwell=[1, 2, 3],
    ),
)


# -----------------------------------------------------------------------------
# Candidate G — HMA(8) slope on 15m, ATR-expansion gate
#
# Hypothesis: the dominant failure mode of all existing candidates on the
# downtrend test cases (apr27, apr29) is *entry lag* from slow smoothers
# (EMA50, ADX14) evaluated on 1h bars. A 5–6h downtrend only gives 5–6 bars
# on 1h, and ADX(14) physically cannot cross a threshold in that window.
#
# Fix: drop to 15m. HMA(8) on 15m represents a 2h adaptive-weighted view
# and flips within 2–3 bars (30–45 min) of a directional move starting.
# ATR expansion (ATR(5) > ATR(5)[3]) is a 3-bar confirmation of real range
# expansion, not a 14-bar Wilder smoother.
#
# Architecture:
#   Direction  : sign(HMA(close, 8) - HMA(close, 8)[1])
#   Enter gate : ATR(5) > ATR(5)[3]  (expanding volatility, fires in 3 bars)
#   Exit gate  : ATR(5) < ATR(5)[3]  (volatility contracting)
#   Dwell      : 3 (45 min — suppresses sub-1h noise, ~23→7 flips/day)
#   Timeframe  : 15m
#   No HTF gate by design — downtrend tests occur inside larger uptrends;
#   any HTF alignment gate would block the very signals we want to catch.
# -----------------------------------------------------------------------------

def _candidate_g_hma15_state(
    df: pd.DataFrame,
    *,
    hma_len: int = 8,
    atr_len: int = 5,
    atr_lookback: int = 3,
    dwell: int = 3,
) -> pd.Series:
    """Candidate G — HMA(8) slope + ATR expansion gate on 15m bars."""
    hma_v = ta.hma(df["close"], hma_len)
    direction = np.sign(hma_v - hma_v.shift(1))

    atr_v = ta.atr(df["high"], df["low"], df["close"], atr_len)
    atr_expanding = atr_v > atr_v.shift(atr_lookback)

    n = len(df)
    raw = np.zeros(n, dtype=np.int8)
    state = 0

    dir_arr = direction.to_numpy(dtype=float)
    gate_arr = atr_expanding.to_numpy()

    for i in range(n):
        d = dir_arr[i]
        if np.isnan(d):
            raw[i] = 0
            state = 0
            continue
        d_int = int(d)
        if state == 0:
            # Enter when direction is non-zero AND ATR expanding
            if d_int != 0 and gate_arr[i]:
                state = d_int
        else:
            # Exit only on direction reversal; ATR contraction does NOT exit
            # (mid-trend vol contractions would otherwise terminate valid trends)
            if d_int != 0 and d_int != state:
                state = 0
        raw[i] = state

    # Dwell smoothing
    if dwell <= 1:
        out = raw
    else:
        out = np.zeros(n, dtype=np.int8)
        reported = 0
        run_state = raw[0] if n else 0
        run_len = 1
        for i in range(n):
            if raw[i] == run_state:
                run_len += 1
            else:
                run_state = raw[i]
                run_len = 1
            if run_len >= dwell:
                reported = run_state
            out[i] = reported

    return pd.Series(out, index=df.index, name="state").astype("int8")


CANDIDATES["G_hma15"] = Candidate(
    name="HMA(8) slope + ATR expansion, 15m",
    fn=_candidate_g_hma15_state,
    defaults=dict(hma_len=8, atr_len=5, atr_lookback=3, dwell=3),
    grid=dict(
        hma_len=[6, 8, 10, 12],
        atr_len=[3, 5, 7],
        atr_lookback=[2, 3, 5],
        dwell=[2, 3, 4],
    ),
)


# -----------------------------------------------------------------------------
# Candidate H — Donchian(6) breakout on 15m, no HTF gate
#
# Hypothesis: a 1.5h (6-bar) Donchian breakout on 15m fires the instant price
# leaves its recent range — zero smoothing lag. The "stepwise decline" and
# "momentum bars" described in the trend test notes should trigger immediately.
#
# Architecture:
#   Direction  : sign(close - midpoint(highest(high,8), lowest(low,8)))
#                — price position in a slightly wider Donchian (8 bars = 2h)
#                  gives the bias; the 6-bar breakout provides the trigger.
#   Enter gate : close > highest(close, dc_enter) shifted by 1 (for longs)
#                close < lowest(close, dc_enter) shifted by 1 (for shorts)
#                — classic Donchian(6) channel breakout, closed-bar safe.
#   Exit gate  : opposite Donchian breakout OR price returns inside the
#                midpoint of the entry channel.
#   Dwell      : 2 (30 min — minimal smoothing; Donchian entry is already
#                  structural so less dwell needed vs HMA slope)
#   Timeframe  : 15m
# -----------------------------------------------------------------------------

def _candidate_h_donch15_state(
    df: pd.DataFrame,
    *,
    dc_dir: int = 8,       # wider band for direction bias
    dc_enter: int = 6,     # tighter band for entry trigger
    dwell: int = 2,
) -> pd.Series:
    """Candidate H — Donchian channel breakout on 15m bars."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # Direction bias: position of close within a wider Donchian
    upper_dir = ta.highest(high, dc_dir)
    lower_dir = ta.lowest(low, dc_dir)
    mid_dir = (upper_dir + lower_dir) / 2.0
    direction = np.sign(close - mid_dir)

    # Entry trigger: breakout of the tighter channel (prior dc_enter bars, shifted)
    entry_high = ta.highest(close, dc_enter).shift(1)  # closed-bar safe
    entry_low = ta.lowest(close, dc_enter).shift(1)

    # Exit: return inside the midpoint of the entry channel
    mid_entry = (entry_high + entry_low) / 2.0

    n = len(df)
    dir_arr = direction.to_numpy(dtype=float)
    c_arr = close.to_numpy(dtype=float)
    eh_arr = entry_high.to_numpy(dtype=float)
    el_arr = entry_low.to_numpy(dtype=float)
    mid_arr = mid_entry.to_numpy(dtype=float)

    raw = np.zeros(n, dtype=np.int8)
    state = 0

    for i in range(n):
        d = dir_arr[i]
        c = c_arr[i]
        if np.isnan(d) or np.isnan(eh_arr[i]):
            raw[i] = 0
            state = 0
            continue
        d_int = int(d)
        if state == 0:
            # Enter on Donchian breakout in the direction of bias
            if d_int == 1 and c > eh_arr[i]:
                state = 1
            elif d_int == -1 and c < el_arr[i]:
                state = -1
        else:
            # Exit when price re-enters the breakout channel (breakout failed)
            # or direction bias has fully reversed. Midpoint exit removed: it
            # fired on normal 1-2 bar pullbacks, killing coverage of sustained trends.
            if state == 1:
                if d_int == -1 or c < el_arr[i]:
                    state = 0
            else:  # state == -1
                if d_int == 1 or c > eh_arr[i]:
                    state = 0
        raw[i] = state

    # Dwell smoothing
    if dwell <= 1:
        out = raw
    else:
        out = np.zeros(n, dtype=np.int8)
        reported = 0
        run_state = raw[0] if n else 0
        run_len = 1
        for i in range(n):
            if raw[i] == run_state:
                run_len += 1
            else:
                run_state = raw[i]
                run_len = 1
            if run_len >= dwell:
                reported = run_state
            out[i] = reported

    return pd.Series(out, index=df.index, name="state").astype("int8")


CANDIDATES["H_donch15"] = Candidate(
    name="Donchian(6) breakout, 15m",
    fn=_candidate_h_donch15_state,
    defaults=dict(dc_dir=8, dc_enter=6, dwell=2),
    grid=dict(
        dc_dir=[6, 8, 10, 12],
        dc_enter=[4, 6, 8],
        dwell=[1, 2, 3],
    ),
)


# -----------------------------------------------------------------------------
# Candidate I — Fast EMA cross momentum, 15m ("momentum crash" type)
#
# Hypothesis: a subset of the target trends (e.g. apr27) is a *late-burst*
# move — 4 quiet hours followed by a single -1.4% momentum bar. No lagged
# indicator predicts this; the signal must fire ON the momentum bar itself.
#
# EMA(3) vs EMA(8) on 15m:
#   - EMA(3) responds within 1 bar to a large candle (alpha ≈ 0.5)
#   - EMA(8) provides the reference; cross fires on bar 1 of a real move
#   - Measured: flips at bar 1 of apr27 drop (within the momentum bar)
#
# Enter gate: ATR(3) > ATR(3)[2] — confirms real range expansion (not drift)
#   Very short lookback so it fires on the momentum bar itself.
#
# Exit: EMA(3) crosses back through EMA(8) — tight, exits the moment
#   momentum fades. No patience for grinds; that's H's job.
#
# Dwell: 1 — momentum can't wait; a 2-bar delay kills the signal.
# Timeframe: 15m
# -----------------------------------------------------------------------------

def _candidate_i_momentum15_state(
    df: pd.DataFrame,
    *,
    fast_len: int = 3,
    slow_len: int = 8,
    atr_len: int = 3,
    atr_lookback: int = 2,
    dwell: int = 1,
) -> pd.Series:
    """Candidate I — Fast EMA(3/8) cross + short ATR expansion gate, 15m."""
    ema_fast = ta.ema(df["close"], fast_len)
    ema_slow = ta.ema(df["close"], slow_len)
    cross = ema_fast - ema_slow
    direction = np.sign(cross)

    atr_v = ta.atr(df["high"], df["low"], df["close"], atr_len)
    atr_expanding = atr_v > atr_v.shift(atr_lookback)

    n = len(df)
    dir_arr = direction.to_numpy(dtype=float)
    gate_arr = atr_expanding.to_numpy()

    raw = np.zeros(n, dtype=np.int8)
    state = 0

    for i in range(n):
        d = dir_arr[i]
        if np.isnan(d):
            raw[i] = 0
            state = 0
            continue
        d_int = int(d)
        if state == 0:
            if d_int != 0 and gate_arr[i]:
                state = d_int
        else:
            # Exit on direction reversal only (tight exit, no ATR holdback)
            if d_int != 0 and d_int != state:
                state = 0
        raw[i] = state

    if dwell <= 1:
        out = raw
    else:
        out = np.zeros(n, dtype=np.int8)
        reported = 0
        run_state = raw[0] if n else 0
        run_len = 1
        for i in range(n):
            if raw[i] == run_state:
                run_len += 1
            else:
                run_state = raw[i]
                run_len = 1
            if run_len >= dwell:
                reported = run_state
            out[i] = reported

    return pd.Series(out, index=df.index, name="state").astype("int8")


CANDIDATES["I_momentum15"] = Candidate(
    name="Fast EMA(3/8) cross + ATR expansion, 15m",
    fn=_candidate_i_momentum15_state,
    defaults=dict(fast_len=3, slow_len=8, atr_len=3, atr_lookback=2, dwell=1),
    grid=dict(
        fast_len=[2, 3, 5],
        slow_len=[6, 8, 13],
        atr_len=[3, 5],
        atr_lookback=[2, 3],
        dwell=[1, 2],
    ),
)


# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Burst-detection candidates (J, K, L, N) live in burst_indicators.py.
# Importing it registers them into CANDIDATES.
# -----------------------------------------------------------------------------
from . import burst_indicators as _burst_indicators  # noqa: E402,F401
