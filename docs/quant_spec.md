# CryoQuant — Implementation Spec v1

**Date:** 18 May 2026
**Status:** Companion to [`quant_plan.md`](quant_plan.md). The plan defines *what* and *why*; this
document defines *how* and *what "done" looks like* per phase.
**Audience:** The implementing agent (and a future me revisiting cold).

Rules of engagement:

- This spec **refines** the plan; if the two disagree, update both in the same change.
- Each phase below has: **Deliverables**, **Module-by-module spec**, **Acceptance tests**, and
  (where it adds value) **Live tests** that hit real external sources.
- Live tests are opt-in (pytest marker `live`). Use them sparingly — one or two per phase, each
  proving an integration that fixtures can't fake. Don't restate the same proof in three tests.
- Artefacts (parquet/csv/html/png under `tests/_artefacts/`) are written **only** when a human
  would actually look at them — typically the phase sign-off run and anything chart-shaped.
  Most unit tests assert and exit; they don't need to leave files behind.
- Phase-boundary rule: **never start phase N+1 until phase N's tests are green** on this machine
  and committed.
- **Use libraries.** Whenever a well-maintained, free library does the job better than hand-rolled
  code, install it and use it. Do not write workarounds or reinvent functionality already available
  in a library. `pip install` freely — no need to ask first.

---

## 0. Conventions used by this spec

### 0.1 Test markers

In `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
    "live: hits external sources (Binance REST, FRED, local CryoBacktester parquets); slow; opt-in",
    "slow: >5s; opt-in",
]
addopts = "-ra --strict-markers -m 'not live and not slow'"
```

Invocations:

- Default (CI / `python -m pytest tests/`) — unit + integration only.
- `python -m pytest tests/ -m live` — live tests only.
- `python -m pytest tests/ -m 'live or not live'` — everything.

### 0.2 Artefact directory

When a test writes artefacts, the destination is `tests/_artefacts/<phase_id>/<test_name>/`. The
whole `_artefacts/` tree is git-ignored. The test cleans its own subdirectory at start so a re-run
is deterministic. Default: no artefacts. Add them only when the test author wants a human to be
able to `open` something afterwards (charts, sample chains, sign-off reports).

### 0.3 Fixtures shared across phases

`tests/conftest.py` provides:

- `artefact_dir(request)` — yields `Path` cleaned & created for the test.
- `tmp_store(tmp_path)` — yields a path suitable for `config.STORE_ROOT` override (monkeypatched).
- `cryobt_data_dir()` — returns `config.CRYOBACKTESTER_DATA_DIR`; `pytest.skip(...)` if it doesn't
  exist (so live option tests are skipped gracefully on machines without CryoBacktester present).
- `requires_network()` — autouse for `live`-marked tests: skip if `os.environ.get("CRYOQUANT_OFFLINE")`.

### 0.4 Coding/style minima (enforced by ruff in CI)

- All public functions typed.
- All public Pydantic models `model_config = ConfigDict(extra="forbid", frozen=True)` where
  feasible.
- No bare `print` in library code — use `logging.getLogger(__name__)`.
- Time always UTC, tz-aware. Never `datetime.utcnow()`; always `datetime.now(timezone.utc)`.

---

## Phase 0 — Scaffolding *(already complete)*

State: directory layout, `pyproject.toml`, `docs/`, empty packages, reference material, and the
existing `tests/test_smoke.py` are in place.

### Acceptance tests (already green)

- `tests/test_smoke.py::test_cryoquant_imports`
- `tests/test_smoke.py::test_cryocore_imports`
- `tests/test_smoke.py::test_config_paths_are_paths`
- `tests/test_smoke.py::test_reference_material_present`
- `tests/test_smoke.py::test_docs_present`

No live tests for Phase 0.

---

## Phase 1 — Data layer

### 1.1 Deliverables

