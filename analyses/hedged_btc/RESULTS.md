# Hedged BTC — Research Results

**Audience:** AI agents continuing this work in CryoQuant  
**Companion doc:** [`APPROACH.md`](APPROACH.md) — plan, candidates, open questions (no results)  
**Status:** Phase 1 complete · Phase 2 v1 (fees, roll rules, C1–C4/C6) · **no candidate selected**

This file accumulates **verified findings** as research phases complete. Append new sections
per phase; do not overwrite prior conclusions without noting a revision and reason.

**Machine-readable snapshots:** `analyses/hedged_btc/data/phase1_summary.json` (latest run)  
**Reproduce Phase 1:** `python -m analyses.hedged_btc.run_phase1`

---

## Conventions

| Topic | Rule |
|---|---|
| Market hours | BTC and Deribit options trade **24/7**. No overnight gaps, weekend gaps, or equity-style EOD. |
| Chain marks | Last 5-min snapshot per **UTC calendar day** (`chain_daily_snapshot` in `_utils.py`). |
| Primary venue | **Deribit** for options, perps, spot. Binance data used for spot RV and funding **reference only**. |
| Candidate selection | Results inform comparison; **no design is chosen** until Phase 3 backtests complete. |
| Carry / L3 | **Deprioritised** post ~Mar 2026 Deribit perp changes — see §Phase 1c. |

---

## Phase 1 — Market-structure analysis

**Completed:** 2026-06-10 (revised run — 24/7 framing, paginated Deribit funding)  
**Maps to:** APPROACH.md §Research plan Phase 1 (1a–1e)  
**Artifacts:**

| File | Content |
|---|---|
| `data/skew_history.csv` | Daily front/mid/back skew and front−back spread |
| `data/vrp_history.csv` | DVOL + chain IV vs RV30 |
| `data/funding_deribit.csv` | Paginated Deribit perp funding (hourly, 2024-01→) |
| `data/funding_binance.csv` | Binance perp funding (reference) |
| `data/drawdown_daily.csv` | Daily close, drawdown, range, close-to-close returns |
| `data/drawdown_monthly.csv` | Monthly max drawdown |
| `data/live_quote_*.csv` | Point-in-time Deribit snapshot |
| `data/phase1_summary.json` | All scalar summaries |

**Data windows:**

| Dataset | Span |
|---|---|
| Deribit option chains | 2025-04-11 → 2026-06-07 (423 days) |
| Deribit funding | 2024-01-01 → 2026-06-10 (~21,399 hourly obs) |
| DVOL / chain VRP | 2023→ / chain-overlap window |
| BTC drawdowns | 2019-01-01 → 2026-06-09 (daily); hourly ~2024→ |

---

### 1a — Skew term structure

**Question:** Is front-end put skew persistently richer than back-end (supporting C3/C4/C5)?

| Metric | Value |
|---|---|
| Days analysed | 423 |
| Front skew mean (−10% put IV − +10% call IV) | **+7.33 pp** |
| Back skew mean | **+2.39 pp** |
| **Front − back spread (mean)** | **+4.89 pp** |
| Spread median / p25 / p75 | 4.50 / 2.94 / 6.74 pp |
| % days spread > 5 pp | **42.0%** |
| % days spread > 10 pp | 4.1% |

**Regime note (monthly means, front−back spread):**

| Month | Spread (pp) |
|---|---|
| 2025-11 | 4.6 |
| 2025-12 | 4.4 |
| 2026-01 | 4.7 |
| **2026-02** | **11.3** (crash month; max single-day spread ~20.7 pp) |
| 2026-03 | 7.6 |
| 2026-04 | 5.7 |
| 2026-05 | 3.7 |
| 2026-06 | 9.6 |

**Conclusion (agent):** Front>back skew is **structurally positive on average** over the chain
window. It is **not constant** — crash months widen the spread sharply (Feb 2026). C3/C4 income
financing is easier post-crash, harder in calm months. **Indicative only** (~14 months of chains).

---

### 1b — Vol risk premium (IV − realised vol)

