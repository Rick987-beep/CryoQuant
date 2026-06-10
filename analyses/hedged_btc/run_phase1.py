#!/usr/bin/env python3
"""Run Phase 1 market-structure analysis for hedged BTC research.

Usage (from repo root):
    python -m analyses.hedged_btc.run_phase1
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from cryoquant.data.sources import deribit_options as deribit

from analyses.hedged_btc._utils import ensure_analysis_data_dir
from analyses.hedged_btc.carry_history import run as run_carry
from analyses.hedged_btc.drawdown_anatomy import run as run_drawdown
from analyses.hedged_btc.live_quote import run as run_live_quote
from analyses.hedged_btc.skew_history import run as run_skew
from analyses.hedged_btc.vrp_history import run as run_vrp

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
OUT = ensure_analysis_data_dir(ROOT)


def main() -> int:
    dates = deribit.list_dates()
    if not dates:
        log.error("No Deribit chain dates found. Set CRYOBACKTESTER_DATA_DIR.")
        return 1

    chain_start, chain_end = dates[0], dates[-1]
    log.info("Chain window: %s → %s (%d days)", chain_start, chain_end, len(dates))

    results: dict = {
        "chain_window": {"start": str(chain_start), "end": str(chain_end), "n_days": len(dates)},
        "market_note": "BTC and Deribit options trade 24/7 — no overnight/weekend gap framing.",
    }

    log.info("── 1a Skew history ──")
    _, skew_summary = run_skew(OUT)
    results["skew"] = skew_summary

    log.info("── 1b VRP history ──")
    _, vrp_summary = run_vrp(OUT, chain_start, chain_end)
    results["vrp"] = vrp_summary

    log.info("── 1c Funding / carry (Deribit primary) ──")
    carry_summary, _ = run_carry(OUT, datetime(2024, 1, 1, tzinfo=timezone.utc))
    results["carry"] = carry_summary

    log.info("── 1d Drawdown anatomy (24/7) ──")
    _, dd_summary = run_drawdown(OUT, start_year=2019)
    results["drawdown"] = dd_summary

    log.info("── 1e Live quote ──")
    live = run_live_quote(OUT)
    results["live_quote"] = {
        "as_of_utc": live["as_of_utc"],
        "spot_usd": live["spot_usd"],
        "dvol_30d": live.get("dvol_30d"),
    }

    summary_path = OUT / "phase1_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Wrote %s", summary_path)

    _sync_results_phase1(results)
    _print_summary(results)
    return 0


def _print_summary(results: dict) -> None:
    print("\n" + "=" * 60)
    print("PHASE 1 SUMMARY (revised — 24/7, Deribit funding regimes)")
    print("=" * 60)
    s = results.get("skew", {})
    print(f"Skew spread (front−back): mean {s.get('skew_spread_mean_pp')}pp, "
          f"median {s.get('skew_spread_median_pp')}pp, "
          f"{s.get('pct_days_spread_gt_5pp')}% days >5pp")
    v = results.get("vrp", {})
    print(f"VRP (DVOL−RV30): mean {v.get('dvol_vrp_mean_pp')}pp, "
          f"{v.get('dvol_pct_positive_vrp')}% days positive")
    c_der = results.get("carry", {}).get("deribit", {})
    pre = c_der.get("pre_2026_03", {})
    post = c_der.get("post_2026_03", {})
    print(f"Deribit funding APR — pre-Mar2026: mean {pre.get('apr_mean_pct', 0):.2f}% "
          f"median {pre.get('apr_median_pct', 0):.2f}%")
    print(f"Deribit funding APR — post-Mar2026: mean {post.get('apr_mean_pct', 0):.2f}% "
          f"median {post.get('apr_median_pct', 0):.4f}%  verdict={c_der.get('verdict')}")
    d = results.get("drawdown", {})
    print(f"Max BTC drawdown since 2019: {d.get('max_drawdown_pct'):.1f}%")
    print(f"Worst 24h return (recent 2y hourly): {d.get('worst_24h_return_pct', 'n/a')}%")
    print(f"Worst daily close-to-close: {d.get('daily_close_return_worst_pct', 'n/a')}%")
    print("=" * 60)


def _sync_results_phase1(results: dict) -> None:
    """Write machine summary + short FINDINGS snapshot; canonical agent doc is RESULTS.md."""
    _write_findings_snapshot(results)
    log.info("Canonical results: %s (update Phase 1 section manually if metrics change materially)", ROOT / "RESULTS.md")


def _write_findings_snapshot(results: dict) -> None:
    """Auto-generated snapshot after each Phase 1 run (supplements RESULTS.md)."""
    path = ROOT / "FINDINGS.md"
    s = results["skew"]
    v = results["vrp"]
    carry = results["carry"]
    c_der = carry.get("deribit", {})
    c_pre = c_der.get("pre_2026_03", {})
    c_post = c_der.get("post_2026_03", {})
    d = results["drawdown"]
    live = results["live_quote"]
    cw = results["chain_window"]

    def _f(val, fmt=".2f", suffix=""):
        if val is None:
            return "n/a"
        return f"{val:{fmt}}{suffix}"

    body = f"""# Hedged BTC — Phase 1 Findings (revised)