1. `cryocore.time` — UTC helpers, bar-open conventions, `floor_to_tf(ts, tf)`.
2. `cryocore.calendars` — port of `pineforge.calendars`; `crypto_24_7`, `nyse`, stub `cme_futures`,
   `fx_eur`. Each exposes `is_open(ts) -> bool`, `session_label(ts) -> str | None`.
3. `cryocore.instruments` — `Symbol`, `Instrument` (frozen dataclasses), `parse_symbol("binance.spot:BTCUSDT")`.
4. `cryoquant.config` — already exists; extend with `STORE_ROOT`, `CATALOG_DB`, `FRED_API_KEY`
   (env-driven), `BINANCE_REST_BASE`.
5. `cryoquant.data.sources.binance_spot` — port of `pineforge.fetch_binance`. Public:
   `fetch_klines(symbol: Symbol, tf: str, start: datetime, end: datetime) -> pd.DataFrame`. UTC
   bar-open index, OHLCV columns `[open, high, low, close, volume]` (`float64`), `Int64` for
   integer-typed source fields where applicable. Closed-bars-only (drops the in-progress bar).
6. `cryoquant.data.sources.binance_perp` — same shape as spot, plus a `fetch_funding(symbol, start, end)`.
7. `cryoquant.data.sources.deribit_options` — **read-only** wrapper over
   `CRYOBACKTESTER_DATA_DIR/{options,spot}_YYYY-MM-DD.parquet`. Public:
   `list_dates() -> list[date]`, `load_chain(d: date) -> pd.DataFrame`,
   `load_spot(d: date) -> pd.DataFrame`.
8. `cryoquant.data.sources.fred` — single function `fetch_series("DXY", start, end) -> pd.Series`.
   Uses `fredapi` if `FRED_API_KEY` is set; otherwise falls back to the public CSV endpoint.
9. `cryoquant.data.catalog` — DuckDB catalog file at `config.CATALOG_DB`. Schema:

   ```sql
   CREATE TABLE IF NOT EXISTS datasets (
       source        TEXT NOT NULL,
       venue         TEXT NOT NULL,
       ticker        TEXT NOT NULL,
       tf            TEXT,
       path          TEXT NOT NULL,
       row_count     BIGINT,
       ts_min        TIMESTAMP,
       ts_max        TIMESTAMP,
       schema_hash   TEXT,
       last_refresh  TIMESTAMP,
       PRIMARY KEY (source, venue, ticker, tf)
   );
   ```

   Public: `register(path, ...)`, `list() -> pd.DataFrame`, `lookup(symbol, tf) -> Row | None`.

10. `cryoquant.data.loader` — `load(symbol, tf, start, end) -> pd.DataFrame`. Reads from parquet
    via the catalog. If not cached, calls the appropriate source, writes parquet partitioned as
    `STORE_ROOT/<source>/<venue>_<ticker>/<tf>/year=YYYY/month=MM.parquet`, updates catalog.
11. `cryoquant.cli` — `python -m cryoquant.cli catalog list|register|refresh`.

### 1.2 Module-by-module detail

**`cryocore.time`** — five functions: `utcnow()`, `floor_to_tf(ts, tf)`, `tf_to_seconds(tf)`,
`bar_open(ts, tf)`, `bar_close(ts, tf)`. `tf` strings: `1m, 5m, 15m, 1h, 4h, 1d, 1w`.

**`cryocore.calendars`** — base class `Calendar(Protocol)` with `is_open(ts)`,
`session_label(ts)`. Registry dict `CALENDARS: dict[str, Calendar]`. Tests in §1.3 below.

**`cryoquant.data.loader`** — internal `_resolve_source(symbol)` maps `venue` → source module.
Range-based caching: a request for `[start, end]` reads existing partitions and only fetches
missing months. Always returns a `pd.DataFrame` indexed by tz-aware `DatetimeIndex` (UTC), strict
schema validated through `cryocore.schemas.OHLCVBars` (new Pydantic model).

