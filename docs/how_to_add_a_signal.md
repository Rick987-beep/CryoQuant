# How to Add a Signal — Step-by-Step Guide

This guide walks through adding a new signal to CryoQuant from scratch.
Signals come in three flavours; pick the one that matches your idea.

| Flavour | When to use | Example |
|---|---|---|
| `BoolSignal` | A rule fires or doesn't — no probability | "4h return ≥ 1 % AND 1h return ≤ −0.5 %" |
| `StateSignal` | Regime detection with {−1, 0, +1} states | Bull / neutral / bear |
| `ProbSignal` | ML model outputs a calibrated probability | LightGBM pullback classifier |

---

## 1. Define the signal class

### Option A — BoolSignal (rule-based)

Edit or create a file in `cryoquant/signals/` (or `cryoquant/models/baselines.py` for
simple baselines):

```python
# cryoquant/signals/my_signals.py
from cryoquant.signals.base import BoolSignal

class BtcOverbought(BoolSignal):
    """Fires when BTC is up >3 % in 4 h and price is above its 24-period EMA."""

    signal_id   = "btc_overbought_v1"
    version     = "1"
    description = "4h momentum + EMA filter"
    symbol_str  = "binance.spot:BTCUSDT"

    def condition(self, df):
        # df columns come from V2SpotFeaturesV1 (ret_4h, close_vs_ema24, …)
        return (df["ret_4h"] >= 3.0) & (df["close_vs_ema24"] > 0)
```

`BoolSignal.as_feature(df)` calls `condition(df)` → returns a boolean Series.
`BoolSignal.emit(ts)` emits a `BoolEmit` record.

### Option B — ProbSignal (ML model)

1. Train a model using `cryoquant.models.tabular.TabularModel`.
2. Wrap it with `bool_from_rule` or `prob_from_model` from `cryoquant.signals.from_model`:

```python
from cryoquant.models.baselines import make_pullback
from cryoquant.signals.from_model import prob_from_model

# make_pullback() returns a TabularModel
model = make_pullback()
# prob_from_model() wraps it in a ProbSignal
signal = prob_from_model(model, name="pullback_v1", threshold=0.60)
```

### Option C — StateSignal (regime classifier)

```python
from cryoquant.signals.base import StateSignal

class VolRegime(StateSignal):
    signal_id = "vol_regime_v1"
    version   = "1"
    symbol_str = "binance.spot:BTCUSDT"

    def condition(self, df):
        # Returns pd.Series of {-1, 0, 1}
        return pd.cut(
            df["rv_rank"],
            bins=[-1, 0.33, 0.67, 1.01],
            labels=[-1, 0, 1],
        ).astype(int)
```

---

## 2. Add features your signal needs

If your condition uses columns that aren't in the feature store yet, add them to
`cryoquant/features/builders.py`:

```python
class V2SpotFeaturesV1(FeatureBuilder):
    id      = "v2_spot_features"
    version = "1"

    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame:
        df = frames[...]
        # Add your new column here:
        df["ret_4h"] = df["close"].pct_change(4) * 100
        ...
```

> **Rule:** Tier-1 primitives (cheap to compute, not versioned) live in
> `cryoquant/features/primitives.py`.  Named feature sets (versioned, optionally
> cached) live as `FeatureBuilder` subclasses in `builders.py`.

---

## 3. Unit-test it

Add a test class in `tests/test_phase*.py` (or a new file):

```python
class TestBtcOverbought:
    def test_fires_when_expected(self):
        from cryoquant.signals.my_signals import BtcOverbought
        import pandas as pd
        idx = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
        df = pd.DataFrame({
            "ret_4h": [0.0] * 19 + [5.0],
            "close_vs_ema24": [0.01] * 20,
        }, index=idx)
        sig = BtcOverbought()
        fires = sig.as_feature(df)
        assert fires.iloc[-1] is True
        assert fires.sum() == 1

    def test_no_fires_when_flat(self):
        ...
```

Run:
```bash
python -m pytest tests/ --ignore=tests/live -q
```

---

## 4. Backtest it (optional but recommended)

### Spot simulation

```python
from cryoquant.data.loader import load
from cryocore.instruments import Symbol
from cryoquant.features.builders import DatasetRef, V2SpotFeaturesV1
from cryoquant.signals.my_signals import BtcOverbought
from cryoquant.backtest import simulate, render_spot_result
from datetime import datetime, timezone

sym = Symbol("binance.spot", "BTCUSDT")
df_raw = load(sym, "1h", datetime(2024, 1, 1, tzinfo=timezone.utc),
                          datetime(2025, 1, 1, tzinfo=timezone.utc))

# Build features and enrich bars
ref = DatasetRef(sym, "1h")
X = V2SpotFeaturesV1().build({ref: df_raw})
new_cols = [c for c in X.columns if c not in df_raw.columns]
bars = df_raw.join(X[new_cols])

signal = BtcOverbought()
result = simulate(signal, bars, hold_h=24, fee_bps=5.0)
print(result.metrics)

# Write HTML report
render_spot_result(result, "reports/btc_overbought_spot.html")
```

### Deflated Sharpe check

```python
from cryoquant.backtest import deflated_sharpe

dsr = deflated_sharpe(
    sharpe=result.metrics["sharpe"],
    n_trials=10,   # how many strategies you tried before this one
    n_obs=len(result.trades),
)
print(f"DSR: {dsr:.3f}")  # > 0.95 = credible after multiple testing
```

---

## 5. Register the signal (optional)

If you want the signal available via the CLI:

1. Import it in `cryoquant/signals/__init__.py`.
2. Add it to the `_REGISTRY` dict if one exists, or use it directly in
   `cryoquant/cli/__init__.py`.

---

## 6. Publish it (for CryoTrader consumption)

```python
from cryoquant.signals.publishers import SignalPublisher
import cryoquant.config as cfg

pub = SignalPublisher(cfg.SIGNAL_PUBLISH_DIR)
pub.publish(signal.emit(ts=pd.Timestamp.utcnow()))
```

The publisher writes NDJSON records to `SIGNAL_PUBLISH_DIR/<signal_id>/`.
CryoTrader polls this directory to pick up new signals.

---

## Summary checklist

```
[ ] Signal class defined in cryoquant/signals/ or cryoquant/models/
[ ] Condition uses only columns from a FeatureBuilder (or Tier-1 primitives)
[ ] Unit tests pass: python -m pytest tests/ --ignore=tests/live -q
[ ] Backtest run (spot simulation at minimum)
[ ] DSR checked — credible after multiple testing?
[ ] Signal published / registered if going live
```
