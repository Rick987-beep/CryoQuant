# HANDOVER — v5 (misc job) → v6 (this study)

**From:** `~/misc/jobs/france-sovereign-stress/` (v1–v5, ad-hoc scripts, misc `.venv` on Python 3.9, no tests)
**To:** `studies/france_sovereign_stress/` (CryoQuant, Python 3.12, tested modules)
**Date:** 10 Oct 2026 · v5 snapshot `2026-10-09T1456` (9 Oct 2026, 14:56 CEST)
**Hard rule:** research only. No orders, no broker connections from this study.

**v6 status (10 Oct 2026):** Phases 0–5 complete and reconciled in [`RESULTS.md`](RESULTS.md).
Phase 6 pitch HTML deferred; use [`explore_interactive.html`](explore_interactive.html)
(or [`EXPLORE.md`](EXPLORE.md) / [`explore.html`](explore.html)). See [`README.md`](README.md).

**12 Oct 2026:** rerun on live snapshot `2026-10-12T0941` (entry 137.34 bp, history to
9 Oct). The 9 Oct outputs are kept in `archive/2026-10-09T1456/`; RESULTS.md carries a
change table against them. §4 targets below remain the reference-replay gates
(`FSS_SNAPSHOT=reference`).

## 1. The trade idea in one paragraph

France's OAT–Bund 10-year spread was 138 bp on 9 Oct 2026 (OAT 4.849%, Bund 3.469%, CNBC). The view: a minority
government, a €54bn budget fight to year-end, the April/May 2027 presidential election and an ECB backstop (TPI)
that France does not qualify for while under an excessive deficit procedure push the spread to 240 bp or more
before 1 Jul 2027. The best v5 expression is **short Euro-OAT futures (FOAT) / long Euro-Bund futures (FGBL)** in
equal € per bp: stop 40 bp below the last add, add every +20 bp, size = equity ÷ 40 bp (all-in), cap 20 FOAT.

## 2. What is in `input/`

| Path | Content |
|------|---------|
| `input/v5_reference/data/yields_daily.csv`, `yields_weekly.csv` | CNBC FR10Y / DE10Y closes and spread (≈2 y daily, ≈10 y weekly) |
| `input/v5_reference/data/eurex_settles*.csv` | FOAT / FGBL front and next settlements (20 days used for calibration) |
| `input/v5_reference/data/eurex_2026-10-09T1456.json` | Live Eurex OOAT / OGBL option chains (all strikes, bid/ask) + futures stats + CNBC quote |
| `input/v5_reference/data/stocks_daily.csv`, `stocks_weekly.csv` | Yahoo closes: ^FCHI + 17 French non-bank stocks |
| `input/v5_reference/data/fred_10y_monthly.csv` | FRED IRLTLT01 FR / DE / IT monthly, 2007 → Aug 2026 |
| `input/v5_reference/results/*.json` | v5 outputs: `v5_*` (base, `_vol1.5`, `_beta0.6`), `extras_*` (mixes, option facts), `maintenance_*` (check frequency) |
| `input/v5_reference/scripts/v4`, `v5` | Frozen copy of the v5 code (reference only; do not import) |
| `input/v5_reference/*.html` | The two v5 deliverables: investor pitch and trade-detail report |
| `input/research/` | Source research extracts (France Tail Risk 28 Sep; Euro Sovereign Crises 29 Sep) and the 9 Oct news check |

The misc job folder stays the home of the trade idea and the reports (`~/misc/jobs/france-sovereign-stress/README.md`).

## 3. How v5 works (module by module)

