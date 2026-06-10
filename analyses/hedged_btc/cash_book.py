"""C7 — USD cash book + long calls (+ optional CSP income), cash-settled."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ._utils import expiry_dte
from .fees import entry_fees_usd, exit_fees_usd
from .book import open_sleeve_legs
from .pricing import (
    LegSpec,
    PricedLeg,
    close_proceeds_usd,
    entry_cost_usd,
    pick_expiry_near_dte,
    price_leg,
    reprice_leg,
)


@dataclass
class CashParticipationSpec:
    """USD-stable base; long calls for upside; optional short puts for income."""

    name: str
    participation_legs: list[tuple[LegSpec, float]]
    income_legs: list[tuple[LegSpec, float]] = field(default_factory=list)
    call_tenor_dte: int = 37
    put_tenor_dte: int = 37
    call_budget_pct: float = 0.02
    income_put_qty: float = 0.25
    roll_day: int = 11
    roll_min_dte: int = 7


@dataclass
class CashBookPosition:
    opened: date
    call_expiry: str | None
    call_legs: list[PricedLeg]
    put_expiry: str | None
    put_legs: list[PricedLeg]

    @property
    def legs(self) -> list[PricedLeg]:
        return self.call_legs + self.put_legs


def call_intrinsic_usd(leg: PricedLeg, spot: float) -> float:
    """USD payoff for long call at expiry (1 BTC contract per unit qty)."""
    if leg.qty <= 0 or not leg.is_call:
        return 0.0
    return max(0.0, spot - leg.strike) * leg.qty


def put_intrinsic_usd(leg: PricedLeg, spot: float) -> float:
    """USD liability for short put at cash-settlement (qty < 0)."""
    if leg.qty >= 0 or leg.is_call:
        return 0.0
    return max(0.0, leg.strike - spot) * abs(leg.qty)


def scale_legs_to_budget(
    snap: pd.DataFrame,
    as_of: date,
    leg_specs: list[tuple[LegSpec, float]],
    *,
    expiry: str,
    budget_usd: float,
) -> list[PricedLeg] | None:
    """Open legs at qty=1, scale down if net debit exceeds budget."""
    legs = open_sleeve_legs(snap, as_of, leg_specs, expiry=expiry)
    if legs is None:
        return None
    debit = entry_cost_usd(legs)
    if debit <= 0:
        return legs
    scale = min(1.0, budget_usd / debit)
    if scale <= 0:
        return None
    scaled: list[PricedLeg] = []
    for leg in legs:
        scaled.append(
            PricedLeg(
                as_of=leg.as_of,
                expiry=leg.expiry,
                strike=leg.strike,
                is_call=leg.is_call,
                qty=leg.qty * scale,
                spot=leg.spot,
                mark_btc=leg.mark_btc,
                bid_btc=leg.bid_btc,
                ask_btc=leg.ask_btc,
                delta=leg.delta,
                iv=leg.iv,
            )
        )
    return scaled


def open_income_puts(
    snap: pd.DataFrame,
    as_of: date,
    spec: CashParticipationSpec,
    *,
    expiry: str,
) -> list[PricedLeg] | None:
    if not spec.income_legs:
        return []
    legs: list[PricedLeg] = []
    for leg_spec, _qty in spec.income_legs:
        priced = price_leg(
            snap, as_of, expiry=expiry, spec=leg_spec, qty=-spec.income_put_qty,
        )
        if priced is None:
            return None
        legs.append(priced)
    return legs


def mark_cash_book(snap: pd.DataFrame, pos: CashBookPosition, as_of: date) -> CashBookPosition | None:
    calls, puts = [], []
    for leg in pos.call_legs:
        p = reprice_leg(snap, leg, as_of)
        if p is None:
            return None
        calls.append(p)
    for leg in pos.put_legs:
        p = reprice_leg(snap, leg, as_of)
        if p is None:
            return None
        puts.append(p)
    return CashBookPosition(
        opened=pos.opened,
        call_expiry=pos.call_expiry,
        call_legs=calls,
        put_expiry=pos.put_expiry,
        put_legs=puts,
    )


def book_mtm_usd(pos: CashBookPosition, *, use_bid_ask: bool = True) -> float:
    return sum(leg.mtm_usd(use_bid_ask=use_bid_ask) for leg in pos.legs)


def _monthly_roll_due(d: date, last_roll: date | None, roll_day: int) -> bool:
    if last_roll is None:
        return True
    if d <= last_roll:
        return False
    period = (d.year, d.month)
    last_period = (last_roll.year, last_roll.month)
    return period != last_period and d.day >= roll_day


def should_roll_calls(
    pos: CashBookPosition | None, d: date, spec: CashParticipationSpec, last_roll: date | None,
) -> bool:
    if pos is None or not pos.call_legs:
        return True
    if pos.call_expiry and expiry_dte(pos.call_expiry, d) <= spec.roll_min_dte:
        return True
    return _monthly_roll_due(d, last_roll, spec.roll_day)


def should_roll_puts(
    pos: CashBookPosition | None, d: date, spec: CashParticipationSpec, last_roll: date | None,
) -> bool:
    if not spec.income_legs:
        return False
    if pos is None:
        return False
    if not pos.put_legs:
        return True
    if pos.put_expiry and expiry_dte(pos.put_expiry, d) <= spec.roll_min_dte:
        return True
    return _monthly_roll_due(d, last_roll, spec.roll_day)


def settle_expired_legs(
    pos: CashBookPosition,
    d: date,
    spot: float,
    cash_usd: float,
    use_fees: bool,
) -> tuple[CashBookPosition, float, float]:
    """Cash-settle legs at expiry (no assignment to BTC). Returns (pos, cash, fees)."""
    fees = 0.0
    calls = list(pos.call_legs)
    puts = list(pos.put_legs)
    call_exp = pos.call_expiry
    put_exp = pos.put_expiry

    if call_exp and expiry_dte(call_exp, d) <= 0:
        for leg in calls:
            cash_usd += call_intrinsic_usd(leg, spot)
            if use_fees and leg.mark_btc > 0:
                cash_usd -= exit_fees_usd([leg])  # settlement event
                fees += exit_fees_usd([leg])
        calls = []
        call_exp = None

    if put_exp and expiry_dte(put_exp, d) <= 0:
        for leg in puts:
            payout = put_intrinsic_usd(leg, spot)
            cash_usd -= payout
            if use_fees and leg.mark_btc > 0:
                cash_usd -= exit_fees_usd([leg])
                fees += exit_fees_usd([leg])
        puts = []
        put_exp = None

    new_pos = CashBookPosition(opened=pos.opened, call_expiry=call_exp, call_legs=calls, put_expiry=put_exp, put_legs=puts)
    return new_pos, cash_usd, fees


def pick_call_expiry(snap: pd.DataFrame, d: date, spec: CashParticipationSpec) -> str | None:
    return pick_expiry_near_dte(snap, d, spec.call_tenor_dte, tol=14)


def pick_put_expiry(snap: pd.DataFrame, d: date, spec: CashParticipationSpec) -> str | None:
    return pick_expiry_near_dte(snap, d, spec.put_tenor_dte, tol=14)