### 1.3 Acceptance tests

- **time/calendars/instruments** — one file each. `floor_to_tf` round-trip; `crypto_24_7` always
  open, `nyse` closed on a known Saturday + a known US holiday; `Symbol` is frozen/hashable.
- **catalog** — register → list → lookup; re-register is an upsert, not a duplicate.
- **loader (offline)** — pre-populated tmp `STORE_ROOT`; `load(...)` returns the expected slice
  with UTC index and passes `OHLCVBars` schema. Schema rejects NaN OHLC, negative volume,
  non-UTC index.

### 1.4 Live tests

One canonical end-to-end live test plus targeted smoke tests where the wire format is the risk:

1. **`test_loader_roundtrip_binance`** (sign-off) — `loader.load(BTCUSDT, 1h, last 30d)` end to
   end: first call fetches Binance REST, writes partitioned parquet, registers the catalog;
   second call returns an identical frame with **zero** REST calls (monkeypatched counter).
   Asserts UTC monotonic index, no gaps > 2 bars, latest bar within 2h of now, `OHLCVBars`
   passes. Writes one artefact: `summary.json` (row_count, ts_min/max, store tree). This single
   test exercises Binance source + storage layout + catalog + loader.

2. **`test_deribit_options_read`** — skipped if `cryobt_data_dir` absent. Loads the most recent
   options + spot parquet; asserts > 100 chain rows and the columns the rest of the codebase
   will rely on (`instrument_name`, `expiry`, `strike`, `option_type`, `mark_iv`, `bid`, `ask`).
   No artefacts — the test asserts the contract; nothing to eyeball.

3. **`test_fred_dxy_smoke`** — only because the source has two code paths (fredapi / CSV
   fallback). One year of DXY, ≥ 200 points, schema valid. No artefacts.

---

## Phase 2 — Features & labels

### 2.1 Deliverables

1. `cryoquant.features.primitives` — port of `pineforge.ta`. Functions, not classes:
   `ema(x, n)`, `sma(x, n)`, `atr(df, n)`, `rsi(x, n)`, `bb(x, n, k)`,
   `realised_vol(x, n)`, `rv_rank(x, n, lookback)`, `vol_z(x, n)`, `range_ratio(df, n)`,
   `bb_width(x, n, k)`. All vectorised, all closed-bar safe (no centered windows).
2. `cryoquant.features.calendar_features` — `dow(idx)`, `hour_utc(idx)`,
   `is_us_session(idx)`, `is_eu_session(idx)`, `is_asia_session(idx)`, `is_weekend(idx)`,
   `is_us_holiday(idx)` (uses `pandas_market_calendars` if available; otherwise local list of
   NYSE federal holidays for the next ~5 years).
3. `cryoquant.features.options` — option-data features computed over the daily chain snapshots:
   `atm_iv(df, dte_target=30)`, `iv_minus_rv(atm_iv_ts, rv_ts)`,
   `term_slope(df)` (front/back ATM IV ratio), `risk_reversal_25d(df)`,
   `butterfly_25d(df)`, `vol_of_vol(atm_iv_ts, n)`. Inputs are the per-date chain DataFrames
   from `deribit_options.load_chain`.
4. `cryoquant.features.builders.SpotFeatures` — technical feature set for 1h spot bars.
   Implements `FeatureBuilder` protocol:

   ```python
   class FeatureBuilder(Protocol):
       id: str
       version: str
       inputs: list[DatasetRef]   # e.g. [DatasetRef(Symbol("binance.spot","BTCUSDT"), "1h")]
       def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame: ...
   ```

5. `cryoquant.features.labels.ForwardReturnLabeler` — `__init__(horizon_h, threshold,
   direction="up"|"down"|"magnitude")`; `apply(df) -> pd.Series[bool]` named
   `{direction}_h{H}_t{thresh}` (e.g. `mag_win_2p5_h24`). Drops the trailing `horizon_h` rows.
