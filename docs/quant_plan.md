# CryoQuant — Plan v2 (refined)

**Date:** 18 May 2026
**Workspace:** `/Users/ulrikdeichsel/CryoQuant` (new, fresh git repo, Python 3.12, local-only)
**Purpose:** A pragmatic, asset-agnostic quant pipeline that turns timeline data → features → models → calibrated signals → backtests, with final consumers being **CryoTrader** (live, automated) and **research notebooks/dashboards**. Built on the lessons of `pineforge` and `research/long_tradable_options`, integrating with `CryoBacktester` as the canonical options engine.

This document supersedes any previous draft. Decisions are baked in; sections with `[OPEN]` flag what is still unresolved.

> **Implementation detail lives in [`quant_spec.md`](quant_spec.md).** This plan stays high-level
> (what, why); the spec defines module APIs, acceptance tests, and live tests per phase.

---

## 1. Decisions made

| # | Decision | Why |
|---|---|---|
| D1 | New sibling workspace `/Users/ulrikdeichsel/CryoQuant`, fresh git repo. | Clean boundary; CryoBacktester/CryoTrader can `pip install -e ../CryoQuant` later. |
| D2 | `cryocore` shared package lives **inside** CryoQuant for now. | Avoid premature multi-repo overhead. Promote to its own repo once the API stabilises. |
| D3 | **Do not touch CryoBacktester** until CryoQuant has produced its first usable signal. Do not pre-port its `indicators/` into `cryocore`. | Stay focused; integrate when there's a concrete reason. |
| D4 | Reference material from `IndicatorBench` (the long_tradable_options scripts, pineforge modules) is **copied** into `CryoQuant/reference/`, not symlinked. | Robustness > disk savings. |
| D5 | Python 3.12. | Matches CryoBacktester and the surrounding ecosystem. |
| D6 | Asset-agnostic from day one: `Symbol = (venue, ticker)`, `Instrument` record, pluggable calendars. | Cheap to design in now, painful to retrofit. |
| D7 | Local-only — no cloud, no Airflow, no managed DBs. Parquet on disk, DuckDB as query layer. | Single-developer pragmatic stack. |
| D8 | BTCUSD end-to-end first. Then ETH, then opportunistic non-crypto (equities/FX/macro) as candidates demand. | Prove the pipeline before generalising. |
| D9 | Options data: read **directly** from `CryoBacktester/backtester/data/*.parquet` via configured absolute path. Zero re-ingestion. | One source of truth. CryoBacktester's pipeline already works. |
| D10 | Macro + on-chain ingestion: design the abstraction now, stub one FRED source (DXY) as smoke test. Build real sources only when a candidate signal needs them. | YAGNI on data we don't yet use. |
| D11 | Two-tier features: Tier-1 primitives (no store, recomputed) + Tier-2 named/versioned/optionally-cached feature sets. | The "feature store" applies only to expensive/tracked features. |
| D12 | Three signal classes: `BoolSignal`, `StateSignal`, `ProbSignal` — all implement a common `Signal` protocol. "Indicator" is a presentation concept, not a class. | Matches how signals actually vary in nature (rules, regimes, ML outputs). |
| D13 | Planning documents live under `CryoQuant/docs/`. This file is the canonical plan. | One place to look. |
| D14 | **Use libraries freely.** When a well-maintained, free library does the job better than hand-rolled code, install and use it. Do not write workarounds or re-implement functionality that already exists in good quality elsewhere. | Less code to maintain; more proven correctness. |

---

## 2. Concepts & taxonomy

### 2.1 Symbol & Instrument

```python
@dataclass(frozen=True)
class Symbol:
    venue: str      # "binance.spot", "binance.perp", "deribit", "nyse", "fred", "cme"
    ticker: str     # "BTCUSDT", "BTC", "AAPL", "DXY", "ES"

@dataclass(frozen=True)
class Instrument:
    symbol: Symbol
    asset_class: Literal["crypto", "equity", "fx", "rates", "commodity", "option", "macro"]
    quote_ccy: str
    tick_size: float | None
    calendar_id: str        # "crypto_24_7", "nyse", "cme_futures", "fx_eur", ...
    meta: dict              # free-form: lot_size, contract_size, etc.
```

Calendars are first-class so day-of-week / session features work uniformly across asset classes. `crypto_24_7` is the trivial calendar.

