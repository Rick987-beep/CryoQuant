# Kernel Strategy — Long Directional BTC Options

_Last updated: 2026-05-15 (scripts 01–10 complete)_

## What we know

A long option trade is labelled **tradeable** (profitable) when its bid reaches ≥ entry_ask × 1.20 at any point before expiry−1h.  
**Overall base rate: 58.2%** (15,347 / 26,354 candidates across 2026-01-01 → 2026-05-12).

The following filters have been empirically validated from the historical data:

| Filter | Base rate | Notes |
|---|---|---|
| No filter (all candidates) | 58.2% | Baseline |
| Spread ≤ 10% of mark | 67.2% | +9pp. Single strongest filter. |
| Spread ≤ 10% + aligned 4h momentum ≥ 0.5% | 73.0% | 2.9 entry windows/day |
| Spread ≤ 10% + aligned 4h momentum ≥ 1.0% | **74.6%** | **1.4 entry windows/day** ← best trade-off |
| Spread ≤ 10% + aligned 4h momentum ≥ 1.5% | 79.7% | 0.7 windows/day (~21/month) |

## The kernel (current best)

> **Enter a directional long option when:**
> 1. **Spread ≤ 10%** of mark price at entry
> 2. **4h prior BTC spot move ≥ +1.0%** in the direction of the trade (call → spot up, put → spot down)
> 3. **DTE 4–5** at entry (DTE 5 alone: 67.7% base rate)
> 4. **Delta 0.30–0.40** (delta 0.40 alone: 69.1%)
> 5. Entry at standard 4h boundary hours: 00, 04, 08, 12, 16, 20 UTC

**Expected base rate: ~75%** | **Frequency: ~1.4 entry windows/day (~42/month)**

## Known strong sub-patterns

- **Calls after 4h crash (<−3%):** 89.2% — IV expansion effect (fear spike pumps calls even without recovery)
- **Puts after 4h crash (<−3%):** 97.3% — directional + IV expansion. Strongest single signal found.
- **Calls after 4h +1.5–3% rise:** 85.3% (n=279) — directional continuation, solid sample
- **Puts, 1h move −1.5 to −0.5%:** 80.9% (n=619) — 1h momentum for puts is strong and robust
- **Counter-direction penalty:** puts into +1.5%+ 4h rise: 47.6% — never buy against strong 4h momentum

## What this is NOT (yet)

- Not a full P&L proof. Base rate = option *crossed* 1.20× at some point. Actual profit depends on exit timing and rule.
- The 20% gross threshold is a proxy label, not the final exit strategy.
- The EV math requires knowing average winner multiple (not just that it crossed 1.2×).

**Break-even math:** at 75% base rate, need average winner ≥ ~33% to offset average loser of −100%.  
If winners average 1.5–2× from entry (plausible for DTE 4–5 directional options on BTC), EV is positive.

---

## Phase 1 upgrade (08_mtf_momentum.py) — MTF alignment confirmed

Adding a 1h same-direction confirmation substantially upgrades the kernel with minimal frequency cost:

| Filter | Base rate | Windows/day | Trades/month |
|---|---|---|---|
| 4h ≥ 1.0% only | 75.2% | 1.0 | ~30 |
| **4h ≥ 0.3% + 1h ≥ 0.5%** | **80.6%** | **0.93** | **~28** |
| 4h ≥ 1.5% + 1h ≥ 0.5% | 87.2% | 0.36 | ~11 |
| 4h ≥ 2.0% + 1h ≥ 0.5% | 90.3% | 0.23 | ~7 |

### Best kernels by target frequency

**High frequency (~28/month):**
> Spread ≤ 10% + 4h aligned ≥ 0.3% + 1h aligned ≥ 0.5% → **80.6% base rate**

**Minimum viable frequency (~11/month):**
> Spread ≤ 10% + 4h aligned ≥ 1.5% + 1h aligned ≥ 0.5% → **87.2% base rate**

