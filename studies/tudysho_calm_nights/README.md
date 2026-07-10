# Tudysho calm nights — session extrusion study

CryoQuant study handover from CryoBacktester (Jul 2026).

**Question:** Does a quiet morning (or London+US window) predict a quiet afternoon and overnight hold — and do **scheduled macro/earnings events** in the afternoon/evening explain the gaps?

## Start here

| Doc | Purpose |
|-----|---------|
| [KICKOFF.md](KICKOFF.md) | Handover brief — status, goals, upstream repos |
| [PLAN.md](PLAN.md) | Full research plan, completed results, Phase 4 events |
| [CALENDAR.md](CALENDAR.md) | Event data sources (FOMC, CPI/NFP, MAG7 earnings) |
| [package/](package/) | Reference package: tudysho strategy, live params, turbulence |
| [config.yaml](config.yaml) | Study parameters and data paths |

## Run phases

```bash
cd /Users/ulrikdeichsel/CryoQuant
source .venv/bin/activate

# Compare predictor variants (Phase 0 + 3)
python studies/tudysho_calm_nights/run_compare_predictors.py

# Per variant:
python studies/tudysho_calm_nights/run_phase0_session_extrusion.py --predictor us_morning
python studies/tudysho_calm_nights/run_phase0_session_extrusion.py --predictor london_us
python studies/tudysho_calm_nights/run_phase3_continuous_calm.py --predictor london_us

# Phase 4 — fetch event calendar via macro_store
python studies/tudysho_calm_nights/run_ingest_calendar.py

# Phase 1–2
python studies/tudysho_calm_nights/run_phase1_feature_rank.py
python studies/tudysho_calm_nights/run_phase2_calm_score.py

# QA + tests
python studies/tudysho_calm_nights/run_phase0_qa.py --predictor london_us
python studies/tudysho_calm_nights/run_phase3_qa.py --predictor london_us
python -m pytest studies/tudysho_calm_nights/tests/ -q
```

Outputs land in `studies/tudysho_calm_nights/data/` and `reports/` (gitignored).

### Narrative reports

| Report | Description |
|--------|-------------|
| [study_a_binary_calm_mornings.html](reports/study_a_binary_calm_mornings.html) | Phase 0 — binary calm hypothesis |
| [study_b_continuous_calm_index.html](reports/study_b_continuous_calm_index.html) | Phase 3 — continuous MCI + entry schedule |
| [predictor_comparison.html](reports/predictor_comparison.html) | US morning vs London+US side-by-side |

Per-variant detail: `reports/{us_morning,london_us}/`.

## Data dependencies

| Source | Path / API |
|--------|------------|
| BTC 15m spot | `load_track(Symbol("binance.spot", "BTCUSDT"), "15m", …)` |
| Deribit options | `CRYOBACKTESTER_DATA_DIR` |
| FOMC / macro / earnings | `cryoquant.data.sources.economic_events` → `macro_store` |
| Live params | `package/strategy/params/*.json` |

## Phases

1. **Phase 0** — Session extrusion + binary hypothesis (`--predictor`)
2. **Phase 1** — Feature ranking vs tail days
3. **Phase 2** — `overnight_calm_score` prototype
4. **Phase 3** — Continuous calm index + walk-forward entry schedule
5. **Phase 3b** — Predictor comparison (`us_morning` vs `london_us`)
6. **Phase 4** — Event calendar + afternoon/hold-night impact *(active)*
7. **Phase 5** — CryoBacktester profile gates
8. **Phase 6** — Walk-forward validation in backtester

Promotion rule: study-local code stays here until a second consumer needs it; then move to `cryoquant/`.
