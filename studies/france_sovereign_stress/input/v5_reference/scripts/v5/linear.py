"""Linear sleeves on IBKR (futures, stocks) with a hard stop and optional pyramiding.

Each sleeve is a cumulative exposure path X[n, T+1] in its own unit (bp for futures, % for stocks), net of carry.
Sizing: units = (equity − floor) / d, so a d-unit adverse move from the last entry costs everything above the floor.
Initial floor is 0 (lose the whole budget if the stop is hit). Pyramiding: each time X gains `step` above the last
entry, resize to (1 − keep) · equity / d and trail the stop to X − d; `keep` is the share of equity locked in.
Stops fill half-way between the stop level (less slippage) and the daily close if the close gaps through it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from model import Calib, FutCalib, World

FUT_FEE = 2.35
TICK_EUR = 10.0


@dataclass(frozen=True)
class Rule:
    d: float
    step: Optional[float] = None
    keep: float = 0.0

    @property
    def text(self) -> str:
        base = f"stop {self.d:g}"
        return base if self.step is None else f"{base}, add every +{self.step:g} (lock {self.keep:.0%})"


@dataclass
class Sleeve:
    key: str
    name: str
    unit: str
    X: np.ndarray
    tcost: float
    slip: float
    cap_units: float
    contracts_per_unit: dict
    rolls: tuple = ()


def futures_sleeves(w: World, fc: FutCalib):
    """Spread trade (short FOAT / long FGBL, DV01-neutral), outright short FOAT, outright long FGBL.

    Futures are quoted in price; a yield rise of 1 bp moves the price by −eur_per_bp / 1000 points. Short FOAT and
    long FGBL in equal EUR/bp therefore gains EUR/bp × (ΔOAT yield − ΔBund yield) = EUR/bp × Δspread.
    """
    eur_bp = fc.eur_per_bp
    carry_bp = fc.carry_bp_per_day
    t = np.arange(w.T + 1)[None, :]
    rolls = tuple(sorted({next(i for i, d in enumerate(w.days) if d.month == mo and d.year == yr)
                          for mo, yr in ((12, 2026), (3, 2027), (6, 2027))}))
    per_tick_bp = {k: (TICK_EUR / 2 + FUT_FEE) / eur_bp[k] for k in eur_bp}
    hb = eur_bp["FOAT"] / eur_bp["FGBL"]
    oat = w.ds + w.db
    cap = 20 * eur_bp["FOAT"]
    return [
        Sleeve("spread", "Spread trade: short FOAT / long FGBL (DV01-neutral)", "bp",
               w.ds - (carry_bp["FOAT"] - carry_bp["FGBL"]) * t, per_tick_bp["FOAT"] + per_tick_bp["FGBL"], 1.0, cap,
               {"FOAT": -1 / eur_bp["FOAT"], "FGBL": hb / eur_bp["FOAT"]}, rolls),
        Sleeve("foat_short", "Short FOAT", "bp", oat - carry_bp["FOAT"] * t, per_tick_bp["FOAT"], 0.7, cap,
               {"FOAT": -1 / eur_bp["FOAT"]}, rolls),
        Sleeve("fgbl_long", "Long FGBL", "bp", -w.db + carry_bp["FGBL"] * t, per_tick_bp["FGBL"], 0.7,
               20 * eur_bp["FGBL"], {"FGBL": 1 / eur_bp["FGBL"]}, rolls),
    ], {"eur_per_bp": eur_bp, "duration": fc.duration, "carry_bp_per_day": carry_bp, "hedge_ratio": hb,
        "corr_price_yield": fc.corr, "calib_days": fc.days}


STOCK_COST = 0.035
CAC_FUT_COST = 0.01


def stock_sleeves(w: World, cal: Calib, names: dict) -> list:
    t = np.arange(w.T + 1)[None, :]
    out = []
    for tic, st in cal.stocks.items():
        cost = CAC_FUT_COST if tic == "^FCHI" else STOCK_COST
        r = w.stock_returns(cal, tic)
        X = -(np.exp(r) - 1) * 100 - cost / 252 * 100 * t
        label = "Short CAC 40 future (FCE)" if tic == "^FCHI" else f"Short {names.get(tic, tic)}"
        out.append(Sleeve(tic, label, "%", X, 0.10, 0.5, 2_000.0, {}))
    return out


def run(s: Sleeve, w: World, rule: Rule, budget: float):
    """Equity at exit per path, and initial units."""
    n = w.n
    X = s.X
    units0 = min(budget / rule.d, s.cap_units)
    units = np.full(n, units0)
    eq = np.full(n, budget) - units * s.tcost
    stop = np.full(n, -rule.d)
    anchor = np.zeros(n)
    alive = np.ones(n, bool)
    rolls = set(s.rolls)
    for t in range(1, w.T + 1):
        act = alive & (t <= w.tc)
        if not act.any():
            break
        x, xp = X[:, t], X[:, t - 1]
        hit = act & (x <= stop)
        fill = stop - s.slip - 0.5 * np.maximum(stop - s.slip - x, 0)
        eq = np.where(hit, eq + units * (fill - xp) - units * s.tcost, np.where(act, eq + units * (x - xp), eq))
        alive &= ~hit
        live = act & ~hit
        if t in rolls:
            eq = eq - np.where(live, units * 2 * s.tcost, 0)
        if rule.step is not None:
            up = live & (x >= anchor + rule.step)
            if up.any():
                new = np.minimum((1 - rule.keep) * np.maximum(eq, 0) / rule.d, s.cap_units)
                eq = np.where(up, eq - np.abs(new - units) * s.tcost, eq)
                units = np.where(up, new, units)
                anchor = np.where(up, x, anchor)
                stop = np.where(up, x - rule.d, stop)
        done = live & (t == w.tc)
        eq = np.where(done, eq - units * s.tcost, eq)
        alive &= ~done
    return eq, units0


def rules(unit: str) -> list:
    ds = (10, 15, 20, 30, 40, 60) if unit == "bp" else (5, 8, 12, 20, 30)
    out = []
    for d in ds:
        out.append(Rule(d))
        for step in (d / 2, d):
            for keep in (0.0, 0.5):
                out.append(Rule(d, step, keep))
    return out