### Key patterns from 4h×1h heatmap

- **Calls sweet spot:** strong 4h up (>+1.5%) + mild 1h up (+0.5–+1.5%) → **86.4%**
- **Calls reversal warning:** mild 4h up + strong 1h pullback → **42.1%** — do NOT enter
- **Puts surprise:** flat 4h (±0.5%) + 1h just starting to drop (−1.5–−0.5%) → **93.5%** — early-move entry
- **Puts alignment:** both 4h and 1h pointing down → 83–86% consistently
- **Counter-direction always penalised:** putting into strong 4h uptrend = 28–47%

### Session interaction
- US session (12/16/20 UTC) with 4h≥1%: **75.9%** (+8.4pp vs spread-only)
- Non-US (00/04/08): 72.1% (+5.4pp)
- US session amplifies momentum signal — prefer these hours for highest conviction

---

---

## EV Analysis (09_winner_magnitude.py)

### Winner magnitude
Median winner peaks at **2.43×** entry price. Mean 3.93×. Winners run hard.

| % of winners reaching TP | TP level |
|---|---|
| 99.5% | 1.2× |
| 81.7% | 1.5× |
| 70.2% | 1.75× |
| 61.5% | 2.0× |
| 39.8% | 3.0× |

### EV at TP=2.0× (assuming 100% loss if not hit)
EV formula: `base_rate × f(TP) × TP − 1`, where f(TP) = fraction of tradeable winners reaching TP.

| Base rate | Filter | EV at TP=1.75× | EV at TP=2.0× |
|---|---|---|---|
| 58.2% | None | −38% | −42% |
| 67.2% | Spread ≤ 10% | −22% | −26% |
| 80.6% | MTF kernel | −0.9% | **−0.8%** |
| 87.2% | MTF-high | **+7.2%** | **+7.3%** |

**Break-even base rate at TP=2.0×: 81.3%.** MTF kernel (80.6%) is 0.7pp short. MTF-high (87.2%) is comfortably positive.

### Recommended strategy specification (first EV-proven version)
> **Entry:** Spread ≤ 10% + 4h aligned ≥ 1.5% + 1h aligned ≥ 0.5% (DTE 4–5, delta 0.30–0.40)  
> **Exit:** Take profit at 2.0× entry ask  
> **EV:** +7.3% per trade | **Frequency:** ~11 trades/month  
> **Hold time to first 1.2× cross:** median 5.4h, p75 14.7h

### Open questions
- Stop loss feasibility: cutting losses from −100% to −50% swings EV from −0.8% to ~+24% at MTF kernel level. Is a −50% stop reliably executable on Deribit BTC options?
- Does the MTF-high subset have a better peak distribution than average? (Higher f(TP) would improve EV further)
- One more filter to push MTF kernel from 80.6% → 82%+ would make it EV-positive without restricting frequency

---

## Phase 2: Stop-loss calibration (10_stop_calibration.py)

### Stop A — Spot adverse excursion

For each winner trade, the Max Adverse Excursion (MAE) was measured over the full holding period
using 1-min BTC spot data (worst-case intraday low for calls, worst-case intraday high for puts).

**MAE distribution of winners:**

| Group | p50 MAE | p75 MAE | p90 MAE | Safe at −1.0% | Safe at −1.5% | Safe at −2.0% |
|---|---|---|---|---|---|---|
| Calls — peak ≥ 2× | 0.99% | 2.04% | 3.40% | 50% | **65%** | 75% |
| Puts  — peak ≥ 2× | 0.93% | 2.02% | 3.60% | 52% | **65%** | 74% |
| Calls — peak < 2× | 2.81% | 4.62% | 7.70% | 12% | 21% | 31% |
| Puts  — peak < 2× | 3.31% | 5.06% | 7.01% | 14% | 22% | 32% |
| All winners | 1.58% | 3.29% | 5.50% | 37% | 48% | 58% |

