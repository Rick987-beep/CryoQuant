# Tudysho reference package

Read-only handover from CryoBacktester (2026-07-09). **Do not treat as live config** — verify against `handover/tudysho_cryotrader/` before production changes.

## Contents

```
package/
├── strategy/
│   ├── OVERVIEW.md          # Slots, headline stats, sizing
│   ├── LOGIC.md             # Entry / exit / concurrency rules
│   ├── params/
│   │   ├── schedule.json    # Slot calendar + combo hashes
│   │   ├── slot_a_mon_thu.json
│   │   ├── slot_b_mon_early.json
│   │   └── slot_c_fri_sat.json
│   └── backtest_stats.json  # Per-slot isolated backtest metrics
└── indicators/
    ├── TURBULENCE.md        # Indicator spec + tudysho usage
    └── turbulence_reference.py  # Snapshot of CryoBacktester indicators/turbulence.py
```

## Upstream sources

| CryoBacktester path | This copy |
|---------------------|-----------|
| `analysis/tudysho_slots_marketing/params.json` | `strategy/params/schedule.json` |
| `handover/tudysho_cryotrader/params/*.json` | `strategy/params/` |
| `handover/tudysho_cryotrader/backtests/summary.json` | `strategy/backtest_stats.json` |
| `indicators/turbulence.py` | `indicators/turbulence_reference.py` |
| `handover/tudysho_cryotrader/STRATEGY_LOGIC.md` | `strategy/LOGIC.md` (condensed) |

## Promotion note

Per CryoQuant D3, turbulence is not yet in `cryoquant/features/`. If Phase 2 validates `overnight_calm_score`, promote a cleaned version to `cryoquant/features/` — do not import from `studies/` in framework code.
