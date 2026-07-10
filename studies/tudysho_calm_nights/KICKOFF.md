---
name: Tudysho calm nights — kickoff
handover_from: CryoBacktester
handover_date: 2026-07-09
status: phase4_events
primary_kpi: contracts_per_trade at fixed nav_premium_pct (0.8%), win rate ≥ 97%
isProject: false
---

# Kickoff — handover from CryoBacktester

## Current status (Jul 2026)

| Phase | Status | Summary |
|-------|--------|---------|
| 0 — Binary extrusion | ✓ | Lift ~1.6×; contract −58%; false-calm & extrusion-safe **fail** |
| 1 — Features | ✓ | Tail-day ranking vs turbulence / IV |
| 2 — calm_score | ✓ | Prototype score |
| 3 — Continuous MCI | ✓ | Spearman 0.31; permutation p 0.0005; gates pass |
| 3b — Predictors | ✓ | London+US beats US morning on OOS ρ (0.38 vs 0.31) |
| **4 — Event calendar** | **→ active** | FOMC, CPI/NFP, MAG7 earnings vs afternoon/hold calm |
| 5 — CryoBacktester | pending | Profile gates after CryoQuant validation |
| 6 — WFO | pending | |

See [PLAN.md](PLAN.md) for full results and [CALENDAR.md](CALENDAR.md) for Phase 4 data sources.

## Why this lives in CryoQuant

The research question is **feature engineering + hypothesis testing**, not backtester engine work:

- Session extrusion metrics on BTC spot (morning / afternoon / overnight)
- Conditional probability: quiet morning → quiet night
- Counterfactual: earlier entry × higher delta on calm days
- Continuous calm index + scheduled macro/earnings risk (Phase 4)

CryoBacktester remains the execution simulator for **Phase 5+** once gates are validated here.

## Strategy under study: tudysho

**TuDySho** sells short-DTE, low-delta BTC option strangles on Deribit. Entry is turbulence-gated after an NYC wall-clock `entry_time`. Sizing targets `nav_premium_pct` of NAV.

Slot A (Mon–Thu, 16:00 NYC, δ=0.10, turbulence < 60) is the primary focus. Params frozen in [`package/strategy/`](package/strategy/).

### The problem

Late entry + low delta → many contracts per leg at 0.8% NAV. Win rate ~99% but execution is painful.

### The hypothesis (evolved)

1. **Morning extrusion** (Phase 0–3): quiet predictor window → quiet hold night → earlier entry, fewer contracts.
2. **Event risk** (Phase 4): afternoon/evening scheduled releases (FOMC, earnings) may break morning calm → need calendar-aware gating.

## Optimization target

**Primary:** Reduce `contracts_per_trade` at fixed `nav_premium_pct` without breaching 97% win rate.

## Upstream references

| Repo | What we read |
|------|--------------|
| **CryoBacktester** | `tudysho.py`, turbulence, handover package |
| **CryoQuant** | `cryoquant.data.sources.fomc_calendar` for FOMC |

## Success criteria

### Phase 0 (binary) — partial pass

| Test | Result |
|------|--------|
| Lift | ✓ ~1.6× |
| Contract reduction | ✓ ~58–60% |
| False calm | ✗ ~12–14% (target 0.7%) |
| Extrusion safe | ✗ ~46–48% (target 97%) |

### Phase 3 (continuous) — pass

Walk-forward MCI→HCI correlation and permutation tests pass; prefer **london_us** predictor.

### Phase 4 (events) — TBD

Quantify incremental false-calm and hold-night extrusion on tier-1 event days in the hold window.

## Next step

```bash
python run_ingest_calendar.py
```
