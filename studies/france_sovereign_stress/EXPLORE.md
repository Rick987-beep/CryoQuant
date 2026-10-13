# EXPLORE — france_sovereign_stress

Snapshot `2026-10-12T0941` · entry spread 137.34 bp · budget €10,000 · n=2000 · seed=11 · rule `stop 40, add every +20 (lock 0%)` · execution `daily_close`.

Static counterpart to the Cursor canvas explorer. Phase 6 pitch HTML is deferred.

## Fine exit grid

Right-world exits **200:400:10** bp. Default costs: **€2.0/side** fee + **€5.0** half-tick (Lynx live commission; half-tick for a 1-tick market).

At **300 bp**: mean **11.73×**, median **15.28×**, p10 **-0.10×**, p90 **16.89×**, lost **25.3%**.

| Exit bp | Mean | p10 | p25 | p50 | p75 | p90 | Lost |
|--------:|-----:|----:|----:|----:|----:|----:|-----:|
| 200 | 2.04× | -0.10× | -0.04× | 2.64× | 3.01× | 3.23× | 25.9% |
| 220 | 3.05× | -0.10× | -0.04× | 3.91× | 4.39× | 4.71× | 25.4% |
| 240 | 4.52× | -0.10× | -0.04× | 5.79× | 6.45× | 6.87× | 25.4% |
| 260 | 6.63× | -0.10× | -0.04× | 8.46× | 9.43× | 10.02× | 25.3% |
| 280 | 9.15× | -0.10× | -0.04× | 11.84× | 12.87× | 13.40× | 25.3% |
| 300 | 11.73× | -0.10× | -0.04× | 15.28× | 16.30× | 16.89× | 25.3% |
| 320 | 14.31× | -0.10× | -0.04× | 18.72× | 19.76× | 20.34× | 25.2% |
| 340 | 16.86× | -0.10× | -0.04× | 22.17× | 23.09× | 23.70× | 25.2% |
| 360 | 19.45× | -0.10× | -0.04× | 25.62× | 26.50× | 27.18× | 25.1% |
| 380 | 22.01× | -0.10× | -0.04× | 29.06× | 29.94× | 30.58× | 25.1% |
| 400 | 24.59× | -0.10× | -0.04× | 32.47× | 33.38× | 34.01× | 25.1% |

## Execution and costs (checked)

- **Instruments:** short FOAT / long FGBL (DV01-neutral); optional short CAC.
- **Fees:** €2.00/contract/side, matching Lynx commission on a live OAT fill (12 Oct 2026). Half-tick €5 kept (1-tick market).
- **Bid–ask:** half-tick (€5) per leg — matches a 1-tick book with aggressive fills in European hours. Markets closed weekends (Mon–Fri only).
- **Execution:** `daily_close` baseline; 1 bp stop slip; quarterly rolls charged.

## Artifacts

- [`explore.html`](explore.html) — branded chart + table
- `data/exit_level_grid.json` — machine-readable curves (gitignored)
- [`RESULTS.md`](RESULTS.md) — Phase 5 v5 reconciliation

Rebuild: `python studies/france_sovereign_stress/run_explore_report.py`
