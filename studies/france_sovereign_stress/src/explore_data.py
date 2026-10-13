"""Explorer payload (``data/canvas_explore.json``) for the canvas and interactive HTML.

Per preset: stats at four exit levels, the no-event outcome, equity percentile
bands and three sample paths at 300 bp, the trade log of path 0 and a terminal
histogram. Plus the noise-free straight-line ladder.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from src.evaluate import payout_stats, run_sleeve_multiples, scale_vol
from src.inputs import MarketInputs
from src.margin import margin_from_config
from src.paths import load_config
from src.rules import (
    Rule,
    Sleeve,
    build_cac_sleeve,
    build_spread_sleeve,
    straight_line_spread_equity,
    straight_line_spread_ladder,
)
from src.scenarios import ScenarioConfig, World, simulate_worlds

LEVELS = [240.0, 300.0, 340.0, 400.0]
HIST_BINS = [0, 0.1, 0.5, 1, 2, 5, 10, 15, 20, 30, 50, 100]
BAND_STEP = 7


def equity_paths(world: World, sleeve: Sleeve, rule: Rule, budget: float, execution: str):
    """``run_continuous`` with the full equity path kept and path 0's trade log."""
    n = world.n
    X = sleeve.X
    units0 = min(budget / rule.d, sleeve.cap_units)
    units = np.full(n, units0)
    eq = np.full(n, budget) - units * sleeve.tcost
    eq_path = np.zeros((n, world.T + 1))
    eq_path[:, 0] = eq
    stop = np.full(n, -rule.d)
    anchor = np.zeros(n)
    alive = np.ones(n, bool)
    rolls = set(sleeve.rolls)

    def ev(t: int, kind: str, x: float, u: float, e: float, s: float) -> dict:
        return {"t": t, "date": str(world.days[t]), "type": kind, "x": x, "units": u, "equity": e, "stop": s}

    events0 = [ev(0, "entry", 0.0, float(units0), float(eq[0]), float(stop[0]))]
    for t in range(1, world.T + 1):
        act = alive & (t <= world.tc)
        x, xp = X[:, t], X[:, t - 1]
        hit = act & (x <= stop)
        if execution == "resting_stop":
            fill = stop - sleeve.slip - 0.5 * np.maximum(stop - sleeve.slip - x, 0)
        else:
            fill = x - sleeve.slip
        eq = np.where(
            hit,
            eq + units * (fill - xp) - units * sleeve.tcost,
            np.where(act, eq + units * (x - xp), eq),
        )
        if hit[0] and alive[0]:
            events0.append(ev(t, "stop", float(x[0]), float(units[0]), float(eq[0]), float(stop[0])))
        alive &= ~hit
        live = act & ~hit
        if t in rolls:
            eq = eq - np.where(live, units * 2 * sleeve.tcost, 0)
            if live[0]:
                events0.append(ev(t, "roll", float(x[0]), float(units[0]), float(eq[0]), float(stop[0])))
        if rule.step is not None:
            up = live & (x >= anchor + rule.step)
            if up.any():
                new = np.minimum((1 - rule.keep) * np.maximum(eq, 0) / rule.d, sleeve.cap_units)
                if up[0]:
                    e0 = float(eq[0] - abs(new[0] - units[0]) * sleeve.tcost)
                    events0.append(ev(t, "add", float(x[0]), float(new[0]), e0, float(x[0] - rule.d)))
                eq = np.where(up, eq - np.abs(new - units) * sleeve.tcost, eq)
                units = np.where(up, new, units)
                anchor = np.where(up, x, anchor)
                stop = np.where(up, x - rule.d, stop)
        done = live & (t == world.tc)
        if done[0]:
            e0 = float(eq[0] - units[0] * sleeve.tcost)
            events0.append(ev(t, "exit", float(x[0]), float(units[0]), e0, float(stop[0])))
        eq = np.where(done, eq - units * sleeve.tcost, eq)
        alive &= ~done
        eq_path[:, t] = eq
    return eq_path, eq, events0


def _band_idx(T: int) -> list[int]:
    idx = list(range(0, T + 1, BAND_STEP))
    if idx[-1] != T:
        idx.append(T)
    return idx


def _bands(m: np.ndarray, world: World) -> dict:
    idx = _band_idx(world.T)
    return {
        "dates": [str(world.days[i]) for i in idx],
        **{f"p{q}": [round(float(np.percentile(m[:, i], q)), 3) for i in idx] for q in (10, 50, 90)},
    }


def _hist(term: np.ndarray) -> dict:
    hist, edges = np.histogram(term, bins=HIST_BINS)
    return {
        "labels": [f"{edges[i]:g}–{edges[i + 1]:g}" for i in range(len(hist))],
        "counts": [int(x) for x in hist],
    }


def _round_events(events: list[dict]) -> list[dict]:
    return [
        {**e, "x": round(e["x"], 3), "units": round(e["units"], 2), "equity": round(e["equity"], 2), "stop": round(e["stop"], 3)}
        for e in events
    ]


