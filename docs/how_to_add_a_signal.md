# How to Add a Signal — Step-by-Step Guide

This guide walks through adding a new signal to CryoQuant from scratch.
Signals come in four flavours; pick the one that matches your idea.

| Flavour | When to use | Example |
|---|---|---|
| `BoolSignal` | A rule fires or doesn't — no probability | "EMA crosses up", "RSI > 70" |
| `ScoreSignal` | A continuous float value — no threshold baked in | RSI value, z-score, IV rank, momentum |
| `StateSignal` | Discrete state — regime, trend direction, or any label | -1/0/+1 trend, "bearish"/"neutral"/"bullish" |
| `ProbSignal` | ML model outputs a calibrated probability | LightGBM pullback classifier |

> **Important:** Signals are instantiated **functionally** — you pass a callable to the
> constructor. Do NOT subclass `BoolSignal` / `ScoreSignal` / `StateSignal`.

---

## 1. Define the signal

### Option A — BoolSignal (rule fires or not)

```python
# cryoquant/signals/my_signals.py
from cryoquant.signals.base import BoolSignal

def make_btc_overbought() -> BoolSignal:
    """Fires when BTC is up >3 % in 4 h and price is above its 24-period EMA."""
    return BoolSignal(
        signal_id="btc_overbought_v1",
        condition=lambda df: (df["ret_4h"] >= 3.0) & (df["close_vs_ema24"] > 0),
        version="1",
        symbol_str="binance.spot:BTCUSDT",
    )
```

`as_feature(df)` calls the condition and returns a bool Series.
`emit(t, X)` emits a `BoolEmit` record for consumption by publishers.

### Option B — ScoreSignal (continuous float)

Use this for any raw indicator value you want to emit without thresholding it first.

```python
from cryoquant.signals.base import ScoreSignal

def make_iv_rank_signal() -> ScoreSignal:
    """Emits the current IV rank (0–100) as a continuous score."""
    return ScoreSignal(
        signal_id="iv_rank_v1",
        score_fn=lambda df: df["iv_rank"],
        version="1",
        symbol_str="binance.spot:BTCUSDT",
    )
```

`as_feature(df)` returns a float Series (unbounded — no [0,1] constraint).
`emit(t, X)` emits a `ScoreEmit` record with the raw value.

### Option C — StateSignal (regime / discrete state)

Accepts any discrete `int` or `str` — not restricted to `{-1, 0, 1}`.

```python
from cryoquant.signals.base import StateSignal
import pandas as pd

def make_vol_regime() -> StateSignal:
    """Three-state volatility regime from RV rank."""
    def _state_fn(df):
        return pd.cut(
            df["rv_rank"],
            bins=[-0.001, 0.33, 0.67, 1.001],
            labels=[-1, 0, 1],
        ).astype("int8")
    return StateSignal(
        signal_id="vol_regime_v1",
        state_fn=_state_fn,
        version="1",
        symbol_str="binance.spot:BTCUSDT",
    )

# String labels work too:
def make_trend_regime() -> StateSignal:
    def _fn(df):
        conditions = [
            df["ema_7"] > df["ema_21"],
            df["ema_7"] < df["ema_21"],
        ]
        return pd.Series(
            pd.np.select(conditions, ["bullish", "bearish"], default="neutral"),
            index=df.index,
        )
    return StateSignal(signal_id="trend_regime_v1", state_fn=_fn)
```

### Option D — ProbSignal (ML model)

```python
from cryoquant.models.baselines import make_pullback
from cryoquant.signals.from_model import prob_from_model

model = make_pullback()   # returns a fitted TabularModel
signal = prob_from_model(model, horizon_h=24, default_threshold=0.60)
```

---

## 2. Add features your signal needs

If your condition references columns not yet in the feature store, add them to
`cryoquant/features/builders.py`.

**Tier-1 primitives** (cheap, stateless, no caching) — add to `_compute_spot_features()` or
a new `_compute_*` function:

```python
df["ret_4h"] = df["close"].pct_change(4) * 100
```

**Tier-2 named feature set** (versioned, optionally cached) — add a new `FeatureBuilder`:

```python
class MyCustomFeatures:
    id = "my_features"
    version = "1"

    @cached
    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame:
        ref = next(iter(frames))
        return _compute_my_features(frames[ref])
```

