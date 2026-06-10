#!/usr/bin/env python3
"""C7 — USD cash + long calls vs BTCUSD buy-and-hold.

Usage (repo root):
    python -m analyses.hedged_btc.run_c7_sim
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from cryoquant.data.sources import deribit_options as deribit

from analyses.hedged_btc.nav_sim import NavResult
from analyses.hedged_btc.nav_sim_c7 import C7_SPECS, simulate_cash_participation
from analyses.hedged_btc.report import build_regime_report, print_regime_summary, write_regime_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

OUT = Path(__file__).resolve().parent / "data"


def main() -> int:
    dates = deribit.list_dates()
    start, end = dates[0], dates[-1]
    log.info("C7 sim window: %s → %s (%d days)", start, end, len(dates))

    sim_results: dict[str, NavResult] = {}
    results = {}
    for key, spec in C7_SPECS.items():
        log.info("── %s (%s) budget=%.1f%% ──", key, spec.name, spec.call_budget_pct * 100)
        try:
            res = simulate_cash_participation(spec, start=start, end=end)
        except Exception as exc:
            log.error("%s failed: %s", key, exc, exc_info=True)
            continue
        sim_results[key] = res
        out = res.nav.to_frame()
        out["btc"] = res.btc
        out.to_csv(OUT / f"nav_{key}.csv")
        res.rolls.to_csv(OUT / f"rolls_{key}.csv", index=False)
        results[key] = res.metrics
        log.info(
            "  rolls=%d ret=%.1f%% btc=%.1f%% maxDD=%.1f%% fees=$%.0f",
            res.metrics["n_rolls"],
            res.metrics["total_return"] * 100,
            res.metrics["btc_total_return"] * 100,
            res.metrics["max_drawdown"] * 100,
            res.metrics.get("total_fees_usd", 0),
        )

    summary_path = OUT / "phase2_c7_sim.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Regime report for C7 + reference C4/C6 if available
    ref_candidates = list(C7_SPECS.keys())
    for ref in ("C4_four_layer", "C6_tail"):
        if (OUT / f"nav_{ref}.csv").exists():
            ref_candidates.append(ref)

    regime = build_regime_report(candidates=ref_candidates, results=sim_results)
    # merge CSV-based refs
    full_regime = build_regime_report(candidates=ref_candidates)
    regime_path = OUT / "phase2_c7_regime_report.json"
    regime_path.write_text(json.dumps(full_regime, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print("C7 USD PARTICIPATION vs BTCUSD (2% NAV/month call budget, cash-settle CSP)")
    print("=" * 78)
    for key, m in results.items():
        print(
            f"{key:16s}  ret={m['total_return']*100:+6.1f}%  "
            f"btc={m['btc_total_return']*100:+6.1f}%  "
            f"excess={(m['total_return']-m['btc_total_return'])*100:+6.1f}%  "
            f"maxDD={m['max_drawdown']*100:6.1f}%  "
            f"rolls={m['n_rolls']:2d}  fees=${m.get('total_fees_usd', 0):,.0f}"
        )
    print("=" * 78)
    print_regime_summary(full_regime)
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