**Generated:** {live['as_of_utc']}  
**Chain data:** {cw['start']} → {cw['end']} ({cw['n_days']} days)  
**Market:** BTC and Deribit options trade **24/7** — no overnight or weekend gap concepts.  
**Artifacts:** `analyses/hedged_btc/data/`

---

## 1a — Skew term structure

| Metric | Value |
|---|---|
| Days analysed | {s.get('n_days')} |
| Front skew mean (−10% put IV − +10% call IV) | {_f(s.get('front_skew_mean_pp'))} pp |
| Back skew mean | {_f(s.get('back_skew_mean_pp'))} pp |
| **Front − back spread (mean)** | **{_f(s.get('skew_spread_mean_pp'))} pp** |
| Spread median | {_f(s.get('skew_spread_median_pp'))} pp |
| % days spread > 5 pp | {_f(s.get('pct_days_spread_gt_5pp'), '.1f', '%')} |
| % days spread > 10 pp | {_f(s.get('pct_days_spread_gt_10pp'), '.1f', '%')} |

**Read:** C3/C4/C5 depend on front skew exceeding back skew. Chain marks use the **last UTC-day**
5-min snapshot (continuous market, not an equity close). See `data/skew_history.csv`.

---

## 1b — Vol risk premium (IV − realised vol)

| Metric | DVOL (2023→) | Chain mid-ATM ({cw['start']}→) |
|---|---|---|
| Mean VRP | {_f(v.get('dvol_vrp_mean_pp'))} pp | {_f(v.get('chain_vrp_mean_pp'))} pp |
| % days VRP > 0 | {_f(v.get('dvol_pct_positive_vrp'), '.1f', '%')} | {_f(v.get('chain_pct_positive_vrp'), '.1f', '%')} |

**Read:** Income-from-premium candidates need sustained positive VRP. See `data/vrp_history.csv`.

---

## 1c — Funding / carry (Deribit primary venue)

**Recommendation:** {carry.get('recommendation', 'n/a')}

| Regime | Deribit mean APR | Deribit median APR | % obs > 5% trigger |
|---|---|---|---|
| All ({c_der.get('span_start', '?')} → {c_der.get('span_end', '?')}) | {_f(c_der.get('all', {}).get('apr_mean_pct'))}% | {_f(c_der.get('all', {}).get('apr_median_pct'))}% | {_f(c_der.get('all', {}).get('pct_above_5pct_apr'), '.1f', '%')} |
| **Pre Mar 2026** | {_f(c_pre.get('apr_mean_pct'))}% | {_f(c_pre.get('apr_median_pct'))}% | {_f(c_pre.get('pct_above_5pct_apr'), '.1f', '%')} |
| **Post Mar 2026** | {_f(c_post.get('apr_mean_pct'))}% | {_f(c_post.get('apr_median_pct'), '.4f')}% | {_f(c_post.get('pct_above_5pct_apr'), '.1f', '%')} |