### 2.2 Features — two tiers

**Tier 1 — primitives & calendar features.** Pure functions; recomputed on every call; no version, no store.
```python
df["dow"]            = df.index.dayofweek
df["is_us_session"]  = us_session_mask(df.index)
df["ema_24"]         = ema(df["close"], 24)
df["atr_14"]         = atr(df, 14)
df["rv_24h"]         = realised_vol(df["close"], 24)
```
Lives in `cryoquant/features/primitives.py` and `cryoquant/features/calendar_features.py`.

**Tier 2 — named feature sets.** A `FeatureBuilder` declares an `id`, `version`, `inputs` (datasets), and a deterministic `build(df) → DataFrame`. Caching is **opt-in** via a `@cached` decorator; only triggered when (a) compute is non-trivial (>~1s for a year of data) or (b) the feature set feeds a tracked model.

Cache layout: `cryoquant/features/store/<feature_set_id>/<venue>_<ticker>_<tf>.parquet`.
Cache key includes `version`, so a logic change invalidates automatically.

### 2.3 Labels

Symmetric to features. A `Labeler` declares horizon + threshold and emits a `{target}_h{H}_t{thresh}` column. Reuse the existing `add_outcomes()` pattern from `06_v2_spot_signals.py`. Multiple labelers per dataset is fine.

### 2.4 Signals — three flavours, one protocol

```python
class Signal(Protocol):
    id: str
    metadata: dict
    def emit(self, t: pd.Timestamp) -> SignalEmit: ...
```

Three concrete kinds, all sharing the same protocol:

