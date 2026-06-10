"""Phase 2b — Multi-leg book position container."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .pricing import LegSpec, PricedLeg, close_proceeds_usd, entry_cost_usd, price_leg, reprice_leg


@dataclass(frozen=True)
class RollPolicy:
    """Parameterized roll behaviour shared across candidates."""

    ratchet_pct: float | None = 0.12
    iv_ceiling_pct: float | None = 55.0
    critical_dte: int = 7
    defer_roll_if_iv_high: bool = True


@dataclass
class BookSpec:
    """Static specification for a candidate book."""

    name: str
    protection_legs: list[tuple[LegSpec, float]]  # (spec, qty)
    income_legs: list[tuple[LegSpec, float]] = field(default_factory=list)
    protection_tenor_dte: int = 90
    income_tenor_dte: int | None = None
    roll_min_dte: int = 14
    income_roll_min_dte: int = 3
    roll_policy: RollPolicy | None = None


@dataclass
class BookPosition:
    """Open book: spot unit + protection and optional income sleeves."""

    opened: date
    protection_expiry: str
    protection_legs: list[PricedLeg]
    income_expiry: str | None
    income_legs: list[PricedLeg]
    entry_cost_usd: float
    spot_at_open: float

    @property
    def expiry(self) -> str:
        """Back-compat: primary protection expiry."""
        return self.protection_expiry

    @property
    def legs(self) -> list[PricedLeg]:
        return self.protection_legs + self.income_legs


def open_sleeve_legs(
    snap: pd.DataFrame,
    as_of: date,
    leg_specs: list[tuple[LegSpec, float]],
    *,
    expiry: str,
) -> list[PricedLeg] | None:
    legs: list[PricedLeg] = []
    for leg_spec, qty in leg_specs:
        priced = price_leg(snap, as_of, expiry=expiry, spec=leg_spec, qty=qty)
        if priced is None:
            return None
        legs.append(priced)
    return legs


def open_book(
    snap: pd.DataFrame,
    as_of: date,
    spec: BookSpec,
    *,
    protection_expiry: str,
    income_expiry: str | None = None,
) -> BookPosition | None:
    prot = open_sleeve_legs(snap, as_of, spec.protection_legs, expiry=protection_expiry)
    if prot is None:
        return None

    inc: list[PricedLeg] = []
    inc_exp = income_expiry
    if spec.income_legs:
        if inc_exp is None:
            return None
        opened = open_sleeve_legs(snap, as_of, spec.income_legs, expiry=inc_exp)
        if opened is None:
            return None
        inc = opened

    all_legs = prot + inc
    cost = entry_cost_usd(all_legs)
    spot = prot[0].spot
    return BookPosition(
        opened=as_of,
        protection_expiry=protection_expiry,
        protection_legs=prot,
        income_expiry=inc_exp,
        income_legs=inc,
        entry_cost_usd=cost,
        spot_at_open=spot,
    )


def mark_book(snap: pd.DataFrame, pos: BookPosition, as_of: date) -> BookPosition | None:
    prot = []
    for leg in pos.protection_legs:
        p = reprice_leg(snap, leg, as_of)
        if p is None:
            return None
        prot.append(p)
    inc = []
    for leg in pos.income_legs:
        p = reprice_leg(snap, leg, as_of)
        if p is None:
            return None
        inc.append(p)
    return BookPosition(
        opened=pos.opened,
        protection_expiry=pos.protection_expiry,
        protection_legs=prot,
        income_expiry=pos.income_expiry,
        income_legs=inc,
        entry_cost_usd=pos.entry_cost_usd,
        spot_at_open=pos.spot_at_open,
    )


def book_option_mtm_usd(pos: BookPosition, *, use_bid_ask: bool = True) -> float:
    return sum(leg.mtm_usd(use_bid_ask=use_bid_ask) for leg in pos.legs)
