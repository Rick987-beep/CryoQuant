# RESULTS — france_sovereign_stress (v6 Phase 5)

Snapshot `2026-10-12T0941` · start 2026-10-12 · entry spread 137.34 bp (quote 2026-10-12T09:41:38.000+0200) · calibration history to 2026-10-09 · budget €10,000 · n=10000 · seed=11 · execution default `daily_close` · common random numbers.

## Change vs the 2026-10-09T1456 run

| Item | 2026-10-09T1456 | 2026-10-12T0941 | Change |
|------|-----:|-----:|-------:|
| Entry spread (bp) | 138.00 | 137.34 | -0.66 |
| FOAT € per bp | 87.58 | 88.32 | +0.74 |
| FGBL € per bp | 96.57 | 97.43 | +0.86 |
| Hedge ratio FGBL per FOAT | 0.907 | 0.906 | -0.000 |
| Net carry (bp/day) | 0.099 | 0.103 | +0.003 |
| Spread vol (bp/day) | 3.179 | 3.179 | +0.000 |
| Bund vol (bp/day) | 3.953 | 3.915 | -0.038 |
| Spread/Bund correlation | 0.144 | 0.137 | -0.007 |
| Mean @ 240 bp | 4.46× | 4.50× | +0.05× |
| Mean @ 300 bp | 11.58× | 11.69× | +0.11× |
| Mean @ 340 bp | 16.65× | 16.79× | +0.14× |
| Mean @ 400 bp | 24.26× | 24.47× | +0.21× |
| Median @ 300 bp | 15.18× | 15.34× | +0.17× |
| Stopped out @ 300 bp (%) | 25.6 | 25.7 | +0.1 |
| ≥10× @ 300 bp (%) | 74.4 | 74.3 | -0.0 |
| No-event mean | 0.51× | 0.51× | -0.00× |
| No-event stopped out (%) | 60.3 | 61.0 | +0.6 |
| Integer contracts mean @ 300 | 11.73× | 11.87× | +0.14× |
| Sensitivity: resting_stop | @300 mean 11.59×, lost 25.6% | @300 mean 11.70×, lost 25.7% |  |
| Sensitivity: stop_30_15 | @300 mean 11.73×, lost 41.6% | @300 mean 12.00×, lost 40.9% |  |
| Sensitivity: vol_x1.5 | @300 mean 8.21×, lost 46.5% | @300 mean 8.48×, lost 45.3% |  |
| Sensitivity: calmer_vol | σ_s=2.40; @300 mean 13.25×, lost 15.1% | σ_s=2.40; @300 mean 13.33×, lost 15.4% |  |
| Sensitivity: bund_flight_terciles | 11.55× / 11.45× / 11.73× | 11.55× / 11.91× / 11.60× |  |
| Sensitivity: timing_terciles | 15.68× / 11.32× / 7.65× | 15.88× / 11.85× / 7.26× |  |
| Sensitivity: cac | mean 3.38×, median 4.00×, wrong 0.81× | mean 3.41×, median 4.00×, wrong 0.82× |  |
| Sensitivity: cac_beta_0.6 | mean 2.34× | mean 2.35× |  |
| Sensitivity: mix_75_25 | mean 9.53×, median 12.35×, corr 0.35 | mean 9.62×, median 12.49×, corr 0.37 |  |
| Sensitivity: stop_only | @300 mean 3.73× | @300 mean 3.75× |  |

## HANDOVER §4 reconciliation (informational on a fresh snapshot)

