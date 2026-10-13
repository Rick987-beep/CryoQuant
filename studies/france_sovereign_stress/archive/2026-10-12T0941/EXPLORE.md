# EXPLORE — france_sovereign_stress

Snapshot `2026-10-12T0941` · entry spread 137.34 bp · budget €10,000 · n=2000 · seed=11 · rule `stop 40, add every +20 (lock 0%)` · execution `daily_close`.

Static counterpart to the Cursor canvas explorer. Phase 6 pitch HTML is deferred.

## Fine exit grid

Right-world exits **200:400:10** bp. Default costs: **€2.35/side** fee + **€5.0** half-tick (Lynx/IBKR-style proxy; Eurex exchange ~€0.27/contract on top in live trading).

At **300 bp**: mean **11.72×**, median **15.28×**, p10 **-0.10×**, p90 **16.89×**, lost **25.3%**.

| Exit bp | Mean | p10 | p25 | p50 | p75 | p90 | Lost |
|--------:|-----:|----:|----:|----:|----:|----:|-----:|
| 200 | 2.04× | -0.10× | -0.04× | 2.64× | 3.00× | 3.23× | 25.9% |
| 220 | 3.05× | -0.10× | -0.04× | 3.91× | 4.39× | 4.71× | 25.4% |
| 240 | 4.51× | -0.10× | -0.04× | 5.78× | 6.44× | 6.86× | 25.4% |
| 260 | 6.62× | -0.10× | -0.04× | 8.45× | 9.42× | 10.01× | 25.3% |
| 280 | 9.14× | -0.10× | -0.04× | 11.83× | 12.86× | 13.39× | 25.3% |
| 300 | 11.72× | -0.10× | -0.04× | 15.28× | 16.29× | 16.89× | 25.3% |
| 320 | 14.30× | -0.10× | -0.04× | 18.72× | 19.75× | 20.34× | 25.2% |
| 340 | 16.86× | -0.10× | -0.04× | 22.16× | 23.08× | 23.70× | 25.2% |
| 360 | 19.44× | -0.10× | -0.04× | 25.61× | 26.49× | 27.17× | 25.1% |
| 380 | 22.00× | -0.10× | -0.04× | 29.05× | 29.94× | 30.57× | 25.1% |
| 400 | 24.58× | -0.10× | -0.04× | 32.46× | 33.38× | 34.01× | 25.1% |

## Execution and costs (checked)

- **Instruments:** short FOAT / long FGBL (DV01-neutral); optional short CAC.
- **Fees:** €2.35/contract/side in sim ≈ Lynx €2.00 + Eurex A-account ~€0.27.
- **Bid–ask:** half-tick (€5) per leg — matches a 1-tick book with aggressive fills in European hours. Markets closed weekends (Mon–Fri only).
- **Execution:** `daily_close` baseline; 1 bp stop slip; quarterly rolls charged.

## Artifacts

- [`explore.html`](explore.html) — branded chart + table
- `data/exit_level_grid.json` — machine-readable curves (gitignored)
- [`RESULTS.md`](RESULTS.md) — Phase 5 v5 reconciliation

Rebuild: `python studies/france_sovereign_stress/run_explore_report.py`