def _pack_spread(pid, label, worlds, mi: MarketInputs, rule, budget, execution="daily_close") -> dict:
    w = worlds[300.0]
    eq_path, eq_term, events0 = equity_paths(w, build_spread_sleeve(w, mi.fc), rule, budget, execution)
    m = eq_path / budget
    term = eq_term / budget
    n = len(term)
    order = np.argsort(term)
    picks = {"low": int(order[max(0, int(0.1 * n) - 1)]), "median": int(order[n // 2]), "high": int(order[min(n - 1, int(0.9 * n))])}
    idx = _band_idx(w.T)
    levels = {}
    for lv in LEVELS:
        mult = run_sleeve_multiples(build_spread_sleeve(worlds[lv], mi.fc), worlds[lv], rule, budget, execution=execution)
        levels[str(int(lv))] = payout_stats(mult).to_dict()
    mult_w = run_sleeve_multiples(build_spread_sleeve(worlds[None], mi.fc), worlds[None], rule, budget, execution=execution)
    return {
        "id": pid,
        "label": label,
        "rule": rule.text,
        "execution": execution,
        "levels": levels,
        "wrong": payout_stats(mult_w).to_dict(),
        "equity_bands_300": _bands(m, w),
        "sample_paths_300": {
            k: {
                "path_i": i,
                "terminal_x": round(float(term[i]), 3),
                "tc": int(w.tc[i]),
                "f": round(float(w.f[i]), 3),
                "equity_x": [round(float(m[i, j]), 3) for j in idx],
                "spread_bp": [round(float(w.s0 + w.ds[i, j]), 2) for j in idx],
            }
            for k, i in picks.items()
        },
        "path0_events": _round_events(events0[:40]),
        "hist_300": _hist(term),
        "mean_by_level": [{"level": int(lv), "mean_x": round(levels[str(int(lv))]["mean"], 3)} for lv in LEVELS],
    }


def _pack_cac(worlds, mi: MarketInputs, budget: float) -> dict:
    rule = Rule(12, 6, 0.0)
    w = worlds[300.0]
    eq_path, eq_term, _ = equity_paths(w, build_cac_sleeve(w, mi.beta_cac), rule, budget, "daily_close")
    term = eq_term / budget
    stats = payout_stats(term).to_dict()
    mult_w = run_sleeve_multiples(build_cac_sleeve(worlds[None], mi.beta_cac), worlds[None], rule, budget, execution="daily_close")
    return {
        "id": "cac",
        "label": "Short CAC · stop 12% / +6%",
        "rule": rule.text,
        "execution": "daily_close",
        "levels": {"300": stats},
        "wrong": payout_stats(mult_w).to_dict(),
        "equity_bands_300": _bands(eq_path / budget, w),
        "hist_300": _hist(term),
        "mean_by_level": [{"level": 300, "mean_x": round(stats["mean"], 3)}],
        "path0_events": [],
    }


def build_explore_payload(mi: MarketInputs, scfg: ScenarioConfig, *, budget: float) -> dict:
    start: date = mi.start
    worlds = simulate_worlds(mi.vol, s0=mi.s0, start=start, levels=LEVELS, cfg=scfg)
    worlds15 = simulate_worlds(scale_vol(mi.vol, 1.5), s0=mi.s0, start=start, levels=LEVELS, cfg=scfg)
    worlds_c = simulate_worlds(mi.vol_calm, s0=mi.s0, start=start, levels=LEVELS, cfg=scfg)
    r40, r30 = Rule(40, 20, 0.0), Rule(30, 15, 0.0)
    presets = {
        "base": _pack_spread("base", "Base · stop 40 / +20 · daily-close", worlds, mi, r40, budget),
        "tight": _pack_spread("tight", "Tight · stop 30 / +15 · daily-close", worlds, mi, r30, budget),
        "resting": _pack_spread("resting", "Base · resting stop", worlds, mi, r40, budget, "resting_stop"),
        "vol15": _pack_spread("vol15", "Vol × 1.5 · stop 40 / +20", worlds15, mi, r40, budget),
        "calm": _pack_spread("calm", "Calmer vol (pre-Sep) · stop 40 / +20", worlds_c, mi, r40, budget),
        "cac": _pack_cac(worlds, mi, budget),
    }

    s_rep = mi.s0_report
    eur_f, eur_g = mi.fc.eur_per_bp["FOAT"], mi.fc.eur_per_bp["FGBL"]
    cfg = load_config()
    margin = margin_from_config(cfg, s0=s_rep, fc=mi.fc)
    primary = margin["budgets"][str(int(budget))]
    rows = primary["rows"]
    grid = np.arange(s_rep, 400.0 + 1e-9, 4.0)
    curve = [
        {
            "spread_bp": round(float(g), 1),
            "equity_x": round(
                straight_line_spread_equity(
                    float(g),
                    s0=s_rep,
                    eur_foat=eur_f,
                    budget=budget,
                    entry_foat=primary["entry_foat"],
                )
                / budget,
                3,
            ),
        }
        for g in grid
    ]
    return {
        "meta": {
            **mi.meta(),
            "budget": budget,
            "n_paths": scfg.n_paths,
            "seed": scfg.seed,
            "foat_eur_bp": round(eur_f, 2),
            "fgbl_eur_bp": round(eur_g, 2),
            "hedge": round(mi.fc.hedge_ratio, 3),
            "carry_net_bp_day": round(mi.fc.carry_bp_per_day["FOAT"] - mi.fc.carry_bp_per_day["FGBL"], 4),
            "sig_s": round(mi.vol.sig_s, 3),
            "sig_b": round(mi.vol.sig_b, 3),
            "rho": round(mi.vol.rho, 3),
            "sig_s_calm": round(mi.vol_calm.sig_s, 3),
            "entry_foat": primary["entry_foat"],
            "entry_fgbl": primary["entry_fgbl"],
            "entry_im_eur": primary["entry_im_eur"],
            "cap_im_eur": primary["cap_im_eur"],
            "margin_asof": margin["asof"],
        },
        "presets": presets,
        "straight_line": {
            "curve": curve,
            "ladder": rows,
            "finals": primary["finals"],
        },
        "margin": margin,
    }