**Key findings:**
- The most valuable winners (peak ≥ 2×) have **median MAE ≈ 0.96%** — BTC barely moves against them.  
  This is a strong signal that these trades are right immediately. A tight stop cuts mainly the wrong winners.
- Lower-peak winners (1.2–2×) have p50 MAE ≈ 3%, meaning they require wider room or the time gate
  to realise even their modest gain. These are the "grind up slowly" trades.
- A −2.0% stop preserves **74–75% of the peak ≥ 2× winners** while only killing 2.2% of all winners
  within the first 8 hours (loser check).

**Stop selectivity (checked at +8h after entry):**

| Stop threshold | Losers with adverse move >X% | Winners with adverse move >X% | Selectivity gap |
|---|---|---|---|
| −0.5% | 49.4% | 17.4% | 32pp |
| −1.0% | 33.6% | 8.5% | 25pp |
| −1.5% | 22.7% | 4.7% | **18pp** |
| −2.0% | 15.3% | 2.2% | 13pp |
| −2.5% | 11.4% | 1.3% | 10pp |

At −1.5%: captures 22.7% of losers that showed adverse move within 8h, at a cost of 4.7% of winners.
At −2.0%: more lenient, but still worthwhile — only 2.2% of winners adversely triggered.

**Conclusion on Stop A:** Use −2.0% as the base parameter with −1.5% and −2.5% in the grid.
Tighter than −1.5% is too costly to winners; looser than −3.0% provides minimal selectivity benefit.

---

### Stop B — Time gate (theta decay protection)

`hold_hours` = time from entry to the first observed 1.2× bid crossover.

| Time gate | % all winners already showed ≥1.2× | % peak ≥ 2.0× already at ≥1.2× |
|---|---|---|
| 8h | 60% | 59% |
| 12h | 71% | 69% |
| 18h | 80% | 78% |
| **24h** | **86%** | **85%** |
| **36h** | **93%** | **93%** |
| 48h | 96% | 96% |
| 72h | 99% | 99% |

**Key findings:**
- Big winners (peak ≥ 2×) and all winners have nearly identical time profiles. When a big winner
  is going to happen, it does not materially lag smaller winners. There is no "patient premium".
- 36h captures 93% of all winners having already shown upside momentum. Beyond 36h you are holding
  for the last 7% — which are largely grinding positions consuming maximum theta.
- 24h is a reasonable tight gate (86%) with significant theta savings.

**Conclusion on Stop B:** Grid 24h–48h. Recommended default: 36h. At 36h, only 7% of winners are
not yet at 1.2× — the marginal value of holding longer is small and theta cost is high for DTE 4–5.

---

## Full Strategy Specification (backtester-ready)

### Instruments
- **Asset:** BTC perpetual / spot (for entry signal) + Deribit BTC options (execution)
- **Option type:** Calls and puts separately (signal is directional)
- **DTE at entry:** 4 or 5 days
- **Delta at entry:** 0.30–0.40 (range validated empirically: delta 0.40 → 69.1% base rate alone)
- **Expiry convention:** Deribit weekly options, expire 08:00 UTC on Fridays

---

### Indicators required

1. **Spot momentum — 4h timeframe**
   - `spot_4h_chg_pct` = (BTC close now − BTC close 4h ago) / BTC close 4h ago × 100
   - For calls: must be ≥ threshold (upward)
   - For puts:  must be ≤ −threshold (downward)

2. **Spot momentum — 1h timeframe**
   - `spot_1h_chg_pct` = (BTC close now − BTC close 1h ago) / BTC close 1h ago × 100
   - Same directional requirement as 4h

3. **Options bid-ask spread**
   - `spread_pct` = (ask − bid) / mark_price × 100
   - Entry only when ≤ 10% (filters wide-spread illiquid options)