| Class | `.emit(t)` returns | Source | Pine-portable? |
|---|---|---|---|
| `BoolSignal` | `bool` | A condition over features. `BTC_IS_UP_TODAY`, `pullback_fires`. | Yes |
| `StateSignal` | `state ∈ {-1, 0, +1}` + flips | A classifier. The existing pineforge contract. | Yes |
| `ProbSignal` | `prob ∈ [0, 1]` + horizon + threshold + calibration | A trained model (LightGBM, etc.). | No (Pine can't run gbm) |

Same time series can simultaneously be:
- a **feature column** (input to other models, displayable on charts) — every signal is implicitly also a feature.
- a **signal** (actionable claim) — published to consumers.

So `BTC_IS_UP_TODAY` is a `BoolSignal` *and* available as a boolean feature — no duplication. "Indicator" = anything displayable on a chart; doesn't need its own class.

### 2.5 Models

```python
class Model(Protocol):
    id: str
    feature_set_id: str
    horizon_hours: int
    def fit(self, X, y, sample_weight=None) -> None: ...
    def predict_proba(self, X) -> np.ndarray:   # P(label=1) per row
```

Three concrete kinds:

1. **`RuleModel`** — a boolean condition over features; `predict_proba` returns the empirical win rate from training. This is how `pullback`, `vol_burst`, `bear_burst` (from the V2 spot research) enter the system without losing them.
2. **`TabularModel`** — wrapper around LightGBM (primary) and sklearn `LogisticRegression` / `RandomForest` (baselines). **Always wrapped in `CalibratedClassifierCV`** (isotonic). LightGBM is the default for tabular crypto features.
3. **`SequenceModel`** — temporal CNN / `pytorch-forecasting`. Deferred; only added if tabular plateaus.

---

## 3. Target architecture

```
CryoQuant/
├── README.md
├── pyproject.toml                  # Python 3.12; deps below
├── .gitignore
├── docs/                           # All planning + decision docs
│   ├── quant_plan.md               # THIS FILE
│   ├── decisions.md                # ADR-style log (one entry per material decision)
│   └── glossary.md                 # Symbol / Feature / Signal / Model definitions
│
├── cryocore/                       # Shared package (used by CryoBacktester/Trader later)
│   ├── __init__.py
│   ├── time.py                     # UTC, bar-open conventions, tz helpers
│   ├── calendars.py                # crypto_24_7, nyse, cme, fx_eur
│   ├── instruments.py              # Symbol, Instrument
│   └── schemas.py                  # Cross-repo Pydantic models: ProbSignal, BoolSignal,
│                                   # StateSignal, RunSpec, RunResult
│
├── cryoquant/                      # The pipeline package
│   ├── __init__.py
│   ├── config.py                   # Paths: cryobt_data_dir, fred_api_key, store_root…
│   │
│   ├── data/                       # 1. sourcing + storage
│   │   ├── sources/
│   │   │   ├── binance_spot.py     # Port of pineforge.fetch_binance
│   │   │   ├── binance_perp.py     # Funding + (later) OI
│   │   │   ├── deribit_options.py  # READ-ONLY against CryoBacktester parquets
│   │   │   └── fred.py             # Stub: DXY only, for smoke test
│   │   ├── catalog.py              # DuckDB catalog of available datasets
│   │   └── loader.py               # load(symbol, tf, start, end) → DataFrame
│   │
│   ├── features/                   # 2. + 3. processing & extraction
│   │   ├── primitives.py           # EMA, ATR, BB, ADX, RV, vol_z, rv_rank…
│   │   ├── calendar_features.py    # day_of_week, hour_of_day, is_us_session, is_weekend…
│   │   ├── options.py              # iv_vs_rv, atm_iv_ts, skew_25d, butterfly_25d,
│   │   │                           # vol_of_vol, forward_curve_slope
│   │   ├── builders.py             # Tier-2 named feature sets (V2SpotFeaturesV1, …)
│   │   ├── labels.py               # ForwardReturnLabeler
│   │   ├── store.py                # @cached decorator + on-disk parquet store
│   │   └── catalog.yaml            # Declarative list of registered feature sets
│   │
│   ├── models/                     # 4. modelling
│   │   ├── base.py                 # Model protocol
│   │   ├── baselines.py            # RuleModel; pullback/vol_burst/bear_burst as instances
│   │   ├── tabular.py              # LightGBM + isotonic calibration wrapper
│   │   ├── cv.py                   # purged-KFold (López de Prado) + walk-forward
│   │   ├── registry.py             # DuckDB-backed model registry
│   │   └── artifacts/              # serialised model files (joblib)
│   │
│   ├── signals/                    # 5. indicators FROM models
│   │   ├── base.py                 # BoolSignal, StateSignal, ProbSignal classes
│   │   ├── thresholds.py           # prob → action threshold maps
│   │   └── publishers/
│   │       ├── cryotrader_adapter.py   # → CryoTrader EntryCondition callable
│   │       ├── csv_emitter.py          # → parquet for notebooks/dashboards
│   │       └── pine_emitter.py         # → Pine v5 snippet (BoolSignal/StateSignal only)
│   │
│   ├── backtest/                   # 6. validation
│   │   ├── spot_pnl.py             # Fast vectorised spot evaluator
│   │   ├── option_lookup.py        # Library-fied 11b/11c/11d (real Deribit P&L)
│   │   ├── cryobt_bridge.py        # Adapt a Signal → CryoBacktester strategy (later)
│   │   ├── robustness.py           # Deflated Sharpe, bootstrap CIs
│   │   └── reports/                # HTML report templates
│   │
│   ├── experiments/                # One folder per experiment: config + thin script
│   │
│   └── cli/                        # `python -m cryoquant.cli ...`
│
├── notebooks/                      # Jupyter — exploration only
│
├── reference/                      # READ-ONLY copies of existing work, for learning
│   ├── README.md                   # What's in here and why
│   ├── long_tradable_options/      # Whole research/long_tradable_options/ tree copied
│   ├── pineforge_snapshot/         # data.py, schemas.py, ta.py, eval.py, coverage.py,
│   │                               # bakeoff.py, trend.py, calendars.py, registry.py,
│   │                               # feeds/, report.py
│   └── cryobacktester_notes.md     # Pointers to which CryoBacktester files we depend on
│
└── tests/
    └── test_smoke.py               # Imports + "load BTC 1h" round-trip
```

---

## 4. Six-stage pipeline mapped to the architecture

### 4.1 Data sourcing & storage *(stage 1)*
- **Sources, priority order:**
  1. Binance spot klines (BTC, ETH; 1m–1d) — port from `pineforge.fetch_binance`.
  2. Binance perp funding + OI — funding done; OI deferred until needed.
  3. Deribit option chains + IV — read directly from `/Users/ulrikdeichsel/CryoBacktester/backtester/data/{options,spot}_YYYY-MM-DD.parquet`. No copying, no re-ingestion. Path lives in `cryoquant/config.py`.
  4. FRED stub (DXY) — smoke test of the source plug-in pattern.
  5. *(later, on demand)* On-chain (Glassnode/CryptoQuant), equities (yfinance / paid).
- **Storage:** Parquet, partitioned by `source/symbol/tf/year=YYYY/`. **DuckDB** sits on top as SQL query layer over the parquets — no ETL step.
- **Catalog:** DuckDB table `datasets(source, symbol, tf, path, row_count, ts_min, ts_max, schema_hash, last_refresh)`. `python -m cryoquant.cli catalog list` prints it.
- **Closed-bar safety** is non-negotiable — port the `htf_align` and feed-`attach()` pattern verbatim.

### 4.2 Data processing & cleanup *(stage 2)*
- Canonical shape per dataset type (OHLCV bars, event stream, option chain snapshot). UTC, tz-aware, indexed by open-ts (bars) or event-ts (events).
- Schema validation via Pydantic on read. Outlier guards (NaN OHLC drops, absurd-volume clamps) logged not silenced.

### 4.3 Feature extraction *(stage 3)*
Per **D11**, two tiers (see §2.2). Specific feature packs to deliver:

**Calendar pack** (Tier 1, ~no cost):
- `dow`, `hour_utc`, `is_us_session`, `is_eu_session`, `is_asia_session`, `is_weekend`, `is_us_holiday`, `minutes_since_midnight_utc`.

**Price-action pack** (Tier 1, may be promoted to Tier 2 builders):
- `ret_1h/4h/1d`, `accel_1h`, `close_vs_ema_24/168`, `rv_24h`, `rv_rank`, `bb_width`, `vol_z`, `range_ratio`, `atr_pct`. *(These are the V2 features — already validated.)*

**Options pack** (Tier 2 — first-class, since this is where the predictive juice for hours-to-days horizons lives):
- `iv_minus_rv_<w>` — IV richness vs realised vol.
- `atm_iv_term_structure` — front vs back, slope, curvature.
- `risk_reversal_25d` — `call_iv_25d − put_iv_25d` (skew).
- `butterfly_25d` — smile convexity.
- `vol_of_vol` — rolling std of ATM IV.
- `forward_curve_slope` — perp/futures basis (when ingested).

**Microstructure pack** (deferred, hook only):
- funding-z, OI delta, basis.

**Macro pack** (stub only):
- DXY 1d return, VIX level. Only DXY ships.

### 4.4 Modelling *(stage 4)*
- Three model classes per §2.5.
- CV: purged-KFold for model selection, walk-forward for the deployment-realistic metric.
- Every trained `TabularModel` wrapped in `CalibratedClassifierCV(method="isotonic")`.
- Metrics emitted per model: AUC, Brier, log-loss, reliability diagram, confusion @ threshold, spot-P&L (via §4.6).
- `model_id = sha1(canonical(feature_set_id | labeler | class | hparams | train_window))`. Registry is a DuckDB table.
- Hyperparam search: **Optuna** (TPE) — much better than grid for >3 params.
- Explainability: **SHAP** for sanity checks.
- No MLflow until we have dozens of models — overkill.

### 4.5 Signals *(stage 5)*
- Three signal classes per §2.4.
- **`ProbSignal` payload** (Pydantic, lives in `cryocore.schemas`):
  ```python
  class ProbSignal(BaseModel):
      ts: datetime
      symbol: Symbol
      model_id: str
      direction: Literal["up", "down", "magnitude"]
      horizon_hours: int
      prob: float
      threshold_used: float
      confidence_band: tuple[float, float] | None
  ```
- **Publishers** (one per consumer):
  - `cryotrader_adapter.py` — returns a callable matching CryoTrader's `EntryCondition` shape.
  - `csv_emitter.py` — writes signal time series to parquet for notebooks / Panel dashboards.
  - `pine_emitter.py` — emits Pine v5 snippet from `BoolSignal`/`StateSignal` (not `ProbSignal`).

### 4.6 Backtesting & validation *(stage 6)*
- **Fast spot evaluator** (`spot_pnl.py`): vectorised next-bar-open execution; equity, drawdown, Sharpe, win rate, expectancy, per-regime breakdown. ≤1s for years of 1h data. Used during model selection.
- **Real-options evaluator** (`option_lookup.py`): library version of `11b/11c/11d`. Takes a `Signal` + DTE/delta/exit grid; returns expected $/fire, win rate, peak distribution. Reads CryoBacktester parquets directly.
- **CryoBacktester bridge** (`cryobt_bridge.py`): adapt a Signal into CryoBacktester's `Strategy` protocol and invoke its full engine. **Built only after CryoQuant has produced its first viable signal** (per **D3**).
- **Validation discipline** (non-negotiable):
  1. Walk-forward for any deploy-bound model.
  2. Deflated Sharpe Ratio for multi-test inflation.
  3. Probability calibration check (reliability diagram).
  4. Regime breakdown.
  5. Bootstrap CIs on win rate / expectancy.

---

## 5. Migration map

| Existing | Destination in CryoQuant |
|---|---|
| `pineforge/pineforge/data.py` | `cryoquant/data/loader.py` |
| `pineforge/pineforge/fetch_binance.py` | `cryoquant/data/sources/binance_spot.py` |
| `pineforge/pineforge/feeds/` | `cryoquant/data/sources/` + feed-attach helpers in `loader.py` |
| `pineforge/pineforge/ta.py` | `cryoquant/features/primitives.py` |
| `pineforge/pineforge/calendars.py` | `cryocore/calendars.py` |
| `pineforge/pineforge/schemas.py` | Split: cross-repo types → `cryocore/schemas.py`; internal → respective modules |
| `pineforge/pineforge/trend.py` candidates | `cryoquant/models/baselines.py` (as `RuleModel`s) |
| `pineforge/pineforge/eval.py`, `coverage.py`, `bakeoff.py`, `report.py` | `cryoquant/backtest/` |
| `research/long_tradable_options/06_v2_spot_signals.py::build_features` | `cryoquant/features/builders.py::V2SpotFeaturesV1` |
| `research/long_tradable_options/06.add_outcomes` | `cryoquant/features/labels.py::ForwardReturnLabeler` |
| `research/long_tradable_options/11a-d` | `cryoquant/backtest/option_lookup.py` (library-fied) |
| Discovered signals (pullback, vol_burst, bear_burst) | `cryoquant/models/baselines.py` as `RuleModel` instances |

---

## 6. Library shortlist

| Layer | Library | Notes |
|---|---|---|
| Data fetching | `requests`, `pandas-datareader` / `fredapi`, (optional) `ccxt` | Existing direct-Binance code is fine; `ccxt` only if a venue stretches us |
| Storage / query | `pyarrow`, `duckdb`, optional `polars` | Parquet + zero-ETL SQL + fast columnar ops |
| Features | `pandas`, `numpy`, our own primitives | Skip ta-lib unless a gap appears |
| Modelling | `lightgbm`, `scikit-learn`, `optuna` | LightGBM is the right default for tabular crypto |
| Calibration | `sklearn.calibration.CalibratedClassifierCV` | One line; essential |
| Explainability | `shap` | For sanity checks |
| Schemas | `pydantic>=2` | Already standard |
| Reports | reuse pineforge HTML; `quantstats` for notebook tearsheets | Don't build a new framework |
| Dashboards | `panel` (consistent with CryoBacktester) | Defer until needed |
| Tracking | none initially; `mlflow` only if we hit ≥dozens of models | Overkill for a solo stack |

**Deliberately avoided / deferred:** `zipline`, `backtrader`, `qlib`, `vectorbt`, TensorFlow/PyTorch (for tabular work).

---

## 7. Rollout sequence

Six phases. No timeboxes. Each leaves the workspace runnable.

**Phase 0 — scaffolding (this commit).**
Create CryoQuant directory layout, `pyproject.toml`, `docs/`, empty `cryocore/` + `cryoquant/`, `reference/` populated with copies, `tests/test_smoke.py`. Git init.

**Phase 1 — data layer.**
1. Port `pineforge.data` + `fetch_binance` + `feeds/` into `cryoquant/data/` with multi-symbol support.
2. Build DuckDB catalog. Register existing BTC/ETH parquets.
3. Add `deribit_options` reader pointed at CryoBacktester's `backtester/data/`.
4. Add FRED-DXY stub. Smoke-test the source plug-in pattern.
5. Implement `cryocore.calendars` + `cryocore.instruments`.

**Phase 2 — features & labels.**
1. Port `pineforge.ta` → `cryoquant/features/primitives.py`. Add `calendar_features.py`.
2. Promote `06_v2_spot_signals.build_features` to `V2SpotFeaturesV1` (Tier 2, versioned).
3. Promote `add_outcomes` to `ForwardReturnLabeler`.
4. Build the **options feature pack** (`features/options.py`) — IV vs RV, ATM term structure, 25d risk reversal, butterfly, vol-of-vol. This is the highest-priority new content.

**Phase 3 — modelling & calibration.**
1. Implement `Model` protocol + `RuleModel`. Re-express the V2 signals as `RuleModel`s with empirical-win-rate calibration.
2. Implement `TabularModel` (LightGBM + isotonic).
3. Walk-forward CV + Deflated Sharpe scorer.
4. Train first LightGBM on `V2SpotFeaturesV1 + options pack` predicting `mag_win_2p5` at 24h horizon. Compare against the `RuleModel` baselines.
5. Model registry (DuckDB).

**Phase 4 — signal publication.**
1. Implement `BoolSignal`/`StateSignal`/`ProbSignal` + the three publishers.
2. **Wire one signal end-to-end into CryoTrader** as an entry condition on a paper/non-prod slot. This is the integration milestone — the proof the pipeline works.
3. Same signal exported to parquet for a Panel/notebook dashboard.

**Phase 5 — backtest harness.**
1. Library-fy `11b/11c/11d` into `cryoquant.backtest.option_lookup`.
2. Build `cryobt_bridge` — adapt a CryoQuant `Signal` into a CryoBacktester strategy. **First touch on CryoBacktester** (lifting D3).
3. Port `pineforge.bakeoff` semantics into `cryoquant.backtest`.

**Phase 6 — cryocore promotion & polish.**
1. Once `cryocore` API is stable and CryoBacktester/CryoTrader benefit, promote it to its own repo (or keep as installable subpackage — TBD).
2. Sunset `IndicatorBench/pineforge/` once everything lives in CryoQuant.
3. Write the "how to add a new signal" guide.

---

## 8. Conventions

- **Time:** UTC everywhere, tz-aware `DatetimeIndex`, **bar-open-timestamp** labelling for klines (matches TradingView + existing pineforge code).
- **Symbols:** `Symbol("binance.spot", "BTCUSDT")` etc. (see §2.1). No bare strings in public APIs.
- **Schemas:** Pydantic v2 with `extra="forbid"`.
- **No look-ahead, ever.** Every feature builder has a unit test that asserts `feature[T]` is unchanged when bars after `T` are masked.
- **IDs:** sha1 of canonical-JSON-encoded inputs. Pattern lifted from `pineforge.RunSpec.run_id()`.
- **Storage:** parquet for data/features/predictions; DuckDB for catalogs and registries; HTML for human reports; CSV only ad-hoc.
- **Reproducibility:** every experiment = one YAML/TOML under `cryoquant/experiments/<id>/` + a thin CLI invocation. No "I tweaked the script and reran" — bump the config.

---

## 9. Non-goals

- Not a live order-execution system (that's CryoTrader).
- Not an options pricing library (CryoBacktester's `pricing.py` covers what we need).
- Not a multi-strategy portfolio optimiser.
- Not a tick-level HFT stack. 1m floor; 1h is the comfort zone.
- Not a managed service. Local Python + parquets.

---

## 10. Open items `[OPEN]`

1. **Source attribution for on-chain data** — Glassnode free tier is thin; CryptoQuant has a paid API. Defer until a candidate motivates it.
2. **`cryocore` external promotion** — own repo vs installable subpackage. Decide in Phase 6.
3. **Sequence models** — left out of Phase 3. Add only if tabular plateaus.
4. **Equities ingestion** — yfinance is convenient but flaky; nothing better is free. Decide when first equity candidate appears.
5. **Dashboard tooling** — Panel (CryoBacktester-consistent) vs Streamlit (faster to build). Pick when first dashboard is actually needed.

---

## 11. How to use this document

- It's the **single source of truth** for the project shape.
- Material decisions get appended to `docs/decisions.md` (one-line ADR per decision) and reflected here.
- Anything labelled `[OPEN]` is fair game to revisit; everything else is settled unless explicitly reopened.
