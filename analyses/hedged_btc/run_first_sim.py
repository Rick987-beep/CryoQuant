#!/usr/bin/env python3
"""Phase 2 sim — daily NAV for C1–C4/C6 vs BTCUSD (fees + bid/ask).

Usage (repo root):
    python -m analyses.hedged_btc.run_first_sim
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from cryoquant.data.sources import deribit_options as deribit

from analyses.hedged_btc.nav_sim import CANDIDATE_SPECS, simulate_book
from analyses.hedged_btc.report import print_regime_summary, write_regime_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

OUT = Path(__file__).resolve().parent / "data"


def main() -> int:
    dates = deribit.list_dates()
    start, end = dates[0], dates[-1]
    log.info("Sim window: %s → %s (%d days)", start, end, len(dates))

    sim_results: dict = {}
    results = {}
    for key, spec in CANDIDATE_SPECS.items():
        log.info("── Simulating %s (%s) ──", key, spec.name)
        try:
            res = simulate_book(spec, start=start, end=end, use_fees=True, use_bid_ask=True)
        except Exception as exc:
            log.error("%s failed: %s", key, exc, exc_info=True)
            continue
        sim_results[key] = res
        out_nav = OUT / f"nav_{key}.csv"
        pd_out = res.nav.to_frame()
        pd_out["btc"] = res.btc
        pd_out.to_csv(out_nav)
        res.rolls.to_csv(OUT / f"rolls_{key}.csv", index=False)
        results[key] = res.metrics
        log.info(
            "  rolls=%d  ret=%.1f%%  maxDD=%.1f%%  fees=$%.0f  up_cap=%s",
            res.metrics["n_rolls"],
            res.metrics["total_return"] * 100,
            res.metrics["max_drawdown"] * 100,
            res.metrics.get("total_fees_usd", 0),
            res.metrics.get("upside_capture"),
        )

    summary_path = OUT / "phase2_sim.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Wrote %s", summary_path)

    print("\n" + "=" * 72)
    print("PHASE 2 SIM (daily NAV, fees + bid/ask, CryoQuant-only)")
    print("=" * 72)
    for key, m in results.items():
        print(
            f"{key:14s}  ret={m['total_return']*100:+6.1f}%  "
            f"btc={m['btc_total_return']*100:+6.1f}%  "
            f"maxDD={m['max_drawdown']*100:6.1f}%  "
            f"btcDD={m['btc_max_drawdown']*100:6.1f}%  "
            f"rolls={m['n_rolls']:3d}  "
            f"fees=${m.get('total_fees_usd', 0):,.0f}  "
            f"up={m.get('upside_capture')}  down={m.get('downside_capture')}"
        )
    print("=" * 72)

    regime_report = write_regime_report(results=sim_results)
    print_regime_summary(regime_report)
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
