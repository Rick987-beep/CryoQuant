"""Option structures (no futures): legs, executable live cost, model cost at the roll, payoff at expiry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from market import Expiry, Skew, b76

TICK = {"OOAT": 0.25, "OGBL": 0.5}
HALF_SPREAD = {"OOAT": 0.09, "OGBL": 0.01}
FEE = 2.35


@dataclass(frozen=True)
class Leg:
    product: str
    cp: str
    k: float
    q: int

    @property
    def text(self) -> str:
        side = "Buy" if self.q > 0 else "Sell"
        kind = "put" if self.cp == "P" else "call"
        return f"{side} {abs(self.q)} {self.product} {self.k:.2f} {kind}"


@dataclass(frozen=True)
class Structure:
    name: str
    legs: Tuple[Leg, ...]

    @property
    def product(self) -> str:
        return self.legs[0].product

    @property
    def n_contracts(self) -> int:
        return sum(abs(l.q) for l in self.legs)

    def live_cost(self, exp: Expiry) -> Optional[float]:
        total = 0.0
        for l in self.legs:
            px = exp.cost(l.cp, l.k, l.q)
            if px is None:
                return None
            total += px * l.q
        return total

    def payoff(self, f_o, f_b):
        out = 0.0
        for l in self.legs:
            f = f_o if l.product == "OOAT" else f_b
            out = out + l.q * (np.maximum(l.k - f, 0) if l.cp == "P" else np.maximum(f - l.k, 0))
        return out

    def rolled(self, f_ref: float, f1, t2: float, skew: Skew, atm1):
        """Re-strike at the roll at the same distance from the money; return (strikes per leg, model cost)."""
        strikes, cost = [], 0.0
        for l in self.legs:
            tick = TICK[l.product]
            k2 = np.round((f1 + (l.k - f_ref)) / tick) * tick
            mid = b76(f1, k2, t2, skew.vol(f1, k2, t2, atm1), l.cp == "C")
            cost = cost + l.q * (mid + np.sign(l.q) * HALF_SPREAD[l.product])
            strikes.append(k2)
        return strikes, cost

    def payoff_at(self, strikes, f_o, f_b):
        out = 0.0
        for l, k in zip(self.legs, strikes):
            f = f_o if l.product == "OOAT" else f_b
            out = out + l.q * (np.maximum(k - f, 0) if l.cp == "P" else np.maximum(f - k, 0))
        return out

    def close_value(self, strikes, f_o, f_b, t_rem, skew: Skew, atm):
        """Model value when closing before expiry: longs sold at mid − half-spread, shorts bought back at mid + it."""
        t_rem = np.maximum(t_rem, 1 / 365)
        out = 0.0
        for l, k in zip(self.legs, strikes):
            f = f_o if l.product == "OOAT" else f_b
            mid = b76(f, k, t_rem, skew.vol(f, k, t_rem, atm), l.cp == "C")
            out = out + l.q * mid - abs(l.q) * HALF_SPREAD[l.product]
        return np.maximum(out, 0)


def single(product: str, cp: str, k: float) -> Structure:
    kind = "put" if cp == "P" else "call"
    return Structure(f"{product} {k:g} {kind}", (Leg(product, cp, k, 1),))


def vertical(product: str, cp: str, k_long: float, k_short: float) -> Structure:
    kind = "put" if cp == "P" else "call"
    return Structure(f"{product} {k_long:g}/{k_short:g} {kind} spread",
                     (Leg(product, cp, k_long, 1), Leg(product, cp, k_short, -1)))


def spread_plus_tail(k_long: float, k_short: float, k_tail: float) -> Structure:
    return Structure(f"OOAT {k_long:g}/{k_short:g} put spread + {k_tail:g} put",
                     (Leg("OOAT", "P", k_long, 1), Leg("OOAT", "P", k_short, -1), Leg("OOAT", "P", k_tail, 1)))


def ooat_universe():
    out = []
    for k1 in np.arange(108.0, 103.25, -0.5):
        out.append(single("OOAT", "P", k1))
        for w in (2, 3, 4, 5, 6):
            out.append(vertical("OOAT", "P", k1, k1 - w))
            if w >= 3:
                out.append(spread_plus_tail(k1, k1 - w, k1 - w - 1))
    return out


def ogbl_universe():
    out = []
    for k1 in np.arange(121.5, 124.25, 0.5):
        out.append(single("OGBL", "C", k1))
        for w in (1.5, 2, 2.5, 3, 4):
            out.append(vertical("OGBL", "C", k1, k1 + w))
    return out