> **Rule:** Tier-1 (cheap + not versioned) → `primitives.py` / inline in `_compute_*`.  
> Tier-2 (expensive or tracked) → new `FeatureBuilder` class in `builders.py`.

---

## 3. Unit-test it

Create `tests/test_<signal_name>.py`:

```python
class TestBtcOverbought:
    def test_fires_when_expected(self):
        from cryoquant.signals.my_signals import make_btc_overbought
        import pandas as pd
        idx = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
        df = pd.DataFrame({
            "ret_4h":        [0.0] * 19 + [5.0],
            "close_vs_ema24": [0.01] * 20,
        }, index=idx)
        sig = make_btc_overbought()
        fires = sig.as_feature(df)
        assert bool(fires.iloc[-1]) is True
        assert fires.sum() == 1

    def test_no_fires_when_flat(self):
        ...
```

Run:
```bash
python -m pytest tests/ -q
```

---

## 4. Backtest it

### Spot simulation (script)

```python
from datetime import datetime, timezone
from cryocore.instruments import Symbol
from cryoquant.data.loader import load
from cryoquant.features.builders import DatasetRef, SpotFeatures
from cryoquant.signals.my_signals import make_btc_overbought
from cryoquant.backtest.spot_pnl import simulate
from cryoquant.backtest.reports import render_spot_result

sym    = Symbol("binance.spot", "BTCUSDT")
df_raw = load(sym, "1h",
              datetime(2024, 1, 1, tzinfo=timezone.utc),
              datetime(2025, 1, 1, tzinfo=timezone.utc))

ref      = DatasetRef(sym, "1h")
X        = SpotFeatures().build({ref: df_raw})
new_cols = [c for c in X.columns if c not in df_raw.columns]
bars     = df_raw.join(X[new_cols])

signal = make_btc_overbought()
result = simulate(signal, bars, hold_h=24, fee_bps=5.0)
print(result.metrics)

render_spot_result(result, path="reports/btc_overbought.html")
```

### Deflated Sharpe check

```python
from cryoquant.backtest.robustness import deflated_sharpe

dsr = deflated_sharpe(
    sharpe=result.metrics["sharpe"],
    n_trials=10,   # how many strategies you tried before this one
    n_obs=len(result.trades),
)
print(f"DSR: {dsr:.3f}")  # > 0.95 = credible after multiple testing
```

### Interactive exploration (notebook)

For parameter sweeps (date ranges, hold periods, fees), a notebook is more productive
than re-running a script. See `notebooks/ema_cross_exploration.ipynb` as a template.

The typical pattern:

```python
# In a notebook — run setup cell once, then slice freely

def run(start=None, end=None, hold=24, fee_bps=5.0):
    window = bars[start:end]          # bars is built once at top
    return simulate(signal, window, hold_h=hold, fee_bps=fee_bps)

# Then in individual cells:
run("2022", "2022")  # calendar year
run("2023-01", "2023-06", hold=5)  # custom window, different hold
```

Results (equity curve, trade table, metrics) appear inline below each cell.

---

## 5. File placement convention

```
cryoquant/signals/<name>.py       ← signal factory functions (library code)
analyses/<name>/backtest.py       ← entry-point script for this analysis
analyses/<name>/exploration.ipynb ← interactive sweeps
analyses/<name>/reports/          ← generated output (gitignored)
```

Keep library code in `cryoquant/`; keep one-off analysis artefacts in `analyses/`.

---

## 6. Publish it (for CryoTrader consumption)

```python
from cryoquant.signals.publishers.csv_emitter import emit_history

emit_history(signal, bars, out_path="analyses/btc_overbought/signal_history.parquet")
```

For CryoTrader integration, use `cryoquant.signals.publishers.cryotrader_adapter`.

---

## Summary checklist

```
[ ] Signal factory function in cryoquant/signals/<name>.py
[ ] Condition/score/state_fn uses only columns from a FeatureBuilder or Tier-1 primitives
[ ] Unit tests pass: python -m pytest tests/ -q
[ ] Backtest run (spot simulation at minimum)
[ ] DSR checked — credible after multiple testing?
[ ] HTML report written to analyses/<name>/reports/
[ ] Signal published / registered if going live
```

