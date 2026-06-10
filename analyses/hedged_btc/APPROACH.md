# Hedged BTC — Agent Brief (v3)

**Created:** 2026-06-10 · **Revised:** 2026-06-10 17:25 CET  
**Status:** Ideation → comparative analysis phase. **No design has been selected.**  
**Audience:** AI agents and quant developers continuing this work in CryoQuant  
**Results (findings):** [`RESULTS.md`](RESULTS.md) — updated as each research phase completes

---

## Objective

Research a **fund-style product** (NAV-based, pro-rata investor flows) that **beats the BTCUSD
equity curve**:

- **~1:1 participation in up moves**
- **Materially limited down moves** (avoid big losses; bounded drawdowns)
- Evaluation on **equity curves vs buy-and-hold BTCUSD**: upside capture, downside capture,
  max drawdown, cost drag per regime — not single-expiry payoff diagrams.

**Universe:** everything on Deribit — options, dated futures, perps, spot. Perps/futures may be
used for delta-hedging and leverage inside structures.

**Product shape (common to all candidates):**

- A **core protective structure**, entered repeatedly (weekly/monthly/quarterly) and rolled
  by smart rules — hedges the downside.
- An **income component** that (partially) finances the protection.
- Optionally further layers (carry, convexity, etc.).

**Next step is NOT a trading system.** It is (1) further analysis inside the CryoQuant
framework, then (2) an options backtester that compares all candidates on common data.

**Explicitly rejected directions:**

- Trend-following / momentum delta overlays as the hedge (too speculative)
- Naked short puts / short strangles on the full book (mandate-inverting)
- Funding cash-and-carry as a **core income pillar** (Deribit perp funding collapsed post ~Mar 2026;
  median ~0.01% APR — see [`RESULTS.md`](RESULTS.md) §Phase 1c)
- Designing around investor gates — pro-rata NAV means gates don't constrain structures

