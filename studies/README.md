# Studies — usage layer

CryoQuant’s **framework** is `cryocore/` + `cryoquant/`. Everything under `studies/` is **usage**: hypothesis workspaces that import the library and never the reverse.

| Kind | Role | Layout cues |
|------|------|-------------|
| **Project** | Phased research with PLAN / RESULTS / HANDOVER | `run_phase*.py`, `src/`, `tests/` |
| **Adhoc** | Path-A one-off jobs without ceremony | `jobs/`, shared `config.yaml` |
| **Private** | Local-only (root `.gitignore`) | Not published |

Canonical layout:

```text
studies/<name>/
  README.md | PLAN.md | HANDOVER.md | RESULTS.md   # as applicable
  config.yaml | universe.yaml
  run_*.py | jobs/          # projects: phases; adhoc: jobs/
  src/                      # study-local only
  tests/
  input/ data/ bundles/ reports/   # data/reports usually gitignored
```

Kickoff / PLAN frontmatter should include: `status`, `path` (A/B/C), `isProject` (true for phased projects).

Path A demos that are not studies live in [`scripts/`](../scripts/) and [`notebooks/`](../notebooks/).

---

## Index

### Projects

| Study | Status | Path | Notes |
|-------|--------|------|-------|
| [`cdx/`](cdx/) | Active / phases 1–5 done | B | CDX.NA.IG overlays; Overlay 3 pending; VIX correlation add-on |
| [`BTCpredict/`](BTCpredict/) | Implemented through Phase 7 | C | ML exemplar; no HANDOVER yet |
| [`tudysho_calm_nights/`](tudysho_calm_nights/) | Complete (HANDOVER) | B | Slot-A calm entry; Ch.2 feature screen |
| [`tudysho_exit_policy/`](tudysho_exit_policy/) | Complete (HANDOVER) | B | Exit/stop layer on Preset B |
| [`tudysho_aggressive_entry/`](tudysho_aggressive_entry/) | Complete (HANDOVER) | B | Reverse-engineering aggressive entries |
| [`tudysho_calm_regime/`](tudysho_calm_regime/) | Complete through Phase 5 (HANDOVER) | B | Multi-week calm → aggressiveness; chain-label re-fit pending |
| [`tudysho_calm_regime_chain/`](tudysho_calm_regime_chain/) | Active (Phase 1) | B | Parallel chain-settlement label refit (does not overwrite parent) |
| [`tenx_thielen_scorecard/`](tenx_thielen_scorecard/) | Active | A (+ B-lite) | 10x Research / Markus Thielen prediction scorecard vs CryoQuant prices |
| [`VIXStrategy/`](VIXStrategy/) | Active (Phase 0) | A | Daily CBOE VIX OHLC strategy; proxy/hypothesis TBD |

### Adhoc

| Study | Status | Path | Notes |
|-------|--------|------|-------|
| [`misc/`](misc/) | Active | A | Job bag: theta, BTC vol, entry move, correlations, … |

### Private (gitignored — leave local)

| Study | Notes |
|-------|-------|
| `hedged_btc/` | Phase-1 snapshot |
| `trend_following/` | Paused at Phase 2 |
| `quickwintrend/` | Sweep RESULTS frozen; partner artifacts |

---

## Library promote backlog

**Promote rule:** move into `cryoquant/` / `cryocore/` when a **second study** needs it, or when it has **zero domain semantics**. Keep hypothesis economics in `studies/`.

### Already promoted (2026-07)

| Capability | Library location |
|------------|------------------|
| Deribit index spot bars | `cryoquant.data.sources.deribit_spot_bars` |
| NYC / Deribit expiry sessions | `cryoquant.sessions.nyc` |
| Study path scaffolding | `cryoquant.study_paths.StudyPaths` |
| Branded HTML report helpers | `cryoquant.reporting.html_brand` |
| Extrusion / Parkinson metrics | `cryoquant.features.extrusion` |
| Turbulence composite | `cryoquant.features.turbulence` |
| Overnight calm score | `cryoquant.features.calm_score` |

### Ready when a second consumer appears

| Candidate | Current home | Target |
|-----------|--------------|--------|
| CDX.NA.IG ingest + panel align | `studies/cdx/src/ingest.py` | `cryoquant.data.sources.cdx` |
| APAC / BoJ decision calendar | `studies/tudysho_aggressive_entry/src/apac_calendar.py` | `cryoquant.data.sources` (next to FOMC) |
| CryoBacktester combo bundle loader | `studies/tudysho_aggressive_entry/src/bundle_loader.py` | `cryoquant.backtest` |
| Deribit fee / spread model | `studies/tudysho_exit_policy/src/costs.py` | `cryoquant.backtest` |
| Pair lead-lag / OLS helpers | `studies/cdx/src/cdx_vix_correlation.py`, `studies/misc/src/correlation.py` | `cryoquant.features` |
| Options ATM IV / IV-rank context | `studies/tudysho_calm_nights/src/options_context.py` | `cryoquant.features.options` |
| Settlement / short-strangle PnL | `studies/tudysho_calm_nights/src/settlement.py` | `cryoquant.backtest` |
| QA causality guards | `studies/tudysho_*/src/qa/causality.py` | `cryoquant.qa` |
| Config-driven overlay loader | `studies/misc/src/loads.py` | `cryoquant.data` |

### Stay study-local

Phase runners, narrative HTML reports, tudysho policies / counterfactuals, CDX overlay economics, misc job-specific PnL stories.