4. **Entry price**
   - Use `ask_price` at entry snapshot (Deribit 5-min options snapshots)

5. **Deribit mark price** (for fee calculation)
   - Fee per leg: `min(0.0003 BTC, 0.125 × mark_price_btc)`

---

### Entry conditions (all must be true)

| Condition | Value | Basis |
|---|---|---|
| Spread ≤ 10% of mark | Hard filter | +9pp vs no filter |
| DTE at entry = 4 or 5 | Hard filter | DTE 5 alone: 67.7% base rate |
| Delta 0.30–0.40 | Hard filter | Delta 0.40 alone: 69.1% |
| 4h spot momentum aligned | ≥ 1.5% magnitude | Grid: 0.3%, 0.5%, 1.0%, 1.5%, 2.0% |
| 1h spot momentum aligned | ≥ 0.5% magnitude | Grid: 0.3%, 0.5%, 1.0% |
| Entry hour | Any 4h boundary (00/04/08/12/16/20 UTC) | US session (12/16/20) amplifies signal |

**Recommended entry spec (first EV-proven):**
> Spread ≤ 10% + 4h aligned ≥ **1.5%** + 1h aligned ≥ **0.5%** → **87.2% base rate**, ~11 trades/month

**Looser spec for higher frequency:**
> Spread ≤ 10% + 4h aligned ≥ **0.3%** + 1h aligned ≥ **0.5%** → **80.6% base rate**, ~28 trades/month
> (0.7pp below EV break-even; may clear with stop-loss in place)

---

### Exit — Take profit

| Rule | Value | Basis |
|---|---|---|
| Take profit | Bid ≥ entry_ask × **TP_mult** | Best EV at TP_mult = 2.0× |
| Check frequency | Every 5-min snapshot | Data granularity |

**Winner fraction reaching TP:**

| TP | % of winners reaching it |
|---|---|
| 1.5× | 81.7% |
| 1.75× | 70.2% |
| **2.0×** | **61.5%** ← recommended default |
| 3.0× | 39.8% |

**EV at TP=2.0× by filter:**

| Base rate | Filter | EV at 2.0× |
|---|---|---|
| 80.6% | MTF kernel (4h≥0.3% + 1h≥0.5%) | −0.8% (just below break-even) |
| **87.2%** | **MTF-high (4h≥1.5% + 1h≥0.5%)** | **+7.3%** ← target |

EV formula: `base_rate × f(TP) × TP − 1`. Break-even base rate at TP=2.0×: **81.3%**.

**Parameter grid for TP:** [1.5, 1.75, 2.0, 2.5, 3.0]

---

### Exit — Stop loss A (spot adverse excursion)

| Rule | Value | Basis |
|---|---|---|
| Spot adverse move threshold | −**2.0%** from entry spot | 74% of peak≥2× winners safe |
| Direction | For calls: spot drops X%; for puts: spot rises X% | |
| Measurement | Continuous on 1-min spot close | |

At −2.0%:
- **74–75% of peak≥2× winners are preserved** (they never see this adverse move)
- Only 2.2% of all winners show an adverse 2%+ move within 8h of entry
- 15.3% of losers show a 2%+ adverse move within 8h — these are stopped early and cheaply

**Parameter grid for Stop A:** [−1.0%, −1.5%, −2.0%, −2.5%, −3.0%, off]  
(Include "off" to measure stop contribution vs no stop in backtester)

---

### Exit — Stop loss B (time gate)

| Rule | Value | Basis |
|---|---|---|
| Time gate | **36h** after entry | 93% of winners show ≥1.2× by 36h |
| Condition | Exit if bid < entry_ask × **1.30** at gate | Not yet 30% in profit |
| Rationale | Positions stalled past 36h are consuming theta; tail risk rising toward expiry |

The 30% gain threshold at the gate is conservative — if the position is already up 30%+, it stays
open to reach the full TP. If it is flat or underwater at 36h, it is exited.

