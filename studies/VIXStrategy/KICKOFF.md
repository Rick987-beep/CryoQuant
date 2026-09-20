---
name: VIXStrategy
status: active
path: A
isProject: true
overview: >
  Dual-overlay VIX study on daily CBOE OHLC with a dollar Mini-VIX (VXM)
  account. Overlay Y isolation complete; Overlay T + compose next.
todos:
  - id: scaffold
    content: "Create studies/VIXStrategy tree, config, universe, paths, phase0"
    status: completed
  - id: phase0-data
    content: "Ingest CBOE VIX OHLC (~2010+), QA, write research-window parquet"
    status: completed
  - id: phase1-overlay-y
    content: "Overlay Y isolation on $100k VXM account + HTML report"
    status: completed
  - id: phase1-overlay-t
    content: "Overlay T + compose with Y (mutex)"
    status: pending
  - id: hypothesis-proxy
    content: "Lock tradable proxy vs cash-VIX signal semantics"
    status: pending
  - id: report
    content: "Keep RESULTS.md + HTML report current with each re-run"
    status: completed
---

# Kickoff — VIXStrategy

## Purpose

Develop a **rules-based dual-overlay strategy on VIX** (Overlay T = spike catcher,
Overlay Y = mean-reversion income) inside CryoQuant, on clean daily CBOE OHLC
with a realistic dollar futures account.

## Decisions so far

| Topic | Choice |
|-------|--------|
| Series | CBOE VIX daily OHLC (`cboe:VIX` → `VIX_{OPEN,HIGH,LOW,CLOSE}`) |
| Research window | **Exact trailing 10 calendar years → yesterday UTC** (override only if asked) |
| Ingest history | From 2010-01-01 (avoids early CBOE open quirks) |
| Account | $100k · Mini VIX (**VXM**) $100/pt · integer contracts |
| Execution | `ExecutionModel` hooks for fees / spread / slippage (currently 0) |
| Overlay Y | Y1 z-score · Y2 percentile · Y3 crush-fade; OHLC touch fills |
| Path | **A** first; Path B if we sweep |

## Open

- Overlay T definition + fear-episode catalog
- T+Y mutex / capital split
- Whether cash VIX remains the signal underlier vs trading VX/VXM directly in production
- Contract sizing policy for risk-matched screens

## Layout

```text
studies/VIXStrategy/
  PLAN.md | README.md | KICKOFF.md | config.yaml | universe.yaml
  run_phase0_data.py | run_ingest.py | run_phase1_overlay_y.py
  src/paths.py | src/vix_data.py | src/overlay_y.py | src/report_overlay_y.py | …
  tests/
  data/ reports/   # gitignored artifacts
```

## Next

1. Spike / fear catalog (Phase 1a)
2. Overlay T + compose with Y
3. Refresh RESULTS.md whenever the grid is re-run
