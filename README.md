# CryoQuant

Asset-agnostic quant pipeline for predicting price moves over hours-to-days horizons.
Built on the work in `IndicatorBench/pineforge` and `IndicatorBench/research/long_tradable_options`,
integrates with **CryoBacktester** (canonical options engine) and **CryoTrader** (live execution).

**Status:** Phase 0 scaffolding. No code yet — just structure + reference material + plan.

## Where to start

1. Read [`docs/quant_plan.md`](docs/quant_plan.md) — the canonical plan and architecture.
2. Read [`docs/glossary.md`](docs/glossary.md) — taxonomy for Symbol / Feature / Signal / Model.
3. Read [`docs/decisions.md`](docs/decisions.md) — log of material decisions.
4. Skim [`reference/`](reference/) — copies of existing research code and pineforge modules
   we are migrating from.

## Setup

```bash
cd /Users/ulrikdeichsel/CryoQuant
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

## Layout

See [`docs/quant_plan.md`](docs/quant_plan.md) §3 for the full directory layout and the
rationale for each module.

```
cryocore/         # Shared package (will also be used by CryoBacktester/CryoTrader later)
cryoquant/        # The pipeline: data → features → models → signals → backtest
docs/             # Planning documents (this is where new plans / ADRs / specs go)
reference/        # READ-ONLY copies of existing work (long_tradable_options, pineforge)
tests/
notebooks/
```

## Sibling repos (do not modify from here)

- `/Users/ulrikdeichsel/CryoBacktester` — options backtester. Source of truth for option parquets at `backtester/data/`.
- `/Users/ulrikdeichsel/CryoTrader` — live trading system. Eventual consumer of `ProbSignal`s.
- `/Users/ulrikdeichsel/IndicatorBench` — TradingView Pine indicators + the original pineforge lab.

## Conventions

- Python 3.12, local-only, parquet on disk + DuckDB as query layer.
- UTC everywhere, tz-aware, bar-open-timestamp labelling.
- Pydantic v2 schemas with `extra="forbid"`.
- No look-ahead: every feature builder has a closed-bar-safety unit test.
- `model_id` / `feature_set_id` / `signal_id` / `run_id` = sha1 of canonical-JSON inputs.
