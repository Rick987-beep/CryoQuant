# CryoQuant — Framework Status

**Last updated:** 2026-06-17  
**Package version:** `cryoquant` 0.0.1 · `cryocore` 0.1.0  
**Tests passing:** 467+  
**Supersedes:** `quant_plan.md` and `quant_spec.md` as the living "what is the framework" reference.
Those files remain for historical context (v1.0 BTC-centric pipeline, May 2026).

---

## Architecture Overview

```
cryocore/          shared types, symbols, calendars, UTC helpers
cryoquant/
  data/            sources → cleaning → loader → catalog → ingest → macro_store
  features/        primitives → builders / trend_builders → labels → store
  models/          baselines, tabular, cv, metrics, registry
  signals/         base, from_model, thresholds, publishers
  backtest/        spot_pnl, breakout_sim, option_lookup, metrics, trades,
                   scoring, bundle, sweep_collector, robustness, reports
  cli/             catalog, models, backtest, signals sub-commands
analyses/          per-study orchestration; imports framework, never the reverse
docs/              planning, specs, decisions, this file
tests/             32 test files; 467+ passing (offline)
```

Data flows left-to-right through the pipeline:

```
data → features → labels → models → signals → backtest
```

Framework code lives exclusively in `cryoquant/` and `cryocore/`.  Analysis
folders (`analyses/`) are research workspaces that consume the framework.

---

## `cryocore` — Shared Foundation

| Module | Key exports | Notes |
|---|---|---|
| `instruments.py` | `Symbol`, `Instrument`, `parse_symbol`, `get_instrument`, `should_use_twelvedata`, `td_ticker_info` | 40+ registered instruments; FX `quote_convention`; auto-routing helper |
| `schemas.py` | `OHLCVBars`, `BoolEmit`, `StateEmit`, `ProbEmit`, `ScoreEmit` | Cross-repo Pydantic types |
| `time.py` | `utcnow`, `floor_to_tf`, `tf_to_seconds`, `tf_to_pandas_freq`, `bar_open`, `bar_close` | UTC bar conventions |
| `calendars.py` | `Crypto24_7`, `NYSE`, `CMEFutures`, `FX24_5`, `FX24_7`, `get_calendar` | `FX24_5` added June 2026 |

---

## `cryoquant.data` — Data Layer

### Sources (`data/sources/`)

| Module | Key exports | Added |
|---|---|---|
| `binance_spot.py` | `fetch_klines` | v1.0 |
| `binance_perp.py` | `fetch_klines`, `fetch_funding` | v1.0 |
| `deribit_options.py` | `list_dates`, `load_chain`, `load_spot` | v1.0 |
| `fred.py` | `fetch_series`, `list_aliases` (25+ aliases) | June 2026 |
| `cboe.py` | `fetch_vix` (+ FRED fallback) | June 2026 |
| `yahoo.py` | `fetch_bars` | June 2026 |
| `twelvedata.py` | `fetch_bars`, `_RateLimiter` | June 2026 |

### Core data modules

| Module | Key exports | Notes |
|---|---|---|
| `loader.py` | `load`, `delete_partitions` | Partitioned parquet; auto-routes `yahoo`+`1h` to Twelve Data |
| `catalog.py` | `register`, `lookup`, `list_datasets` | DuckDB dataset index |
| `cleaning.py` | `normalize_ohlcv`, `clean_ohlcv`, `audit_bars`, `AuditWarning` | Asset-class spike thresholds; FX weekend drops via calendar |
| `ingest.py` | `IngestResult`, `load_universe`, `run_ingest`, `ingest_ohlcv`, `ingest_macro` | YAML universe orchestration; added June 2026 |
| `macro_store.py` | `write_series`, `load_series`, `list_macro` | Non-OHLCV parquet store; added June 2026 |

---

## `cryoquant.features` — Feature Layer

### Tier-1: Primitives (no cache)

**`features/primitives.py`** — All pure functions; no state; recomputed on call.

| Original (v1.0) | Added June 2026 |
|---|---|
| `sma`, `ema`, `rma`, `wma` | `donchian` |
| `tr`, `atr`, `atr_pct` | `adx` |
| `rsi` | `keltner` |
| `bb`, `bb_width` | `supertrend` |
| `realised_vol`, `rv_rank` | `macd` |
| `vol_z`, `range_ratio` | `roc` |
| `resample`, `htf_align` | `linear_reg_slope` |
| | `hurst` (slow — always use `@cached`) |
| | `obv`, `vwap`, `relative_strength` |

**`features/calendar_features.py`** — `dow`, `hour_utc`, `is_weekend`, `is_us_session`, `is_eu_session`, `is_asia_session`, `is_us_holiday`, `minutes_since_midnight_utc`

**`features/filters.py`** — Entry-filter factories: `adx_filter`, `ema_trend_filter` *(added June 2026)*

### Tier-2: Builders (`@cached`, versioned)

**`features/builders.py`** — `DatasetRef`, `FeatureBuilder` protocol, `SpotFeatures`, `DailyEmaCrossFeatures`

**`features/trend_builders.py`** — Three trend-research builders *(added June 2026)*:

| Class | `id` | `version` | Output columns |
|---|---|---|---|
| `TrendFeatures` | `trend_features` | `1` | ~40 (Group A rule-ready + Group B ML-ready + 3 composites + 3 calendar) |
| `MacroFeatures` | `macro_features` | `1` | Up to 9 (VIX, yield curve, DGS10, HY spread, DFF, CPI, DXY) |
| `CrossAssetFeatures` | `cross_asset_features` | `1` | Up to 4 (RS vs SPY, RS trend, GLD/USO ratio) |

Composite functions: `trend_regime`, `vol_expansion`, `friday_monday_stress`