6. `cryoquant.features.store` — `@cached(builder)` decorator. Cache file
   `STORE_ROOT/features/<builder.id>/v=<version>/<venue>_<ticker>_<tf>__<start>__<end>.parquet`.
   Cache key = sha1(`builder.id | version | inputs | start | end`). Reads via
   `pyarrow`. Eviction not implemented (manual cleanup).
7. `cryoquant.features.catalog` — yaml file `cryoquant/features/catalog.yaml` listing registered
   feature sets. Loader function `list_feature_sets() -> list[BuilderInfo]`.

### 2.2 Closed-bar safety harness (cross-cutting)

A single helper `tests/util/lookahead.py::assert_no_lookahead(builder, frames, t_cut)`:

1. Run the builder on the full frame → `out_full`.
2. Truncate each input frame at `t_cut` → `frames_trunc`.
3. Run the builder on truncated frames → `out_trunc`.
4. Assert `out_full.loc[:t_cut].equals(out_trunc.loc[:t_cut])` column by column.

Every builder gets one test using this helper.

### 2.3 Acceptance tests

- **primitives** — golden-value tests against hand-computed numbers on a small synthetic series
  for each indicator. Edge cases: leading NaNs, constant series, single-row.
- **calendar features** — spot checks: `is_us_session` true at 14:30 UTC Monday, false at 03:00
  UTC; `is_weekend` Saturday; `is_us_holiday` 2025-12-25.
- **SpotFeatures** — builds on a synthetic 1000-row frame; expected columns/dtypes;
  `assert_no_lookahead` passes.
- **labels** — hand-crafted series → expected label vector; trailing horizon rows dropped.
- **`@cached` decorator** — first call writes parquet, second call uses it (spy); bumping
  `version` invalidates.

### 2.4 Live tests

One integration test — the V2 port is the headline risk of this phase.

1. **`test_spot_features_and_options_on_real_data`** (sign-off) — pulls 180d real BTC 1h via the
   Phase-1 loader, builds `SpotFeatures`, then reads 30 recent Deribit daily chains and
   computes `atm_iv` + `risk_reversal_25d`, joins ATM IV with daily RV. Asserts: no NaNs after
   warmup; 30/30 chain days produce finite IV; join yields ≥ 25 aligned rows. Writes one chart
   pair so the user can sanity-check the port: `features_describe.html`, `iv_minus_rv.png`.

---

## Phase 3 — Modelling & calibration

### 3.1 Deliverables

1. `cryoquant.models.base` — `Model` protocol per glossary; `ModelMetadata` Pydantic record
   (id, feature_set_id, labeler, class, hparams, train_window, metrics).
2. `cryoquant.models.baselines.RuleModel(condition: Callable[[pd.DataFrame], pd.Series],
   name: str)` — `fit(X, y)` records empirical win rate; `predict_proba(X)` returns that rate
   wherever the condition is True, 1−rate otherwise (or `nan_to_num`).
   - Concrete instances: `Pullback`, `VolBurst`, `BearBurst` ported from V2 research.
3. `cryoquant.models.tabular.TabularModel` — wraps `lightgbm.LGBMClassifier` (default) or any
   sklearn classifier; **always wrapped** in `CalibratedClassifierCV(method="isotonic", cv=5)`
   after the underlying fit. Public: `fit`, `predict_proba`, `feature_importances_`, `save`,
   `load`.
4. `cryoquant.models.cv` — `purged_kfold(n_splits, embargo_bars)` (López de Prado);
   `walk_forward(train_window_bars, test_window_bars, step)`; both yield `(train_idx, test_idx)`
   tuples consumable by sklearn-style code.
5. `cryoquant.models.metrics` — `compute_metrics(y_true, y_prob, y_pred=None) -> dict`:
   `auc, brier, log_loss, calibration_error, win_rate_at_thr, expectancy_at_thr`. Plus
   `reliability_diagram(y_true, y_prob, bins=10) -> pd.DataFrame`.
