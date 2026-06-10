# Hedged BTC — Phase 1 snapshot (auto-generated)

> **Canonical agent handoff:** [`RESULTS.md`](RESULTS.md). This file is rewritten on each
> `run_phase1` execution; use it for quick numbers, `RESULTS.md` for conclusions and context.

# Phase 1 snapshot (revised)

**Generated:** 2026-06-10T15:36:33.090733+00:00  
**Chain data:** 2025-04-11 → 2026-06-07 (423 days)  
**Market:** BTC and Deribit options trade **24/7** — no overnight or weekend gap concepts.  
**Artifacts:** `analyses/hedged_btc/data/`

---

## 1a — Skew term structure

| Metric | Value |
|---|---|
| Days analysed | 423 |
| Front skew mean (−10% put IV − +10% call IV) | 7.33 pp |
| Back skew mean | 2.39 pp |
| **Front − back spread (mean)** | **4.89 pp** |
| Spread median | 4.50 pp |
| % days spread > 5 pp | 42.0% |
| % days spread > 10 pp | 4.1% |

**Read:** C3/C4/C5 depend on front skew exceeding back skew. Chain marks use the **last UTC-day**
5-min snapshot (continuous market, not an equity close). See `data/skew_history.csv`.

---

## 1b — Vol risk premium (IV − realised vol)

| Metric | DVOL (2023→) | Chain mid-ATM (2025-04-11→) |
|---|---|---|
| Mean VRP | 2.14 pp | 1.31 pp |
| % days VRP > 0 | 74.9% | 72.0% |

**Read:** Income-from-premium candidates need sustained positive VRP. See `data/vrp_history.csv`.

---

## 1c — Funding / carry (Deribit primary venue)

**Recommendation:** Do not model L3/carry as a core income pillar. Deribit funding collapsed after ~Mar 2026 (median ~0.01% APR). Optional opportunistic overlay at most.

| Regime | Deribit mean APR | Deribit median APR | % obs > 5% trigger |
|---|---|---|---|
| All (2024-01-01 → 2026-06-10) | 6.59% | 2.08% | 36.8% |
| **Pre Mar 2026** | 7.40% | 2.89% | 41.0% |
| **Post Mar 2026** | 0.25% | 0.0104% | 4.3% |

Binance perp (reference only — product trades on Deribit): post-Mar2026 mean APR
0.14%.

**Read:** L3 / conditional carry is **not a viable core income pillar** after Deribit's ~Mar 2026
perpetual changes (median funding ~0.01% APR). Historical pre-Mar2026 rates must not be extrapolated.
See `data/funding_deribit.csv`.

---

## 1d — Drawdown anatomy (24/7 BTC, 2019→)

| Metric | Value |
|---|---|
| Max drawdown from peak | -76.6% (2022-11-21) |
| Monthly DD median / worst | -34.8% / -76.6% |
| Quarterly DD median / worst | -44.7% / -76.6% |
| Worst daily **close-to-close** return | -39.5% |
| Worst **24h** return (hourly, ~last 2y) | -18.4% |
| Worst **1h** return (hourly, ~last 2y) | -4.9% |
| Daily range (H−L)/close median / p95 | 3.8% / 10.6% |
| % calendar days close down > 5% | 4.5% |

**Read:** Drawdowns are measured on **continuous trading** — peak-to-trough and rolling windows,
not session gaps. Sizes buffer (C2) vs hard-floor (C1/C3). See `data/drawdown_*.csv`.

---

## 1e — Live snapshot

| | |
|---|---|
| Spot | $62,284 |
| DVOL | 45.43% |

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
