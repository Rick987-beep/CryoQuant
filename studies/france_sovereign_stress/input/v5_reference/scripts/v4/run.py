"""Sleeve A v4: rolling OOAT main leg + optional OGBL helper on a fixed premium budget to mid-2027.

OOAT test: OOAT leg alone pays ≥ OOAT_MIN× its cumulative premium in the 2018-pattern stress (Bunds −24 bp at
240 bp), averaged over the event day (uniform to 30 Jun 2027). Book test: whole book ≥ BOOK_MIN× on every stress
Bund path (f from 0.10 to 0.70), same averaging. Books passing both are ranked by expected P&L (regime probabilities).

    .venv/bin/python jobs/france-sovereign-stress/scripts/v4/run.py [--budget 10000] [--cadence 2] [--chain PATH]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import market
from book import DUR, FIRST_EXPIRY, HORIZON_END, ROLL_STOP, VOL_UP, Env, mc_metrics, sleeve_cash, tranches
from scenarios import EVENT_DAYS, REGIMES, simulate, stress_fs, stress_grid
from structures import FEE, HALF_SPREAD, ogbl_universe, ooat_universe

JOB = Path(__file__).resolve().parents[2]
OUT = JOB / "data" / "v4"
OOAT_MIN, BOOK_MIN = 4.0, 3.0
WS = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
N_MC = 40_000


def mult(w, o, h):
    spent = w * o[0] + (1 - w) * (h[0] if h else 0)
    pay = w * o[1] + (1 - w) * (h[1] if h else 0)
    return pay / np.maximum(spent, 1)


def timing_buckets(env, grid):
    cuts = [0.0] + [env.day(b) for _, b in env.tranches[:-1]] + [env.horizon]
    names = [f"event by {env.tranches[0][1]:%d %b}"] + [f"{a:%d %b}–{b:%d %b %y}" for a, b in env.tranches[1:]]
    return [(n, (grid.te >= lo) & (grid.te < hi)) for n, lo, hi in zip(names, cuts[:-1], cuts[1:])]


def order_now(env, s, w, budget_share):
    e = env.e1[s.product]
    px = s.live_cost(e)
    unit = px * 1000 + FEE * s.n_contracts
    n = math.floor(env.budget * env.shares[0] * budget_share / unit)
    legs = []
    for l in s.legs:
        q = e.quotes[l.cp][l.k]
        legs.append({"text": l.text.replace(f"{abs(l.q)} ", f"{n * abs(l.q)} ", 1), "product": l.product,
                     "expiry": FIRST_EXPIRY, "cp": l.cp, "k": l.k, "n": n * l.q, "bid": q.bid, "ask": q.ask,
                     "iv_mid": round(float(e.skew.vol(e.fwd, l.k, e.t)), 4)})
    return {"structure": s.name, "n": n, "px": round(px, 3), "unit_eur": round(unit), "spent": round(n * unit),
            "legs": legs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=10_000)
    ap.add_argument("--cadence", type=int, default=2, help="roll into the expiry this many months ahead")
    ap.add_argument("--chain", type=Path)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--ooat-min", type=float, default=OOAT_MIN)
    ap.add_argument("--book-min", type=float, default=BOOK_MIN)
    ap.add_argument("--frontier", action="store_true",
                    help="no hard multiple: books on the EV vs 2018-path-multiple Pareto frontier")
    args = ap.parse_args()

    snap = market.load(args.chain)
    env = Env(snap, args.budget, args.cadence)
    s0 = snap.spread
    named = stress_fs(s0)
    fs_all = sorted(set(np.round(np.linspace(0.10, 0.70, 13), 3)) | {round(f, 3) for f in named.values()})
    grid = stress_grid(s0, env.horizon, fs_all)
    mc = simulate(N_MC, s0, env.horizon)
    f2018 = round(named["2018 pattern (−24 bp)"], 3)
    m2018 = np.isclose(grid.f, f2018)
    fmask = {f: np.isclose(grid.f, f) for f in fs_all}

    def cash(s, p):
        trs = tranches(env, s, p)
        return None if trs is None else sleeve_cash(env, s, trs)

    oo = [(s, cash(s, grid)) for s in ooat_universe()]
    oo = [(s, c) for s, c in oo if c is not None]
    hh = [(s, cash(s, grid)) for s in ogbl_universe()]
    hh = [(s, c) for s, c in hh if c is not None]
    fut = snap.futures.get("FOAT", {}).get("months", [])
    print(f"spread {s0} bp · OOAT fwd {env.f0['OOAT']:.2f} (Eurex FOAT Dec {fut[0]['live'] if fut else '–'}) · "
          f"OGBL fwd {env.f0['OGBL']:.2f} · ladder {[f'{b:%d %b %y}' for _, b in env.tranches]} · "
          f"shares {np.round(env.shares, 2).tolist()} · {len(oo)} OOAT × {len(hh)} OGBL")

    ooat_x = {s.name: float((c[1] / np.maximum(c[0], 1))[m2018].mean()) for s, c in oo}
    frontier = sorted(oo, key=lambda r: -ooat_x[r[0].name])
    print("OOAT alone, 2018 path, avg over event day — best:",
          [(s.name, round(ooat_x[s.name], 2)) for s, _ in frontier[:6]])

    mc_cash = {}

    def mc_of(s):
        if s is None:
            return None
        if s.name not in mc_cash:
            mc_cash[s.name] = cash(s, mc)
        return mc_cash[s.name]

    def books():
        for so, co in oo:
            for sh, ch in [(None, None)] + hh:
                for w in WS:
                    if (w == 1.0) != (sh is None):
                        continue
                    mm = mult(w, co, ch)
                    yield so, sh, w, float(mm[m2018].mean()), min(float(mm[m].mean()) for m in fmask.values())

    if args.frontier:
        ev = {s.name: mc_metrics(*mc_of(s), mc)["ev"] for s, _ in oo + hh}
        ranked = sorted(((w * ev[so.name] + (1 - w) * (ev[sh.name] if sh else 0), x, worst, so, sh, w)
                         for so, sh, w, x, worst in books()), key=lambda b: (-b[0], -b[1]))
        pool, best_x = [], -1.0
        for e, x, worst, so, sh, w in ranked:
            if x > best_x + 0.005:
                pool.append((False, worst, so, sh, w))
                best_x = x
                print(f"  EV {e:7.0f} · 2018 book {x:.2f}× · min stress {worst:.2f}× · {w:.0%} {so.name} + "
                      f"{sh.name if sh else '—'}")
        n_ok = sum(b[0] > 0 for b in ranked)
        print(f"EV vs 2018-multiple frontier: {len(pool)} of {len(ranked)} books; books with EV > 0: {n_ok}")
        args.top = max(args.top, len(pool))
    else:
        cands = [(worst >= args.book_min, worst, so, sh, w) for so, sh, w, x, worst in books()
                 if ooat_x[so.name] >= args.ooat_min]
        n_ok = sum(c[0] for c in cands)
        print(f"OOAT ≥{args.ooat_min}× (2018): {sum(ooat_x[s.name] >= args.ooat_min for s, _ in oo)} structures · "
              f"books also ≥{args.book_min}× on all stress paths: {n_ok}")
        if not cands:
            cands = [(False, 0.0, s, None, 1.0) for s, _ in frontier[:10]]
        pool = [c for c in cands if c[0]] or sorted(cands, key=lambda c: -c[1])[:300]

    scored = []
    for ok, worst, so, sh, w in pool:
        o, h = mc_of(so), mc_of(sh)
        spent = w * o[0] + (1 - w) * (h[0] if h else 0)
        pay = w * o[1] + (1 - w) * (h[1] if h else 0)
        scored.append((mc_metrics(spent, pay, mc), ok, worst, so, sh, w, spent, pay))
    scored.sort(key=lambda r: -r[0]["ev"])

    buckets = timing_buckets(env, grid)
    gcash = dict(oo) | dict(hh)
    results, seen = [], set()
    for m, ok, worst, so, sh, w, spent, pay in scored:
        key = (so.name, sh.name if sh else None)
        if key in seen:
            continue
        seen.add(key)
        co, ch = gcash[so], (gcash[sh] if sh else None)
        mo, mb = co[1] / np.maximum(co[0], 1), mult(w, co, ch)
        stress = {}
        for name, f in named.items():
            fm = fmask[round(f, 3)]
            stress[name] = {"book": round(float(mb[fm].mean()), 2), "ooat": round(float(mo[fm].mean()), 2),
                            "by_event": {b: [round(float(mb[fm & bm].mean()), 2), round(float(mo[fm & bm].mean()), 2)]
                                         for b, bm in buckets}}
        results.append({
            "ooat": so.name, "helper": sh.name if sh else None, "w_ooat": w, "constraints_met": ok,
            "ooat_2018_x": round(ooat_x[so.name], 2), "stress_min_book": round(worst, 2),
            "order_now": [order_now(env, so, w, w)] + ([order_now(env, sh, w, 1 - w)] if sh else []),
            "stress": stress,
            "mc": {k: (round(v, 3) if isinstance(v, float) and abs(v) < 5 else (round(v) if isinstance(v, float) else v))
                   for k, v in m.items()},
        })
        if len(results) >= args.top:
            break

    e_o, e_b = env.e1["OOAT"], env.e1["OGBL"]
    out = {
        "snapshot": {"chain_file": snap.path.name, "fetched_at": snap.fetched_at.isoformat(), "oat10": snap.oat10,
                     "bund10": snap.bund10, "spread": s0, "ooat_fwd": round(e_o.fwd, 2), "ogbl_fwd": round(e_b.fwd, 2),
                     "futures": snap.futures, "ooat_atm_iv": round(e_o.skew.atm, 4),
                     "ogbl_atm_iv": round(e_b.skew.atm, 4), "ooat_ivs": e_o.ivs, "ogbl_ivs": e_b.ivs},
        "assumptions": {"budget": env.budget, "cadence": env.cadence, "horizon_end": HORIZON_END.isoformat(),
                        "ladder": [[a.isoformat(), b.isoformat()] for a, b in env.tranches],
                        "budget_shares": np.round(env.shares, 3).tolist(), "event_days": EVENT_DAYS,
                        "roll_stop_bp": ROLL_STOP, "duration": DUR, "roll_vol_up_per_100bp": VOL_UP,
                        "roll_half_spread": HALF_SPREAD, "fee_per_contract": FEE, "ooat_min_x": args.ooat_min,
                        "book_min_x": args.book_min,
                        "regimes": [{"key": r[0], "spread": r[2], "p": r[3]} for r in REGIMES],
                        "stress_fs": {k: round(v, 3) for k, v in named.items()}, "n_mc": N_MC},
        "ooat_frontier": [{"structure": s.name, "x_2018": round(ooat_x[s.name], 2)} for s, _ in frontier[:15]],
        "n_feasible": n_ok, "books": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"sleeve_a_v4_{snap.path.stem.replace('eurex_', '')}_c{env.cadence}{'_frontier' if args.frontier else ''}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))

    for r in results:
        mcx = r["mc"]
        print(f"\n{r['ooat']} + {r['helper']} · OOAT share {r['w_ooat']:.0%} · ok={r['constraints_met']} · "
              f"OOAT 2018 {r['ooat_2018_x']}× · min stress book {r['stress_min_book']}×")
        for o in r["order_now"]:
            print(f"  now: {o['n']}× {o['structure']} @{o['px']} = €{o['spent']}")
        print(f"  EV {mcx['ev']} · EV½ {mcx['ev_half']} · spent {mcx['avg_spent']} · P+ {mcx['p_profit']} · "
              f"P3x {mcx['p_3x']} · full loss {mcx['p_full_loss']}")
        for name, v in r["stress"].items():
            be = " · ".join(f"{b} {x[0]}/{y}" for b, x in v["by_event"].items() for y in [x[1]])
            print(f"    {name:22} book {v['book']:5.2f}× OOAT {v['ooat']:5.2f}× | {be}")
    print("\nwrote", path)


if __name__ == "__main__":
    main()