6. `cryoquant.models.registry` — DuckDB table:

   ```sql
   CREATE TABLE models (
       model_id     TEXT PRIMARY KEY,
       class        TEXT NOT NULL,
       feature_set_id TEXT,
       feature_set_version TEXT,
       labeler      TEXT,
       hparams_json TEXT,
       train_start  TIMESTAMP, train_end TIMESTAMP,
       metrics_json TEXT,
       artifact_path TEXT,
       created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   ```
7. `cryoquant.models.artifacts/` — joblib pickles named `<model_id>.joblib`.
8. `cryoquant.cli` — `python -m cryoquant.cli models list|inspect <id>`.

### 3.2 Acceptance tests

- **RuleModel** — fit on synthetic; `predict_proba` matches empirical rate.
- **TabularModel calibration** — sanity that calibrated output is bounded & monotonic on a
  monotone toy problem. Don't assert calibrated Brier beats uncalibrated on synthetic data
  (flaky); just check the wrapper is wired up.
- **CV** — purged k-fold respects embargo; walk-forward windows don't overlap and cover the
  span.
- **Registry** — register/retrieve idempotent; different hparams → different `model_id`;
  `model_id` is deterministic across processes (subprocess test, since this is the cross-repo
  contract).

### 3.3 Live tests

One sign-off run — the whole point of this phase is producing a real trained model.