| v5 file | Role | Notes for v6 |
|---------|------|--------------|
| `v5/history.py` | CNBC chart API (FR10Y-FR, DE10Y-DE) + Yahoo closes | Unofficial CNBC endpoint; make it a source module with caching |
| `v4/fetch.py` | Eurex OOAT / OGBL chains via headless Chromium (React props), futures stats API, CNBC quote | Eurex stats API had no same-day data on 9 Oct, so futures levels came from put–call parity on the chains |
| `v5/model.py` `FutCalib` | € per bp = −slope × 1000 of daily FOAT/FGBL settle changes on yield changes; carry = mean (front − next) calendar ÷ 63 days | Only **20 settlement days**; see §5 |
| `v5/model.py` `Calib` | Daily spread / Bund vol and correlation over the last 126 days; stock betas to Δspread and ΔBund by OLS (2 y) | The 126-day window contains the Sept–Oct stress itself |
| `v5/model.py` `simulate` | Business-day paths to 1 Jul 2027. Driftless Student-t (4 df) walks; right world: completion day tc ~ U(15, T), 15-day bridge to exactly the level with doubled noise, Bunds move −f × jump, f ~ U(0.10, 0.70); exit at tc. Wrong world: no event, close on 1 Jul 2027 | Seeds 11 + i per level, so levels are not on common random numbers |
| `v5/linear.py` | Sleeves (spread, short FOAT, long FGBL, stock shorts) as cumulative exposure X in bp or %, net of carry; `run()` applies stop, pyramid, rolls (first business day of Dec / Mar / Jun), costs | Units are **continuous € per bp**, not integer contracts |
| `v5/options.py` + `v4/book.py`, `structures.py`, `market.py` | OOAT / OGBL structures, Black-76 at live bid/ask, front-only or rolled ladder, sold at model value on tc | Later expiries priced at today's skew with ATM vol rising with the spread (heuristic) |
| `v5/run.py` | ~190 candidates × levels → ranking, families, mixes; flags `--vol-mult`, `--stock-beta-mult` | |
| `v5/extras.py` | 75/25 and 50/50 spread + CAC mixes on common paths; Black-76 put at implied vs realised vol | |
| `v5/maintenance.py` | Same engine with check calendars: resting stop vs daily close vs weekly; add counts | |
| `v5/build_report.py`, `build_pitch.py` | HTML reports (agent-commons strategy CSS, misc chart utils) | Hard-coded text facts; see §5 |

## 4. v5 reference numbers (acceptance targets)

€10k unit, 10,000 paths, snapshot `2026-10-09T1456`. v6 must reproduce these within Monte Carlo noise on the same
inputs and assumptions, **or** document each difference with its cause.

| Item | v5 value |
|------|----------|
| Calibration | FOAT €87.58/bp (duration 7.93), FGBL €96.57/bp (8.02), hedge 0.907; carry FOAT 0.114, FGBL 0.015 bp/day (≈6.3 bp/quarter net); daily vol spread 3.18 bp, Bund 3.95 bp, ρ 0.14 |
| Live P&L check | Short 3 FOAT / long 3 FGBL, 11 Sep → 8 Oct 2026 settles: **+€11,490** for +44.8 bp |
| Spread trade, stop 40 / +20 | mean **4.47 / 11.67 / 16.65 / 24.29×** at 240 / 300 / 340 / 400 bp; median 15.21× at 300; lost if right **25.2%**; ≥10× 74.7%; wrong world **0.53×** |
| Spread trade, stop 30 / +15 | 11.88× mean at 300 (top raw rank), but 41% lost if right and weaker under vol × 1.5 |
| Vol × 1.5 | spread 40 / +20: 8.36×, 46% lost |
| Bund-flight terciles / timing terciles | 11.63 / 11.63 / 11.74× · 16.06 / 12.10 / 7.74× |
| Short CAC 40 future, stop 12% / +6% | 3.41× mean, 4.00× median, 21% lost, wrong 0.84×; betas × 0.6 → 2.47× |
| Mix 75% spread / 25% CAC | 9.60× mean, 12.39× median, 13% lost; payout correlation 0.36 |
| Options | best OGBL: 124 call front-only 2.45×, 79% lost; best OOAT: 105.5 put ladder 1.38×; OOAT ATM IV 11.9% ≈ 151 bp/yr |
| Monitoring | daily close check 11.65×; weekly adds 9.10×; weekly all 9.37×; stop only, no ladder 3.78× |
| Straight-line equity (no noise) | 240 bp €76,563; 300 bp €181,664; 340 bp €251,730; 400 bp €356,831 |

## 5. Known weak spots and suspected errors (check these first)

1. **DV01 calibration on 20 days.** € per bp comes from a 20-day regression of settle changes on CNBC yield changes.
   Cross-check against the CTD bond and conversion factor (or futures duration × price × €1,000 / 10,000) and use a
   longer window. The hedge ratio and every € figure depend on it.
