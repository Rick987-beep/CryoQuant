"""v5: super-convex France stress book. Base case: spread reaches ≥ 240 bp by 1 Jul 2027; optimised at 300 bp.

Candidates: IBKR linear sleeves (spread trade, short FOAT, long FGBL, short French non-bank stocks / CAC future) with
a hard stop and optional pyramiding; Swissquote Eurex options (OOAT puts, spreads, backspreads; OGBL calls), either
front-only (20 Nov) or rolled. Payout multiple = equity at exit / budget. Ranked by mean multiple at 300 bp.

    .venv/bin/python jobs/france-sovereign-stress/scripts/v5/run.py [--budget 10000] [--n 10000]
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

import numpy as np

import linear
import options
from history import STOCKS
from model import EVENT_BD, F_RANGE, LEVELS, Calib, FutCalib, simulate

JOB = Path(__file__).resolve().parents[2]
OUT = JOB / "data" / "v5"
OPT_LEVEL = 300
MIX_TOP = 8
MIX_W = (0.25, 0.5, 0.75)


def stats(m: np.ndarray) -> dict:
    return {"mean": float(m.mean()), "median": float(np.median(m)), "p_lost": float((m <= 0.1).mean()),
            "p_5x": float((m >= 5).mean()), "p_10x": float((m >= 10).mean()), "p95": float(np.percentile(m, 95))}


def evaluate(snap, cal, fc, budget, n, level, seed):
    w = simulate(cal, snap.spread, snap.val_date, n, level, seed)
    sleeves, info = linear.futures_sleeves(w, fc)
    sleeves += linear.stock_sleeves(w, cal, STOCKS)
    out = {}
    for s in sleeves:
        for r in linear.rules(s.unit):
            eq, u0 = linear.run(s, w, r, budget)
            out[(s.key, r.text)] = {"family": "futures" if s.unit == "bp" else "stocks", "name": s.name,
                                    "rule": r.text, "m": eq / budget, "units0": u0, "cpu": s.contracts_per_unit,
                                    "unit": s.unit}
    p = options.OptPaths(w, snap.val_date)
    for mode in ("front", "ladder"):
        env = options.make_env(snap, budget, mode, fc.duration)
        for st in options.universe():
            c = options.option_cash(env, st, p)
            if c is None:
                continue
            spent, pay = c
            out[(st.name, mode)] = {"family": f"{st.product} options", "name": st.name, "rule": mode,
                                    "m": (pay + budget - spent) / budget, "structure": st, "env": env}
    return w, out, info


def order_text(rec, budget, info) -> list:
    if rec["family"].endswith("options"):
        env, st = rec["env"], rec["structure"]
        e = env.e1[st.product]
        px = st.live_cost(e)
        unit = px * 1000 + 2.35 * st.n_contracts
        k = math.floor(budget * env.shares[0] / unit)
        return [f"{l.text.replace(f'{abs(l.q)} ', f'{k * abs(l.q)} ', 1)} 20/11/2026 "
                f"(bid {e.quotes[l.cp][l.k].bid} / ask {e.quotes[l.cp][l.k].ask})" for l in st.legs] + \
               [f"cost ≈ €{k * unit:,.0f} now"]
    if rec["family"] == "futures":
        return [f"{'Sell' if c < 0 else 'Buy'} {abs(c * rec['units0']):.1f} {code} Dec"
                for code, c in rec["cpu"].items()] + [f"€{rec['units0']:,.0f} per bp"]
    return [f"Short ≈ €{rec['units0'] * 100:,.0f} notional ({rec['name'][6:]})"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=10_000)
    ap.add_argument("--n", type=int, default=10_000)
    ap.add_argument("--chain", type=Path)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--vol-mult", type=float, default=1.0, help="scale realized spread and Bund vol")
    ap.add_argument("--stock-beta-mult", type=float, default=1.0, help="scale stock betas to spread and Bund")
    args = ap.parse_args()

    snap = options.load_snapshot(args.chain)
    cal = Calib.load()
    fc = FutCalib.load()
    print(f"futures (Eurex settles vs CNBC yields, {fc.days} days): EUR/bp {fc.eur_per_bp}, duration "
          f"{ {k: round(v, 2) for k, v in fc.duration.items()} }, carry bp/day "
          f"{ {k: round(v, 3) for k, v in fc.carry_bp_per_day.items()} }")
    cal.sig_s *= args.vol_mult
    cal.sig_b *= args.vol_mult
    for st in cal.stocks.values():
        st["beta_s"] *= args.stock_beta_mult
        st["beta_b"] *= args.stock_beta_mult
    print(f"spread {snap.spread} bp · realized daily vol spread {cal.sig_s:.2f} bp, Bund {cal.sig_b:.2f} bp, "
          f"corr {cal.rho:.2f} · base case {LEVELS} bp by 1 Jul 2027, optimise {OPT_LEVEL}")

    worlds, res = {}, {}
    info = None
    for i, level in enumerate(list(LEVELS) + [None]):
        w, out, info = evaluate(snap, cal, fc, args.budget, args.n, level, seed=11 + i)
        worlds[level], res[level] = w, out
        print(f"  level {level}: {len(out)} candidates")

    base = res[OPT_LEVEL]
    ranked = sorted(base, key=lambda k: -base[k]["m"].mean())
    w300 = worlds[OPT_LEVEL]
    third = (w300.days.size - 1) / 3

    def row(k, m_by_level=None):
        rec = base[k]
        m = rec["m"]
        r = {"family": rec["family"], "name": rec["name"], "rule": rec["rule"], **stats(m),
             "levels": {str(l): round(float(res[l][k]["m"].mean()), 2) for l in LEVELS},
             "wrong_mean": round(float(res[None][k]["m"].mean()), 2),
             "by_f": [round(float(m[(w300.f >= a) & (w300.f < b)].mean()), 2)
                      for a, b in ((0.10, 0.30), (0.30, 0.50), (0.50, 0.70))],
             "by_timing": [round(float(m[(w300.tc >= a * third) & (w300.tc < (a + 1) * third + 1)].mean()), 2)
                           for a in range(3)],
             "order": order_text(rec, args.budget, info)}
        return r

    best = [row(k) for k in ranked[:args.top]]
    fam_best = {}
    for k in ranked:
        fam_best.setdefault(base[k]["family"], k)
    families = {f: row(k) for f, k in fam_best.items()}

    pool, seen = [], set()
    for k in ranked:
        if base[k]["name"] not in seen:
            pool.append(k)
            seen.add(base[k]["name"])
        if len(pool) >= MIX_TOP:
            break
    for k in fam_best.values():
        if k not in pool:
            pool.append(k)
    mixes = []
    for a, b in itertools.combinations(pool, 2):
        for wt in MIX_W:
            m = wt * base[a]["m"] + (1 - wt) * base[b]["m"]
            mixes.append({"a": f"{base[a]['name']} [{base[a]['rule']}]", "b": f"{base[b]['name']} [{base[b]['rule']}]",
                          "w_a": wt, **stats(m),
                          "levels": {str(l): round(float(wt * res[l][a]["m"].mean() + (1 - wt) * res[l][b]["m"].mean()), 2)
                                     for l in LEVELS}})
    mixes.sort(key=lambda r: (-r["median"], -r["mean"]))

    out = {"snapshot": {"chain": snap.path.name, "spread": snap.spread, "fetched_at": snap.fetched_at.isoformat()},
           "assumptions": {"budget": args.budget, "levels": LEVELS, "optimise": OPT_LEVEL, "end": "2027-07-01",
                           "event_bdays": EVENT_BD, "f_range": F_RANGE, "sig_s_daily": cal.sig_s,
                           "sig_b_daily": cal.sig_b, "rho": cal.rho, "futures": info, "n": args.n,
                           "fut_cap_contracts": 20, "stock_cost_pa": linear.STOCK_COST, "vol_mult": args.vol_mult,
                           "stock_beta_mult": args.stock_beta_mult,
                           "stocks": {k: {kk: round(v, 6) for kk, v in s.items()} for k, s in cal.stocks.items()}},
           "stock_rank": sorted(({"tic": base[k]["name"], "rule": base[k]["rule"],
                                  "mean": round(float(base[k]["m"].mean()), 2),
                                  "median": round(float(np.median(base[k]["m"])), 2),
                                  "p_lost": round(float((base[k]["m"] <= 0.1).mean()), 3)}
                                 for k in {next(kk for kk in ranked if base[kk]["name"] == nm)
                                           for nm in {base[x]["name"] for x in base if base[x]["family"] == "stocks"}}),
                                key=lambda r: -r["mean"]),
           "best": best, "family_best": families, "mixes_by_median": mixes[:15]}
    OUT.mkdir(parents=True, exist_ok=True)
    tag = ("" if args.vol_mult == 1 else f"_vol{args.vol_mult:g}") + \
          ("" if args.stock_beta_mult == 1 else f"_beta{args.stock_beta_mult:g}")
    path = OUT / f"v5_{snap.path.stem.replace('eurex_', '')}{tag}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))

    def show(r):
        print(f"  {r['mean']:6.2f}× mean · {r['median']:5.2f}× median · lost {r['p_lost']:.0%} · ≥5× {r['p_5x']:.0%} · "
              f"≥10× {r['p_10x']:.0%} | levels {r['levels']} | wrong {r['wrong_mean']} | f-terciles {r['by_f']} | "
              f"timing {r['by_timing']} :: {r['family']} · {r['name']} [{r['rule']}]")
    print("\nTOP by mean multiple at 300 bp")
    for r in best:
        show(r)
    print("\nBEST per family")
    for r in families.values():
        show(r)
        print("     order:", " · ".join(r["order"]))
    print("\nMIXES by median")
    for r in mixes[:8]:
        print(f"  {r['median']:5.2f}× median · {r['mean']:6.2f}× mean · lost {r['p_lost']:.0%} · ≥5× {r['p_5x']:.0%} | "
              f"{r['levels']} :: {r['w_a']:.0%} {r['a']} + {r['b']}")
    print("\nwrote", path)


if __name__ == "__main__":
    main()
