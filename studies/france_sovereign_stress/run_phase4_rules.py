#!/usr/bin/env python3
"""Phase 4: stop/pyramid rule engine — straight-line reconcile + MC smoke.

Writes ``data/phase4_rules.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

import numpy as np

from src.calibrate import calibrate_futures, calibrate_vol, stock_betas
from src.data.reference import (
    load_eurex_settles,
    load_eurex_snapshot,
    load_stocks_daily,
    load_yields_daily,
)
from src.paths import data_dir, load_config
from src.rules import (
    Rule,
    build_cac_sleeve,
    build_spread_sleeve,
    run_continuous,
    run_integer_spread,
    straight_line_spread_ladder,
)
from src.scenarios import ScenarioConfig, simulate_worlds


V5_STRAIGHT = {240: 76_563, 300: 181_664, 340: 251_730, 400: 356_831}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000, help="MC paths for smoke (default 2000)")
    args = ap.parse_args()

    cfg = load_config()
    stamp = cfg["reference"]["stamp"]
    s0 = (
        float(load_eurex_snapshot(stamp)["yields"]["oat10"])
        - float(load_eurex_snapshot(stamp)["yields"]["bund10"])
    ) * 100.0
    # Use rounded 138.0 for straight-line parity with v5 report
    s0_report = 138.0
    levels = [float(x) for x in cfg["view"]["levels_bp"]]
    budget = float(cfg["budget_eur"])
    stop = float(cfg["rules"]["recommended"]["stop_bp"])
    add = float(cfg["rules"]["recommended"]["add_every_bp"])
    keep = float(cfg["rules"]["recommended"]["keep"])
    rule = Rule(stop, add, keep)

    fc = calibrate_futures(load_eurex_settles(), load_yields_daily())
    ladder = straight_line_spread_ladder(
        s0=s0_report,
        eur_foat=fc.eur_per_bp["FOAT"],
        eur_fgbl=fc.eur_per_bp["FGBL"],
        levels=levels,
        budget=budget,
        stop_bp=stop,
        add_every_bp=add,
        foat_cap=int(cfg["rules"]["spread_cap_foat"]),
    )

    print("france_sovereign_stress Phase 4 — rules")
    print(f"rule: {rule.text}  budget=€{budget:,.0f}  s0_report={s0_report}  snap_s0={s0:.2f}")
    print("Straight-line integer ladder (no costs):")
    problems: list[str] = []
    straight_cmp = {}
    for L in levels:
        eq = ladder["finals"][L]
        target = V5_STRAIGHT[int(L)]
        diff = eq - target
        ok = abs(diff) < 1.0
        straight_cmp[str(int(L))] = {
            "v6": eq,
            "v5": target,
            "diff": diff,
            "ok": ok,
        }
        flag = "OK" if ok else "FAIL"
        print(f"  [{flag}] {int(L)} bp → €{eq:,.0f}  (v5 €{target:,})  diff={diff:+.2f}")
        if not ok:
            problems.append(f"straight-line {L}: {eq} vs {target}")

    print("Ladder contract sizes:")
    for r in ladder["rows"][:7]:
        print(
            f"  {r['step']:<8} +{r['delta_bp']:.0f} bp  "
            f"FOAT={r['foat']} FGBL={r['fgbl']}  eq=€{r['equity']:,.0f}"
        )

    # MC smoke: continuous daily_close vs resting; integer daily_close
    vol = calibrate_vol(load_yields_daily(), window=int(cfg["simulation"]["vol_window_bdays"]))
    scfg = ScenarioConfig.from_study_config(cfg)
    scfg = ScenarioConfig(
        n_paths=args.n,
        seed=scfg.seed,
        event_bdays=scfg.event_bdays,
        event_vol_mult=scfg.event_vol_mult,
        bund_flight_share=scfg.bund_flight_share,
        dof=scfg.dof,
        end=scfg.end,
    )
    start = date.fromisoformat(stamp.split("T", 1)[0])
    worlds = simulate_worlds(vol, s0=s0, start=start, levels=levels, cfg=scfg)
    opt = float(cfg["view"]["optimise_bp"])

    mc: dict[str, Any] = {}
    for exec_mode in ("daily_close", "resting_stop"):
        sleeve = build_spread_sleeve(worlds[opt], fc)
        eq, u0 = run_continuous(sleeve, worlds[opt], rule, budget, execution=exec_mode)
        mult = eq / budget
        mc[f"spread_continuous_{exec_mode}"] = {
            "n": args.n,
            "units0": u0,
            "mean_x": float(mult.mean()),
            "median_x": float(np.median(mult)),
            "p_lost": float((mult <= 0.1).mean()),
            "p_ge_10x": float((mult >= 10).mean()),
            "wrong_mean_x": float(
                run_continuous(
                    build_spread_sleeve(worlds[None], fc),
                    worlds[None],
                    rule,
                    budget,
                    execution=exec_mode,
                )[0].mean()
                / budget
            ),
        }
        print(
            f"MC spread continuous/{exec_mode} @ {int(opt)} (n={args.n}): "
            f"mean={mc[f'spread_continuous_{exec_mode}']['mean_x']:.2f}×  "
            f"median={mc[f'spread_continuous_{exec_mode}']['median_x']:.2f}×  "
            f"lost={mc[f'spread_continuous_{exec_mode}']['p_lost']:.1%}  "
            f"wrong={mc[f'spread_continuous_{exec_mode}']['wrong_mean_x']:.2f}×"
        )

    eq_i, _ = run_integer_spread(worlds[opt], fc, rule, budget, execution="daily_close")
    mult_i = eq_i / budget
    mc["spread_integer_daily_close"] = {
        "n": args.n,
        "mean_x": float(mult_i.mean()),
        "median_x": float(np.median(mult_i)),
        "p_lost": float((mult_i <= 0.1).mean()),
        "p_ge_10x": float((mult_i >= 10).mean()),
    }
    print(
        f"MC spread integer/daily_close @ {int(opt)} (n={args.n}): "
        f"mean={mc['spread_integer_daily_close']['mean_x']:.2f}×  "
        f"median={mc['spread_integer_daily_close']['median_x']:.2f}×  "
        f"lost={mc['spread_integer_daily_close']['p_lost']:.1%}"
    )

    beta = stock_betas(load_stocks_daily(), load_yields_daily(), tickers=["^FCHI"])["^FCHI"]
    cac = build_cac_sleeve(worlds[opt], beta, carry_pa=float(cfg["costs"]["cac_future_carry_pa"]))
    eq_c, _ = run_continuous(cac, worlds[opt], Rule(12, 6, 0.0), budget, execution="daily_close")
    mult_c = eq_c / budget
    mc["cac_continuous_daily_close"] = {
        "n": args.n,
        "mean_x": float(mult_c.mean()),
        "median_x": float(np.median(mult_c)),
        "p_lost": float((mult_c <= 0.1).mean()),
    }
    print(
        f"MC CAC continuous/daily_close @ {int(opt)} (n={args.n}): "
        f"mean={mc['cac_continuous_daily_close']['mean_x']:.2f}×  "
        f"median={mc['cac_continuous_daily_close']['median_x']:.2f}×"
    )

    # Note: full n=10k reconcile vs HANDOVER 11.67× is Phase 5
    out = {
        "stamp": stamp,
        "s0_report": s0_report,
        "s0_snapshot": s0,
        "rule": rule.text,
        "execution_default": "daily_close",
        "straight_line": {
            "finals": {str(int(k)): v for k, v in ladder["finals"].items()},
            "vs_v5": straight_cmp,
            "ladder_rows": ladder["rows"],
        },
        "mc_smoke": mc,
        "problems": problems,
        "ok": not problems,
        "note": "Full 10k-path v5 mean reconcile is Phase 5; smoke uses --n paths.",
    }
    path = data_dir() / "phase4_rules.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {path}")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Phase 4 OK — straight-line targets matched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
