# BTC Long Directional Options — Agent Brief

_Generated: 2026-05-15 · Scripts 01–10 complete_

## Purpose

Backwards analysis of BTC Deribit options to identify conditions under which buying a directional
option at the ask is EV-positive after fees. An option entry is **tradeable** if its bid reaches
≥ 1.20× the entry ask before expiry − 1h. Dataset: 2026-01-01 → 2026-05-12, Deribit BTC weekly
options, 4h entry boundaries (00/04/08/12/16/20 UTC).

---

## Dataset

| Key fact | Value |
|---|---|
| Total candidate entries | 26,354 |
| Tradeable (profitable) | 15,347 (58.2%) |
| Never hit 1.2× | 9,244 (35.1%) |
| Fee-killed | 1,281 (4.9%) |
| Date range | 2026-01-01 → 2026-05-12 |
| Spot data | 546,137 rows (1-min OHLC, 379 days) |
| Options data | 5-min snapshots, Deribit BTC weekly options |

**Labelling rule:** `tradeable = (bid_price ≥ entry_ask × 1.20)` at any 5-min snapshot from
entry to expiry − 1h (Deribit expire 08:00 UTC → cutoff 07:00 UTC).

**Fee model (per leg):** `fee_btc = min(0.0003, 0.125 × mark_price_btc)`. Round trip = entry + exit.

---

## Workflow History (Scripts 01–10)

### 01 — Scan tradeable longs
Scanned all 5-min option snapshots. Filters: DTE 1–7, |delta| 0.10–0.40, entry ask ≥ $75,
standard 4h UTC boundaries. Produced `candidates_summary.parquet` (26,354 rows).

### 02 — Enrich context
For each tradeable winner: located first 1.2× crossover, computed hold_hours, exit_bid,
gross_gain_pct, net_pnl_usd. Looked up prior spot momentum at 1h/4h/24h windows before entry.
Produced `tradeable_longs_enriched.parquet`.

Key numbers from enriched file:
- hold_hours: median 5.4h, p75 14.7h, p90 30.1h
- gross_gain_pct (to first 1.2× cross): median 26.7%, mean 32.5%
- net_pnl_usd: median $84 calls, $93 puts

### 03 — Frequency stats
Base rate by DTE: DTE 5 = 67.7%, DTE 4 = 63.4%, DTE 1 = 51.5% (too hard).
Base rate by delta: monotone — delta 0.40 = 69.1%, delta 0.10 = 42.1%.
Calls vs puts: 58.6% vs 60.0% (no structural asymmetry).
**Sweet spot: DTE 4–5, delta 0.30–0.40.**

### 04 — Timing analysis
Best hour: 12:00 UTC (63.6%, 3.2h median). Best day: Sunday (66.3%). Saturday = 11.3h median.
DTE=1 resolves 90% within 12h. DTE=7 takes up to 68h (p90).

### 05 — Vol regime
Negative IV-premium common (58% of entries: IV < HV24). Options are often cheap vs realised.
Note: HV scaling bug found (sqrt(365×288) used instead of sqrt(365×1440)) — ordinal ranks valid.

### 06 — Entry quality
Spread ≤ 10% of mark: **+9pp** base rate (58.2% → 67.2%). Single strongest individual filter.
Wide-spread options (>20%) barely reach 45% base rate.

### 07 — Momentum features (Phase 0)
Computed spread_pct + spot_30m/1h/4h/24h prior momentum for all 26,354 candidates.
Key output: `candidates_enriched.parquet`, `phase0_by_4h_momentum.csv`.
Best Phase 0 combo: tight spread + 4h ≥ 1.5% + 1h ≥ 0.5% → 80.6% at 0.93 windows/day.

Notable sub-patterns (4h momentum buckets, tight spread):
- Puts after crash (<−3%): **97.3%** (n=111) — directional + IV spike. Strongest single signal.
- Calls after crash (<−3%): **89.2%** (n=74) — IV expansion pumps calls despite adverse direction.
- Calls after +1.5–3% rise: **85.3%** (n=279) — directional continuation.
- Puts into +1.5%+ 4h rise: **47.6%** — strong counter-direction penalty.

### 08 — MTF momentum (Phase 1)
Full 4h × 1h cross-tabulation for calls and puts separately. US session interaction.

Both-aligned filter table (tight spread, all DTE/delta):

| 4h thr | 1h thr | Base rate | Windows/day | Trades/month |
|---|---|---|---|---|
| ≥0.3% | ≥0.5% | 80.6% | 0.93 | ~28 |
| ≥1.0% | ≥0.5% | 80.0% | 0.59 | ~18 |
| **≥1.5%** | **≥0.5%** | **87.2%** | **0.36** | **~11** |
| ≥2.0% | ≥0.5% | 90.3% | 0.23 | ~7 |

