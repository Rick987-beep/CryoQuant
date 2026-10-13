# RESULTS — france_sovereign_stress (v6 Phase 5)

Snapshot `2026-10-09T1456` · budget €10,000 · n=10000 · seed=11 · execution default `daily_close` · common random numbers.

## HANDOVER §4 reconciliation

| Item | v5 | v6 | Diff / cause |
|------|----|----|--------------|
| Calibration €/bp FOAT / FGBL / hedge | 87.58 / 96.57 / 0.907 | 87.58 / 96.57 / 0.907 | same 20-day regression on v5 settles ✓ |
| Carry FOAT / FGBL bp/day | 0.114 / 0.015 | 0.114 / 0.015 | same calendar/63 formula ✓ |
| Daily vol spread / Bund / ρ | 3.18 / 3.95 / 0.14 | 3.18 / 3.95 / 0.14 | same 126-day window ✓ |
| Live P&L 3/3 FOAT/FGBL 11 Sep→8 Oct | +€11,490 (+44.8 bp) | +€11,490 (+44.8 bp) | settlement mark-to-market ✓ |
| Spread 40/+20 means @ 240/300/340/400 | 4.47 / 11.67 / 16.65 / 24.29× | 4.46× / 11.58× / 16.65× / 24.26× | daily-close + common RNG (v5: resting stop, seed+i per level); Δ@300=-0.09× ✓ |
| Spread 40/+20 @300 median / lost / ≥10× / wrong | 15.21× / 25.2% / 74.7% / 0.53× | 15.18× / 25.6% / 74.4% / 0.51× | same rule; execution/CRN differences as above ✓ |
| Spread 30/+15 mean @300 | 11.88× (41% lost) | 11.73× (41.6% lost) | daily-close CRN ✓ |
| Vol × 1.5, spread 40/+20 @300 | 8.36×, 46% lost | 8.21×, 46.5% lost | σ×1.5 on same CRN family ✓ |
| Bund-flight terciles @300 | 11.63 / 11.63 / 11.74× | 11.55× / 11.45× / 11.73× | terciles of f on CRN paths ✓ |
| Timing terciles @300 | 16.06 / 12.10 / 7.74× | 15.68× / 11.32× / 7.65× | terciles of tc; CRN changes timing mix vs v5 seeds ✓ |
| Short CAC stop 12/+6 @300 | 3.41× mean, 4.00× median, 21% lost, wrong 0.84× | 3.38× mean, 4.00× median, 21.6% lost, wrong 0.81× | daily-close CRN ✓ |
| CAC betas × 0.6 @300 | 2.47× | 2.34× | beta_mult=0.6 ✓ |
| Mix 75% spread / 25% CAC @300 | 9.60× mean, 12.39× median, 13% lost; corr 0.36 | 9.53× mean, 12.35× median, 13.5% lost; corr 0.35 | common-path mix ✓ |
| Options (OGBL/OOAT) | best OGBL 2.45×; OOAT 1.38×; ATM IV 11.9% | parked | Phase 0 scope: spread + CAC only |
| Monitoring daily-close / weekly / stop-only | 11.65× / 9.10–9.37× / 3.78× | daily-close 11.58×; resting 11.59×; stop-only 3.73×; weekly not re-run | v6 default=daily-close; weekly calendars deferred ✓ |
| Straight-line equity 240/300/340/400 | €76,563 / €181,664 / €251,730 / €356,831 | €76,563 / €181,664 / €251,730 / €356,831 | integer FOAT ladder, identical formula ✓ |
| Calmer vol window (pre-2026-09) @300 | (not in v5 primary) | 13.25× mean, 15.1% lost (σ_s=2.40) | v6 sensitivity; primary remains 126d stress window |

## Primary book (spread stop 40 / +20, daily-close)

- Means by level: 4.46× / 11.58× / 16.65× / 24.26×
- At 300 bp: mean 11.58×, median 15.18×, lost 25.6%, ≥10× 74.4%
- Wrong world: 0.51×
- Integer contracts @ 300: mean 11.73×, median 15.37×

## Sensitivities

- **resting_stop**: @300 mean 11.59×, lost 25.6%
- **stop_30_15**: @300 mean 11.73×, lost 41.6%
- **vol_x1.5**: @300 mean 8.21×, lost 46.5%
- **calmer_vol**: σ_s=2.40; @300 mean 13.25×, lost 15.1%
- **bund_flight_terciles**: 11.55× / 11.45× / 11.73×
- **timing_terciles**: 15.68× / 11.32× / 7.65×
- **cac**: mean 3.38×, median 4.00×, wrong 0.81×
- **cac_beta_0.6**: mean 2.34×
- **mix_75_25**: mean 9.53×, median 12.35×, corr 0.35
- **stop_only**: @300 mean 3.73×

## Notes

- Options families are **parked** (Phase 0 scope: spread + CAC).
- v5 used `seed + i` per level; v6 uses common random numbers (documented difference).
- v6 default execution is daily-close; resting-stop reported as sensitivity.
- Phase 6 pitch HTML **deferred**. Scenario explorer: [`explore_interactive.html`](explore_interactive.html) (interactive), [`EXPLORE.md`](EXPLORE.md), [`explore.html`](explore.html).

Machine-readable: `data/phase5_evaluate.json` (gitignored; regenerate via `run_phase5_evaluate.py`).
