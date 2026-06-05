# CryoQuant

CryoQuant is a research-to-backtest quant pipeline for systematic trading workflows:

data -> features -> labels -> models -> signals -> backtests

It was built from crypto-native research, with particular roots in BTC spot and options trading
(including Deribit chain analysis and option PnL evaluation). The architecture is
asset-agnostic, but the first productionized workflows are crypto-focused.

## Why this repo exists

CryoQuant gives you one place to:

- Ingest and cache market data (Binance spot/perp, Deribit options snapshots, optional macro series)
- Build versioned features
- Train and calibrate predictive models
- Publish actionable signals
- Evaluate strategy behavior in spot and options contexts

It is designed for quant developers who want reproducible local research loops with typed Python
modules, deterministic feature sets, and portable backtest artifacts.

## Current status

- v1 baseline pipeline is implemented and tested
- First end-to-end strategy is included:
  - EMA 7/21 crossover on BTCUSDT (spot backtest)
  - Directional options follow-through on Deribit chains (call/put evaluation around crossover events)

## Tech stack

- Python 3.12+
- pandas, numpy, pyarrow, duckdb, pydantic
- scikit-learn, lightgbm, optuna, shap
- local parquet + DuckDB catalog (no mandatory cloud infra)

See [pyproject.toml](pyproject.toml) for dependency definitions.

## Repository layout

- [cryocore](cryocore): Shared domain types and time/calendar helpers
- [cryoquant](cryoquant): Main pipeline package (data, features, models, signals, backtest)
- [scripts](scripts): Runnable end-to-end examples
- [docs](docs): Design and usage documentation
- [tests](tests): Test suite
- [notebooks](notebooks): Exploratory analysis notebooks
- [reports](reports): Generated HTML reports
- [reference](reference): Read-only research lineage and snapshots

## Quick start

1. Create and activate a Python 3.12 environment.
2. Install package in editable mode with dev extras:

```bash
pip install -e ".[dev]"
```

3. Run tests:

```bash
python -m pytest tests/ -v
```

4. Run the spot EMA crossover example:

```bash
python scripts/ema_cross_backtest.py
```

5. Run the options example:

```bash
python scripts/ema_cross_options_backtest.py
```

Generated reports are written under [reports](reports).

## Configuration

Runtime paths and source settings are in [cryoquant/config.py](cryoquant/config.py).

Common environment overrides:

- CRYOQUANT_STORE_ROOT: where local market parquet data is stored
- CRYOQUANT_CATALOG_DB: DuckDB catalog path
- CRYOBACKTESTER_DATA_DIR: path to Deribit options/spot parquet snapshots used by options backtests
- FRED_API_KEY: optional macro series API key

If your machine layout differs, you can also use local overrides via config_local.py support
already present in config loading.

## What you can run today

Spot workflow:

- Load BTC daily bars from Binance
- Build EMA-cross features
- Simulate long and short legs
- Compute summary metrics and robustness stats
- Render HTML reports

Entry point: [scripts/ema_cross_backtest.py](scripts/ema_cross_backtest.py)

Options workflow:

- Reuse spot-side signal events (EMA crosses)
- Select option legs by DTE and delta from Deribit daily chain snapshots
- Evaluate mark-to-market or expiry outcomes
- Generate directional options performance reports

Entry point: [scripts/ema_cross_options_backtest.py](scripts/ema_cross_options_backtest.py)

## CLI surface

Basic CLI commands are available via:

```bash
python -m cryoquant.cli --help
```

Implemented command groups include catalog/model listing and stubs for signal publishing/backtest
wrappers. CLI entry point: [cryoquant/cli/__init__.py](cryoquant/cli/__init__.py).

## Data model and design principles

- UTC-first, tz-aware timestamps
- Closed-bar safety for feature generation
- Versioned feature builders and reusable dataset references
- Local-first storage and reproducible outputs
- Strict schema style and typed interfaces

## Crypto/options lineage

CryoQuant is intentionally rooted in crypto derivatives research:

- Initial signal and validation loops are BTC-centric
- Options evaluation path is built around Deribit chain data
- Practical integration targets include options-aware backtesting and downstream live execution systems

If you are a quant developer coming from equities or futures, the patterns are transferable, but
you should expect crypto-native assumptions in early examples and reference material.

## Documentation map

- Usage walkthrough: [docs/how_to_use.md](docs/how_to_use.md)
- Add a signal: [docs/how_to_add_a_signal.md](docs/how_to_add_a_signal.md)
- Implementation spec: [docs/quant_spec.md](docs/quant_spec.md)
- Project decisions: [docs/decisions.md](docs/decisions.md)
- Glossary: [docs/glossary.md](docs/glossary.md)

## Typical workflow for a new quant experiment

1. Load or refresh market data through the data loader.
2. Build or extend a feature set in the features layer.
3. Define labels for your prediction horizon.
4. Train a baseline or tabular model.
5. Convert outputs to typed signals.
6. Run spot or options backtests and inspect reports.
7. Iterate with feature/version changes and compare run artifacts.

## Testing

Default test run:

```bash
python -m pytest tests/ -v
```

Pytest markers are configured in [pyproject.toml](pyproject.toml), including optional live and
slow handling.

## Notes for contributors

- Keep public functions typed.
- Prefer deterministic feature and model IDs.
- Preserve UTC/time safety assumptions across modules.
- Add or update tests for any behavior change.
