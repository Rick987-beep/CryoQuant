# Long Tradable Options — Analysis Findings

**Dataset:** BTC options on Deribit, 2026-01-01 → 2026-05-12  
**Universe:** DTE 1–7, |delta| 0.10–0.40, entry ask ≥ $75, entry cadence 4-hourly (00/04/08/12/16/20 UTC)  
**Profit definition:** exit bid ≥ entry ask × 1.20 AND net P&L (after Deribit round-trip taker fees) > 0  
**Scan result:** 15,347 tradeable / 26,354 candidates = **58.2% overall base rate**

---

## Script 01 — Scan

Skip reasons for non-tradeable candidates:
- `never_hit` — 9,244 (35.1%) — bid never reached the 1.20× threshold before expiry
- `fee_kill` — 1,281 (4.9%) — bid hit 1.20× but net P&L negative after fees
- `ask_too_low` — 482 (1.8%) — entry ask below $75 minimum

---

## Script 03 — Frequency Stats

### By DTE at entry

| DTE | Base rate | Median hold | Median net PnL | Median gross gain |
|-----|-----------|-------------|----------------|-------------------|
| 1   | 51.5%     | 2.7h        | $52            | 31.3%             |
| 2   | 57.4%     | 4.4h        | $75            | 28.0%             |
| 3   | 61.0%     | 6.1h        | $97            | 26.2%             |
| 4   | 63.4%     | 6.1h        | $114           | 25.8%             |
| 5   | 67.7%     | 10.7h       | $138           | 25.1%             |
| 6   | 62.7%     | 17.3h       | $130           | 24.8%             |
| 7   | 64.6%     | 12.6h       | $152           | 24.7%             |

**Key insight:** DTE=1 is hardest (51.5%) but fastest to resolve (63.9% exit within 4h, 90.4% within 12h). DTE=3–5 is the sweet spot: 61–68% base rate with 6–11h median hold. DTE=7 ties up capital for 12–17h.

### By |delta|

| Delta | Base rate | Median hold | Median net PnL |
|-------|-----------|-------------|----------------|
| 0.10  | 42.1%     | 6.0h        | $18            |
| 0.15  | 53.4%     | 5.5h        | $34            |
| 0.20  | 62.3%     | 5.4h        | $59            |
| 0.25  | 63.4%     | 5.6h        | $83            |
| 0.30  | 67.1%     | 5.3h        | $121           |
| 0.35  | 67.8%     | 5.6h        | $151           |
| 0.40  | 69.1%     | 5.4h        | $190           |

**Key insight:** Hold time is flat (~5–6h) across all deltas. Higher delta = higher probability AND higher dollar PnL. Delta=0.10 options ($18 median PnL) are borderline uneconomical.

### By side

| Side  | Base rate | Median hold | Median net PnL |
|-------|-----------|-------------|----------------|
| Calls | 58.6%     | 5.6h        | $84            |
| Puts  | 60.0%     | 5.3h        | $93            |

No structural asymmetry. BTC directional opportunity is symmetric across this period.

---

## Script 04 — Timing Analysis

### By entry hour (UTC)

| Hour  | Base rate | Median hold |
|-------|-----------|-------------|
| 00:00 | 58.3%     | 7.2h        |
| 04:00 | 59.8%     | 7.0h        |
| 08:00 | 62.8%     | 4.4h        |
| 12:00 | **63.6%** | **3.2h**    |
| 16:00 | 57.6%     | 3.9h        |
| 20:00 | 58.1%     | 5.7h        |

**12:00 UTC is the best entry hour:** highest base rate and fastest resolution. This is ~2h before the NY open (14:00 UTC). Overnight entries (00:00, 04:00) are average base rate but 2× slower to resolve.

### By day of week

| Day | Base rate | Median hold |
|-----|-----------|-------------|
| Mon | 58.5%     | 4.7h        |
| Tue | 58.7%     | 3.6h        |
| Wed | 56.6%     | 4.5h        |
| Thu | 59.5%     | 3.6h        |
| Fri | 57.8%     | 4.1h        |
| Sat | 58.1%     | 11.3h       |
| **Sun** | **66.3%** | 7.2h    |