Notable heatmap cells:
- Calls: strong up 4h + mild up 1h (+0.5–+1.5%) → 86.4%
- Puts: neutral 4h + 1h just starting down (−1.5–−0.5%) → **93.5%** (early-move entry)
- Counter-direction: puts into strong 4h up → 28–47%

US session (12/16/20 UTC) + 4h ≥ 1%: 75.9% vs Non-US: 72.1% (+3.8pp).

### 09 — Winner magnitude
Full rescan of 15,347 winners to find peak_multiple (max bid / entry_ask_btc, all snapshots).
Produced `winner_peaks.parquet`.

Peak distribution: mean 3.93×, **median 2.43×**, p75 4.38×, p90 7.40×, p99 25.64×.

EV formula: `EV(TP) = base_rate × f(TP) × TP − 1`  
f(TP) = fraction of tradeable winners reaching TP:
- 1.5× = 81.7%, 1.75× = 70.2%, **2.0× = 61.5%**, 3.0× = 39.8%

EV at TP=2.0× by kernel:
- 80.6% kernel: **−0.8%** (0.7pp below break-even of 81.3%)
- **87.2% kernel: +7.3%** ← first EV-proven specification

### 10 — Stop calibration
MAE (max adverse spot excursion) for all 15,347 winners using 1-min OHLC spot data.
- Calls used spot LOW (worst case intraday drop)
- Puts used spot HIGH (worst case intraday rise)

**MAE summary:**

| Group | p50 MAE | Safe at −1.5% | Safe at −2.0% |
|---|---|---|---|
| Calls — peak ≥ 2× | 0.99% | 65% | 75% |
| Puts  — peak ≥ 2× | 0.93% | 65% | 74% |
| All winners | 1.58% | 48% | 58% |

**Stop selectivity (8h check):**

| Stop | Losers stopped | Winners stopped | Gap |
|---|---|---|---|
| −1.0% | 33.6% | 8.5% | 25pp |
| −1.5% | 22.7% | 4.7% | 18pp |
| −2.0% | 15.3% | 2.2% | 13pp |

**Time gate CDF (hold_hours to first 1.2× sign):**
- 24h → 86% of all winners + 85% of peak≥2× winners
- **36h → 93% of all winners + 93% of peak≥2×** ← recommended default
- 48h → 96%

Big winners (peak ≥ 2×) and all winners have nearly identical time CDFs — no "patient big winner" segment.

---

## Final Strategy Specification

### Entry conditions (all required)

| Condition | Value |
|---|---|
| Spread ≤ N% of mark | ≤ 10% (grid: 5, 10, 15) |
| DTE at entry | 4–5 (grid: (3,5), (4,5), (4,6)) |
| \|delta\| at entry | 0.30–0.40 (grid: (0.25,0.35), (0.30,0.40), (0.35,0.50)) |
| 4h prior spot momentum aligned | ≥ 1.5% (grid: 0.3, 0.5, 1.0, 1.5, 2.0) |
| 1h prior spot momentum aligned | ≥ 0.5% (grid: 0.3, 0.5, 1.0) |
| Entry cadence | 4h UTC boundaries: 00, 04, 08, 12, 16, 20 |

"Aligned" = call requires positive %, put requires negative % (above thresholds are magnitudes).

### Take profit

Exit when `bid_price ≥ entry_ask × tp_mult` at any 5-min snapshot.
- Default TP: **2.0×**
- Grid: [1.5, 1.75, 2.0, 2.5, 3.0]

### Stop A — spot adverse excursion

Exit when BTC spot (1-min close) moves ≥ `spot_stop_pct` % against trade direction from entry spot.
- Default: **2.0%**
- Grid: [1.0, 1.5, 2.0, 2.5, 3.0, off]
- Rationale: preserves 74–75% of peak ≥ 2× winners, captures 15% of losers within 8h

### Stop B — time gate

Exit `time_gate_h` hours after entry if `bid_price < entry_ask × time_gate_min_gain`.
- Default: **36h + 1.30× (30% gain threshold)**
- Grid: gates [18, 24, 36, 48, off] × gain threshold [1.20, 1.30, 1.50]
- Rationale: 93% of winners show ≥1.2× momentum by 36h; holding further is mostly theta bleed

### Fee model

```
entry_fee_btc = min(0.0003, 0.125 × entry_mark_btc)
exit_fee_btc  = min(0.0003, 0.125 × exit_mark_btc)
round_trip    = entry_fee_btc + exit_fee_btc
```

Trade at ask on entry, bid on exit. No additional slippage modelled.

