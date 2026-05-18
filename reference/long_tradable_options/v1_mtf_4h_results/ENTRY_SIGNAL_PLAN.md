# Entry Signal Discovery Plan

**Goal:** Find at-entry conditions that predict whether a tight-spread, DTE 3–5, directional long BTC option will be tradeable (hit +20% gross gain net of fees).

**Core advantage:** We already have 26,354 labelled candidate entries (`tradeable=True/False`). This is a supervised discovery problem — we test features against known outcomes, not against a backtest.

**Key constraint:** Only use information available AT or BEFORE the entry timestamp.

---

## Context: Why previous experiments failed

- Tested 1DTE straddles with intraday trend/breakout indicators
- Failed due to: double spread cost (both legs), brutal theta at 1DTE, winners couldn't recover combined entry cost
- **Conclusion:** Option structure was wrong, indicators were not validated on the right structure
- **Do not assume indicators are broken** — test them on the new structure (DTE 3–5, single directional leg, tight spread) before discarding

---

## What we already know (from scripts 01–06)

| Feature | Effect | Status |
|---------|--------|--------|
| `spread_pct ≤ 10%` | 68.2% base rate (vs 41.7% for widest) | **Hard filter — always apply** |
| DTE 3–5 | 61–68% base rate, 6–11h hold | Prefer over DTE 1–2 |
| delta ≥ 0.25 | 63–69% base rate, >$80 median PnL | Prefer over 0.10–0.15 |
| 12:00 UTC entry | 63.6% base rate, 3.2h hold | Soft preference |
| Sunday entry | 66.3% base rate | Soft preference |
| HV/IV ratio | No monotonic effect | **Discard** |
| IV percentile | No monotonic effect | **Discard** |
| 30-min accel (aligned, >1%) | 89.9% calls / 18.0% puts | Real but rare (<1% of entries) |

**Open gap:** We have 4h prior momentum for tradeable trades but NOT for all candidates. We can't compute base rate by 4h momentum without enriching `candidates_summary`.

---

## Phase 0 — Close the 4h momentum gap
**Status: Not started**

### What to build
Script: `07_candidates_momentum.py`

Enrich `candidates_summary.parquet` with the same spot context as script 02:
- `spot_30m_chg_pct` — 30-min change before entry
- `spot_1h_chg_pct` — 1h change before entry
- `spot_4h_chg_pct` — 4h change before entry
- `spot_24h_chg_pct` — 24h change before entry

### What to measure
For **calls and puts separately**, in **tight-spread subset only** (`spread_pct ≤ 10%` — requires joining with script 06 output or recomputing):
- Base rate by `spot_4h_chg_pct` momentum bucket
- Base rate by `spot_1h_chg_pct` momentum bucket
- Daily opportunity count per bucket (how often does this condition fire?)
- Combined: `spread ≤ 10% AND aligned 4h momentum > X%` → base rate + frequency

### Decision gate
| Outcome | Action |
|---------|--------|
| 4h aligned momentum shows 68%+ base rate AND fires ≥1×/day | **We have a strategy kernel. Build it.** |
| Signal exists but fires < 0.5×/day | Useful filter but too rare alone — continue to Phase 1 |
| Base rate flat across momentum buckets | Momentum doesn't add edge beyond spread — continue to Phase 1 |

---

## Phase 1 — Characterise pre-entry spot behaviour
**Status: Not started | Only run if Phase 0 doesn't give a complete answer**

### What to build
Script: `08_pre_entry_behaviour.py`

For tight-spread call candidates (tradeable=1 vs tradeable=0):
- **Average spot path** normalised to entry price: plot mean ± 1σ trajectory in the 12h before entry for tradeable vs non-tradeable
- **Return distributions**: KDE plots of 1h, 4h, 12h, 24h prior returns, split by tradeable label
- **Range compression**: compute `(12h high − 12h low) / ATR20` at entry, compare distributions
- **Position in range**: where is spot within its 12h high/low range at entry?

Repeat for puts (with inverted momentum sign).

### Decision gate
| What the chart shows | Implication |
|---|---|
| Tradeable calls preceded by rising spot | Build a momentum/trend indicator (Phase 2a) |
| Tradeable calls preceded by tight range / low HV | Build a vol squeeze indicator (Phase 2b) |
| Tradeable calls at range extremes | Build a range-position indicator (Phase 2c) |
| No visual separation between groups | OHLC signals don't add edge — stop here, accept that spread/DTE/delta is the full edge |

---

## Phase 2 — Test candidate features
**Status: Not started | Only run if Phase 1 shows clear patterns**

### What to build
Script: `09_feature_test.py`

Based on Phase 1 findings, pick 2–3 candidate features. For each:
- Compute value at every entry in tight-spread candidates
- Measure AUC (ROC) vs tradeable label, **separately for calls and puts**
- Compute base rate by feature quartile
- Compute daily opportunity count when feature is in "best" quartile

Features to test (selected based on Phase 1 outcome):

**2a — Momentum/trend features** (if Phase 1 shows pre-entry rise for calls):
- `ema_slope_4h`: sign and magnitude of 4h EMA slope at entry
- `pct_above_ma_20`: spot vs 20-period MA (15-min bars)
- `trend_consistency_4h`: fraction of 15-min bars above prior bar in last 4h

