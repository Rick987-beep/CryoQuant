"""Stop / pyramid rule engine for spread and CAC sleeves.

Execution modes
---------------
- ``daily_close`` (v6 default): stop and adds evaluated on the daily close; stop
  fill is the close (minus slippage in bp / %). Matches Eurex/IBKR reality for a
  synthetic OAT–Bund spread (no resting exchange stop).
- ``resting_stop`` (v5): continuous mark; fill at stop − slip, half the gap if the
  close jumps through.

Sizing
------
- ``continuous``: exposure in € per bp (or € per % for stocks), as in v5.
- ``integer``: whole FOAT / FGBL contracts (spread) or MFC minis (CAC).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Optional, Sequence

import numpy as np

from src.calibrate import FutCalib, StockBeta
from src.instruments import FOAT, FGBL
from src.scenarios import World

ExecutionMode = Literal["daily_close", "resting_stop"]
SizingMode = Literal["continuous", "integer"]

FUT_FEE = 2.35
TICK_EUR = 10.0
HALF_TICK = TICK_EUR / 2.0


@dataclass(frozen=True)
class Rule:
    d: float
    step: Optional[float] = None
    keep: float = 0.0

    @property
    def text(self) -> str:
        base = f"stop {self.d:g}"
        if self.step is None:
            return base
        return f"{base}, add every +{self.step:g} (lock {self.keep:.0%})"


@dataclass
class Sleeve:
    key: str
    name: str
    unit: str  # "bp" or "%"
    X: np.ndarray
    tcost: float
    slip: float
    cap_units: float
    contracts_per_unit: dict[str, float]
    rolls: tuple[int, ...] = ()


def roll_indices(days: np.ndarray, months: Sequence[tuple[int, int]] | None = None) -> tuple[int, ...]:
    """First business day of each (month, year) on the path (v5 roll dates)."""
    months = months or ((12, 2026), (3, 2027), (6, 2027))
    found: list[int] = []
    for mo, yr in months:
        for i, d in enumerate(days):
            dd = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
            if dd.month == mo and dd.year == yr:
                found.append(i)
                break
    return tuple(sorted(set(found)))


def per_tick_cost_bp(
    eur_per_bp: float,
    *,
    fee_per_side: float = FUT_FEE,
    half_tick_eur: float = HALF_TICK,
) -> float:
    """One-side cost in bp of spread exposure for a single futures leg."""
    return (half_tick_eur + fee_per_side) / eur_per_bp


def build_spread_sleeve(
    world: World,
    fc: FutCalib,
    *,
    fee_per_side: float = FUT_FEE,
    half_tick_eur: float = HALF_TICK,
    slip_bp: float = 1.0,
) -> Sleeve:
    """Short FOAT / long FGBL, equal €/bp; X = Δspread − net carry.

    ``fee_per_side`` / ``half_tick_eur`` are per-contract, per-side (€). Defaults
    match the v5 IBKR/Lynx proxy (€2.35 + half of €10 tick).
    """
    t = np.arange(world.T + 1)[None, :]
    net_carry = fc.carry_bp_per_day["FOAT"] - fc.carry_bp_per_day["FGBL"]
    X = world.ds - net_carry * t
    ef, eg = fc.eur_per_bp["FOAT"], fc.eur_per_bp["FGBL"]
    hb = ef / eg
    tcost = per_tick_cost_bp(ef, fee_per_side=fee_per_side, half_tick_eur=half_tick_eur) + per_tick_cost_bp(
        eg, fee_per_side=fee_per_side, half_tick_eur=half_tick_eur
    )
    return Sleeve(
        key="spread",
        name="Spread trade: short FOAT / long FGBL (DV01-neutral)",
        unit="bp",
        X=X,
        tcost=tcost,
        slip=float(slip_bp),
        cap_units=20.0 * ef,
        contracts_per_unit={"FOAT": -1.0 / ef, "FGBL": hb / ef},
        rolls=roll_indices(world.days),
    )


def build_cac_sleeve(world: World, beta: StockBeta, *, carry_pa: float = 0.01) -> Sleeve:
    """Short CAC: X = −(exp(r)−1)×100 − carry%/year."""
    from src.scenarios import stock_cum_returns

    r = stock_cum_returns(world, beta)
    t = np.arange(world.T + 1)[None, :]
    X = -(np.exp(r) - 1.0) * 100.0 - carry_pa / 252.0 * 100.0 * t
    return Sleeve(
        key="^FCHI",
        name="Short CAC 40 future (FCE)",
        unit="%",
        X=X,
        tcost=0.10,
        slip=0.5,
        cap_units=2_000.0,
        contracts_per_unit={},
        rolls=(),
    )


def run_continuous(
    sleeve: Sleeve,
    world: World,
    rule: Rule,
    budget: float,
    *,
    execution: ExecutionMode = "daily_close",
    check: np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    """v5-style continuous units; default execution is daily-close.

    ``check[t]`` — if provided, adds (and non-resting stops) only on True days.
    """
    n = world.n
    X = sleeve.X
    if check is None:
        check = np.ones(world.T + 1, dtype=bool)

    units0 = min(budget / rule.d, sleeve.cap_units)
    units = np.full(n, units0)
    eq = np.full(n, float(budget)) - units * sleeve.tcost
    stop = np.full(n, -rule.d)
    anchor = np.zeros(n)
    alive = np.ones(n, dtype=bool)
    rolls = set(sleeve.rolls)

    for t in range(1, world.T + 1):
        act = alive & (t <= world.tc)
        if not act.any():
            break
        x, xp = X[:, t], X[:, t - 1]

        if execution == "resting_stop":
            hit = act & (x <= stop)
            fill = stop - sleeve.slip - 0.5 * np.maximum(stop - sleeve.slip - x, 0.0)
        else:
            hit = act & (x <= stop) & check[t]
            fill = x - sleeve.slip

        eq = np.where(
            hit,
            eq + units * (fill - xp) - units * sleeve.tcost,
            np.where(act, eq + units * (x - xp), eq),
        )
        alive &= ~hit
        live = act & ~hit

        if t in rolls:
            eq = eq - np.where(live, units * 2 * sleeve.tcost, 0.0)

        if rule.step is not None and check[t]:
            up = live & (x >= anchor + rule.step)
            if up.any():
                new = np.minimum((1.0 - rule.keep) * np.maximum(eq, 0.0) / rule.d, sleeve.cap_units)
                eq = np.where(up, eq - np.abs(new - units) * sleeve.tcost, eq)
                units = np.where(up, new, units)
                anchor = np.where(up, x, anchor)
                stop = np.where(up, x - rule.d, stop)

        done = live & (t == world.tc)
        eq = np.where(done, eq - units * sleeve.tcost, eq)
        alive &= ~done

    return eq, float(units0)


def straight_line_spread_equity(
    level_bp: float,
    *,
    s0: float,
    eur_foat: float,
    budget: float = 10_000.0,
    stop_bp: float = 40.0,
    add_every_bp: float = 20.0,
    foat_cap: int = 20,
    entry_foat: int = 3,
) -> float:
    """Integer FOAT ladder, no noise / no costs (v5 report ``eq_spread``)."""
    e, n, last = float(budget), int(entry_foat), 0.0
    gain = level_bp - s0
    kk = 1
    while True:
        if add_every_bp * kk > gain:
            break
        e += add_every_bp * n * eur_foat
        n = min(int(round(e / stop_bp / eur_foat)), foat_cap)
        last = add_every_bp * kk
        kk += 1
        if kk > 10_000:
            break
    return e + (gain - last) * n * eur_foat


def straight_line_spread_ladder(
    *,
    s0: float,
    eur_foat: float,
    eur_fgbl: float,
    levels: Sequence[float],
    budget: float = 10_000.0,
    stop_bp: float = 40.0,
    add_every_bp: float = 20.0,
    foat_cap: int = 20,
    fgbl_cap: int = 18,
    entry_foat: int = 3,
    entry_fgbl: int = 3,
) -> dict[str, Any]:
    """Step table + final equities at each level (integer contracts)."""
    rows: list[dict[str, Any]] = []
    eq, nf, ng = float(budget), entry_foat, entry_fgbl
    rows.append(
        {
            "step": "Entry",
            "spread_bp": s0,
            "delta_bp": 0.0,
            "equity": eq,
            "foat": nf,
            "fgbl": ng,
        }
    )
    k = 0
    while True:
        k += 1
        lvl = s0 + add_every_bp * k
        if lvl >= max(levels):
            break
        eq += add_every_bp * nf * eur_foat
        u = eq / stop_bp
        nf = min(int(round(u / eur_foat)), foat_cap)
        ng = min(int(round(u / eur_fgbl)), fgbl_cap)
        rows.append(
            {
                "step": f"Add {k}",
                "spread_bp": lvl,
                "delta_bp": add_every_bp * k,
                "equity": eq,
                "foat": nf,
                "fgbl": ng,
            }
        )

    finals = {
        float(L): straight_line_spread_equity(
            float(L),
            s0=s0,
            eur_foat=eur_foat,
            budget=budget,
            stop_bp=stop_bp,
            add_every_bp=add_every_bp,
            foat_cap=foat_cap,
            entry_foat=entry_foat,
        )
        for L in levels
    }
    return {"rows": rows, "finals": finals}


def run_integer_spread(
    world: World,
    fc: FutCalib,
    rule: Rule,
    budget: float,
    *,
    foat_cap: int = 20,
    fgbl_cap: int = 18,
    entry_foat: int = 3,
    entry_fgbl: int = 3,
    execution: ExecutionMode = "daily_close",
) -> tuple[np.ndarray, dict[str, Any]]:
    """Integer FOAT/FGBL book on path; P&L from Δspread and residual Bund exposure.

    Daily mark: ``dP&L = n_foat·ef·d_oat − n_fgbl·eg·d_bund`` with
    ``d_oat = d_spread + d_bund``. Carry applied in bp via net carry on FOAT/FGBL.
    """
    if rule.step is None:
        raise ValueError("integer spread runner expects a pyramid rule with step")

    n = world.n
    ef, eg = fc.eur_per_bp["FOAT"], fc.eur_per_bp["FGBL"]
    net_carry = fc.carry_bp_per_day["FOAT"] - fc.carry_bp_per_day["FGBL"]
    # Exposure path in bp (carry-adjusted), same as continuous sleeve
    tgrid = np.arange(world.T + 1)
    X = world.ds - net_carry * tgrid[None, :]
    # Bund cumulative for residual
    db = world.db

    # Per-contract round-turn cost in € approximated when resizing
    rt_foat = 2 * (HALF_TICK + FUT_FEE)
    rt_fgbl = 2 * (HALF_TICK + FUT_FEE)

    nf = np.full(n, entry_foat, dtype=int)
    ng = np.full(n, entry_fgbl, dtype=int)
    eq = np.full(n, float(budget))
    # entry costs
    eq -= nf * (HALF_TICK + FUT_FEE) + ng * (HALF_TICK + FUT_FEE)

    stop = np.full(n, -rule.d)
    anchor = np.zeros(n)
    alive = np.ones(n, dtype=bool)
    rolls = set(roll_indices(world.days))
    slip = 1.0

    for t in range(1, world.T + 1):
        act = alive & (t <= world.tc)
        if not act.any():
            break
        x, xp = X[:, t], X[:, t - 1]
        d_spread_raw = world.ds[:, t] - world.ds[:, t - 1]
        d_bund = db[:, t] - db[:, t - 1]
        d_oat = d_spread_raw + d_bund
        # carry drag already in X; use ΔX for economic P&L of the spread book
        dx = x - xp

        # Mark-to-market with integer residual Bund: U_f*d_oat - U_g*d_bund, plus
        # carry embedded by using dx on the FOAT € amount and residual on Bund.
        uf = nf * ef
        ug = ng * eg
        pnl = uf * dx + (uf - ug) * d_bund  # dx already carry-adjusted spread
        # When uf≈ug, pnl ≈ uf * dx. Residual term captures integer mismatch.

        if execution == "resting_stop":
            hit = act & (x <= stop)
            fill = stop - slip - 0.5 * np.maximum(stop - slip - x, 0.0)
            pnl_hit = uf * (fill - xp) + (uf - ug) * d_bund
        else:
            hit = act & (x <= stop)
            fill = x - slip
            pnl_hit = uf * (fill - xp) + (uf - ug) * d_bund

        eq = np.where(hit, eq + pnl_hit - (nf + ng) * (HALF_TICK + FUT_FEE), np.where(act, eq + pnl, eq))
        alive &= ~hit
        live = act & ~hit

        if t in rolls:
            # One round-turn (two sides) per contract on roll
            eq = np.where(live, eq - nf * rt_foat - ng * rt_fgbl, eq)

        up = live & (x >= anchor + rule.step)
        if up.any():
            target_u = (1.0 - rule.keep) * np.maximum(eq, 0.0) / rule.d
            new_f = np.minimum(np.rint(target_u / ef).astype(int), foat_cap)
            new_g = np.minimum(np.rint(target_u / eg).astype(int), fgbl_cap)
            # costs on size change
            d_f = np.abs(new_f - nf)
            d_g = np.abs(new_g - ng)
            eq = np.where(up, eq - d_f * (HALF_TICK + FUT_FEE) - d_g * (HALF_TICK + FUT_FEE), eq)
            nf = np.where(up, new_f, nf)
            ng = np.where(up, new_g, ng)
            anchor = np.where(up, x, anchor)
            stop = np.where(up, x - rule.d, stop)

        done = live & (t == world.tc)
        eq = np.where(done, eq - (nf + ng) * (HALF_TICK + FUT_FEE), eq)
        alive &= ~done

    meta = {
        "entry_foat": entry_foat,
        "entry_fgbl": entry_fgbl,
        "execution": execution,
        "eur_per_bp": {"FOAT": ef, "FGBL": eg},
    }
    return eq, meta
