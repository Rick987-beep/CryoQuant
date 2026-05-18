# Reference Material

**This directory is read-only by intent.** It contains frozen copies of existing work, used as a
learning aid and a migration source. New code goes into `cryoquant/` and `cryocore/`, not here.

## Contents

### `long_tradable_options/`
Full copy of `/Users/ulrikdeichsel/IndicatorBench/research/long_tradable_options/`.
Contains the V2 spot-signal discovery pipeline (scripts `01`–`12`) — feature builders, AUC tables,
train/test runs, option universe scans, real-options P&L lookups, and exit-rule optimisations.

**Highest-value entry points:**
- `06_v2_spot_signals.py` — `build_features()` (the V2 12-feature set) and `add_outcomes()`. Will
  become `cryoquant/features/builders.py::V2SpotFeaturesV1` and `cryoquant/features/labels.py`.
- `11b_option_universe.py` / `11c_pnl_lookup.py` / `11d_optimise.py` — the real-Deribit P&L
  pipeline. Will become `cryoquant/backtest/option_lookup.py`.
- `V2_PLAN.md` — narrative of the research findings (pullback, vol_burst, bear_burst signals).

### `pineforge_snapshot/`
Selected modules from `/Users/ulrikdeichsel/IndicatorBench/pineforge/pineforge/`:
- `data.py` — BTC parquet loader, multi-TF resample, closed-bar-safe HTF align.
- `fetch_binance.py` — Binance spot kline fetcher with incremental resume.
- `schemas.py` — Pydantic models (RunSpec, RunResult, FeedSpec, ...).
- `ta.py` — technical primitives.
- `calendars.py` — trading calendars.
- `eval.py`, `coverage.py`, `bakeoff.py`, `report.py` — evaluation + reporting pipeline.
- `trend.py`, `registry.py`, `compose.py` — candidate registry and runner.
- `robustness.py`, `artifacts.py` — supporting utilities.
- `feeds/` — funding-rate plugin + the `FEED_ATTACH` registry pattern.

## CryoBacktester dependency

CryoQuant reads option parquets directly from CryoBacktester via configured path. We do **not**
copy that data here — it's gigabytes and CryoBacktester is the source of truth.

See [`cryobacktester_notes.md`](cryobacktester_notes.md) for details.