**Question:** How often is implied vol above realised (tailwind for premium selling / C5 / L2)?

| Metric | DVOL (2023→, n=446) | Chain mid-ATM (n=354) |
|---|---|---|
| Mean VRP | **+2.14 pp** | **+1.31 pp** |
| Median VRP | +4.23 pp | +3.28 pp |
| % days VRP > 0 | **74.9%** | **72.0%** |
| % days VRP > 5 pp (DVOL) | 44.4% | — |

**Conclusion (agent):** VRP is **positive most days** but **modest on average**. Supports L2
covered calls and C5 as a **partial** hedge financier, not a full substitute for explicit
protection cost. Do not extrapolate self-financing from VRP alone.

---

### 1c — Funding / carry (L3)

**Question:** Can perp funding finance the hedge book? **Primary: Deribit** (product venue).

**Verdict:** `not_viable_core_income_post_mar2026`

| Regime | Deribit mean APR | Deribit median APR | % obs > 5% APR trigger |
|---|---|---|---|
| All (2024-01-01 → 2026-06-10) | 6.59% | 2.08% | 36.8% |
| **Pre Mar 2026** | **7.40%** | **2.89%** | **41.0%** |
| **Post Mar 2026** | **0.25%** | **0.010%** | **4.3%** |

Binance perp (reference only): post-Mar2026 mean **0.14%** APR, median **0.21%**.

**Conclusion (agent):** Deribit perp funding **collapsed after ~Mar 2026** (exchange perpetual
mechanics change). Pre-Mar2026 history **must not** be extrapolated into forward product models.
L3 / conditional carry: **optional overlay at most**; **not a core income pillar**. Income must
come from **options premium** (skew/VRP), not funding.

---

### 1d — Drawdown anatomy (24/7 BTC)

**Question:** What move sizes must floors/buffers cover? (No session-gap framing.)

| Metric | Value |
|---|---|
| Max drawdown from peak | **−76.6%** (2022-11-21) |
| Monthly DD median / p10 / worst | −34.8% / −68.2% / −76.6% |
| Quarterly DD median / p10 / worst | −44.7% / −72.0% / −76.6% |
| Worst daily close-to-close | **−39.5%** |
| Worst 24h return (hourly, ~2024→) | **−18.4%** |
| Worst 1h return (hourly, ~2024→) | **−4.9%** |
| Daily (H−L)/close median / p95 | 3.8% / 10.6% |
| % calendar days close down > 5% | 4.5% |
| % hours down > 2% (~2024→) | 0.48% |

**Conclusion (agent):**

- Losses are **sustained multi-week declines**, not discrete session gaps.
- **C2 soft buffer (~6%)** absorbs routine volatility only; **fails on crash tails**.
- **Hard floors** (C1/C3/C4) or **tail puts** (C6/C4 L4) needed if mandate is "avoid big losses."
- Fast 24h moves (−18%) matter for **mid-period MTM** on long-dated hedges before expiry (C3).

---

### 1e — Live snapshot (point-in-time)

**As of:** 2026-06-10T15:36:33 UTC

| | |
|---|---|
| BTC spot (Deribit index) | $62,284 |
| DVOL (30d) | 45.43% |

Refresh: `python -m analyses.hedged_btc.live_quote` or full Phase 1 rerun.

---

### Phase 1 — Implications per candidate (hypotheses)

| Candidate | Phase 1 read |
|---|---|
| **C1** collar+reopener | Viable floor story; expensive at ~43% IV; no skew edge |
| **C2** buffer/seagull | Cheap; drawdown data shows **inadequate for tails** |
| **C3** skew diagonal | **Supported** by persistent front−back spread; regime-dependent income |
| **C4** four-layer | Same skew support as C3; L4 tail kicker addresses drawdown tails; L3 carry **off** |
| **C5** VRP harvester | Modest VRP tailwind; thin margin; perp hedge for delta only |
| **C6** tail-only | Cheap benchmark; does not stop −10% months |
| **L3 carry** | **Deprioritise** — post-Mar2026 Deribit funding negligible |