**Sunday outlier:** 66.3% base rate, second fastest hold of weekend. Saturday entries are slow (11h median hold). Weekdays: consistent 56–60%, fast resolution.

### Hold period distribution by DTE

- DTE=1: 63.9% resolve within 4h; 90.4% within 12h
- DTE=3: 40% within 4h; 75% within 12h
- DTE=7: 22% within 4h; 61% within 24h; p90 = 68h

### Hour × DTE heatmap (base rate highlights)

- Best: DTE=5 / 12:00 UTC → ~69%
- Worst: DTE=1 / 20:00 UTC → 43.1%
- DTE=4–7 consistently outperforms DTE=1–2 at every hour
- 12:00 UTC is the best hour across all DTEs

---

## Script 05 — Vol Regime

**Result: NEGATIVE — IV cheapness does not predict profitability**

### HV/IV quintile (HV24 / ATM IV at entry)

| Quintile | HV/IV median | ATM IV | Base rate |
|----------|-------------|--------|-----------|
| Q1 (lowest) | 0.28 | 46.9% | 61.4% |
| Q2       | 0.41         | 49.7%  | 58.3%     |
| Q3       | 0.47         | 46.6%  | 56.6%     |
| Q4       | 0.53         | 47.8%  | 61.7%     |
| Q5 (highest) | 0.70    | 33.0%  | 55.7%     |

No monotonic relationship. Spread across quintiles is only ~6pp.

### IV 30-day percentile decile

Range: 52.9%–65.2%. Non-monotonic, no clear trend.

**Why this fails:** At DTE 1–7, the main P&L driver is delta/gamma (directional moves), not vega. IV level at entry has minimal effect on whether a +20% gain materialises within the holding window. Do not build an IV-cheapness entry filter.

*Technical note: HV24 absolute values are systematically ~2.24× too low (spot data is 1-min, code used 5-min annualisation factor). Ordinal quintile comparisons are unaffected.*

---

## Script 06 — Entry Quality

### Spread quality — strongest predictor found

`spread_pct = (ask − bid) / mark × 100` at entry snapshot.

| Quartile         | Spread median | Range      | Base rate |
|------------------|---------------|------------|-----------|
| Q1 (tightest)    | 6.25%         | 1.1–8.1%   | **68.2%** |
| Q2               | 9.6%          | 8.1–11.4%  | 64.9%     |
| Q3               | 13.5%         | 11.5–15.8% | 57.8%     |
| Q4 (widest)      | 19.0%         | 15.8–283%  | **41.7%** |

**26.5pp spread from Q1 to Q4.** Monotonic, large effect size. The widest-spread options (deep OTM, illiquid strikes) are structurally penalised: you pay a premium above mark at entry, then need the bid to clear 1.20× that inflated ask. Wide spread is both an entry cost and a signal that market makers are unwilling to quote efficiently.

**Actionable filter:** `spread_pct ≤ 10%` selects Q1+Q2 (~50% of candidates) with a combined base rate of ~66.5%, up from the overall 58.2%.

**Critical reframe:** We only need to find ONE option with a tight spread at entry time. Since there are typically many expiry × strike × side combinations available at any entry snapshot, a tight-spread option is almost always available. The spread filter narrows the option SELECTION, not the entry TIMING.

### 30-min spot acceleration

`accel_30m_pct = (spot_now − spot_30min_ago) / spot_30min_ago × 100`

**Combined (calls+puts):** 74% of all entries are in the neutral ±0.3% bucket (58.1% base rate). The signal is diluted when directions are mixed.

**Split by side (the real signal):**

| 30-min move | Calls    | Puts      |
|-------------|----------|-----------|
| −2 to −1%   | **80.4%** (n=143) | 57.1% (n=154) |
| −1 to −0.3% | 57.1%    | 60.1%     |
| ±0.3%       | 56.4%    | 59.6%     |
| +0.3 to +1% | 57.5%    | 58.9%     |
| **+1 to +2%**   | **89.9%** (n=89) | **18.0%** (n=100) |

**Key finding:** Strong directional momentum in the 30 minutes before entry is a powerful signal — but only when aligned with the option direction. Calls into rising markets and calls after a sharp drop (IV expansion effect) both perform well. Puts bought into a rising market are nearly always losers. The neutral zone (most entries) is uninformative.

