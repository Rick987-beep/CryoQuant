"""Short-volatility option selling backtest (sell-side economics)."""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from cryoquant.backtest.option_lookup import (
    ExitRule,
    _DERIBIT_MONTHS,
    _best_leg,
    _load_chain_df,
    _spot_price_on_date,
    _to_deribit_expiry,
)

log = logging.getLogger(__name__)

StructureKind = Literal["strangle", "credit_spread", "naked"]
TiltKind = Literal["symmetric", "call_heavy", "put_heavy"]


class ShortVolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    side: Literal["sell"] = "sell"
    structure: StructureKind = "credit_spread"
    target_delta: float = Field(gt=0, lt=1)
    wing_delta_offset: float | None = Field(default=0.05, ge=0)
    dte: int = Field(ge=1)
    exit_rule: ExitRule = Field(default_factory=ExitRule)
    tilt: TiltKind = "symmetric"


class ShortVolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fires_evaluated: int
    fires_with_data: int
    pnl_pct: list[float]
    win_rate: float
    expectancy: float
    entry_credits_usd: list[float]
    dte_actual: list[int]
    realized_otm: list[bool]


def _valid_chain(chain: pd.DataFrame) -> bool:
    return {"expiry", "is_call", "bid_price", "ask_price"}.issubset(chain.columns)


def _parse_deribit_expiry(label: str) -> date | None:
    m = re.match(r"(\d+)([A-Z]{3})(\d+)", str(label).upper())
    if not m:
        return None
    day_s, mon, yr = m.groups()
    months = {m: i + 1 for i, m in enumerate(_DERIBIT_MONTHS)}
    if mon not in months:
        return None
    return date(2000 + int(yr), months[mon], int(day_s))


def _nearest_expiry(chain: pd.DataFrame, fire_date: date, target_dte: int) -> date | None:
    best: tuple[int, date] | None = None
    for lab in chain["expiry"].unique():
        exp = _parse_deribit_expiry(str(lab))
        if exp is None or exp <= fire_date:
            continue
        dte = (exp - fire_date).days
        score = abs(dte - target_dte)
        if best is None or score < best[0]:
            best = (score, exp)
    return best[1] if best else None


def _best_short_leg(
    chain: pd.DataFrame,
    expiry: date,
    target_delta: float,
    is_call: bool,
) -> pd.Series | None:
    leg = _best_leg(chain, expiry, target_delta, is_call=is_call)
    if leg is None:
        return None
    if float(leg.get("bid_price", 0) or 0) <= 0:
        return None
    return leg


def _wing_delta(target: float, offset: float | None, is_call: bool) -> float:
    off = offset if offset is not None else 0.05
    return min(0.99, target + off)


def _leg_credit(leg: pd.Series, *, side: str) -> float:
    bid = float(leg["bid_price"]) if leg["bid_price"] > 0 else 0.0
    ask = float(leg["ask_price"]) if leg["ask_price"] > 0 else 0.0
    if side == "sell":
        return bid
    return -ask


def _leg_exit_cost(leg: pd.Series, *, side: str) -> float:
    bid = float(leg["bid_price"]) if leg["bid_price"] > 0 else 0.0
    ask = float(leg["ask_price"]) if leg["ask_price"] > 0 else 0.0
    if side == "sell":
        return ask if ask > 0 else bid * 1.1
    return -(bid if bid > 0 else ask * 0.9)


def _spread_credit(
    chain: pd.DataFrame,
    expiry: date,
    target_delta: float,
    wing_offset: float | None,
    is_call: bool,
    *,
    structure: StructureKind,
) -> tuple[float, pd.Series | None, pd.Series | None]:
    short_leg = _best_short_leg(chain, expiry, target_delta, is_call=is_call)
    if short_leg is None:
        return 0.0, None, None
    credit = _leg_credit(short_leg, side="sell")
    long_leg = None
    if structure == "credit_spread":
        wing_d = _wing_delta(target_delta, wing_offset, is_call)
        long_leg = _best_leg(chain, expiry, wing_d, is_call=is_call)
        if long_leg is not None:
            credit += _leg_credit(long_leg, side="buy")
    if credit <= 0:
        return 0.0, short_leg, long_leg
    return credit, short_leg, long_leg


def _spread_exit_cost(
    chain: pd.DataFrame,
    expiry: date,
    short_leg: pd.Series,
    long_leg: pd.Series | None,
    target_delta: float,
    wing_offset: float | None,
    is_call: bool,
    *,
    structure: StructureKind,
) -> float:
    strike = float(short_leg["strike"])
    short_row = _best_leg(chain, expiry, target_delta, is_call=is_call)
    if short_row is None:
        short_row = short_leg
    cost = _leg_exit_cost(short_row, side="sell")
    if structure == "credit_spread" and long_leg is not None:
        wing_d = _wing_delta(target_delta, wing_offset, is_call)
        long_row = _best_leg(chain, expiry, wing_d, is_call=is_call)
        if long_row is not None:
            cost += _leg_exit_cost(long_row, side="buy")
    return cost


def _intrinsic_straddle_frac(spot: float, call_strike: float, put_strike: float) -> float:
    call_intr = max(0.0, spot - call_strike)
    put_intr = max(0.0, put_strike - spot)
    return (call_intr + put_intr) / spot if spot > 0 else 0.0


