# How to Use CryoQuant

**Version:** 1.0  
**Date:** 20 May 2026  
**Audience:** Anyone running a new analysis, adding a signal, or integrating with CryoTrader.

CryoQuant is a local quant pipeline that turns raw market data into calibrated, actionable signals.
The pipeline has six layers: **data → features → labels → models → signals → backtest**.
You only need the layers relevant to your task — a rule-based signal skips models entirely.

---

## Contents

1. [Setup](#1-setup)
2. [Core concepts in 90 seconds](#2-core-concepts-in-90-seconds)
3. [Hello World — EMA crossover signal end-to-end](#3-hello-world--ema-crossover-signal-end-to-end)
4. [Loading market data](#4-loading-market-data)
5. [Building features](#5-building-features)
6. [Labelling bars for ML](#6-labelling-bars-for-ml)
7. [Training a model](#7-training-a-model)
8. [Creating signals](#8-creating-signals)
9. [Running a backtest](#9-running-a-backtest)
10. [Options backtesting](#10-options-backtesting)
11. [Publishing a signal](#11-publishing-a-signal)
12. [Best practices](#12-best-practices)
13. [Workflow: adding a new analysis](#13-workflow-adding-a-new-analysis)

---

## 1. Setup

```bash
cd /Users/ulrikdeichsel/CryoQuant
source .venv/bin/activate          # Python 3.12

# Verify everything is working
python -m pytest tests/ -v         # ~30 tests, ~5 s
```

The venv already has all dependencies. If you ever need to reinstall:

```bash
pip install -e ".[dev]"
```

**Optional — Deribit options data.** The options backtest reads parquets from CryoBacktester.
Set `CRYOBACKTESTER_DATA_DIR` in the environment (or `config_local.py`) if it lives somewhere
other than the default `~/CryoBacktester/backtester/data`.

---

## 2. Core concepts in 90 seconds

| Concept | What it is | Where it lives |
|---|---|---|
| `Symbol` | `(venue, ticker)` pair — e.g. `"binance.spot:BTCUSDT"` | `cryocore.instruments` |
| `Instrument` | Static metadata about a symbol (asset class, calendar, tick size) | `cryocore.instruments` |
| **Tier-1 feature** | Pure function over a bar series — `ema(s, 24)`, `rsi(s, 14)` | `cryoquant.features.primitives` |
| **Tier-2 feature builder** | Named, versioned class that produces a set of columns; optionally cached | `cryoquant.features.builders` |
| **Label** | A forward-looking outcome column — what you're trying to predict | `cryoquant.features.labels` |
| **Model** | Fitted thing with `.fit(X, y)` and `.predict_proba(X)` | `cryoquant.models` |
| **Signal** | Actionable claim: `BoolSignal`, `ScoreSignal`, `StateSignal`, `ProbSignal` | `cryoquant.signals` |
| **Backtest** | `simulate(signal, bars)` → equity curve + trade list + metrics | `cryoquant.backtest` |

All times are **UTC tz-aware**. Never use `datetime.utcnow()` — always `datetime.now(timezone.utc)`.

---

## 3. Hello World — EMA crossover signal end-to-end

The EMA 7/21 daily crossover on BTC/USDT is the first signal shipped in CryoQuant v1.
Run it now to confirm the stack is working:

```bash
python scripts/ema_cross_backtest.py
```

Expected output (numbers will vary with current date):

```
── 1. Loading daily bars ────────────────────────────────────────────────
   1965 bars  (2019-09-09 → 2026-05-20)

── 2. Building EMA cross features ───────────────────────────────────────
   up-crosses: 18   down-crosses: 17

── 3. Long leg (EMA 7 crosses above EMA 21, hold 5 days) ─────────────────
   n_trades            : 18
   win_rate            : 0.6111
   sharpe              : 1.1432
   ...

── 6. Writing reports ────────────────────────────────────────────────────
   reports/ema_cross_long_7_21_1d.html
   reports/ema_cross_short_7_21_1d.html

Done.
```

Open `reports/ema_cross_long_7_21_1d.html` in a browser to see the equity curve and trade log.

### What the script does

```python
from cryocore.instruments import Symbol
from cryoquant.data.loader import load
from cryoquant.features.builders import DatasetRef, DailyEmaCrossFeatures
from cryoquant.signals.ema_cross import make_ema_cross_long, make_ema_cross_short
from cryoquant.backtest.spot_pnl import simulate
from cryoquant.backtest.reports import render_spot_result

# 1. Fetch (or read from cache) daily BTCUSDT bars
sym    = Symbol("binance.spot", "BTCUSDT")
df_raw = load(sym, "1d", START, END)

# 2. Build the EMA cross feature set (adds ema_7, ema_21, cross_up, cross_down)
ref  = DatasetRef(sym, "1d")
X    = DailyEmaCrossFeatures().build({ref: df_raw})
bars = df_raw.join(X[[c for c in X.columns if c not in df_raw.columns]])

# 3. Create signals (functionally — no subclassing)
long_sig  = make_ema_cross_long()   # BoolSignal — fires on bullish cross
short_sig = make_ema_cross_short()  # BoolSignal — fires on bearish cross

# 4. Simulate
result_long = simulate(long_sig, bars, hold_h=5, fee_bps=5.0)

# 5. Report
render_spot_result(result_long, "reports/ema_cross_long.html")
```

---

## 4. Loading market data

`load()` is the single entry point for all market data.
On the first call it fetches from the source (Binance REST) and writes partitioned parquet.
On subsequent calls it reads from disk — **no network request**.

```python
from datetime import datetime, timezone
from cryocore.instruments import Symbol
from cryoquant.data.loader import load

sym = Symbol("binance.spot", "BTCUSDT")

# 1-hour bars, last 180 days
df = load(sym, "1h", datetime(2025, 11, 1, tzinfo=timezone.utc), datetime.now(timezone.utc))

print(df.head())
# DatetimeIndex (UTC), columns: open  high  low  close  volume
```

### Supported venues and timeframes

| Venue | Ticker examples | Source |
|---|---|---|
| `binance.spot` | `BTCUSDT`, `ETHUSDT` | Binance REST klines |
| `binance.perp` | `BTCUSDT`, `ETHUSDT` | Binance perpetual futures |

Supported timeframes: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`, `1w`.

### Data catalog

```bash
python -m cryoquant.cli catalog list
```

Parquet files live under `data/binance_spot/<venue>_<ticker>/<tf>/year=YYYY/month=MM.parquet`.
The DuckDB catalog at `data/catalog.duckdb` tracks metadata (row counts, date ranges, schema hash).

### Deribit options data

Options chain data is read directly from CryoBacktester parquets (no re-ingestion):

```python
from cryoquant.data.sources.deribit_options import list_dates, load_chain, load_spot

dates = list_dates()               # available chain dates
chain = load_chain(dates[-1])      # most recent chain as DataFrame
spot  = load_spot(dates[-1])       # spot price on that date
```

---

## 5. Building features

### Tier-1 primitives — inline, no boilerplate

```python
from cryoquant.features.primitives import ema, rsi, atr, bb, realised_vol

df["ema_24"]  = ema(df["close"], 24)
df["rsi_14"]  = rsi(df["close"], 14)
df["atr_14"]  = atr(df, 14)
df["rv_24h"]  = realised_vol(df["close"], 24)
upper, mid, lower, width = bb(df["close"], 20, 2.0)
```

All primitives are pure, vectorised, and closed-bar safe (no look-ahead).
They mirror Pine Script v5 semantics (`ema` is SMA-seeded, `rma` is Wilder smoothing).

### Tier-2 feature builders — named, versioned, optionally cached

Use a builder when you want:
- a stable, reusable set of columns with a version string
- optional on-disk caching (useful for expensive features)

```python
from cryocore.instruments import Symbol
from cryoquant.features.builders import DatasetRef, SpotFeatures, DailyEmaCrossFeatures

sym = Symbol("binance.spot", "BTCUSDT")
ref = DatasetRef(sym, "1h")

# SpotFeatures — 12-column technical feature set for 1h bars
builder = SpotFeatures()
X = builder.build({ref: df_1h})
# Columns: ret_1h, ret_4h, ret_1d, accel_1h, close_vs_ema24, close_vs_ema168,
#          rv_24h, rv_rank, rv_trend, bb_width, vol_z, range_ratio,
#          hour_utc, day_of_week, close, high, low, volume

# DailyEmaCrossFeatures — for 1d bars
ref_1d = DatasetRef(sym, "1d")
X_1d = DailyEmaCrossFeatures().build({ref_1d: df_1d})
# Columns: ema_7, ema_21, cross_up, cross_down
```

The `@cached` decorator (applied inside `SpotFeatures.build`) writes parquet to
`cryoquant/features/store/<builder_id>/v=<version>/...` and reuses it on the next call.
Change `version` to invalidate the cache automatically.

### Calendar features

```python
from cryoquant.features.calendar_features import (
    dow, hour_utc, is_us_session, is_eu_session, is_weekend, is_us_holiday
)

df["dow"]          = dow(df.index)           # 0=Monday … 6=Sunday
df["hour"]         = hour_utc(df.index)
df["us_session"]   = is_us_session(df.index) # 14:30–21:00 UTC Mon–Fri
df["is_weekend"]   = is_weekend(df.index)
```

---

## 6. Labelling bars for ML

Labels are forward-looking outcome columns. Use `ForwardReturnLabeler` to generate them.
**Never use label columns as model features** — they contain future information.

```python
from cryoquant.features.labels import ForwardReturnLabeler

# Did price move up >= 2.5% within the next 24 hours?
labeler = ForwardReturnLabeler(horizon_h=24, threshold=2.5, direction="up")
df["label"] = labeler.apply(df)
# Column name: "up_win_t2.5_h24"
# Trailing 24 rows are NaN (no complete forward window)

# Magnitude label — either direction
mag_labeler = ForwardReturnLabeler(horizon_h=24, threshold=2.5, direction="magnitude")
df["label_mag"] = mag_labeler.apply(df)
```

Drop NaN label rows before fitting:

```python
clean = df.dropna(subset=["label"])
X = clean[feature_cols]
y = clean["label"]
```

---

## 7. Training a model

### Rule model (no training data needed)

```python
from cryoquant.models.baselines import RuleModel

# Condition: close is above EMA-24 AND RSI < 70
rule = RuleModel(
    condition=lambda df: (df["close_vs_ema24"] > 0) & (df["rsi_14"] < 70),
    name="pullback_entry",
)
rule.fit(X_train, y_train)   # records empirical win rate
probs = rule.predict_proba(X_test)  # returns the empirical rate for True rows
```

### LightGBM tabular model

```python
from cryoquant.models.tabular import TabularModel

model = TabularModel()           # LightGBM with isotonic calibration, cv=5
model.fit(X_train, y_train)
probs = model.predict_proba(X_test)   # calibrated [0, 1]
model.save("cryoquant/models/artifacts/my_model.joblib")
```

### Walk-forward cross-validation

```python
from cryoquant.models.cv import walk_forward, purged_kfold
from cryoquant.models.metrics import compute_metrics

results = []
for train_idx, test_idx in walk_forward(len(df), train_window=4380, test_window=720, step=720):
    X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
    X_te, y_te = X.iloc[test_idx],  y.iloc[test_idx]

    m = TabularModel()
    m.fit(X_tr, y_tr)
    probs_oos = m.predict_proba(X_te)
    results.append(compute_metrics(y_te, probs_oos))

# Each entry in results: {"auc": ..., "brier": ..., "log_loss": ..., "win_rate_at_thr": ...}
```

Use `purged_kfold` when training on the full dataset and you want embargo to prevent leakage:

```python
for train_idx, test_idx in purged_kfold(n=len(df), n_splits=5, embargo_bars=24):
    ...
```

---

## 8. Creating signals

Signals are instantiated **functionally** — pass a callable, do not subclass.

### BoolSignal — a rule that fires or doesn't

```python
from cryoquant.signals.base import BoolSignal

entry = BoolSignal(
    signal_id="ema_cross_long_7_21_1d",
    condition=lambda df: df["cross_up"].fillna(False).astype(bool),
    version="1",
    symbol_str="binance.spot:BTCUSDT",
)

# Vectorised (DataFrame → bool Series)
fires = entry.as_feature(bars)

# Per-timestamp emit (returns a BoolEmit Pydantic record)
emit = entry.emit(bars.index[-1], bars)
```

### ScoreSignal — a continuous float value

```python
from cryoquant.signals.base import ScoreSignal

iv_rank = ScoreSignal(
    signal_id="iv_rank_daily",
    score_fn=lambda df: df["iv_rank"],
    version="1",
    symbol_str="deribit:BTC",
)
```

### StateSignal — discrete states (regime / trend direction)

```python
from cryoquant.signals.base import StateSignal

regime = StateSignal(
    signal_id="ema_trend",
    state_fn=lambda df: df["cross_up"].map({True: 1, False: -1}).fillna(0).astype("int8"),
    version="1",
    symbol_str="binance.spot:BTCUSDT",
)
```

States can be integers **or** strings (e.g. `"bullish"`, `"neutral"`, `"bearish"`).

### ProbSignal — calibrated probability from a model

```python
from cryoquant.signals.from_model import prob_from_model, state_from_model

prob_sig  = prob_from_model(model, horizon_h=24, default_threshold=0.55)
state_sig = state_from_model(model, up_thr=0.60, down_thr=0.40)
```

### Wrapping the EMA cross signals (factory pattern)

The built-in EMA cross signals use factory functions for convenience:

```python
from cryoquant.signals.ema_cross import make_ema_cross, make_ema_cross_long, make_ema_cross_short

signal       = make_ema_cross()       # StateSignal: +1 / -1 / 0
long_signal  = make_ema_cross_long()  # BoolSignal: True on bullish cross
short_signal = make_ema_cross_short() # BoolSignal: True on bearish cross
```

---

## 9. Running a backtest

### Spot backtest

```python
from cryoquant.backtest.spot_pnl import simulate
from cryoquant.backtest.robustness import deflated_sharpe
from cryoquant.backtest.reports import render_spot_result

result = simulate(
    signal   = long_signal,
    bars     = bars,           # OHLCV DataFrame with feature columns attached
    hold_h   = 5,              # hold 5 daily bars after entry
    fee_bps  = 5.0,            # 5 bps round-trip fee
)

print(result.metrics)
# {
#   "n_trades": 18,
#   "win_rate": 0.611,
#   "avg_pnl_pct": 0.032,
#   "sharpe": 1.14,
#   "max_drawdown": -0.08,
#   ...
# }

# Equity curve
result.equity.plot()

# Trade log
print(result.trades)  # entry_ts, exit_ts, entry_price, exit_price, pnl_pct, fee_pct

# Robustness — Deflated Sharpe Ratio (corrects for selection bias)
dsr = deflated_sharpe(
    sharpe   = result.metrics["sharpe"],
    n_trials = 1,              # how many strategy variants did you test?
    n_obs    = result.metrics["n_trades"],
)
print(f"DSR: {dsr:.3f}  (>0.95 = credible)")

# HTML report
render_spot_result(result, "reports/my_signal.html")
```

The `simulate` function is **non-overlapping** — a new trade is only entered after the previous
one closes. Execution is `next_open` (enters at the open of the bar after the signal fires).

### Interpreting the metrics

| Metric | What it means |
|---|---|
| `n_trades` | Total trades fired and completed |
| `win_rate` | Fraction of trades with positive net P&L |
| `avg_pnl_pct` | Mean P&L per trade, net of fees |
| `sharpe` | Annualised Sharpe ratio (trade returns / std) |
| `max_drawdown` | Worst peak-to-trough equity drawdown |
| DSR | Probability the true SR > 0 after selection bias correction |

---

## 10. Options backtesting

The options backtest uses real Deribit chain snapshots from CryoBacktester.
The signal fires on EMA cross dates; the backtest selects the nearest-DTE option at a target delta.

```bash
python scripts/ema_cross_options_backtest.py
```

Or call the underlying function directly:

```python
from cryoquant.backtest.option_lookup import _eval_leg, _load_chain_df

# The eval_leg function returns (pnl_pct, entry_costs_usd, dte_actual)
pnl_pct, costs, dte_actual = _eval_leg(
    fire_timestamps,
    is_call    = True,
    bars       = bars,
    dte        = 3,           # target days to expiry at entry
    delta      = 0.30,        # target absolute delta
    hold_days  = 3,
    chains_dir = config.CRYOBACKTESTER_DATA_DIR,
)
```

Tunable parameters: `DTE` (days to expiry at entry), `DELTA` (target option delta), `HOLD_DAYS`.
Reports are written to `reports/ema_cross_calls_dte3_d30_h72.html` etc.

---

## 11. Publishing a signal

### CSV / parquet history

```python
from cryoquant.signals.publishers.csv_emitter import emit_history

out_path = emit_history(signal, bars, out_path="reports/ema_cross_long.parquet")
# Parquet columns: ts, value, signal_id, version
```

### Pine Script v5 snippet

Works for `BoolSignal` and `StateSignal` only (no ML signals in Pine):

```python
from cryoquant.signals.publishers.pine_emitter import emit_pine

snippet = emit_pine(long_signal)
print(snippet)  # //@version=5 indicator(...) ...
```

### CryoTrader adapter

```python
from cryoquant.signals.publishers.cryotrader_adapter import as_entry_condition

entry_fn = as_entry_condition(long_signal, bars)
# Returns a callable: entry_fn(ctx) -> bool
# ctx is a SimpleNamespace matching CryoTrader's EntryCondition signature
```

---

## 12. Best practices

### Data

- Always pass a **tz-aware UTC** `datetime` to `load()`. Naive datetimes will raise.
- Add a warmup margin to your `start` date to give indicators enough bars to seed.
  For a 168-bar EMA, load at least 200 bars before your analysis window starts.
- The first call to `load()` hits Binance REST — subsequent calls are disk reads. The catalog
  only fetches missing months, so partial re-runs are cheap.

### Features

- **Never** use a label column as a model feature. `ForwardReturnLabeler` uses future prices by
  design — feeding it back as a feature will produce perfect but useless out-of-sample results.
- When writing a new `FeatureBuilder`, run `assert_no_lookahead` in its test (see
  `tests/test_phase2.py` for the pattern).
- Bump `version` on a builder whenever the computation logic changes. This invalidates the cache
  and prevents silent stale-feature bugs.

### Signals

- Prefer factory functions (e.g. `make_ema_cross_long()`) for signals used in multiple places.
- Signal `signal_id` values must be unique across the registry. Use a naming convention:
  `{description}_{params}_{tf}` e.g. `ema_cross_long_7_21_1d`.
- A signal is also a feature. Use `signal.as_feature(df)` to include it as a column in another
  builder or model.

### Backtesting

- Always report the **Deflated Sharpe Ratio** alongside the raw Sharpe. The DSR accounts for
  how many strategy variants you tested — if you tested 10 variants and picked the best, the raw
  Sharpe is inflated.
- Use `n_trials` in `deflated_sharpe` honestly: count every parameter combination you explored,
  including ones you discarded.
- `simulate` assumes your signal fires on **closed bars** and executes at the **next bar's open**.
  There is no look-ahead — verifiable by inspection of `spot_pnl.py`.
- Options backtest P&L is expressed as a fraction of entry cost (e.g. `+0.50` = 50% profit on
  premium paid). It covers 2025-04-11 → present; signals firing outside that window are skipped.

### Code organisation

- Library improvements → `cryoquant/` or `cryocore/`.
- New analysis → `analyses/<name>/` with its own `backtest.py` and notebook.
- Scripts in `scripts/` are the canonical runnable examples for each signal.
- Never commit generated HTML/parquet/PNG artefacts (`reports/` is gitignored).

---

## 13. Workflow: adding a new analysis

The recommended workflow for a new signal idea:

```
1. Explore               notebooks/my_signal_exploration.ipynb
2. Prototype signal       cryoquant/signals/my_signal.py
3. Write a backtest       scripts/my_signal_backtest.py
4. Run and check DSR      python scripts/my_signal_backtest.py
5. If credible (DSR>0.95) move to analyses/my_signal/
6. Optional: train a model and wrap it as a ProbSignal
7. Register the signal    (model registry + signal_id naming convention)
8. Publish to CryoTrader  cryotrader_adapter.as_entry_condition(...)
```

For a step-by-step guide to adding a signal, see [`how_to_add_a_signal.md`](how_to_add_a_signal.md).

### Pipeline summary

```
Symbol + timeframe
    ↓  load()
Raw OHLCV bars (parquet cache)
    ↓  FeatureBuilder.build()  /  primitives.*
Feature DataFrame
    ↓  ForwardReturnLabeler.apply()
Label Series (drop NaN tail before fitting)
    ↓  TabularModel.fit() / RuleModel.fit()
Fitted Model
    ↓  prob_from_model() / bool_from_rule() / make_*()
Signal (BoolSignal / ProbSignal / StateSignal / ScoreSignal)
    ↓  simulate() / option_lookup._eval_leg()
SpotResult / OptionResult
    ↓  render_spot_result() / deflated_sharpe()
HTML report + DSR
    ↓  as_entry_condition() / emit_pine() / emit_history()
CryoTrader / TradingView / CSV
```
