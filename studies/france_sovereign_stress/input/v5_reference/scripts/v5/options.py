"""Eurex OOAT / OGBL option sleeves (Swissquote) on v5 paths, reusing the v4 pricing and roll machinery.

Two modes: `front` puts the whole budget in the liquid 20 Nov series (no roll; dead if the stress comes later),
`ladder` rolls into the second-nearest expiry to mid-2027 with the budget spread by tranche length.
Positions are sold at model value on the stress completion day.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "v4"))

import book  # noqa: E402
import market  # noqa: E402
from book import Env, sleeve_cash, tranches  # noqa: E402
from structures import Leg, Structure, ogbl_universe, single, spread_plus_tail, vertical  # noqa: E402

from model import World  # noqa: E402


class OptPaths:
    """v4 Paths interface (calendar-day lookups) over a v5 business-day World."""

    def __init__(self, w: World, start: date):
        self.w = w
        self.s0 = w.s0
        self.n = w.n
        self._ord = np.array([(d - start).days for d in w.days])
        self._rows = np.arange(w.n)
        self.t_exit = self._ord[w.tc].astype(float) if w.level is not None else np.full(w.n, 1e9)

    def _idx(self, t):
        t = np.broadcast_to(np.asarray(t, dtype=float), (self.n,))
        return np.clip(np.searchsorted(self._ord, t, side="right") - 1, 0, self.w.T)

    def ds(self, t):
        return self.w.ds[self._rows, self._idx(t)]

    def db(self, t):
        return self.w.db[self._rows, self._idx(t)]


def backspread(k_short: float, k_long: float, ratio: int) -> Structure:
    return Structure(f"OOAT {k_short:g}/{k_long:g} 1×{ratio} put backspread",
                     (Leg("OOAT", "P", k_short, -1), Leg("OOAT", "P", k_long, ratio)))


def ooat_universe() -> list:
    out = []
    for k1 in np.arange(108.0, 101.75, -0.5):
        out.append(single("OOAT", "P", k1))
        for w in (2, 3, 4, 6):
            out.append(vertical("OOAT", "P", k1, k1 - w))
        out.append(spread_plus_tail(k1, k1 - 3, k1 - 4))
    for ks in (109.0, 108.5, 108.0, 107.5, 107.0):
        for gap in (1.5, 2, 3, 4):
            for ratio in (2, 3):
                out.append(backspread(ks, ks - gap, ratio))
    return out


def make_env(snap, budget: float, mode: str, duration: dict) -> Env:
    """`duration` maps FOAT / FGBL to the measured futures duration; options use it for their underlying."""
    book.DUR.update({"OOAT": duration["FOAT"], "OGBL": duration["FGBL"]})
    env = Env(snap, budget, 2)
    if mode == "front":
        env.tranches = env.tranches[:1]
        env.shares = np.array([1.0])
    return env


def option_cash(env: Env, s: Structure, p: OptPaths):
    trs = tranches(env, s, p)
    return None if trs is None else sleeve_cash(env, s, trs)


def universe() -> list:
    return ooat_universe() + ogbl_universe()


def load_snapshot(path=None):
    return market.load(path)