| Item | v5 | v6 | Diff / cause |
|------|----|----|--------------|
| Calibration €/bp FOAT / FGBL / hedge | 87.58 / 96.57 / 0.907 | 88.32 / 97.43 / 0.906 | same 20-day regression on v5 settles |
| Carry FOAT / FGBL bp/day | 0.114 / 0.015 | 0.117 / 0.014 | same calendar/63 formula |
| Daily vol spread / Bund / ρ | 3.18 / 3.95 / 0.14 | 3.18 / 3.91 / 0.14 | same 126-day window |
| Live P&L 3/3 FOAT/FGBL 11 Sep→8 Oct | +€11,490 (+44.8 bp) | +€11,490 (+44.8 bp) | settlement mark-to-market ✓ |
| Spread 40/+20 means @ 240/300/340/400 | 4.47 / 11.67 / 16.65 / 24.29× | 4.50× / 11.69× / 16.79× / 24.47× | daily-close + common RNG (v5: resting stop, seed+i per level); Δ@300=+0.02× |
| Spread 40/+20 @300 median / lost / ≥10× / wrong | 15.21× / 25.2% / 74.7% / 0.53× | 15.34× / 25.7% / 74.3% / 0.51× | same rule; execution/CRN differences as above |
| Spread 30/+15 mean @300 | 11.88× (41% lost) | 12.00× (40.9% lost) | daily-close CRN |
| Vol × 1.5, spread 40/+20 @300 | 8.36×, 46% lost | 8.48×, 45.3% lost | σ×1.5 on same CRN family |
| Bund-flight terciles @300 | 11.63 / 11.63 / 11.74× | 11.55× / 11.91× / 11.60× | terciles of f on CRN paths ✓ |
| Timing terciles @300 | 16.06 / 12.10 / 7.74× | 15.88× / 11.85× / 7.26× | terciles of tc; CRN changes timing mix vs v5 seeds ✓ |
| Short CAC stop 12/+6 @300 | 3.41× mean, 4.00× median, 21% lost, wrong 0.84× | 3.41× mean, 4.00× median, 21.2% lost, wrong 0.82× | daily-close CRN |
| CAC betas × 0.6 @300 | 2.47× | 2.35× | beta_mult=0.6 |
| Mix 75% spread / 25% CAC @300 | 9.60× mean, 12.39× median, 13% lost; corr 0.36 | 9.62× mean, 12.49× median, 13.6% lost; corr 0.37 | common-path mix |
| Options (OGBL/OOAT) | best OGBL 2.45×; OOAT 1.38×; ATM IV 11.9% | parked | Phase 0 scope: spread + CAC only |
| Monitoring daily-close / weekly / stop-only | 11.65× / 9.10–9.37× / 3.78× | daily-close 11.69×; resting 11.70×; stop-only 3.75×; weekly not re-run | v6 default=daily-close; weekly calendars deferred |
| Straight-line equity 240/300/340/400 | €76,563 / €181,664 / €251,730 / €356,831 | €78,359 / €184,343 / €254,998 / €360,981 | integer FOAT ladder, identical formula |
| Calmer vol window (pre-2026-09) @300 | (not in v5 primary) | 13.33× mean, 15.4% lost (σ_s=2.40) | v6 sensitivity; primary remains 126d stress window |

## Primary book (spread stop 40 / +20, daily-close)

- Means by level: 4.50× / 11.69× / 16.79× / 24.47×
- At 300 bp: mean 11.69×, median 15.34×, lost 25.7%, ≥10× 74.3%
- Wrong world: mean 0.51×, median -0.06×, lost 61.0%
- Integer contracts @ 300: mean 11.87×, median 15.57×

## Sensitivities

- **resting_stop**: @300 mean 11.70×, lost 25.7%
- **stop_30_15**: @300 mean 12.00×, lost 40.9%
- **vol_x1.5**: @300 mean 8.48×, lost 45.3%
- **calmer_vol**: σ_s=2.40; @300 mean 13.33×, lost 15.4%
- **bund_flight_terciles**: 11.55× / 11.91× / 11.60×
- **timing_terciles**: 15.88× / 11.85× / 7.26×
- **cac**: mean 3.41×, median 4.00×, wrong 0.82×
- **cac_beta_0.6**: mean 2.35×
- **mix_75_25**: mean 9.62×, median 12.49×, corr 0.37
- **stop_only**: @300 mean 3.75×

## Notes

- Options families are **parked** (Phase 0 scope: spread + CAC).
- v5 used `seed + i` per level; v6 uses common random numbers (documented difference).
- v6 default execution is daily-close; resting-stop reported as sensitivity.
- Phase 6 pitch HTML **deferred**. Scenario explorer: [`explore_interactive.html`](explore_interactive.html) (interactive), [`EXPLORE.md`](EXPLORE.md), [`explore.html`](explore.html).
- Earlier runs: [`archive/`](archive/) (results, explorer and data per snapshot stamp).

Machine-readable: `data/phase5_evaluate.json` (gitignored; regenerate via `run_phase5_evaluate.py`).
