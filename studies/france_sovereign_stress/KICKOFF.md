---
name: france_sovereign_stress
status: active
path: B
isProject: true
overview: >
  v6 rebuild of the France sovereign-stress trade study (OAT–Bund spread to 240 bp+ by 1 Jul 2027).
  v1–v5 were built as ad-hoc scripts in ~/misc/jobs/france-sovereign-stress; v6 rebuilds data, pricing,
  simulation and reporting as tested CryoQuant modules and must reproduce or explain the v5 numbers.
todos:
  - id: phase0-scaffold
    content: "Scaffold, read HANDOVER, decide framework vs study-local for each module"
    status: completed
  - id: phase1-data
    content: "Ingest yields, Eurex settles, Eurex option chains, Yahoo, FRED into macro_store / study data with QA"
    status: completed
  - id: phase2-pricing
    content: "Instruments + pricing: FOAT/FGBL DV01 and carry, Black-76 / Bachelier, P&L reconciliation"
    status: completed
  - id: phase3-paths
    content: "Scenario path generator (right / wrong worlds, event model) with tests"
    status: completed
  - id: phase4-rules
    content: "Stop / pyramid / take-profit rule engine on integer contracts, daily-close execution, rolls, costs"
    status: completed
  - id: phase5-evaluate
    content: "Candidate sweep (spread, CAC, options), sensitivities, v5 reconciliation table"
    status: completed
  - id: phase6-report
    content: "HTML pitch reports deferred; explorer report (EXPLORE.md + reports/explore.html) shipped"
    status: cancelled
---

# Kickoff — france_sovereign_stress (v6)

## Purpose

Rebuild the France sovereign-stress trade model inside CryoQuant: cleaner modules, unit tests, documented
assumptions, and an explicit reconciliation against v5. The trade view is unchanged: the OAT–Bund 10-year spread
widens from about 138 bp to at least 240 bp before 1 July 2027 (base-case exit 300 bp).

Start with [HANDOVER.md](HANDOVER.md). It describes what v5 does, where every number comes from, the known weak
spots and the acceptance checks.

## Decisions carried over from v5 (user-confirmed)

| Topic | Choice |
|-------|--------|
| View | Spread ≥ 240 bp by 1 Jul 2027; ladder of exit levels 240 / 300 / 340 / 400 bp, optimise at 300 |
| Budget | €10,000 per unit; lose all of it if wrong is acceptable |
| Rules | Hard stop, no re-entry, pyramiding allowed; exit when the spread reaches the target level |
| Exclusions | No French banks |
| Accounts | IBKR / LYNX for futures and stocks; Swissquote only for Eurex options (OOAT not at IBKR) |
| Orders | Research only. Never place orders from this study |
| Expected values | Not required. Report conditional payouts (right world by level, wrong world) and the scenario odds side by side |

## Phase 0 decisions (locked)

See PLAN.md § Phase 0 decisions. Summary: spread + CAC; framework data sources only;
causal closed-bar pipeline; 126-day vol primary; v5 event model for acceptance.
