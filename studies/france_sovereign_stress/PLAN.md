---
name: france_sovereign_stress
status: active
path: B
isProject: true
overview: >
  v6 rebuild of the France sovereign-stress study as tested CryoQuant modules, reconciled against v5.
todos:
  - id: phase0-scaffold
    content: "Read HANDOVER; lock module boundaries (framework vs src/); environment check"
    status: completed
  - id: phase1-data
    content: "Ingest + QA all inputs; reproduce v5 inputs byte-for-byte from input/v5_reference first"
    status: completed
  - id: phase2-pricing
    content: "Instruments, DV01 / carry calibration, Black-76 / Bachelier; P&L reconciliation (+€11,490)"
    status: completed
  - id: phase3-paths
    content: "Scenario generator with common random numbers; optional peak-and-retrace"
    status: completed
  - id: phase4-rules
    content: "Rule engine on integer contracts; daily-close execution baseline; rolls; costs"
    status: completed
  - id: phase5-evaluate
    content: "Sweep, sensitivities, v5 reconciliation table in RESULTS.md"
    status: completed
  - id: phase6-report
    content: "Pitch + trade-detail HTML from RESULTS JSON (deferred; explorer report shipped instead)"
    status: cancelled
  - id: explore-report
    content: "Fine exit grid + EXPLORE.md + explore.html"
    status: completed
---

# PLAN — france_sovereign_stress (v6)

## Module layout (as built)

```text
src/
  paths.py          # StudyPaths wrapper
  data/             # reference loads + QA (v5 freeze + live CNBC/Eurex/FRED/Yahoo)
  instruments.py    # FOAT / FGBL / FCE / MFC specs
  calibrate.py      # DV01, carry, vols, correlations, stock betas
  scenarios.py      # right / wrong worlds, event model, common random numbers
  rules.py          # stop / pyramid engine, continuous + integer, daily-close / resting
  evaluate.py       # payout stats, mixes, sensitivities
run_phase1_data.py … run_phase5_evaluate.py
run_explore_report.py
tests/
```

Options pricing / pitch HTML remain parked (Phase 0 scope).

## Phases and exit criteria

| Phase | Deliverable | Done when |
|-------|-------------|-----------|
| 0 | Boundaries + env | Module list approved by the user; `pytest studies/france_sovereign_stress` green |
| 1 | Data | All inputs load from `input/v5_reference` and from live sources; QA report (gaps, duplicates, stale days) |
| 2 | Pricing | DV01 cross-checked two ways; P&L on 11 Sep → 8 Oct settles reproduces +€11,490; Black-76 parity and known-value tests |
| 3 | Paths | Unit tests: wrong world driftless, right world hits the level on tc, Bund-flight share within range, seed reproducibility |
| 4 | Rules | Deterministic straight-line test reproduces the v5 exit equity (€76,563 / €181,664 / €251,730 / €356,831 at 240 / 300 / 340 / 400 bp); integer-contract variant reported |
| 5 | Evaluate | RESULTS.md table: every v5 number in HANDOVER §4 next to v6, difference and cause |
| 6 | Report | **Deferred.** Explorer shipped instead: `EXPLORE.md` + `explore.html` via `run_explore_report.py` |

## Conventions

- Research only; no broker or order code.
- Every phase writes JSON under `data/` and a short section in RESULTS.md.
- Keep v5 code under `input/v5_reference/scripts` read-only; do not import it.

## Phase 0 decisions (locked 10 Oct 2026)

| Topic | Decision |
|-------|----------|
| Scope | Spread (FOAT/FGBL) + CAC short first; options parked |
| Framework | Promote **data sources / series only** (CNBC yields, Eurex settles, FRED LT aliases, Yahoo tickers). Pricing, Monte Carlo, rules stay in `src/` |
| Causality | Closed-bar / as-of decisions; daily-close execution baseline; no lookahead |
| Vol primary | Last 126 business days (v5); calmer pre-stress window as sensitivity |
| Event model | Match v5 for acceptance; peak-and-fail optional later |
