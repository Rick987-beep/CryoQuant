"""Rolling book valuation to mid-2027.

Roll ladder: tranche 1 is bought now in the 20 Nov expiry at live Eurex bid/ask. At each expiry the next tranche is
bought in the expiry `cadence` months ahead (cadence 2 = always the second-nearest, liquid series), re-struck at the
same distance from the money, priced off today's 20 Nov skew with ATM vol raised by the spread widening so far, plus
a half-spread per leg. Premium per tranche is proportional to its length, so the budget covers the whole horizon.

Exit: when the stress event completes, open options are sold at model value and rolling stops. No new tranche is
bought when the spread is already at or above ROLL_STOP. Calm paths hold every tranche to expiry.
Positions are fractional here; integer contracts are set when sizing the order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

import numpy as np

from market import Snapshot
from scenarios import HALF, REGIMES, Paths
from structures import FEE, Structure

FIRST_EXPIRY = "20/11/2026"
HORIZON_END = date(2027, 6, 30)
DUR = {"OOAT": 7.1, "OGBL": 7.4}
VOL_UP = {"OOAT": 0.50, "OGBL": 0.30}
ROLL_STOP = 200.0
HOLIDAYS = {date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31), date(2027, 1, 1),
            date(2027, 3, 26), date(2027, 3, 29), date(2027, 12, 24), date(2027, 12, 31)}


def exchange_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def eurex_expiry(year: int, month: int) -> date:
    """Last trading day of an Eurex bond option contract month: the last Friday before the first calendar day of the
    month that is followed by at least two exchange days before that first day; moved earlier if a holiday."""
    first = date(year, month, 1)
    d = first - timedelta(days=1)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    gap = sum(exchange_day(d + timedelta(days=i)) for i in range(1, (first - d).days))
    if gap < 2:
        d -= timedelta(days=7)
    while not exchange_day(d):
        d -= timedelta(days=1)
    return d


def schedule(first: date, cadence: int, end: date) -> List[date]:
    months = [(first.year + (first.month + i) // 12, (first.month + i) % 12 + 1) for i in range(24)]
    expiries = sorted({eurex_expiry(y, m) for y, m in months} | {first})
    expiries = [e for e in expiries if e >= first]
    out = [first]
    i = 0
    while out[-1] < end:
        i += cadence
        out.append(expiries[i])
    return out


@dataclass
class Env:
    snap: Snapshot
    budget: float = 10_000.0
    cadence: int = 2

    def __post_init__(self):
        self.e1 = {p: self.snap.expiries[(p, FIRST_EXPIRY)] for p in ("OOAT", "OGBL")}
        self.f0 = {p: e.fwd for p, e in self.e1.items()}
        self.dv01 = {p: self.f0[p] * DUR[p] / 1e4 for p in self.f0}
        self.t0 = self.snap.val_date
        ends = schedule(self.e1["OOAT"].date, self.cadence, HORIZON_END)
        self.tranches = list(zip([self.t0] + ends[:-1], ends))
        days = np.array([(b - a).days for a, b in self.tranches], dtype=float)
        self.shares = days / days.sum()
        self.horizon = float((HORIZON_END - self.t0).days)

    def day(self, d: date) -> float:
        return float((d - self.t0).days)


@dataclass
class Tranche:
    cost: np.ndarray
    value: np.ndarray
    deploy: np.ndarray
    closed: np.ndarray
    strikes: list


def futures(env: Env, p: Paths, t) -> dict:
    db = p.db(t)
    return {"OOAT": env.f0["OOAT"] - env.dv01["OOAT"] * (p.ds(t) + db), "OGBL": env.f0["OGBL"] - env.dv01["OGBL"] * db}


def tranches(env: Env, s: Structure, p: Paths) -> Optional[List[Tranche]]:
    e = env.e1[s.product]
    c1 = s.live_cost(e)
    if c1 is None or c1 <= 0:
        return None
    vol = lambda t: e.skew.atm * (1 + VOL_UP[s.product] * np.maximum(p.ds(t), 0) / 100)
    t_exit = p.t_exit
    out = []
    for k, (start, end) in enumerate(env.tranches):
        ts, tend = env.day(start), env.day(end)
        if k == 0:
            strikes = [np.full(p.n, l.k) for l in s.legs]
            cost = np.full(p.n, c1)
            deploy = np.ones(p.n, bool)
        else:
            f_roll = futures(env, p, ts)[s.product]
            strikes, cost = s.rolled(e.fwd, f_roll, (tend - ts) / 365, e.skew, vol(ts))
            deploy = (t_exit > ts) & (p.s0 + p.ds(ts) < ROLL_STOP)
        closed = (t_exit > ts) & (t_exit < tend)
        f_end = futures(env, p, tend)
        intrinsic = s.payoff_at(strikes, f_end["OOAT"], f_end["OGBL"])
        tx = np.minimum(t_exit, tend)
        f_x = futures(env, p, tx)
        close = s.close_value(strikes, f_x["OOAT"], f_x["OGBL"], (tend - tx) / 365, e.skew, vol(tx))
        out.append(Tranche(np.maximum(cost, 1e-3), np.where(closed, close, intrinsic), deploy, closed, strikes))
    return out


def sleeve_cash(env: Env, s: Structure, trs: List[Tranche]):
    """Spend and payoff (EUR) per path with the whole budget on this structure; scales linearly with the share."""
    nc = s.n_contracts
    spent = 0.0
    pay = 0.0
    for share, tr in zip(env.shares, trs):
        unit = tr.cost * 1000 + FEE * nc
        n = np.where(tr.deploy, env.budget * share / unit, 0)
        spent = spent + n * unit
        pay = pay + n * (tr.value * 1000 - FEE * nc * tr.closed)
    return spent, pay


def mc_metrics(spent: np.ndarray, pay: np.ndarray, p: Paths) -> dict:
    pnl = pay - spent
    reg = [float(pnl[p.regime == i].mean()) for i in range(4)]
    reg_spent = [float(spent[p.regime == i].mean()) for i in range(4)]
    return {
        "ev": float(sum(r[3] * x for r, x in zip(REGIMES, reg))),
        "ev_half": float(sum(q * x for q, x in zip(HALF, reg))),
        "avg_spent": float(spent.mean()),
        "p_profit": float((pnl > 0).mean()),
        "p_3x": float((pay >= 3 * spent).mean()),
        "p_full_loss": float((pay <= 0.02 * spent).mean()),
        "p5": float(np.percentile(pnl, 5)), "p50": float(np.percentile(pnl, 50)), "p95": float(np.percentile(pnl, 95)),
        "regimes": {r[0]: {"pnl": round(x), "spent": round(c), "x": round((x + c) / c, 2) if c else 0}
                    for r, x, c in zip(REGIMES, reg, reg_spent)},
    }
