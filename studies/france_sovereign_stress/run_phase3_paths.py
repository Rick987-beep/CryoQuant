#!/usr/bin/env python3
"""Phase 3: generate right/wrong-world paths (common RNGs) and write QA summaries.

Writes ``data/phase3_paths.json``. Does not run the trading rule engine (Phase 4).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

import numpy as np

from src.inputs import load_market_inputs
from src.paths import data_dir, load_config
from src.scenarios import ScenarioConfig, simulate_worlds, stock_cum_returns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=None, help="Override n_paths (default: config)")
    args = ap.parse_args()

    cfg = load_config()
    scfg = ScenarioConfig.from_study_config(cfg)
    if args.n is not None:
        scfg = ScenarioConfig(
            n_paths=args.n,
            seed=scfg.seed,
            event_bdays=scfg.event_bdays,
            event_vol_mult=scfg.event_vol_mult,
            bund_flight_share=scfg.bund_flight_share,
            dof=scfg.dof,
            end=scfg.end,
        )

    mi = load_market_inputs(cfg)
    stamp, start, s0, vol = mi.stamp, mi.start, mi.s0, mi.vol
    levels = [float(x) for x in cfg["view"]["levels_bp"]]

    worlds = simulate_worlds(vol, s0=s0, start=start, levels=levels, cfg=scfg)

    # Light CAC path check on the optimise level
    opt = float(cfg["view"]["optimise_bp"])
    cac_r = stock_cum_returns(worlds[opt], mi.beta_cac)
    rows = np.arange(worlds[opt].n)
    cac_at_exit = cac_r[rows, worlds[opt].tc]

    print("france_sovereign_stress Phase 3 — scenario paths")
    print(
        f"asof={start}  s0={s0:.2f} bp  end={scfg.end}  n={scfg.n_paths}  "
        f"seed={scfg.seed}  common_rng=True"
    )
    print(
        f"vol: σ_s={vol.sig_s:.3f}  σ_b={vol.sig_b:.3f}  ρ={vol.rho:.3f}  "
        f"event_bdays={scfg.event_bdays}  f∈{scfg.bund_flight_share}"
    )

    summaries = {}
    problems: list[str] = []
    for key in [None, *levels]:
        w = worlds[key]
        sm = w.summary()
        label = "wrong" if key is None else f"{int(key)}bp"
        summaries[label] = sm
        print(
            f"  [{label}] T={sm['T']}  mean_tc={sm['mean_tc']:.1f}  "
            f"spread@exit_mean={sm['spread_at_exit_mean']:.2f}"
            + (
                f"  hit_err={sm['hit_level_max_err']:.2e}  f∈[{sm['f_min']:.2f},{sm['f_max']:.2f}]"
                if key is not None
                else ""
            )
        )
        if key is not None and sm["hit_level_max_err"] > 1e-6:
            problems.append(f"level {key} hit error {sm['hit_level_max_err']}")

    # Common RNG check: tc identical across levels
    tcs = [worlds[lv].tc for lv in levels]
    if not all(np.array_equal(tcs[0], t) for t in tcs[1:]):
        problems.append("tc not shared across levels")

    out = {
        **mi.meta(),
        "asof": str(start),
        "s0_bp": s0,
        "n_paths": scfg.n_paths,
        "seed": scfg.seed,
        "common_random_numbers": True,
        "levels_bp": levels,
        "vol": vol.to_dict(),
        "summaries": summaries,
        "cac_at_exit_opt_level": {
            "level_bp": opt,
            "mean_log_return": float(cac_at_exit.mean()),
            "median_log_return": float(np.median(cac_at_exit)),
            "p_negative": float((cac_at_exit < 0).mean()),
        },
        "problems": problems,
        "ok": not problems,
    }
    path = data_dir() / "phase3_paths.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {path}")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Phase 3 OK — no problems.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