**2b — Volatility squeeze features** (if Phase 1 shows consolidation before winning entries):
- `hv4_hv48_ratio`: 4h realised vol / 48h realised vol (< 0.7 = coiling)
- `bb_width_pct`: Bollinger Band width as % of mid (12h, 2σ)
- `atr_ratio`: ATR4 / ATR48

**2c — Range position features** (if Phase 1 shows entries near range extremes):
- `pos_in_12h_range`: (spot − 12h low) / (12h high − 12h low) — 0=bottom, 1=top
- `dist_from_12h_high_pct`: % below 12h high
- `range_break`: bool, spot within 0.3% of 12h high (call) or 12h low (put)

### Decision gate
Keep only features with AUC > 0.55. Below that is noise.

---

## Phase 3 — Test existing pineforge indicators
**Status: Not started | Run in parallel or after Phase 2**

### Approach
For each existing indicator in the pineforge registry, compute its state/value at each entry timestamp. Ask: "when this indicator is in state X, what fraction of tight-spread candidates are tradeable?"

**Do NOT run a new backtest.** Test the indicator signal against the labelled entry dataset directly.

Indicators to test:
- `market_wildness` / `market_wildness_v2` — vol regime at entry
- `supertrend_longcall_trigger` — already directional, test state vs tradeable label
- `daily_regime_overlay` — regime state at entry
- Other candidates in `pine/candidates/`

### Decision gate
If any existing indicator shows AUC > 0.55 in the tight-spread subset → it has latent predictive value on the correct option structure. Build a combined rule with spread filter.

---

## Guiding principles

1. **Supervised first.** Always measure feature predictive power against the labelled dataset before building anything in pineforge or Pine.
2. **Tight-spread universe only.** All signal tests should use `spread_pct ≤ 10%` as a pre-filter. A signal in the full pool that disappears in the tight-spread pool is irrelevant.
3. **Calls and puts separately.** Combining them cancels directional signals.
4. **Frequency is as important as base rate.** A 90% base rate that fires 3 times per month is not a strategy.
5. **Stop early if the data says stop.** If Phase 0 gives a complete answer, skip the rest. If Phase 1 shows no pattern, accept that spread/DTE/delta is the full edge and don't fish further.

---

## Progress tracker

- [x] Phase 0 — `07_candidates_momentum.py` — **COMPLETE. Decision gate PASSED.**
- [ ] Phase 1 — `08_pre_entry_behaviour.py` — visual characterisation of pre-entry spot
- [ ] Phase 2 — `09_feature_test.py` — compute and rank candidate features
- [ ] Phase 3 — `10_pineforge_indicators.py` — test existing indicators against labelled entries

---

## Phase 0 Results (07_candidates_momentum.py)

**Tight-spread overall base rate: 67.2%** (spread filter alone = +9pp vs 58.2% overall)

### 4h momentum — calls
| Bucket | Base rate | n |
|--------|-----------|---|
| < −3%  | **89.2%** | 74 |
| −3 to −1.5% | 61.1% | 247 |
| −1.5 to −0.5% | 64.2% | 823 |
| ±0.5% | 67.9% | 2193 |
| +0.5 to +1.5% | 69.1% | 861 |
| **+1.5 to +3%** | **85.3%** | 279 |
| > +3% | 73.0% | 37 |

### 4h momentum — puts
| Bucket | Base rate | n |
|--------|-----------|---|
| **< −3%** | **97.3%** | 111 |
| −3 to −1.5% | 69.4% | 317 |
| −1.5 to −0.5% | 71.5% | 1127 |
| ±0.5% | 65.2% | 2952 |
| +0.5 to +1.5% | 67.1% | 1200 |
| +1.5 to +3% | **47.6%** | 393 |
| > +3% | **48.3%** | 58 |

### 1h momentum — puts (strong signal)
- −1.5 to −0.5%: **80.9%** (n=619, large robust sample)
- −3 to −1.5%: **82.1%** (n=67)
- +0.5 to +1.5%: 55.5% — penalised buying against 1h momentum

### Combined filter (spread ≤ 10% + aligned 4h momentum)
| Threshold | Base rate | Windows/day |
|-----------|-----------|-------------|
| ≥ 0.3%   | 72.5%     | 3.9         |
| ≥ 0.5%   | 73.0%     | 2.9         |
| **≥ 1.0%**   | **74.6%** | **1.4**  |
| ≥ 1.5%   | 79.7%     | 0.7         |
| ≥ 2.0%   | 81.5%     | 0.4         |
| ≥ 3.0%   | 91.2%     | 0.1         |

**Decision gate: PASSED at ≥0.5%** (73% base rate, 2.9 windows/day)

**Strategy kernel:**
> Buy a tight-spread (≤10%), DTE 3–5, delta 0.25–0.40 option in the direction of the prior 4h BTC move, when that move is ≥ 0.5–1.0%.

### Key patterns to explain / explore further
1. **IV expansion in crashes:** calls after <−3% 4h drop: 89.2% — fear spike pumps call prices
2. **1h put signal is very clean:** −1.5 to −0.5% 1h move → 80.9% puts, large sample
3. **Counter-direction is severely penalised:** puts into +1.5%+ = 47.6% (below baseline)
4. **Phase 1 goal narrows:** confirm whether the 4h momentum signal is a proxy for trend or a breakout signal, and check if range compression compounds it