**`features/store.py`** — `@cached` decorator (keyed by `id + version`)

**`features/labels.py`** — `ForwardReturnLabeler`

**`features/options.py`** — `atm_iv`, `iv_minus_rv`, `term_slope`, `risk_reversal_25d`, `vol_of_vol`

---

## `cryoquant.models` — Model Layer

| Module | Key exports |
|---|---|
| `base.py` | `Model` protocol, `ModelMetadata` |
| `baselines.py` | `RuleModel`, `make_pullback`, `make_vol_burst`, `make_bear_burst` |
| `tabular.py` | `TabularModel` (LightGBM + isotonic `CalibratedClassifierCV`) |
| `cv.py` | `purged_kfold`, `walk_forward` |
| `metrics.py` | `compute_metrics` (classification), `reliability_diagram` |
| `registry.py` | `generate_model_id`, `register`, `get_model`, `list_models` |

---

## `cryoquant.signals` — Signal Layer

| Module | Key exports |
|---|---|
| `base.py` | `Signal`, `BoolSignal`, `StateSignal`, `ProbSignal`, `ScoreSignal` |
| `from_model.py` | `bool_from_rule`, `prob_from_model`, `state_from_model` |
| `thresholds.py` | `pick_threshold` |
| `ema_cross.py` | `make_ema_cross`, `make_ema_cross_long`, `make_ema_cross_short` |
| `publishers/csv_emitter.py` | `emit_history` |
| `publishers/pine_emitter.py` | `emit_pine` |
| `publishers/cryotrader_adapter.py` | `to_cryotrader_condition` |

---

## `cryoquant.backtest` — Backtest Layer

### v1.0 modules

| Module | Key exports |
|---|---|
| `spot_pnl.py` | `SpotResult`, `simulate` — fixed-hold spot simulator |
| `option_lookup.py` | `ExitRule`, `OptionResult`, `evaluate` |
| `robustness.py` | `deflated_sharpe`, `bootstrap_ci` |
| `reports.py` | `render`, `render_spot_result`, `render_option_result`, `render_sweep_leaderboard` |
| `cryobt_bridge.py` | `CryoBTAdapter` |

### June 2026 additions

| Module | Key exports | Purpose |
|---|---|---|
| `metrics.py` | `compute_metrics`, `empty_metrics` | Single source of truth for CAGR, Sortino, Calmar, omega, profit factor, trade Sharpe, equity Sharpe |
| `trades.py` | `TRADE_COLUMNS`, `enrich_trades` | Canonical TradeLog schema; normalises any simulator output |
| `scoring.py` | `ScoringConfig`, `score_leaderboard` | Generic percentile-composite leaderboard scoring |
| `bundle.py` | `RunBundle`, `write_bundle`, `load_bundle` | Sweep artifact I/O (parquet + JSON layout) |
| `sweep_collector.py` | `RunRecord`, `SweepCollection`, `collect_runs` | Injectable multi-run aggregator |
| `breakout_sim.py` | `BreakoutConfig`, `simulate_breakout` | Donchian-channel-breakout simulator: dynamic trailing exits, ATR hard stop, long/short/both |

All modules are re-exported from `cryoquant.backtest.__init__`.

### Simulator comparison

| Simulator | Entry | Exit | Directions | Module |
|---|---|---|---|---|
| `simulate` | Boolean signal | Fixed hold period | Long | `spot_pnl` |
| `simulate_breakout` | Donchian channel breakout | Trailing Donchian or Supertrend + ATR hard stop | Long / Short / Both | `breakout_sim` |

---

## `cryoquant.cli`

`catalog list/refresh` · `models list/inspect` · `backtest spot/options/cryobt` · `signals publish`

---

## `__init__.py` Export Status

| Package | Status |
|---|---|
| `cryocore` | ✅ All public symbols exported |
| `cryoquant` | ⚠ Stub only (`__version__ = "0.0.1"`) — no sub-package exports |
| `cryoquant.backtest` | ✅ All modules including June 2026 additions |
| `cryoquant.features` | ⚠ No `__init__.py` re-exports — callers import directly from sub-modules |
| `cryoquant.models` | Not checked |
| `cryoquant.signals` | ⚠ `ScoreSignal` not exported from `signals/__init__.py` |

---

## Open Framework TODOs

| Item | Priority | Notes |
|---|---|---|
| Add `yfinance` to `pyproject.toml` | High | `data/sources/yahoo.py` uses it; not declared as a dependency |
| Portfolio-level trade-frequency governor | Medium | Needed for multi-instrument trend portfolio (≤ 3 trades/day constraint). Per-instrument workaround in Phase 3A. |
| `cryoquant/__init__.py` — re-export sub-packages | Low | Currently a stub; callers import from sub-modules directly |
| `signals/__init__.py` — export `ScoreSignal` | Low | Defined in `base.py`, not yet in `__all__` |
| `@cached` round-trip test | Low | Deferred from Phase 2; exercise on real store data in Phase 3 |
| QA JSON reports (`data/qa/`) | Low | Per-run ingest quality JSON not yet implemented |
| `hurst` in `TrendFeatures` | Low | Omitted from default build (too slow); add as opt-in column |

---

## Analyses

| Analysis | Location | Status | Framework impact |
|---|---|---|---|
| Hedged BTC options | `analyses/hedged_btc/` | Active | Used `option_lookup`, `robustness` |
| Trend following | `analyses/trend_following/` | Phase 1+2 complete; Phase 3A next | Built multi-asset data layer, 11 trend primitives, 3 feature builders |
| QuickWinTrend | `analyses/quickwintrend/` | v2 sweep complete | Built sweep backtest infrastructure, `breakout_sim` |