def _expiry_otm(spot: float, call_strike: float, put_strike: float) -> bool:
    """Both legs OTM at expiry."""
    return spot < call_strike and spot > put_strike


def evaluate_short_vol(
    signal: object,
    bars: pd.DataFrame,
    *,
    cfg: ShortVolConfig,
    chains_dir: Path,
) -> ShortVolResult:
    """Evaluate short-vol P&L against daily option chain snapshots.

    PnL_pct = (entry_credit_frac - exit_cost_frac) / entry_credit_frac.
  Credit is sum of short-leg bids minus long-wing asks (credit spreads).
    """
    from cryoquant.signals.base import ProbSignal

    exit_rule = cfg.exit_rule
    hold_days = max(1, exit_rule.hold_h // 24)

    if isinstance(signal, ProbSignal):
        thr = signal.default_threshold
        probs = signal.as_feature(bars).to_numpy(dtype=float)
        fires_mask = probs >= thr
    else:
        fires_mask = signal.as_feature(bars).fillna(False).to_numpy(dtype=bool)

    fire_timestamps = bars.index[fires_mask]
    pnl_pct: list[float] = []
    entry_credits_usd: list[float] = []
    dte_actual: list[int] = []
    realized_otm: list[bool] = []

    sell_call = cfg.tilt != "put_heavy"
    sell_put = cfg.tilt != "call_heavy"

    for ts in fire_timestamps:
        fire_date = ts.date()
        entry_chain = _load_chain_df(chains_dir, fire_date)
        if entry_chain is None or not _valid_chain(entry_chain):
            continue

        expiry_date = _nearest_expiry(entry_chain, fire_date, cfg.dte)
        if expiry_date is None:
            continue

        spot = _spot_price_on_date(chains_dir, fire_date)
        if spot is None and "underlying_price" in entry_chain.columns:
            up = entry_chain["underlying_price"].dropna()
            if len(up):
                spot = float(up.iloc[0])
        if spot is None and ts in bars.index:
            spot = float(bars.loc[ts, "close"])
        if spot is None or spot <= 0:
            continue

        credit_frac = 0.0
        call_short = put_short = None
        call_long = put_long = None
        call_strike = put_strike = float("nan")

        if sell_call:
            c_credit, call_short, call_long = _spread_credit(
                entry_chain,
                expiry_date,
                cfg.target_delta,
                cfg.wing_delta_offset,
                True,
                structure=cfg.structure,
            )
            credit_frac += c_credit
            if call_short is not None:
                call_strike = float(call_short["strike"])

        if sell_put:
            p_credit, put_short, put_long = _spread_credit(
                entry_chain,
                expiry_date,
                cfg.target_delta,
                cfg.wing_delta_offset,
                False,
                structure=cfg.structure,
            )
            credit_frac += p_credit
            if put_short is not None:
                put_strike = float(put_short["strike"])

        if credit_frac <= 0 or not np.isfinite(credit_frac):
            continue

        entry_usd = credit_frac * spot
        exit_date = min(fire_date + timedelta(days=hold_days), expiry_date)
        exit_chain = _load_chain_df(chains_dir, exit_date)
        if exit_chain is not None and not _valid_chain(exit_chain):
            exit_chain = None
        exit_spot = _spot_price_on_date(chains_dir, exit_date)
        if exit_spot is None and exit_chain is not None and "underlying_price" in exit_chain.columns:
            up = exit_chain["underlying_price"].dropna()
            if len(up):
                exit_spot = float(up.iloc[0])
        if exit_spot is None:
            exit_spot = spot

        if exit_chain is not None and exit_spot is not None:
            exit_cost = 0.0
            if sell_call and call_short is not None:
                exit_cost += _spread_exit_cost(
                    exit_chain,
                    expiry_date,
                    call_short,
                    call_long,
                    cfg.target_delta,
                    cfg.wing_delta_offset,
                    True,
                    structure=cfg.structure,
                )
            if sell_put and put_short is not None:
                exit_cost += _spread_exit_cost(
                    exit_chain,
                    expiry_date,
                    put_short,
                    put_long,
                    cfg.target_delta,
                    cfg.wing_delta_offset,
                    False,
                    structure=cfg.structure,
                )
        elif exit_spot is not None and np.isfinite(call_strike) and np.isfinite(put_strike):
            exit_cost = _intrinsic_straddle_frac(exit_spot, call_strike, put_strike)
        else:
            continue

        pnl = (credit_frac - exit_cost) / credit_frac
        pnl_pct.append(float(pnl))
        entry_credits_usd.append(float(entry_usd))
        dte_actual.append((expiry_date - fire_date).days)
        if exit_spot is not None and np.isfinite(call_strike) and np.isfinite(put_strike):
            realized_otm.append(_expiry_otm(exit_spot, call_strike, put_strike))
        else:
            realized_otm.append(pnl > 0)

    n = len(pnl_pct)
    if n > 0:
        win_rate = float(np.mean(np.array(pnl_pct) > 0))
        expectancy = float(np.mean(pnl_pct))
    else:
        win_rate = float("nan")
        expectancy = float("nan")

    return ShortVolResult(
        fires_evaluated=len(fire_timestamps),
        fires_with_data=n,
        pnl_pct=pnl_pct,
        win_rate=win_rate,
        expectancy=expectancy,
        entry_credits_usd=entry_credits_usd,
        dte_actual=dte_actual,
        realized_otm=realized_otm,
    )