Binance perp (reference only — product trades on Deribit): post-Mar2026 mean APR
{_f(carry.get('binance', {}).get('post_2026_03', {}).get('apr_mean_pct'))}%.

**Read:** L3 / conditional carry is **not a viable core income pillar** after Deribit's ~Mar 2026
perpetual changes (median funding ~0.01% APR). Historical pre-Mar2026 rates must not be extrapolated.
See `data/funding_deribit.csv`.

---

## 1d — Drawdown anatomy (24/7 BTC, 2019→)

| Metric | Value |
|---|---|
| Max drawdown from peak | {_f(d.get('max_drawdown_pct'), '.1f', '%')} ({d.get('max_drawdown_date', '')}) |
| Monthly DD median / worst | {_f(d.get('monthly_dd_median_pct'), '.1f', '%')} / {_f(d.get('monthly_dd_worst_pct'), '.1f', '%')} |
| Quarterly DD median / worst | {_f(d.get('quarterly_dd_median_pct'), '.1f', '%')} / {_f(d.get('quarterly_dd_worst_pct'), '.1f', '%')} |
| Worst daily **close-to-close** return | {_f(d.get('daily_close_return_worst_pct'), '.1f', '%')} |
| Worst **24h** return (hourly, ~last 2y) | {_f(d.get('worst_24h_return_pct'), '.1f', '%')} |
| Worst **1h** return (hourly, ~last 2y) | {_f(d.get('worst_1h_return_pct'), '.1f', '%')} |
| Daily range (H−L)/close median / p95 | {_f(d.get('daily_range_median_pct'), '.1f', '%')} / {_f(d.get('daily_range_p95_pct'), '.1f', '%')} |
| % calendar days close down > 5% | {_f(d.get('pct_days_close_down_gt_5pct'), '.1f', '%')} |

**Read:** Drawdowns are measured on **continuous trading** — peak-to-trough and rolling windows,
not session gaps. Sizes buffer (C2) vs hard-floor (C1/C3). See `data/drawdown_*.csv`.

---

## 1e — Live snapshot

| | |
|---|---|
| Spot | ${live.get('spot_usd', 0):,.0f} |
| DVOL | {live.get('dvol_30d', 'n/a')}% |

---

## Implications for candidates (hypotheses — not decisions)

1. **Skew spread:** Front−back spread supports C3/C4 income financing on average; spikes in crash months (e.g. Feb 2026).
2. **VRP:** Positive ~75% of days — modest tailwind for L2/C5 premium selling; not a substitute for explicit hedge cost.
3. **Carry (L3):** **Deprioritise.** Deribit funding post-Mar2026 is negligible (median ~0.01% APR). Do not model carry as self-financing.
4. **Drawdowns:** Sustained multi-week declines dominate; soft buffers (C2) fail on crash tails without tail puts (C6/C4 L4).

---

## Limitations

- Chain skew/VRP: ~14 months of daily chain snapshots — indicative, not definitive.
- Chain marks: last 5-min snapshot per UTC calendar day.
- Deribit funding: paginated hourly history from 2024-01; regime break ~Mar 2026 documented above.
- Hourly crash stats: last ~2 years only (compute cost).

---

## Next step

Phase 2: build multi-leg options backtester (`pricing.py`, `book.py`, `nav_sim.py`) per `APPROACH.md`.
"""
    path.write_text(body, encoding="utf-8")
    log.info("Wrote %s", path)


if __name__ == "__main__":
    sys.exit(main())