2. **Carry.** Measured as the mean Dec–Mar calendar over the window and applied linearly. Check sign and size per
   roll; carry is the main cost in the wrong world (≈€26/day at 3/3, ≈€5k over the horizon).
3. **Continuous vs integer contracts.** The simulation sizes in continuous € per bp; the ladder tables round to
   whole contracts (3/3, 4/4, 6/6, 9/8, 14/13, 20/18) and the legs are not exactly DV01-neutral. Model integer
   contracts per leg and the residual Bund exposure.
4. **Hard-coded spread in the report ladder.** `build_report.spread_ladder` and `eq_spread` use `138.0` instead of
   the snapshot spread. Fine for 9 Oct, wrong after any refresh. *v6: fixed. The ladder starts at the active
   snapshot's entry spread (`MarketInputs.s0_report`).*
5. **Execution model.** v5 assumes a resting stop (fill at stop − 1 bp, half the gap when a close jumps through).
   IBKR cannot hold a stop on an OAT–Bund spread (no Eurex order book for it), so the realistic baseline is a
   **daily-close check**; maintenance.py showed the difference is small (11.65× vs 11.67×). Make daily close the
   default.
6. **Event model.** Completion day uniform; the spread is bridged exactly to the level and the trade exits there.
   No path peaks below the target and retraces. Right-world results are conditional on reaching the level. The
   user does not want forced expected values, but a peak-and-retrace variant would show what happens between
   levels.
7. **Vol window.** The 126-day calibration includes the current stress, which raises pre-event noise and the
   stop-out rate. Report a calmer window as a sensitivity.
8. **Common random numbers.** Different seeds per level make level-to-level comparisons noisier than needed.
9. **Options pricing heuristics.** Rolled ladders use today's skew with ATM vol rising with the spread; no term
   structure. Front-only books are priced at live bid/ask.
10. **Stocks.** Betas from a 2-year OLS on daily Δspread and ΔBund; CAC future carry is a flat 1% a year; single
    stocks 3.5% a year borrow plus costs. CAC spot (7,802.8) is hard-coded in the report.
11. **Data fragility.** CNBC and Eurex endpoints are unofficial or scraped; Eurex settles lag a day.
12. **Already fixed in v5, keep them covered by tests:** FOAT/FGBL are price-quoted, so short FOAT / long FGBL is
    long the yield spread (sign verified on real settles); risk-box add sizes (−9/+8, −14/+13, −20/+18).

## 6. Mapping to CryoQuant

| Need | Existing CryoQuant piece | Proposal |
|------|--------------------------|----------|
| Yield and settle history | `cryoquant.data.macro_store` (`write_series` / `write_frame`) | Study-local ingest (`manual` / `cnbc` / `eurex` keys) first; promote a CNBC or Eurex source only if a second study needs it |
| Yahoo stocks, ^FCHI | `load_track(Symbol("yahoo", …))` | Register the tickers in `cryocore/instruments.py` |
| FRED IRLTLT01FR/DE/IT | FRED macro routing | Register the series |
| Futures specs, fees, rolls | `cryoquant.backtest.account` (`InstrumentSpec`, `ExecutionModel`, `RollPolicy`) | Add FOAT / FGBL / FCE / MFC specs; check the module fits €-denominated, physically delivered bond futures |
| Black-76 / Bachelier | none | Zero domain semantics → candidate for a framework pricing module (decide in Phase 0) |
| Path simulator, stop / pyramid engine | none (`breakout_sim`, `simulate` are signal-driven backtests on history) | Start in `src/`; promote if a second study wants scenario Monte Carlo |
| Robustness | `cryoquant.backtest.robustness` (bootstrap CI) | Use for Monte Carlo confidence intervals on the means |
| Reports | `cryoquant.reporting.html_brand`, `charts`, `manifest` | Rebuild both reports from RESULTS JSON; keep narrative text in config or markdown, not in code |

## 7. Out of scope / parked

- Daily-check automation through IB Gateway (discussed 9 Oct, parked).
- Sending reports: the v5 pitch and trade-detail files were emailed to an outside investor on 9 Oct 2026 from
  misc. v6 reports go back to the misc job for distribution.
