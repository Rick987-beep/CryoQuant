"""v7 low-ops sleeves: options with ~8w rolls, fixed spread, naked FOAT, bank trades.

All structures consume common-RNG worlds from ``src.scenarios`` and return
equity multiples of a €budget stake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np

from src.calibrate import FutCalib, StockBeta
from src.options import (
    DEFAULT_HALF,
    OPT_FEE_EUR,
    OPT_MULT,
    Expiry,
    Leg,
    OptionSnapshot,
    Structure,
    b76,
    roll_schedule,
    single,
    vertical,
)
from src.rules import (
    FUT_FEE,
    HALF_TICK,
    Rule,
    Sleeve,
    build_spread_sleeve,
    per_tick_cost_bp,
    roll_indices,
    run_continuous,
)
from src.scenarios import World, stock_cum_returns
from src.vol_fit import VolFit


HORIZON_END = date(2027, 6, 30)
ROLL_STOP_BP = 200.0  # no new tranche once the spread is already stressed


@dataclass
class SleeveResult:
    name: str
    kind: str
    detail: dict[str, Any]
    multiples: dict[float | None, np.ndarray]  # level → path multiples
    spent_mean: float
    n_contracts_entry: float

    def stats_at(self, level: float | None) -> dict[str, float]:
        m = self.multiples[level]
        return {
            "mean": float(m.mean()),
            "median": float(np.median(m)),
            "p10": float(np.percentile(m, 10)),
            "p90": float(np.percentile(m, 90)),
            "p_lost": float((m <= 0.1).mean()),
        }


# ---------------------------------------------------------------------------
# Option roll sleeve
# ---------------------------------------------------------------------------


def _futures_from_world(
    world: World,
    t_idx: np.ndarray | int,
    f0: dict[str, float],
    dv01: dict[str, float],
) -> dict[str, np.ndarray]:
    """Map spread/Bund paths to OOAT / OGBL futures levels."""
    rows = np.arange(world.n)
    if np.isscalar(t_idx):
        ti = int(t_idx)
        ds = world.ds[rows, ti]
        db = world.db[rows, ti]
    else:
        ti = np.asarray(t_idx, dtype=int)
        ds = world.ds[rows, ti]
        db = world.db[rows, ti]
    return {
        "OOAT": f0["OOAT"] - dv01["OOAT"] * (ds + db),
        "OGBL": f0["OGBL"] - dv01["OGBL"] * db,
    }


def _day_index(world: World, d: date) -> int:
    """Nearest business-day index ≥ d (or last)."""
    days = world.days
    for i, x in enumerate(days):
        dd = x if isinstance(x, date) else date.fromisoformat(str(x)[:10])
        if dd >= d:
            return i
    return world.T


def option_roll_multiples(
    worlds: dict[float | None, World],
    snap: OptionSnapshot,
    structure: Structure,
    vol_fit: VolFit,
    *,
    budget: float = 10_000.0,
    cadence_months: int = 2,
    duration: dict[str, float] | None = None,
    levels: list[float] | None = None,
) -> SleeveResult:
    """Buy structure in front expiry; roll every ``cadence_months`` (~8w); exit on tc.

    Entry at live ask/bid. Rolls and early exits at model mid ± observed half-spread,
    with ATM vol scaled by ``vol_fit`` (history-grounded) vs today's skew.
    """
    product = structure.product
    front = snap.best_front(product)
    if front is None:
        raise RuntimeError(f"no front expiry for {product}")
    live = structure.live_cost(front)
    if live is None or live <= 0:
        raise RuntimeError(f"{structure.name}: no two-sided live cost on {front.label}")

    duration = duration or {"OOAT": 7.1, "OGBL": 7.4}
    f0 = {
        "OOAT": next((e.fwd for (p, _), e in snap.expiries.items() if p == "OOAT"), front.fwd),
        "OGBL": next((e.fwd for (p, _), e in snap.expiries.items() if p == "OGBL"), front.fwd),
    }
    if product in f0:
        f0[product] = front.fwd
    dv01 = {p: f0[p] * duration.get(p, 7.2) / 1e4 for p in f0}
    hs = {
        product: front.half_spread_table.get("mid", DEFAULT_HALF.get(product, 0.05))
        for product in ("OOAT", "OGBL")
    }
    # Prefer product-specific observed near-money half-spread.
    hs[product] = front.half_spread(structure.legs[0].cp, structure.legs[0].k)

    ends = roll_schedule(front.date, cadence_months, HORIZON_END)
    tranches = list(zip([snap.val_date] + ends[:-1], ends))
    days_len = np.array([(b - a).days for a, b in tranches], dtype=float)
    shares = days_len / days_len.sum()

    unit0 = live * OPT_MULT + OPT_FEE_EUR * structure.n_contracts
    n0 = int(budget // unit0)
    if n0 < 1:
        # Allow fractional for very expensive structures so the scorecard still runs.
        n0_f = budget / unit0
    else:
        n0_f = float(n0)

    levels = levels or [200.0, 250.0, 300.0, 350.0, 400.0]
    out_m: dict[float | None, np.ndarray] = {}
    spent_acc = []

    for lv in [None, *levels]:
        world = worlds[lv]
        tc = world.tc  # completion index
        # Calendar day of completion.
        t_exit_day = np.array(
            [
                (
                    world.days[min(int(tc[i]), world.T)]
                    if not isinstance(world.days[min(int(tc[i]), world.T)], date)
                    else world.days[min(int(tc[i]), world.T)]
                )
                for i in range(world.n)
            ],
            dtype=object,
        )
        # Convert to float ordinal days from val_date for comparisons.
        t0 = snap.val_date
        t_exit = np.array(
            [
                (
                    date.fromisoformat(str(t_exit_day[i])[:10]) - t0
                ).days
                for i in range(world.n)
            ],
            dtype=float,
        )
        if lv is None:
            t_exit = np.full(world.n, 1e9)  # hold to expiry of each tranche

        spent = np.zeros(world.n)
        pay = np.zeros(world.n)

        for k, (share, (start, end)) in enumerate(zip(shares, tranches)):
            ts = float((start - t0).days)
            tend = float((end - t0).days)
            t_rem_full = max((end - start).days, 1) / 365.0

            if k == 0:
                strikes = [np.full(world.n, l.k) for l in structure.legs]
                cost = np.full(world.n, live)
                deploy = np.ones(world.n, dtype=bool)
            else:
                # Index into world at roll date.
                ti = _day_index(world, start)
                fut = _futures_from_world(world, ti, f0, dv01)
                f_roll = fut[product]
                ds = world.ds[np.arange(world.n), min(ti, world.T)]
                mult = vol_fit.atm_mult(ds, world.s0)
                atm = front.skew.atm * mult
                strikes = structure.rolled_strikes(front.fwd, f_roll)
                cost = structure.model_cost(
                    f_roll, t_rem_full, front.skew, atm, half_spreads=hs, strikes=strikes
                )
                spread_now = world.s0 + ds
                deploy = (t_exit > ts) & (spread_now < ROLL_STOP_BP)

            closed = (t_exit > ts) & (t_exit < tend)
            # Value at exit or expiry.
            # Map t_exit / tend to world indices for futures.
            ti_end = np.array([_day_index(world, end)] * world.n)
            # For early exit use tc; for expiry use end index.
            ti_x = np.where(closed, np.minimum(tc, world.T), ti_end)
            fut_x = _futures_from_world(world, ti_x, f0, dv01)
            f_x = fut_x[product]
            ds_x = world.ds[np.arange(world.n), np.minimum(ti_x, world.T)]
            mult_x = vol_fit.atm_mult(ds_x, world.s0)
            atm_x = front.skew.atm * mult_x
            t_rem = np.maximum((tend - np.minimum(t_exit, tend)) / 365.0, 1 / 365)
            close = structure.close_value(
                strikes, f_x, t_rem, front.skew, atm_x, half_spreads=hs
            )
            # At natural expiry use intrinsic.
            fut_e = _futures_from_world(world, ti_end, f0, dv01)
            intrinsic = structure.payoff_at(strikes, fut_e[product])
            value = np.where(closed, close, intrinsic)

            unit = np.maximum(cost, 1e-4) * OPT_MULT + OPT_FEE_EUR * structure.n_contracts
            # Allocate budget * share per tranche (fractional OK for MC).
            n = np.where(deploy, (budget * share) / unit, 0.0)
            spent = spent + n * unit
            fee_exit = OPT_FEE_EUR * structure.n_contracts * closed.astype(float)
            pay = pay + n * (value * OPT_MULT - fee_exit)

        # If wrong world / no exit, leftover cash = budget - spent (premium lost + residual value).
        # Multiples = terminal equity / budget, equity = (budget - spent) + pay.
        # When spent < budget (undeployed share), cash sits idle.
        equity = (budget - spent) + pay
        # Clamp: never report negative spent; equity can be near 0.
        out_m[lv] = equity / budget
        spent_acc.append(float(spent.mean()))

    return SleeveResult(
        name=structure.name,
        kind="option_roll",
        detail={
            "front": front.label,
            "fwd": front.fwd,
            "points_per_bp": dv01[product],
            "live_cost": live,
            "unit0_eur": unit0,
            "n_entry": n0_f if n0 >= 1 else n0_f,
            "cadence_months": cadence_months,
            "n_tranches": len(tranches),
            "half_spread": hs[product],
            "fee_eur": OPT_FEE_EUR,
            "vol_fit_use_level": vol_fit.use_level,
            "structure": structure.name,
            "legs": [l.text for l in structure.legs],
        },
        multiples=out_m,
        spent_mean=float(np.mean(spent_acc)),
        n_contracts_entry=float(n0_f if n0 >= 1 else n0_f),
    )


def option_front_only_multiples(
    worlds: dict[float | None, World],
    snap: OptionSnapshot,
    structure: Structure,
    vol_fit: VolFit,
    *,
    budget: float = 10_000.0,
    duration: dict[str, float] | None = None,
    levels: list[float] | None = None,
) -> SleeveResult:
    """Entire budget in the front expiry; no roll. Dies if stress comes after expiry."""
    # Reuse roll machinery with a single tranche by forcing cadence huge and
    # horizon = front expiry.
    product = structure.product
    front = snap.best_front(product)
    if front is None:
        raise RuntimeError(f"no front expiry for {product}")
    # Temporarily shrink schedule: monkey via local copy of logic.
    live = structure.live_cost(front)
    if live is None or live <= 0:
        raise RuntimeError(f"{structure.name}: no live cost")
    duration = duration or {"OOAT": 7.1, "OGBL": 7.4}
    f0 = {
        "OOAT": next((e.fwd for (p, _), e in snap.expiries.items() if p == "OOAT"), front.fwd),
        "OGBL": next((e.fwd for (p, _), e in snap.expiries.items() if p == "OGBL"), front.fwd),
    }
    f0[product] = front.fwd
    dv01 = {p: f0[p] * duration.get(p, 7.2) / 1e4 for p in f0}
    hs = {product: front.half_spread(structure.legs[0].cp, structure.legs[0].k)}
    unit0 = live * OPT_MULT + OPT_FEE_EUR * structure.n_contracts
    n = max(int(budget // unit0), 0)
    n_f = float(n) if n >= 1 else budget / unit0
    levels = levels or [200.0, 250.0, 300.0, 350.0, 400.0]
    out_m: dict[float | None, np.ndarray] = {}
    t0 = snap.val_date
    tend = float((front.date - t0).days)
    t_rem0 = front.t

    for lv in [None, *levels]:
        world = worlds[lv]
        strikes = [np.full(world.n, l.k) for l in structure.legs]
        spent = np.full(world.n, n_f * unit0)
        tc = world.tc
        t_exit = np.array(
            [
                (
                    date.fromisoformat(str(world.days[min(int(tc[i]), world.T)])[:10]) - t0
                ).days
                for i in range(world.n)
            ],
            dtype=float,
        )
        if lv is None:
            closed = np.zeros(world.n, dtype=bool)
            ti_x = np.full(world.n, _day_index(world, front.date))
        else:
            closed = t_exit < tend
            ti_x = np.where(closed, np.minimum(tc, world.T), _day_index(world, front.date))
        fut = _futures_from_world(world, ti_x, f0, dv01)
        f_x = fut[product]
        ds_x = world.ds[np.arange(world.n), np.minimum(ti_x, world.T)]
        atm = front.skew.atm * vol_fit.atm_mult(ds_x, world.s0)
        t_rem = np.where(closed, np.maximum((tend - t_exit) / 365.0, 1 / 365), 1 / 365)
        close = structure.close_value(strikes, f_x, t_rem, front.skew, atm, half_spreads=hs)
        intrinsic = structure.payoff_at(strikes, f_x)
        value = np.where(closed, close, intrinsic)
        # Wrong world / after expiry: intrinsic (likely ~0 for OTM).
        pay = n_f * (value * OPT_MULT - OPT_FEE_EUR * structure.n_contracts)
        equity = (budget - spent) + pay
        out_m[lv] = equity / budget

    return SleeveResult(
        name=structure.name + " [front]",
        kind="option_front",
        detail={
            "front": front.label,
            "live_cost": live,
            "unit0_eur": unit0,
            "n_entry": n_f,
            "legs": [l.text for l in structure.legs],
        },
        multiples=out_m,
        spent_mean=float(n_f * unit0),
        n_contracts_entry=n_f,
    )


# ---------------------------------------------------------------------------
# Fixed FOAT/FGBL (no adds)
# ---------------------------------------------------------------------------


def fixed_spread_multiples(
    worlds: dict[float | None, World],
    fc: FutCalib,
    *,
    stop_bp: float = 40.0,
    foat_n: int = 3,
    fgbl_n: int = 3,
    budget: float = 10_000.0,
    levels: list[float] | None = None,
    execution: str = "daily_close",
) -> SleeveResult:
    """Fixed integer contracts, stop anchored at entry (no pyramid)."""
    levels = levels or [200.0, 250.0, 300.0, 350.0, 400.0]
    # Continuous engine with step=None; size so units0 matches foat_n * eur_foat.
    # units = €/bp exposure = foat_n * eur_per_bp_FOAT (matched).
    eur = fc.eur_per_bp["FOAT"]
    units = foat_n * eur
    # The continuous engine sets units0 = budget / rule.d. To force fixed size we
    # scale the rule stop and budget notionally, OR run a custom loop.
    # Custom integer loop is clearer for fixed N.
    out_m: dict[float | None, np.ndarray] = {}
    tcost_bp = (
        per_tick_cost_bp(fc.eur_per_bp["FOAT"]) + per_tick_cost_bp(fc.eur_per_bp["FGBL"])
    )
    slip = 1.0

    for lv in [None, *levels]:
        world = worlds[lv]
        sleeve = build_spread_sleeve(world, fc)
        # Override: run with continuous but force units via fake budget = units * stop.
        rule = Rule(d=stop_bp, step=None)
        fake_budget = units * stop_bp
        eq, _ = run_continuous(sleeve, world, rule, fake_budget, execution=execution)
        # Map P&L back onto real budget: the fake run starts with fake_budget at risk.
        # Equity change = eq - fake_budget; real equity = budget + (eq - fake_budget).
        # But entry costs scale with units; the continuous engine already deducted them.
        # Simpler interpretation: risk budget is the stop loss ≈ units*stop ≈ fake_budget.
        # Report multiple of the risk budget (stop risk), which equals fake_budget.
        out_m[lv] = eq / fake_budget

    return SleeveResult(
        name=f"fixed {foat_n}/{fgbl_n} stop {stop_bp:g}",
        kind="fixed_spread",
        detail={
            "foat_n": foat_n,
            "fgbl_n": fgbl_n,
            "stop_bp": stop_bp,
            "eur_per_bp": eur,
            "stop_risk_eur": units * stop_bp,
            "tcost_bp": tcost_bp,
            "execution": execution,
        },
        multiples=out_m,
        spent_mean=units * stop_bp,
        n_contracts_entry=float(foat_n + fgbl_n),
    )


# ---------------------------------------------------------------------------
# Naked short FOAT with stop-loss + take-profit
# ---------------------------------------------------------------------------


def naked_foat_multiples(
    worlds: dict[float | None, World],
    fc: FutCalib,
    *,
    stop_bp: float = 40.0,
    take_profit_bp: float = 160.0,
    budget: float = 10_000.0,
    levels: list[float] | None = None,
) -> SleeveResult:
    """Short FOAT only. OAT yield change = ΔBund + Δspread.

    Stop / take-profit on the outright OAT yield move (bp), checked on daily close.
    Size so stop ≈ budget.
    """
    levels = levels or [200.0, 250.0, 300.0, 350.0, 400.0]
    eur = fc.eur_per_bp["FOAT"]
    n = max(int(round(budget / (stop_bp * eur))), 1)
    # One-side cost in € for n contracts.
    tcost = n * (FUT_FEE + HALF_TICK)
    carry = fc.carry_bp_per_day["FOAT"]  # short FOAT earns/pays this
    rolls = None
    out_m: dict[float | None, np.ndarray] = {}

    for lv in [None, *levels]:
        world = worlds[lv]
        if rolls is None:
            rolls = set(roll_indices(world.days))
        # X = change in OAT yield from entry, carry-adjusted, in bp.
        # Short FOAT profits when OAT yield rises (futures price falls).
        t = np.arange(world.T + 1)[None, :]
        oat_up = (world.ds + world.db) - carry * t  # bp; positive = OAT cheapened
        # P&L in € for short = n * eur * oat_up
        n_paths = world.n
        eq = np.full(n_paths, budget - tcost)
        alive = np.ones(n_paths, dtype=bool)
        stop_lvl = -stop_bp  # yield fell → short loses
        tp_lvl = take_profit_bp

        for ti in range(1, world.T + 1):
            act = alive & (ti <= world.tc)
            if not act.any():
                break
            x = oat_up[:, ti]
            xp = oat_up[:, ti - 1]
            # Mark-to-market
            eq = np.where(act, eq + n * eur * (x - xp), eq)
            # Daily-close stop
            hit_stop = act & (x <= stop_lvl)
            fill_stop = x - 1.0  # 1 bp slip
            eq = np.where(
                hit_stop,
                eq - n * eur * (x - fill_stop) - tcost,  # adjust to fill + exit cost
                eq,
            )
            # Actually: we already marked to x; correct to fill and charge exit.
            # Simpler: reset those paths' last mark.
            # Recompute from previous for hit paths:
            eq = np.where(
                hit_stop,
                eq - n * eur * (x - xp) + n * eur * (fill_stop - xp) - tcost,
                eq,
            )
            alive &= ~hit_stop
            live = act & ~hit_stop
            # Take-profit: fill at limit only if close through it.
            hit_tp = live & (x >= tp_lvl)
            eq = np.where(
                hit_tp,
                eq - n * eur * (x - xp) + n * eur * (tp_lvl - xp) - tcost,
                eq,
            )
            alive &= ~hit_tp
            live = live & ~hit_tp
            if ti in rolls:
                eq = eq - np.where(live, 2 * tcost, 0.0)
            done = live & (ti == world.tc)
            eq = np.where(done, eq - tcost, eq)
            alive &= ~done

        out_m[lv] = eq / budget

    return SleeveResult(
        name=f"naked FOAT {n}c stop {stop_bp:g} / tp {take_profit_bp:g}",
        kind="naked_foat",
        detail={
            "n": n,
            "stop_bp": stop_bp,
            "take_profit_bp": take_profit_bp,
            "eur_per_bp": eur,
            "stop_risk_eur": n * stop_bp * eur,
        },
        multiples=out_m,
        spent_mean=float(n * stop_bp * eur),
        n_contracts_entry=float(n),
    )


# ---------------------------------------------------------------------------
# Bank short stock / put spread
# ---------------------------------------------------------------------------


def bank_short_stock_multiples(
    worlds: dict[float | None, World],
    beta: StockBeta,
    *,
    stop_pct: float = 12.0,
    budget: float = 10_000.0,
    stock_cost_pa: float = 0.035,
    ftt: float = 0.004,
    half_spread_pct: float = 0.05,
    levels: list[float] | None = None,
    seed_offset: int = 2000,
) -> SleeveResult:
    """Short stock sized so stop ≈ budget. Daily-close stop. FTT on cover."""
    levels = levels or [200.0, 250.0, 300.0, 350.0, 400.0]
    # Exposure in €: units such that stop_pct move ≈ budget.
    # units = budget / (stop_pct/100)  → euro notional.
    notional = budget / (stop_pct / 100.0)
    entry_cost = notional * (half_spread_pct / 100.0)  # cross spread on short
    out_m: dict[float | None, np.ndarray] = {}

    for lv in [None, *levels]:
        world = worlds[lv]
        r = stock_cum_returns(world, beta, seed_offset=seed_offset)
        # Short P&L fraction = -(exp(r)-1) − carry
        t = np.arange(world.T + 1)[None, :] / 252.0
        # Price relative: px = exp(r); short return = 1 - px - carry*t
        px = np.exp(r)
        # Stop when price rises stop_pct (short loses).
        stop_px = 1.0 + stop_pct / 100.0
        eq = np.full(world.n, budget - entry_cost)
        alive = np.ones(world.n, dtype=bool)
        for ti in range(1, world.T + 1):
            act = alive & (ti <= world.tc)
            p = px[:, ti]
            pp = px[:, ti - 1]
            # Daily P&L on short notional
            day_ret = -(p - pp)  # price up → short loses
            eq = np.where(act, eq + notional * day_ret - notional * stock_cost_pa / 252.0, eq)
            hit = act & (p >= stop_px)
            # Fill at stop + half-spread; FTT on buy-to-cover.
            fill = stop_px * (1 + half_spread_pct / 100.0)
            eq = np.where(
                hit,
                eq - notional * (p - pp) + notional * -(fill - pp) - notional * ftt - entry_cost,
                eq,
            )
            alive &= ~hit
            live = act & ~hit
            done = live & (ti == world.tc)
            # Cover at close + half-spread + FTT
            eq = np.where(
                done,
                eq - notional * (half_spread_pct / 100.0) - notional * ftt,
                eq,
            )
            alive &= ~done
        out_m[lv] = eq / budget

    return SleeveResult(
        name=f"short stock stop {stop_pct:g}%",
        kind="bank_stock",
        detail={
            "stop_pct": stop_pct,
            "notional": notional,
            "beta_s": beta.beta_s,
            "beta_b": beta.beta_b,
            "idio": beta.idio,
            "ftt": ftt,
            "stock_cost_pa": stock_cost_pa,
        },
        multiples=out_m,
        spent_mean=budget,
        n_contracts_entry=1.0,
    )


def bank_put_spread_multiples(
    worlds: dict[float | None, World],
    beta: StockBeta,
    *,
    spot: float,
    long_k: float,
    short_k: float,
    expiry: date,
    live_debit: float,
    half_spread: float,
    atm_iv: float,
    budget: float = 10_000.0,
    mult: float = 100.0,
    fee: float = OPT_FEE_EUR,
    levels: list[float] | None = None,
    seed_offset: int = 2100,
    vol_fit: VolFit | None = None,
) -> SleeveResult:
    """Debit put spread on a bank name. Front/long-dated: hold to exit or expiry.

    ``live_debit`` is the live ask-bid crossed cost in points. Sized to budget.
    """
    levels = levels or [200.0, 250.0, 300.0, 350.0, 400.0]
    unit = live_debit * mult + 2 * fee
    n = max(int(budget // unit), 0)
    n_f = float(n) if n >= 1 else budget / unit
    structure = vertical("BANK", "P", long_k, short_k)
    # Reuse b76 with equity spot as forward proxy (no rates adj for short horizon).
    from src.options import Skew

    skew = Skew(atm=atm_iv, b=0.0, c=0.0)
    out_m: dict[float | None, np.ndarray] = {}
    t0 = date.today()  # overwritten per world start if needed

    for lv in [None, *levels]:
        world = worlds[lv]
        t0 = world.days[0] if isinstance(world.days[0], date) else date.fromisoformat(str(world.days[0])[:10])
        r = stock_cum_returns(world, beta, seed_offset=seed_offset)
        px = spot * np.exp(r)
        tc = world.tc
        t_exp = max((expiry - t0).days, 1) / 365.0
        t_exit_days = np.array(
            [
                (
                    date.fromisoformat(str(world.days[min(int(tc[i]), world.T)])[:10]) - t0
                ).days
                for i in range(world.n)
            ],
            dtype=float,
        )
        if lv is None:
            closed = np.zeros(world.n, dtype=bool)
            ti = np.full(world.n, min(_day_index(world, expiry), world.T))
        else:
            closed = t_exit_days < (expiry - t0).days
            ti = np.where(closed, np.minimum(tc, world.T), min(_day_index(world, expiry), world.T))
        s_x = px[np.arange(world.n), ti]
        # Intrinsic at expiry; model close if early.
        intrinsic = np.maximum(long_k - s_x, 0) - np.maximum(short_k - s_x, 0)
        t_rem = np.maximum(((expiry - t0).days - t_exit_days) / 365.0, 1 / 365)
        # Vol: equity ATM; optional mild lift with spread via vol_fit.
        mult_v = vol_fit.atm_mult(world.ds[np.arange(world.n), ti], world.s0) if vol_fit else 1.0
        mid_long = b76(s_x, long_k, t_rem, atm_iv * mult_v, False)
        mid_short = b76(s_x, short_k, t_rem, atm_iv * mult_v, False)
        close = np.maximum(mid_long - mid_short - 2 * half_spread, 0.0)
        value = np.where(closed, close, intrinsic)
        spent = n_f * unit
        pay = n_f * (value * mult - 2 * fee)
        equity = (budget - spent) + pay
        out_m[lv] = equity / budget

    return SleeveResult(
        name=f"put spread {long_k:g}/{short_k:g}",
        kind="bank_put_spread",
        detail={
            "spot": spot,
            "long_k": long_k,
            "short_k": short_k,
            "expiry": str(expiry),
            "live_debit": live_debit,
            "n": n_f,
            "unit_eur": unit,
            "atm_iv": atm_iv,
            "half_spread": half_spread,
        },
        multiples=out_m,
        spent_mean=float(n_f * unit),
        n_contracts_entry=n_f,
    )


def pick_option_structures(snap: OptionSnapshot) -> list[Structure]:
    """Candidate naked puts/calls and verticals with two-sided live quotes."""
    out: list[Structure] = []
    ooat = snap.best_front("OOAT")
    ogbl = snap.best_front("OGBL")
    if ooat is not None:
        # OTM puts: 1–6 pts below forward, 0.5 grid.
        for dk in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0):
            k = round((ooat.fwd - dk) * 2) / 2
            s = single("OOAT", "P", k)
            if s.live_cost(ooat) is not None:
                out.append(s)
            for w in (2.0, 3.0, 4.0, 6.0):
                v = vertical("OOAT", "P", k, k - w)
                if v.live_cost(ooat) is not None:
                    out.append(v)
    if ogbl is not None:
        for dk in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
            k = round((ogbl.fwd + dk) * 2) / 2
            s = single("OGBL", "C", k)
            if s.live_cost(ogbl) is not None:
                out.append(s)
            for w in (1.5, 2.0, 3.0):
                v = vertical("OGBL", "C", k, k + w)
                if v.live_cost(ogbl) is not None:
                    out.append(v)
    return out