**Source conversations:** [Claude share — collar ideation](https://claude.ai/share/b89b23bd-d961-4ccc-826d-27166e79057b),
plus live-data ideation in this repo's chat history (2026-06-10).

---

## Live market snapshot (2026-06-10, ~15:15 UTC — re-verify before relying on it)

| Metric | Value |
|---|---|
| BTC index | ~$61,950 (mid-drawdown: −24% over 30d from $81.7k) |
| ATM IV | ~43.5%, flat across tenors |
| DVOL (30d implied) | 45.5% |
| Realized vol 30/60/90d | 39.9% / 38.6% / 39.0% → **VRP +3.6 to +5.6 pts** |
| Put skew (−10% vs +10% strikes) | 2d: **+21pp** · 16d: **+15pp** · 51d: +7pp · 107d: **+4.3pp** |
| Deribit perp funding (post-Mar2026) | **~0.01% APR median** (regime break; not viable as core income) |
| Dated futures basis | +2.1% → +3.9% APR contango (Jun→Mar27) |
| Option bid/ask at liquid strikes | 2–5% of mark (execution viable) |

**Two structural observations that all candidates can exploit:**

1. **Skew term-structure spread** — front-end downside protection trades 3–5x richer (in skew
   points) than back-end. Buying protection long-dated and selling optionality short-dated
   captures this spread. *Caveat: this is today's regime (post-Feb-2026-crash memory); it must
   be verified historically before any design depends on it.*
2. **Modest positive VRP** (+4–6 pts) — systematic premium selling has tailwind, but not a large
   one; income projections should be conservative.

---

## Candidate designs

All leg prices verified live 2026-06-10. Each candidate is a complete product; the backtester
compares them on identical data.

### C1 — Rolling collar + call-spread reopener *(origin: source conversation)*

```
Long spot + long ~ATM put (quarterly) + short OTM call + long further-OTM call
```

| Live cost | Floor | Upside |
|---|---|---|
| ~7.1% / quarter (Sep tenor: 62kP / −70kC / +75kC) | Hard at ~spot | Dead zone +13%…+21%, full above |

**Pros:** hard floor; simplest investor story; single-tenor book (easy ops/NAV); income embedded
(short call) rather than a separate engine.
**Cons:** expensive at current IV (~2.4%/month); dead zone gives up a popular rally band; rolls
buy ATM vol every quarter regardless of regime; pays the skew rather than harvesting it.
**Backtest questions:** realized drag across 2025-04→now incl. Feb-2026 crash; ratchet rules vs
fixed strikes; reopener width optimization.

### C2 — Buffer book: put spread + short call ("seagull")

```
Long spot + long put spread (e.g. ATM/−10%) + short OTM call, monthly or quarterly
```

| Live cost | Floor | Upside |
|---|---|---|
| **0.66–0.80% / 51d** (62/58PS−70C or 62/56PS−68C) | Soft: buffer covers first ~6–10% only | Capped +10…13% per period |

**Pros:** near-zero cost — cheapest honest structure on the board; buffer-ETF analogy is easy to
market; defined risk everywhere.
**Cons:** **not crash protection** — verified stress: −30% BTC → −24% book; upside cap binds in
every strong rally; "hedged" label is generous (manage expectations).
**Backtest questions:** how often does the buffer fully absorb monthly losses historically?
distribution of cap exceedances; monthly vs quarterly tenor.

### C3 — Skew diagonal: long-dated put financed by short-dated calls

```
Long spot + long quarterly+ ATM put + systematically sell 1–2 week OTM calls against spot
```

| Live cost | Floor | Upside |
|---|---|---|
| Put ~2.5%/30d (Sep ATM) minus call income ~1.3–2%/30d → **net ~0.4–1%/month** | Hard at put strike (quarterly) | Capped at short call strike (~+7%) between rolls, then reset |

**Pros:** directly harvests the skew term-structure spread; hard floor retained; cheap;
short legs expire fast (flexible).
**Cons:** mid-period drawdown risk before expiry (put delta ~−0.45, so a fast selloff is only
  ~half-hedged mark-to-market); rolling short calls systematically sell every rally's first +7%;
income is regime-dependent (front vol can deflate).
**Backtest questions:** realized call-away cost vs collected premium across regimes; floor
ratchet rules; whether put spread (vs ATM put) improves net drag.

### C4 — Four-layer book *(synthesis candidate)*

```
L1 long-dated put spread (e.g. Dec 62/50k, ~1.1%/30d, buffer to −19%)
L2 income: covered calls 0.20–0.25δ weekly/biweekly (+ optional capped perp-delta-hedged strangle)
L3 conditional carry: short perp/futures slice when funding > ~5% APR (dormant today)
L4 convexity kicker: long-dated put back-ratio (sell 1x −6% put, buy 2x −19% puts) — entered at
   ~zero cost or credit (live Sep: +$427 credit); pays off big below ~−32%
```

Verified combined stress (L1+L4, before L2 income): **+11 to +19pp vs BTC at −32%/−40%**, −4.8pp
flat drag, ≈ 0 net drag after L2 income at current vol.

**Pros:** each layer has one job; anti-fragile in crashes (L4); approximately self-financing at
current surface; carry layer self-activates in bulls.
**Cons:** most complex book (4 tenors, ~7 legs); more roll decisions = more parameter risk and
more ways to overfit; L4 has a **strike-overlap trap** (verified: L4 short strike inside L1's
protected band creates a pain pocket at −19…−25% — rule: L4 short ≤ L1 lower strike); NAV
marking of long-dated wings needs care with wide quotes.
**Backtest questions:** does complexity beat C3 net of fees? layer attribution per regime;
sensitivity to L4 credit availability (does it survive at Dec/Mar tenor? unverified).

### C5 — Protected core + VRP harvester

```
Long spot + long-dated put spread + income from delta-hedged short front straddle/strangle
(delta-hedged with perps to δ≈0, strictly capped sleeve)
```

Live: 9d 58P/66C strangle = 1.48% credit at net δ −0.03.

**Pros:** income source independent of call-aways (keeps upside fully open — no short calls on
the core); cleanest expression of "VRP pays for the hedge"; perps used productively (delta hedge).
**Cons:** short gamma — the income engine loses exactly when the hedge pays (crash), partially
canceling protection unless sleeve is small; operationally heaviest (continuous delta-hedging);
VRP is only +4–6pts today — thin margin after fees.
**Backtest questions:** sleeve size where crash-correlation stays acceptable; net income after
realistic hedging slippage; daily-data limitation (delta-hedge sim needs intraday assumptions —
flag as approximation).

### C7 — USD participation book *(new — 2026-06-10)*

```
USD cash (stables) + monthly long calls (budget = fixed % NAV) + optional CSP income
```

No long BTC. No protective puts. Downside = premium bleed + CSP cash-settlement losses.
Benchmark still BTCUSD buy-and-hold.

| Live design | Floor | Upside |
|---|---|---|
| 2%/month call budget; ATM, +5% OTM, or ATM/+15% spread | Cash floor (no −50% BTC DD) | Capped by budget — ~15% rally capture in v1 sim |
| Optional: short −12% puts (0.25×) for income | CSP tail paid from cash | Hurts in decline (v1 finding) |

**Pros:** massive bear-leg outperformance (+39 pp vs BTC Oct decline); shallow max DD (−11%);
  simple investor story for USD holders wanting BTC upside optionality.
**Cons:** **fails rally mandate** (−36 pp vs BTC in Apr–Sep 2025); buying vol is a headwind
  (positive VRP); CSP income did not help in v1. Different product than C4, not a drop-in replacement.
**Phase 2 results:** [`RESULTS.md`](RESULTS.md) §C7 — `python -m analyses.hedged_btc.run_c7_sim`

### C6 — Pure tail-risk overlay (minimalist benchmark)

```
Long spot + far-OTM long-dated puts only (e.g. −20…−30% strikes), ~0.5–1%/quarter budget,
no income engine
```

**Pros:** maximal upside (nothing sold); minimal complexity; cheap insurance against
catastrophe; useful as the **control candidate** in backtests.
**Cons:** investors still eat every −5…−15% drawdown; mark-to-market bleed in calm markets;
"hedged" only against disasters.
**Backtest questions:** exact budget for surviving a −30% fast drawdown; how much does it drag in
2025-04→now window?

### Cross-cutting module — conditional carry (deprioritised)

Short perp/future against a spot slice when funding is rich. **Phase 1 finding:** Deribit BTC
perp funding averaged ~7% APR pre-Mar2026 but **collapsed to ~0.25% mean / ~0.01% median APR
post-Mar2026** after exchange perpetual changes. Not viable as a core book layer; at most an
opportunistic flag in the backtester if funding regimes revert. Product trades on Deribit — do
not extrapolate Binance funding history.

---

## Comparison matrix (live-priced, pre-backtest hypotheses)

| | C1 collar+reopen | C2 buffer | C3 diagonal | C4 four-layer | C5 VRP-financed | C6 tail-only |
|---|---|---|---|---|---|---|
| Net cost/month (today) | ~2.4% | **~0.4%** | ~0.4–1% | **≈ 0%** | ~0.5–1.5% | ~0.2–0.3% |
| Floor quality | Hard | First ~6–10% only | Hard (MTM risk mid-period) | Hard + crash kicker | Hard (sleeve-degraded) | Crash-only |
| Upside retention | Dead zone, then full | Capped/period | Capped +7% between rolls | Mostly full (call-aways) | **Full** | **Full** |
| Crash (−30%+) behavior | Floor holds | **Fails** (−24%) | Floor holds at expiry | **Anti-fragile** (+11–19pp) | Floor minus sleeve losses | Strong |
| Complexity (legs/tenors) | 3/1 | 3/1 | 2/2 | ~7/4 | 3+hedging/2 | 1/1 |
| Overfit/parameter risk | Low | Low | Medium | **High** | Medium | **Lowest** |
| Key dependency | IV level | No big crash | Skew spread persists | Skew spread + L4 credit | VRP persists | Nothing |

**Hypothesis ranking (to be tested, not assumed):** C3 and C4 look best on paper *because* the
current skew term structure favors them — which is exactly why their historical robustness is
the top research question. C2 and C6 are the cheap honest benchmarks every fancier design must
beat. C1 is the baseline from the source conversation. C5 is the most operationally demanding.

---

## Where each approach pays (no-free-lunch table)

| Cost center | Candidates exposed |
|---|---|
| Explicit premium bleed (calm/grind-up markets) | C1, C6, (C4 small) |
| Upside give-up / call-aways (vertical rallies) | C2, C3, (C4 via L2) |
| Fast drawdown before hedge expiry (24/7 market) | C3, C5; C2 catastrophically |
| Short-gamma losses in crashes | C5; C4's optional strangle sleeve |
| Complexity/overfit risk | C4 > C5 > C3 > others |
| Regime dependency (skew/VRP normalizing) | C3, C4, C5 |

A grinding bull is the common worst regime for all hedged designs: quantifying each candidate's
drag there is a primary backtest deliverable.

---

## Research plan (CryoQuant-first, then options backtester)

### Phase 1 — Market-structure analysis in CryoQuant *(no backtester yet)* — **DONE**

Goal: validate the structural assumptions the candidates depend on.  
**Results:** [`RESULTS.md`](RESULTS.md) §Phase 1

```
[ ] 1a. Skew history: from local Deribit daily chains (2025-04-11 → present), reconstruct
        daily skew term structure (−10%/+10% IV spread per tenor bucket).
        → Is today's front>back skew spread persistent or post-crash artifact?
[ ] 1b. VRP history: DVOL (Deribit API) or chain-implied ATM IV vs realized vol from
        loader.load() 1h/1d bars. → How often is VRP positive? Distribution?
[ ] 1c. Funding/basis history: binance_perp.fetch_funding (exists) + Deribit perp funding +
        dated futures basis fetcher. → How often would the carry module trigger since 2023?
[ ] 1d. Drawdown anatomy: BTC daily since 2019 (loader) — distribution of monthly/quarterly
        drawdowns, 24h/1h move distribution, sustained decline anatomy. → Sizes buffer/floor/tenor.
[ ] 1e. live_quote.py — repeatable snapshot tool: index, DVOL, ATM IV term structure, skew,
        candidate leg prices. Run at analysis time, store CSV in analyses/hedged_btc/data/.
```

Tools: `cryoquant.data.loader`, `cryoquant.data.sources.deribit_options`,
`cryoquant.features.primitives` (realised_vol), `SpotFeatures.rv_rank`. New code stays in
`analyses/hedged_btc/`.

### Phase 2 — Options backtester (multi-leg NAV simulator) — **v1 DONE**

CryoBacktester **data** is required (`CRYOBACKTESTER_DATA_DIR`); the CryoBacktester **engine**
is not — v0 daily NAV sim runs in `analyses/hedged_btc/`. See [`RESULTS.md`](RESULTS.md) §Phase 2.

The existing `option_lookup.evaluate()` is single-fire/single-straddle; candidates need a
**book-level daily NAV simulator**:

```
[x] 2a. pricing.py — chain snapshot + leg spec → entry/exit marks (bid/ask + mark fallback)
[x] 2b. book.py — protection + income sleeves, RollPolicy
[x] 2c. roll_rules.py — calendar + ratchet + IV-gate rules
[x] 2d. nav_sim.py — daily loop: mark book, apply rolls, Deribit fees; C1/C2/C3/C4/C6
[x] 2e. report.py — regime-segmented daily path analysis (rally / Oct-decline / monthly)
[ ] 2e+. C4 faithful implementation + layer attribution before Phase 3 verdict
[x] 2f. Unit tests — tests/test_hedged_btc_phase2.py
```

Constraints: daily chain snapshots only (intraday roll precision out of scope; C5's delta-hedge
sim needs explicit approximation assumptions); window 2025-04-11 → present (~14 months,
includes Feb-2026 crash and the 2025 rally — both key regimes, but short; flag overfit risk).

### Phase 3 — Comparative backtest (CryoBacktester)

**Strategy specs (implementation handoff):** [`CRYOBACKTESTER_STRATEGY_SPECS.md`](CRYOBACKTESTER_STRATEGY_SPECS.md)

```
[ ] Implement hedged_btc_c4, c3, c5, c6 in CryoBacktester (see specs)
[ ] All candidates on identical window, identical fee model, 5-min ticks
[ ] Deliverables per candidate: equity curve, capture ratios, max DD, monthly drag by regime,
    cost attribution (protection vs income vs fees)
[ ] Sensitivity: ±1 strike step, ±1 tenor step per candidate (cheap robustness check)
[ ] Honest n_trials accounting for deflated metrics
```

### Phase 4 — Decision + deeper optimization of surviving candidate(s)

Parameter sweeps only for candidates that survive Phase 3 on robustness, not just point
estimates. Then consider promotion to `cryoquant/backtest/` + `scripts/`.

**Rules for agents:**

- Phases 1–2 may proceed autonomously (analysis-dir code + tests only).
- Phase 3+ requires presenting results and getting user sign-off between steps.
- Re-verify all live prices before relying on the snapshot above.
- Never commit generated artifacts; never copy CryoBacktester data into the repo.

---

## Open questions

1. **Data depth:** 14 months of daily chains is thin for regime conclusions. Extend via external
   IV history (e.g. exchange exports, vendor data) or accept and caveat?
2. **L4 credit robustness (C4):** does the put back-ratio credit survive at Dec/Mar tenors and
   in low-skew regimes? (Unverified beyond Sep.)
3. **Floor semantics for investors:** hard floor at all times (C1/C3/C4) vs buffer (C2) vs
   crash-only (C6) — product decision that filters candidates before Phase 3.
4. **Call-away tolerance:** if giving up rally chunks is unacceptable, C2/C3 weaken and C5/C6
   strengthen — second product decision.
5. **Inverse settlement accounting:** BTC-settled options → USD NAV conversion convention at
   every mark.
6. **Fee model:** Deribit options 0.03% of underlying capped at 12.5% of premium per leg
   (cf. `reference/long_tradable_options/`); futures/perp taker ~0.05%. Confirm current schedule.
7. **Minimum viable AUM** given 0.1 BTC option granularity across multi-leg books.

---

## CryoQuant integration map

| Need | Exists | Notes |
|---|---|---|
| BTC spot/perp OHLCV | `cryoquant.data.loader.load()` | 2019 → present |
| Funding history (Binance) | `binance_perp.fetch_funding` | Deribit funding fetcher to add |
| Deribit daily chains | `deribit_options` + `CRYOBACKTESTER_DATA_DIR` | 2025-04-11 → present |
| Leg selection | `option_lookup._best_leg` | Reuse in pricing.py |
| Realized vol / vol regime | `features.primitives.realised_vol`, `SpotFeatures` | For VRP + income gates |
| Robustness | `backtest.robustness` | Adapt DSR for NAV series |
| Reports | `backtest.reports` | New template for book NAV later |
| Multi-leg book NAV sim | **missing** | Phase 2 core deliverable |

---

## Summary for the next agent

Six candidate hedged-BTC designs (C1 collar+reopener, C2 buffer/seagull, C3 skew diagonal,
C4 four-layer book, C5 VRP-financed, C6 tail-only control), all live-priced 2026-06-10, none
selected. Two structural edges identified (front/back skew spread, modest VRP) that C3/C4/C5
depend on and that **must be validated historically first**.

**Next task: Phase 1 (market-structure analysis in CryoQuant)** — skew history from local
chains, VRP history, funding/basis history, drawdown anatomy, and `live_quote.py`. Then Phase 2:
build the multi-leg NAV backtester. Phase 3 compares all candidates on identical data and decides.