### Expected performance (pre-backtest estimates)

| Metric | Value |
|---|---|
| Base rate | 87.2% |
| EV per trade at TP=2.0× | +7.3% |
| Frequency | ~11 trades/month (~0.36/day) |
| Median winner hold | 5.4h (to first 1.2× cross) |
| % big winners (peak ≥ 2×) safe from −2% spot stop | 74–75% |

---

## Backtester Parameter Grid

Default parameters marked with *.

| Parameter | Grid | Default |
|---|---|---|
| 4h_momentum_thr | 0.3, 0.5, 1.0, 1.5, 2.0 | **1.5** |
| 1h_momentum_thr | 0.3, 0.5, 1.0 | **0.5** |
| spread_max_pct | 5, 10, 15 | **10** |
| dte_range | (3,5), (4,5), (4,6) | **(4,5)** |
| delta_range | (0.25,0.35), (0.30,0.40), (0.35,0.50) | **(0.30,0.40)** |
| tp_mult | 1.5, 1.75, 2.0, 2.5, 3.0 | **2.0** |
| spot_stop_pct | 1.0, 1.5, 2.0, 2.5, 3.0, off | **2.0** |
| time_gate_h | 18, 24, 36, 48, off | **36** |
| time_gate_min_gain_pct | 20, 30, 50 | **30** |
| session_filter | off, US_only | **off** |

**Priority run:** defaults only (1 backtest) to confirm baseline EV.  
**Reduced grid:** fix spread=10, dte=(4,5), delta=(0.30,0.40), session=off.  
Vary: 4h_thr (3) × 1h_thr (3) × tp_mult (3) × spot_stop (3) × time_gate (3) = 243 combinations.

---

## File Index

### Analysis scripts
| File | Purpose |
|---|---|
| 01_scan_tradeable_longs.py | Scan options snapshots, label tradeable |
| 02_enrich_context.py | Enrich winners with hold_hours, exit_bid, momentum |
| 03_frequency_stats.py | Base rate by DTE, delta, side |
| 04_timing_analysis.py | Base rate by hour, day-of-week; hold CDF |
| 05_vol_regime.py | IV vs realised vol regime |
| 06_entry_quality.py | Spread analysis |
| 07_candidates_momentum.py | Phase 0: momentum features for all candidates |
| 08_mtf_momentum.py | Phase 1: 4h × 1h heatmaps |
| 09_winner_magnitude.py | Full peak rescan; EV table |
| 10_stop_calibration.py | MAE distribution, time gate, loser check, joint grid |

### Key data files
| File | Contents |
|---|---|
| candidates_summary.parquet | 26,354 candidates + tradeable label |
| tradeable_longs_enriched.parquet | 15,347 winners + hold_hours, exit_bid, momentum |
| candidates_enriched.parquet | 26,354 candidates + spread_pct + all momentum features |
| winner_peaks.parquet | 15,347 winners + peak_multiple (full rescan) |
| ev_table.csv | EV across TP multiples × base rates |
| phase0_by_4h_momentum.csv | Base rate by 4h momentum bucket |
| phase1_both_aligned.csv | MTF alignment table (4h × 1h) |
| phase1_heatmap_calls.csv | 4h × 1h heatmap — calls |
| phase1_heatmap_puts.csv | 4h × 1h heatmap — puts |
| stop_mae_distribution.csv | MAE percentiles by direction + TP category |
| stop_time_gate.csv | CDF of hold_hours by peak category |
| stop_loser_check.csv | Loser/winner adverse move rates at each stop × time |
| stop_joint_grid.csv | % winners preserved under (stop_pct × time_gate) grid |

### Strategy documents
| File | Contents |
|---|---|
| KERNEL_STRATEGY.md | Full backtester-ready strategy spec (detailed) |
| AGENT_BRIEF.md | This file — AI agent reference |
| SUMMARY.html | Human summary with all charts embedded |
| ENTRY_SIGNAL_PLAN.md | Phase-by-phase entry signal plan |
| FINDINGS.md | Raw findings per script |

### Charts (SVG)
| File | Contents |
|---|---|
| freq_overview.svg | Base rate by DTE, delta, side, momentum |
| phase0_overview.svg | Phase 0 momentum filter analysis |
| phase1_overview.svg | Phase 1 MTF heatmap |
| magnitude_overview.svg | Winner peak distribution and EV table |
| stop_calibration.svg | MAE histogram, survival, loser check, joint grid |
| timing_overview.svg | Hold time distributions |
| timing_heatmap.svg | Hour × DTE base rate heatmap |
| vol_regime.svg | IV vs realised vol |
| entry_quality.svg | Spread analysis |