**No candidate eliminated.** C2 and L3 weakened; C3/C4 skew thesis strengthened on average.

---

### Phase 1 — Limitations

1. Chain skew/VRP: **~14 months** — includes 2025 rally and Feb-2026 crash but short for regime claims.
2. Chain marks: daily snapshot only; no intraday roll simulation.
3. Deribit funding regime break dated **~Mar 2026**; cutoff is configurable in `carry_history.py`.
4. Hourly crash stats: ~2 years (compute); daily stats from 2019.

---

## Phase 2 — Options backtester

**Status:** v1 complete (fees + bid/ask, roll rules, C1/C2/C3/C4/C6) — **no CryoBacktester engine**  
**Reproduce:** `python -m analyses.hedged_btc.run_first_sim`  
**See:** APPROACH.md §Phase 2

### Prerequisites check (2026-06-10)

| Prerequisite | Status |
|---|---|
| Deribit option chains (`CRYOBACKTESTER_DATA_DIR`) | **OK** — 423 days, 2025-04-11 → 2026-06-07 |
| Spot in chain (`underlying_price`) | **OK** — daily snapshot |
| Phase 1 skew/VRP/drawdown | **OK** — see §Phase 1 |
| CryoBacktester **engine** | **Not required** — data-only dependency |
| CryoBacktester **repo** | Optional for 5-min replay, C5 delta-hedge, production strategies |

**Implemented (v1):**

| Module | Role |
|---|---|
| `pricing.py` | Leg selection; bid/ask entry/exit marks |
| `fees.py` | Deribit taker fee model (0.03% / 12.5% cap) |
| `book.py` | `BookSpec`, `RollPolicy`, protection + income sleeves |
| `roll_rules.py` | Calendar + ratchet + IV-gate roll decisions |
| `nav_sim.py` | Daily NAV loop, C1/C2/C3/C4/C6 specs |
| `run_first_sim.py` | Comparative runner |
| `tests/test_hedged_btc_phase2.py` | Unit tests (fees, rolls, pricing) |

**Not yet:** C5 (intraday delta-hedge approx), C4 layer attribution, C4 L3 carry overlay.

### Phase 2 v1 — implementation shortcuts (must fix before Phase 3 verdict)

The v1 sim is a **smoke test**, not a faithful C4 implementation:

| Design element | APPROACH spec | v1 sim shortcut |
|---|---|---|
| C4 L1 put spread | Long-dated ATM / −19% spread | ✓ approximated |
| C4 L2 income | 0.20–0.25δ covered calls, biweekly | **Single +10% OTM call, ~14d** |
| C4 L3 carry | Conditional perp short when funding > 5% APR | **Not implemented** (deprioritised post-Mar2026) |
| C4 L4 back-ratio | Sell −6% put / buy 2× −19% puts, separate tenor logic | **Same expiry as L1; legs net at −19% strike** |
| L4 overlap trap | L4 short must be ≤ L1 lower strike | **Violated** — −6% short sits inside L1 buffer band |
| Evaluation | Daily path vs BTC curve by regime | **Initially only start→end totals (wrong)** |

**Revision:** Prior agent conclusion naming C3 the “winner” from endpoint returns alone was
**premature and misleading**. Correct evaluation requires the **daily equity curve** segmented
by BTC regime. See §Regime analysis below and `report.py`.

### Phase 2 v1 — full-window summary (2025-04-11 → 2026-06-07)

**Method:** `NAV = (spot + option_mtm_bid_ask + cash_premiums) / spot₀`; Deribit fees; daily marks.  
**Reproduce:** `python -m analyses.hedged_btc.run_first_sim` (includes regime report)

| Candidate | Return | BTC B&H | Max DD | BTC DD | Rolls | Fees |
|---|---|---|---|---|---|---|
| C3_diagonal | +1.4% | −24.3% | −24.2% | −51.4% | 64 | $2,717 |
| C4_four_layer | −11.5% | −24.3% | −38.4% | −51.4% | 34 | $2,287 |
| C6_tail | −25.9% | −24.3% | −49.5% | −51.4% | 7 | $308 |
| C2_buffer | −27.2% | −24.3% | −40.3% | −51.4% | 14 | $1,958 |
| C1_collar | −34.3% | −24.3% | −42.6% | −51.4% | 9 | $1,315 |