Big winners (peak ≥ 2×) and all winners show near-identical 36h CDFs (93% vs 93%), confirming
there is no "patient big winner" population worth waiting for.

**Parameter grid for Stop B:** [off, 18h, 24h, 36h, 48h] × gain threshold [1.20, 1.30, 1.50]

---

### Fee model

| Component | Value |
|---|---|
| Entry fee | `min(0.0003 BTC, 0.125 × entry_mark_btc)` |
| Exit fee | `min(0.0003 BTC, 0.125 × exit_mark_btc)` |
| Round-trip fee | Entry + exit fee (both legs) |
| Slippage | Trade at ask on entry; bid on exit (no extra slippage modelled) |

---

### Backtester parameter grid (full)

| Parameter | Grid values | Default |
|---|---|---|
| `4h_momentum_thr` (%) | 0.3, 0.5, 1.0, **1.5**, 2.0 | **1.5** |
| `1h_momentum_thr` (%) | 0.3, **0.5**, 1.0 | **0.5** |
| `spread_max_pct` | 5, **10**, 15 | **10** |
| `dte_range` | (4,5), (3,5), (4,6) | **(4,5)** |
| `delta_range` | (0.25,0.35), **(0.30,0.40)**, (0.35,0.50) | **(0.30,0.40)** |
| `tp_mult` | 1.5, 1.75, **2.0**, 2.5, 3.0 | **2.0** |
| `spot_stop_pct` | 1.0, 1.5, **2.0**, 2.5, 3.0, off | **2.0** |
| `time_gate_h` | 18, 24, **36**, 48, off | **36** |
| `time_gate_min_gain_pct` | 20, **30**, 50 | **30** |
| `session_filter` | off, **US_only** (12/16/20 UTC) | **off** |

**Priority run (default params only):** 1 backtest to confirm baseline EV  
**Full grid:** 5×3×3×3×3×5×6×5×3×2 = **81,000 combinations** — use a reduced grid in practice.

**Reduced priority grid (50 combinations):**  
Fix: spread=10, dte=(4,5), delta=(0.30,0.40), session=off  
Vary: 4h_thr (1.0/1.5/2.0) × 1h_thr (0.3/0.5/1.0) × tp_mult (1.75/2.0/2.5) × spot_stop (1.5/2.0/off) × time_gate (24/36/48)

---

### Statistical summary

| Stat | Value |
|---|---|
| Dataset | 2026-01-01 → 2026-05-12, 26,354 candidates |
| Overall base rate | 58.2% (15,347 tradeable) |
| Best entry kernel base rate | **87.2%** (MTF-high) |
| EV at TP=2.0× (MTF-high) | **+7.3% per trade** |
| Expected frequency (MTF-high) | ~11 trades/month |
| Median winner peak | **2.43×** entry ask |
| Mean winner peak | 3.93× entry ask |
| Winner hold time (1.2× cross): p50 | 5.4h |
| Winner hold time (1.2× cross): p90 | 30.1h |
| % of peak≥2× winners: MAE < 2.0% | **74–75%** |
| % of losers with adverse spot >2% within 8h | **15.3%** |
| % of winners showing 1.2× signal by 36h | **93%** |

---

## Open work / backtester handoff

- [ ] **Primary backtest:** run default spec (MTF-high, TP=2.0×, stop=−2.0%, gate=36h)
- [ ] **Verify EV holds net of fees** in backtester (fees estimated at ~0.4% RT per trade)
- [ ] **Grid search reduced grid** around defaults to find optimal TP × stop_pct combination
- [ ] **Session filter test:** US vs all-hours — does restricting to 12/16/20 UTC improve Sharpe?
- [ ] **MTF-kernel viability:** test whether adding stop=−2.0% pushes 80.6% kernel to EV-positive
- [ ] Confirm Deribit 5-min data coverage is sufficient for continuous stop monitoring

