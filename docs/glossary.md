# Glossary

Definitions for the core concepts used across CryoQuant. If something here disagrees with code,
**update the code**; this document is the source of truth.

---

## Symbol

A `(venue, ticker)` pair identifying a tradable or observable instrument.

```python
Symbol(venue="binance.spot", ticker="BTCUSDT")
Symbol(venue="deribit",      ticker="BTC")
Symbol(venue="nyse",         ticker="AAPL")
Symbol(venue="fred",         ticker="DXY")
```

Symbols are always frozen, hashable, and serialise to `"<venue>:<ticker>"`.

## Instrument

Static metadata about a `Symbol`: asset class, quote currency, tick size, trading calendar id,
free-form meta. Loaded from a registry; not stored alongside time series data.

## Calendar

A pluggable function `is_open(ts: datetime) -> bool` plus session helpers. Implementations:
`crypto_24_7`, `nyse`, `cme_futures`, `fx_eur`, ... Used by calendar features (`is_us_session`,
`is_market_open`) and by data validators (gaps during closed periods are not errors).

## Feature

A **numeric or boolean input column** computed from one or more data sources.

- **Tier 1 (primitives / calendar):** pure function, no version, no cache. E.g. `ema_24`,
  `is_us_session`, `dow`.
- **Tier 2 (feature set):** a named, versioned `FeatureBuilder` producing multiple columns.
  Optionally cached on disk. E.g. `V2SpotFeaturesV1` produces 12 columns. Cache key includes
  `feature_set_id + version + symbol + tf + range`.

Features are never "actionable" on their own — they are inputs.

## Label

A column representing the **outcome** to predict. Forward-looking by construction; always shifted
appropriately to avoid look-ahead.

Example: `mag_win_2p5_h24 = (max(close[t+1..t+24]) / close[t] - 1) >= 0.025`.

## Model

A fitted thing with `.fit(X, y)` and `.predict_proba(X) -> [0,1]`. Three concrete classes:

- **`RuleModel`** — a boolean condition over features; `predict_proba` returns the empirical win
  rate from training. Calibration "for free".
- **`TabularModel`** — sklearn-style classifier, always wrapped in `CalibratedClassifierCV`.
- **`SequenceModel`** — temporal NN. Deferred.

`model_id` = sha1 of `feature_set_id | labeler | class | hparams | train_window`.

## Signal

An **actionable claim about the future**, derived from a model or a rule.

| Class | Output | Typical source |
|---|---|---|
| `BoolSignal` | `bool` | Rule over features |
| `StateSignal` | `int ∈ {-1, 0, +1}` + flips | Trend classifier (pineforge contract) |
| `ProbSignal` | `prob ∈ [0,1]` + horizon + threshold | Trained `Model` |

All three implement a common `Signal` protocol (`.emit(t)`, `.id`, `.metadata`).
Signals are consumed by **publishers** (CryoTrader adapter, CSV emitter, Pine emitter).

## Indicator

**Not a class.** Anything displayable on a chart — a feature column, a signal time series, an
intermediate calculation. Purely a presentation concept.

## Publisher

Adapts a `Signal` to a specific consumer's interface.

- `cryotrader_adapter` — returns a callable matching CryoTrader's `EntryCondition` signature.
- `csv_emitter` — writes parquet for notebooks / dashboards.
- `pine_emitter` — emits Pine v5 snippet (only from `BoolSignal`/`StateSignal`).

## Experiment

One folder under `cryoquant/experiments/<id>/` containing a YAML/TOML config + a thin script.
Fully reproducible: the config is the input, the run folder is the output. No "I tweaked the
script and reran" — bump the config.

## RunSpec / RunResult

Pydantic models (in `cryocore.schemas`) describing the inputs and outputs of one evaluation.
Cross-repo contract: CryoBacktester, CryoTrader, and CryoQuant all understand them.