1. **`test_lgbm_walkforward_on_real_btc`** (sign-off) — 12 months of BTC 1h → `SpotFeatures`
   → `ForwardReturnLabeler(24, 0.025, "magnitude")` → `TabularModel(LGBMClassifier(...))`
   walk-forward (180d train / 30d test, step 30d). Registers the model; reloads via registry;
   asserts reloaded predictions match in-memory ones within 1e-9. Asserts AUC and Brier are
   finite (no quality threshold — that's the model's problem, not the test's). Writes the only
   artefacts a human will actually look at: `oos_predictions.parquet`, `reliability.png`,
   `feature_importance.csv`. SHAP optional and skipped if it imports slow.

---

## Phase 4 — Signal publication

### 4.1 Deliverables

1. `cryoquant.signals.base` — `Signal` protocol; concrete classes `BoolSignal`, `ScoreSignal`,
   `StateSignal`, `ProbSignal`. Each `.emit(t)` returns a Pydantic record
   (`cryocore.schemas.{Bool,Score,State,Prob}Emit`) with `ts`, `symbol`, `signal_id`, `metadata`.
   Each implements `as_feature(df) -> pd.Series` so signals are usable as features (per D12).
   All are instantiated **functionally** (pass a callable, not a subclass).
   - `BoolSignal(signal_id, condition)` — bool Series
   - `ScoreSignal(signal_id, score_fn)` — unbounded float Series
   - `StateSignal(signal_id, state_fn)` — arbitrary `int | str` Series (relaxed from `{-1,0,1}`)
   - `ProbSignal(signal_id, model)` — `[0,1]` float, requires `model.predict_proba(X)`
2. `cryoquant.signals.from_model` — adapters:
   - `bool_from_rule(rule_model, name) -> BoolSignal`
   - `prob_from_model(model, horizon_h, default_threshold) -> ProbSignal`
   - `state_from_model(model, up_thr, down_thr) -> StateSignal`
3. `cryoquant.signals.thresholds` — `pick_threshold(y_true, y_prob, target="precision",
   value=0.6) -> float`; reused by publishers.
4. `cryoquant.signals.publishers.csv_emitter` —
   `emit_history(signal, X, out_path) -> Path`. Writes parquet with columns
   `ts, value, prob?, state?, signal_id, version`.
5. `cryoquant.signals.publishers.pine_emitter` — accepts `BoolSignal`/`StateSignal`; emits a
   Pine v5 snippet string. Will not accept `ProbSignal` (raises `TypeError`).
6. `cryoquant.signals.publishers.cryotrader_adapter` — returns a callable matching the
   `EntryCondition(ctx) -> bool` shape used by CryoTrader. **Does not import CryoTrader**;
   instead, the callable's signature is documented and unit-tested with a mock context.
7. `cryoquant.cli` — `python -m cryoquant.cli signals publish <signal_id> --out <path>`.

### 4.2 Acceptance tests

- **protocol** — every concrete signal satisfies `Signal`; metadata round-trips through Pydantic.
- **pine emitter** — accepts `BoolSignal`/`StateSignal`, rejects `ProbSignal`/`ScoreSignal`; output starts with
  `//@version=5`, contains exactly one `indicator(` call (regex sanity).
- **cryotrader adapter shape** — callable accepts a `SimpleNamespace` ctx matching CryoTrader's
  signature; returns a `bool`. Pure-Python test, no live deps.
- **signal-as-feature** — `BoolSignal.as_feature(df)` returns same dtype as the condition.
- **replay consistency** — `emit_history(...)` vs per-timestamp `emit(t)` agree on a synthetic
  frame within 1e-9. (Catches off-by-one alignment bugs; doesn't need real data.)

### 4.3 Live tests

1. **`test_publish_lgbm_probsignal_end_to_end`** (sign-off) — wraps the Phase-3 LGBM as a
   `ProbSignal`; `csv_emitter.emit_history` over 12 months of real BTC 1h. Asserts output
   parquet schema, no NaNs after warmup, row count matches features minus warmup. Writes the
   parquet + a `prob_distribution.png` (the only thing worth eyeballing). Also emits the
   `RuleModel(Pullback)` BoolSignal as a Pine snippet and confirms the file is non-empty.
   One test, both publishers exercised.

---

## Phase 5 — Backtest harness

### 5.1 Deliverables

1. `cryoquant.backtest.spot_pnl` — `simulate(signal: BoolSignal | ProbSignal, bars: pd.DataFrame,
   thr: float | None = None, hold_h: int = 24, exec: Literal["next_open"] = "next_open",
   fee_bps: float = 1.0) -> SpotResult`. Vectorised; ≤ 1s for 5 years of 1h data on M-series.
   `SpotResult` is a Pydantic record with `equity`, `trades`, `metrics`.
2. `cryoquant.backtest.option_lookup` — library-fy `11b/11c/11d`. Public:
   `evaluate(signal, *, dte: int, delta: float, exit_rule: ExitRule, chains_dir: Path)
   -> OptionResult`. Takes the same dated parquets via `deribit_options`. Returns
   per-fire P&L distribution, win rate, expectancy.
3. `cryoquant.backtest.robustness` — `deflated_sharpe(sharpe, n_trials, n_obs, skew, kurt)`;
   `bootstrap_ci(trades, metric_fn, n=10000, alpha=0.05)`.
4. `cryoquant.backtest.reports` — `render(html_template, context) -> Path`; templates for
   `spot_pnl.html`, `option_lookup.html`.
5. `cryoquant.backtest.cryobt_bridge` — adapt a `Signal` to CryoBacktester's `Strategy`
   protocol. **Lifts D3**; sibling repo touched only in read mode (no edits to CryoBacktester).
   Discovery: `import sys; sys.path.insert(0, str(config.CRYOBACKTESTER_ROOT))`.
6. `cryoquant.cli` — `python -m cryoquant.cli backtest spot|options|cryobt --signal <id>
   --start ... --end ...`.

### 5.2 Acceptance tests

- **spot_pnl** — handcrafted 100-bar series with 3 known trades; assert trade boundaries, P&L
  per trade, aggregate equity. Same fixture verifies next-open execution (no look-ahead).
- **deflated sharpe** — closed-form cases.
- **bootstrap CI** — IID synthetic returns; 95% CI covers the true mean in ≥ 92/100
  simulations (`slow`-marked).
- **cryobt_bridge shape** — the adapted object implements CryoBacktester's `Strategy` protocol
  (duck-typed check; no actual invocation).

### 5.3 Live tests

One canonical sign-off; one option-data smoke. Skip the rest — they restate the same proof.

1. **`test_full_pipeline_live`** (sign-off, gated by `CRYOQUANT_FULL_LIVE=1`) — end-to-end:
   load BTC 1h → features → train LGBM walk-forward → wrap as `ProbSignal` → `spot_pnl.simulate`
   → `option_lookup.evaluate` (30d of real chains) → publish parquet → render one HTML report.
   Artefact: `phase5/full_pipeline/report.html` plus the underlying parquet/csv. This is the
   single test that says "CryoQuant works".

2. **`test_option_lookup_real_chains`** — lighter, runs even without the env var: same
   `option_lookup.evaluate` on a `BoolSignal` over 30d of real chains. Asserts ≥ 5 fires
   resolved with finite P&L. No artefacts — just contract validation that the 11b/c/d port
   handles real data.

3. **`test_cryobt_bridge_smoke`** — skipped if `CRYOBACKTESTER_ROOT` absent. Adapts the
   Pullback BoolSignal into a CryoBacktester strategy and runs a tiny invocation (7 days).
   Asserts the run produced a report path; no artefact copying from CryoBacktester's tree.

---

## Phase 6 — `cryocore` promotion & polish

### 6.1 Deliverables

1. Decide installation mode for `cryocore` (own repo vs subpackage) — see plan §10 OPEN-2.
2. CryoBacktester + CryoTrader pinned to `cryocore` (either via `pip install -e ../CryoQuant`
   or a published version) — touching sibling repos for the first time. **One PR each, opt-in
   by the user.**
3. `docs/how_to_add_a_signal.md` — step-by-step.
4. Sunset note in `IndicatorBench/pineforge/README.md` pointing at CryoQuant.

### 6.2 Acceptance tests

- **public API** — pin the public symbol surface of `cryocore` (a `__all__` snapshot test) so
  accidental removals are caught.

### 6.3 Live tests

1. **`test_cryotrader_consumes_signal_live`** — gated by `CRYOTRADER_PAPER_AVAILABLE=1`. Pushes
   a `ProbSignal` history file to CryoTrader's paper slot; runs its replay tool via
   subprocess; asserts at least one entry was evaluated. This is the only test that proves
   the cross-repo contract works on real bytes.

---

## Phase sign-off checklist

A phase is "shipped" when:

1. All acceptance tests for this phase + earlier phases pass under default `pytest tests/`.
2. The phase's live test(s) pass under `pytest tests/ -m live`.
3. Any sign-off artefacts written by the live test have been eyeballed by a human at least
   once.
4. An ADR is appended to `docs/decisions.md` for any material decision made during the phase.

Test file layout is left to the implementer — one file per topic is fine; one file per phase
is fine too. Live tests live under `tests/live/` so the default `-m 'not live'` selector keeps
them off the hot path.

---

## Appendix A — environment variables consumed

| Variable | Used by | Required? |
|---|---|---|
| `FRED_API_KEY` | `data.sources.fred` | optional (CSV fallback) |
| `CRYOQUANT_OFFLINE` | live test guard | optional |
| `CRYOQUANT_FULL_LIVE` | `test_full_pipeline_live` | optional |
| `CRYOTRADER_PAPER_AVAILABLE` | Phase 6 live test | optional |
| `CRYOBACKTESTER_DATA_DIR` | `data.sources.deribit_options` | required for option live tests |
| `CRYOBACKTESTER_ROOT` | `backtest.cryobt_bridge` | required for cryobt bridge tests |

All read in `cryoquant/config.py`. None hard-coded in tests.
