#!/usr/bin/env python3
"""Phase 2: DV01 / carry / vol calibration + live P&L reconcile (+€11,490).

Writes ``data/phase2_pricing.json``. Options / Black-76 deferred (scope: spread + CAC).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from src.calibrate import (
    calibrate_futures,
    calibrate_vol,
    duration_cross_check,
    live_spread_pnl,
    reconcile_v5,
    stock_betas,
)
from src.data.reference import load_eurex_settles, load_stocks_daily, load_yields_daily
from src.paths import data_dir, load_config


def main() -> int:
    cfg = load_config()
    window = int(cfg["simulation"]["vol_window_bdays"])

    yields = load_yields_daily()
    settles = load_eurex_settles()
    stocks = load_stocks_daily()

    fc = calibrate_futures(settles, yields)
    vol = calibrate_vol(yields, window=window)
    pnl = live_spread_pnl(settles, yields)
    xcheck = duration_cross_check(fc)
    betas = stock_betas(stocks, yields, vol_window=window, tickers=["^FCHI"])
    cac = betas.get("^FCHI")

    # Prefer exact v5 JSON assumptions when present
    v5_path = (
        STUDY_DIR
        / cfg["reference"]["v5_dir"]
        / "results"
        / f"v5_{cfg['reference']['stamp']}.json"
    )
    v5_eur = {"FOAT": 87.58, "FGBL": 96.57}
    v5_vol = {"sig_s": 3.18, "sig_b": 3.95, "rho": 0.14, "hedge": 0.907}
    if v5_path.is_file():
        ass = json.loads(v5_path.read_text())["assumptions"]
        fut = ass["futures"]
        v5_eur = {k: float(fut["eur_per_bp"][k]) for k in ("FOAT", "FGBL")}
        v5_vol = {
            "sig_s": float(ass["sig_s_daily"]),
            "sig_b": float(ass["sig_b_daily"]),
            "rho": float(ass["rho"]),
            "hedge": float(fut["hedge_ratio"]),
        }

    recon = reconcile_v5(fc, vol, pnl, v5_eur=v5_eur, v5_vol=v5_vol)

    print("france_sovereign_stress Phase 2 — pricing / calibration")
    print(f"FutCalib days={fc.days}  hedge_ratio={fc.hedge_ratio:.4f}")
    for code in ("FOAT", "FGBL"):
        print(
            f"  {code}: €{fc.eur_per_bp[code]:.2f}/bp  duration={fc.duration[code]:.3f}  "
            f"carry={fc.carry_bp_per_day[code]:.4f} bp/day  "
            f"corr(price,yield)={fc.corr_price_yield[code]:.3f}  "
            f"calendar={fc.calendar_points[code]:.3f} pts"
        )
    print(
        f"Vol ({vol.window}d): σ_spread={vol.sig_s:.3f} bp  σ_Bund={vol.sig_b:.3f} bp  "
        f"ρ={vol.rho:.3f}  n={vol.n_obs}"
    )
    print(
        f"Live P&L short {pnl.foat_n} FOAT / long {pnl.fgbl_n} FGBL  "
        f"{pnl.start} → {pnl.end}: €{pnl.pnl_eur:,.2f}  "
        f"(target €{pnl.target_eur:,.0f})  "
        f"spread {pnl.spread_start_bp:.2f}→{pnl.spread_end_bp:.2f} "
        f"(Δ{pnl.spread_change_bp:.2f} bp)  ok={pnl.pnl_ok}"
    )
    print(
        f"  settles FOAT {pnl.foat_start:.2f}→{pnl.foat_end:.2f}  "
        f"FGBL {pnl.fgbl_start:.2f}→{pnl.fgbl_end:.2f}  "
        f"realized €/bp of spread={pnl.eur_per_bp_realized:.1f}"
    )
    print("Duration cross-check (identity dur×P/10 vs regression; D=8 assumed):")
    for code, row in xcheck.items():
        print(
            f"  {code}: identity_diff={row['identity_diff']:.6g}  "
            f"D8=€{row['assumed_D8_eur_per_bp']:.1f}/bp "
            f"({row['assumed_D8_vs_regression_pct']:+.1f}% vs regression)"
        )
    if cac:
        print(
            f"CAC ^FCHI betas: β_spread={cac.beta_s:.6f}  β_Bund={cac.beta_b:.6f}  "
            f"idio={cac.idio:.4f}  R²={cac.r2:.3f}  "
            f"last={float(stocks['^FCHI'].iloc[-1]):.2f}"
        )

    # Acceptance gates
    problems: list[str] = []
    if not pnl.pnl_ok:
        problems.append(f"live P&L {pnl.pnl_eur} ≠ target {pnl.target_eur}")
    for code in ("FOAT", "FGBL"):
        if abs(xcheck[code]["identity_diff"]) > 1e-6:
            problems.append(f"{code} duration identity failed")
        if abs(fc.eur_per_bp[code] - v5_eur[code]) > 0.05:
            problems.append(
                f"{code} €/bp {fc.eur_per_bp[code]:.4f} vs v5 {v5_eur[code]:.4f}"
            )
    if abs(vol.sig_s - v5_vol["sig_s"]) > 0.02:
        problems.append(f"sig_s {vol.sig_s} vs v5 {v5_vol['sig_s']}")

    out = {
        "stamp": cfg["reference"]["stamp"],
        "futures": fc.to_dict(),
        "vol": vol.to_dict(),
        "live_pnl": pnl.to_dict(),
        "duration_cross_check": xcheck,
        "cac": {
            "ticker": "^FCHI",
            "last": float(stocks["^FCHI"].iloc[-1]),
            "beta_s": cac.beta_s if cac else None,
            "beta_b": cac.beta_b if cac else None,
            "idio": cac.idio if cac else None,
            "r2": cac.r2 if cac else None,
            "stop_pct": 12.0,
            "add_every_pct": 6.0,
            "eur_per_point_fce": cfg["instruments"]["FCE"]["eur_per_point"],
        },
        "reconcile_v5": recon,
        "problems": problems,
        "ok": not problems,
    }
    path = data_dir() / "phase2_pricing.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {path}")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Phase 2 OK — no problems.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
