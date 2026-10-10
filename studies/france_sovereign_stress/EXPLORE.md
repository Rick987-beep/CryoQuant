# EXPLORE — france_sovereign_stress

Snapshot `2026-10-09T1456` · budget €10,000 · n=2000 · seed=11 · rule `stop 40, add every +20 (lock 0%)` · execution `daily_close`.

Static counterpart to the Cursor canvas explorer. Phase 6 pitch HTML is deferred.

## Fine exit grid

Right-world exits **200:400:10** bp. Default costs: **€2.35/side** fee + **€5.0** half-tick (Lynx/IBKR-style proxy; Eurex exchange ~€0.27/contract on top in live trading).

At **300 bp**: mean **11.58×**, median **15.21×**, p10 **-0.11×**, p90 **16.74×**, lost **25.8%**.

| Exit bp | Mean | p10 | p25 | p50 | p75 | p90 | Lost |
|--------:|-----:|----:|----:|----:|----:|----:|-----:|
| 200 | 2.01× | -0.12× | -0.04× | 2.64× | 2.99× | 3.19× | 27.0% |
| 220 | 3.02× | -0.11× | -0.04× | 3.90× | 4.36× | 4.65× | 26.2% |
| 240 | 4.46× | -0.11× | -0.04× | 5.75× | 6.39× | 6.76× | 25.9% |
| 260 | 6.55× | -0.11× | -0.04× | 8.48× | 9.38× | 9.90× | 25.9% |
| 280 | 9.04× | -0.11× | -0.04× | 11.77× | 12.74× | 13.31× | 25.9% |
| 300 | 11.58× | -0.11× | -0.04× | 15.21× | 16.17× | 16.74× | 25.8% |
| 320 | 14.09× | -0.11× | -0.04× | 18.56× | 19.57× | 20.15× | 25.8% |
| 340 | 16.61× | -0.11× | -0.04× | 22.01× | 22.98× | 23.51× | 25.8% |
| 360 | 19.14× | -0.11× | -0.04× | 25.41× | 26.36× | 26.84× | 25.8% |
| 380 | 21.66× | -0.11× | -0.04× | 28.82× | 29.68× | 30.32× | 25.8% |
| 400 | 24.18× | -0.11× | -0.04× | 32.23× | 33.11× | 33.72× | 25.8% |

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