**Artifacts:** `data/nav_*.csv`, `data/phase2_sim.json`, `data/phase2_regime_report.json`

### Phase 2 v1 — regime analysis (daily path, not endpoint-only)

BTC path in the chain window is **bimodal**: strong rally Apr→Sep 2025, then sustained
decline Oct 2025→Jun 2026. Full-window endpoint ranking **hides** this.

#### Early rally — 2025-04-11 → 2025-09-30 (BTC **+37.4%**)

| Candidate | NAV return | Excess vs BTC | Max DD | Upside capture |
|---|---|---|---|---|
| **C6_tail** | +30.5% | −6.9 pp | −12.9% | **0.93** |
| **C4_four_layer** | +29.7% | −7.7 pp | −11.6% | **0.75** |
| C3_diagonal | +21.6% | −15.8 pp | −10.0% | 0.57 |
| C2_buffer | +8.8% | −28.6 pp | −9.5% | 0.50 |
| C1_collar | −9.0% | −46.4 pp | −22.4% | 0.49 |

**Read:** C4 **tracked the bull leg** (≈80% of BTC gain, shallow DD). C3 **gave up 16 pp**
vs BTC — short-call income sleeve caps rallies. C1 **lost money** in a +37% BTC rally.

#### Oct decline — 2025-10-01 → 2026-06-07 (BTC **−46.8%**)

| Candidate | NAV return | Excess vs BTC | Max DD | Upside capture |
|---|---|---|---|---|
| **C3_diagonal** | −18.5% | **+28.4 pp** | −22.2% | 0.24 |
| C1_collar | −29.4% | +17.4 pp | −32.3% | 0.32 |
| **C4_four_layer** | −33.7% | **+13.1 pp** | −38.0% | 0.51 |
| C2_buffer | −34.5% | +12.4 pp | −40.3% | 0.67 |
| C6_tail | −45.2% | +1.7 pp | −49.1% | 0.75 |

**Read:** C3 **dominates the bear leg** (hard quarterly put + front-call income). C4 still
**beats BTC by 13 pp** on the decline with less extreme upside cap than C3. C6 ≈ unhedged.

#### Feb 2026 crash month (BTC **−13.3%**)

| Candidate | NAV return | Excess vs BTC |
|---|---|---|
| C3_diagonal | +0.8% | +14.1 pp |
| C1_collar | −1.1% | +12.1 pp |
| C4_four_layer | −6.2% | +7.1 pp |
| C6_tail | −5.8% | +7.5 pp |

**Read:** C4 convexity layer did **not** show anti-fragile outperformance in v1 sim (L4
overlap/strike bugs likely). C3 shines in crash months; C4 is middling.

#### C4 monthly excess vs BTC (selected months)

| Month | C4 excess (pp) | C3 excess (pp) | BTC month |
|---|---|---|---|
| 2025-05 (rally) | −0.2 | −6.6 | +11.1% |
| 2025-07 (rally) | −5.5 | −2.3 | +8.1% |
| 2025-11 (decline) | +5.0 | +8.4 | −17.6% |
| 2026-02 (crash) | +7.9 | +16.1 | −14.9% |
| 2026-06 (decline) | +6.7 | +12.0 | −14.3% |

### Phase 2 v1 — revised conclusion (agent)

1. **Do not crown a winner from start/end totals.** C3’s +1.4% full-window return is
   almost entirely the Oct→Jun bear leg (+28 pp excess); it **sacrificed 16 pp** in the rally.
2. **C4 is the balanced candidate on paper** — best rally participation among hedged designs
   (after C6 control), meaningful bear-leg protection (+13 pp), matches the product brief
   (core hedge + income + convexity). v1 sim **under-represents** C4 due to L2/L4/L3 shortcuts.