**Caveat:** Extreme buckets have small samples (89–297 over 4.5 months ≈ 0.6–2 events/day). Signal is real but rare.

---

## Combined Signal Summary

| Feature          | Effect size | Monotonic? | Actionable? |
|------------------|-------------|------------|-------------|
| spread_pct       | 26.5pp      | Yes        | Yes — hard filter ≤10% |
| delta            | 27pp (0.10→0.40) | Yes   | Yes — prefer delta ≥0.25 |
| DTE              | 16pp (1→5)  | Mostly     | Yes — prefer DTE 3–5 |
| entry_hour       | 6pp         | No         | Soft preference for 12:00 |
| day_of_week      | 10pp (Sun vs Wed) | No  | Soft — Sun best, Sat slow |
| HV/IV ratio      | ~6pp        | No         | No — noise |
| IV percentile    | ~12pp       | No         | No — non-monotonic |
| accel_30m × side | Up to 72pp at extremes | N/A | Yes at tails (>1% aligned) |

---

## Script 07 — Phase 0: Candidates Momentum (tight-spread subset only)

**Tight-spread base rate: 67.2%** — spread filter alone adds +9pp vs overall 58.2%.

### 4h momentum base rate (spread ≤ 10%)

| 4h move | Calls | Puts |
|---|---|---|
| < −3%  | **89.2%** (n=74) | **97.3%** (n=111) |
| −3 to −1.5% | 61.1% | 69.4% |
| −1.5 to −0.5% | 64.2% | 71.5% |
| ±0.5% neutral | 67.9% | 65.2% |
| +0.5 to +1.5% | 69.1% | 67.1% |
| +1.5 to +3% | **85.3%** (n=279) | 47.6% |
| > +3% | 73.0% | 48.3% |

**1h momentum — puts:** −1.5 to −0.5% → **80.9%** (n=619). Large sample, strong signal.

### Combined filter: spread ≤ 10% + aligned 4h momentum

| Threshold | Base rate | Windows/day |
|---|---|---|
| ≥ 0.3% | 72.5% | 3.9 |
| ≥ 0.5% | 73.0% | 2.9 |
| **≥ 1.0%** | **74.6%** | **1.4** |
| ≥ 1.5% | 79.7% | 0.7 |
| ≥ 2.0% | 81.5% | 0.4 |
| ≥ 3.0% | 91.2% | 0.1 |

**Decision gate PASSED at ≥0.5%:** 73% base rate, 2.9 qualifying entry windows per day.

**Strategy kernel:**
> Buy a tight-spread (≤10%), DTE 3–5, delta 0.25–0.40 option in the direction of the prior 4h BTC move, when that move is ≥ 0.5–1.0%.

Key observations:
- **IV expansion effect confirmed:** calls after <−3% crash = 89.2%. Fear spike drives call prices up even without directional recovery.
- **Counter-direction penalty is severe:** puts into +1.5%+ 4h rise = 47.6% — well below the 67.2% tight-spread baseline. Do not buy against strong momentum.
- **1h put signal is robust:** 80.9% for puts after a −1.5 to −0.5% 1h move, n=619 (large sample).
- Neutral zone (±0.5% 4h) is 67.9% for calls and 65.2% for puts — spread filter is already doing most of the work; momentum adds 5–18pp on top.

---

## Open Questions / Next Steps

1. **Combined spread + momentum filter:** What base rate and daily opportunity count does `spread < 10% AND aligned accel > 0.5%` yield? This is the core next question.
2. **Momentum lookback window:** Is 30-min the right window, or is 5-min, 15-min, or 1-hour more predictive? To be tested.
3. **Why does Sunday outperform?** IV is often depressed on weekends (thin market) — does that interact with spread quality? Or is it a mean-reversion gap effect from Monday open?
4. **Fee-kill trades:** 1,281 candidates hit 1.20× gross but were killed by fees. These are likely wide-spread OTM options. Does the spread filter eliminate most of them?
5. **Realised volatility accuracy:** The HV24 scaling bug (1-min bars, 5-min annualisation) should be fixed before any HV-based signal is revisited.