3. **Next engineering priority:** fix C4 book spec (separate L4 tenor, resolve overlap trap,
   delta-targeted L2), then re-run regime report before Phase 3 sign-off.
4. C5 still absent; C6 remains the unhedged upside benchmark.

**v1 limitations:** daily marks; roll-driven expiry (no settlement); full-window capture ratios
are meaningless when regimes oppose; C4 not faithfully implemented.

---

## Phase 2 — C7 USD participation book (2026-06-10)

**Concept:** Hold USD (stables), buy calls for upside only — no long BTC, no protective puts.
Optional income: cash-secured short puts (−12% OTM, 0.25× qty), **cash-settled** at expiry.
**Benchmark:** BTCUSD buy-and-hold. **Call budget:** 2% of NAV per monthly roll.

**Reproduce:** `python -m analyses.hedged_btc.run_c7_sim`

### Full window (2025-04-11 → 2026-06-07)

| Variant | Return | BTC | Excess | Max DD | Fees |
|---|---|---|---|---|---|
| **C7_spread** (ATM/+15% CS) | **−5.5%** | −24.3% | **+18.8 pp** | **−11.1%** | $1,462 |
| C7_atm | −6.5% | −24.3% | +17.8 pp | −12.1% | $768 |
| C7_spread_csp | −7.7% | −24.3% | +16.7 pp | −14.2% | $2,163 |
| C7_atm_csp | −8.7% | −24.3% | +15.6 pp | −15.1% | $1,469 |
| C7_otm (+5%) | −8.6% | −24.3% | +15.7 pp | −14.5% | $757 |
| C7_otm_csp | −10.8% | −24.3% | +13.5 pp | −17.4% | $1,459 |

**Artifacts:** `data/phase2_c7_sim.json`, `data/phase2_c7_regime_report.json`, `data/nav_C7_*.csv`

### Regime analysis

| Regime | BTC | Best C7 | C7 excess | C4 excess | Read |
|---|---|---|---|---|---|
| Early rally | +37.4% | C7_spread +1.6% | **−35.8 pp** | −7.7 pp | Fails upside mandate — ~15% capture |
| Oct decline | −46.8% | C7_spread −7.7% | **+39.1 pp** | +13.1 pp | **Dominates** all spot-based hedges |
| Feb crash | −13.3% | C7_spread −0.6% | **+12.7 pp** | +7.1 pp | Cash floor works; CSP slightly worse |
| Full window | −24.3% | C7_spread −5.5% | **+18.8 pp** | +12.8 pp | Beats BTC and C4 on excess return |

### Conclusion (agent)

1. **C7 beats BTC on the full path** (+19 pp excess, −11% max DD vs BTC −51%) — but by **not participating in rallies**, not by matching them.
2. **CSP income hurts** in this window: short puts lose in Oct decline despite premium collected; calls-only variants outperform +CSP pairs.
3. **Call spread > ATM > OTM** on cost efficiency (lower bleed, similar rally participation).
4. **Different product line** from C4: USD-stable with optional BTC convexity; not a substitute if mandate is ~1:1 rally participation.
5. **C7_spread** is the best variant in v1; add to CryoBacktester specs as `hedged_btc_c7`.

---

## Phase 3 — Comparative backtest (C1–C6)

**Status:** Not started  
**See:** APPROACH.md §Phase 3

*No results yet.*

---

## Phase 4 — Optimization of surviving candidate(s)

**Status:** Not started  

*No results yet.*

---

## Revision log

| Date | Change |
|---|---|
| 2026-06-10 | Initial RESULTS.md — Phase 1 complete (revised: 24/7 framing, Deribit funding regimes) |
| 2026-06-10 | Phase 2 v0 — daily NAV sim in CryoQuant; first results C6/C2 smoke test |
| 2026-06-10 | Phase 2 v1 — fees, bid/ask, roll_rules, C1–C4/C6 comparative sim |
| 2026-06-10 | Phase 2 regime report — retracted C3 “winner”; C4 rally/bear path analysis |
| 2026-06-10 | C7 USD participation sim — 6 variants, regime vs C4/C6 |
