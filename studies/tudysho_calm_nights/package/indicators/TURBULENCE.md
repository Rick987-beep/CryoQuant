# Turbulence indicator

Read-only snapshot: [`turbulence_reference.py`](turbulence_reference.py)  
Canonical source: `CryoBacktester/indicators/turbulence.py` (Pine port of `market_wildness_v2.pine`)

## Purpose

Composite **0–100** score of market turbulence. Tudysho uses it as an **entry gate**: sell premium when calm.

| Signal | Range | Meaning |
|--------|-------|---------|
| Green | 0–35 | Calm — safe to sell |
| Yellow | 35–65 | Caution |
| Red | 65–100 | Stay out |

## Input / output

- **Input:** OHLC DataFrame at **15-minute** resolution (Binance BTCUSDT)
- **Output:** Hourly DataFrame with columns:
  - `composite` — weighted sum (0–100)
  - `vol_score` — Component A
  - `trend_score` — Component B
  - `burst_score` — Component C
  - `decay_score` — Component D
  - `signal` — green / yellow / red

## Components

| Component | Weight | Method |
|-----------|--------|--------|
| A — Parkinson vol | 0.40 | Realized variance per 1h bar; percentile vs 336h lookback |
| B — Kaufman ER | 0.25 | Direction / path over 6 active hours |
| C — Burst | 0.15 | Outsized 15m ranges vs daily ATR |
| D — Decay / calm | 0.20 | Short/long vol ratio + calm streak |

Weekend bars excluded from baselines (NaN on weekends when `exclude_weekends=True`).

## Tudysho usage

```python
# Backtester: IndicatorDep(name="turbulence", symbol="BTCUSDT", interval="15m")
# Entry allowed when:
composite < turbulence_threshold
```

| Slot | `turbulence_threshold` | Effective behaviour |
|------|------------------------|---------------------|
| A (Mon–Thu) | 60 | Gate active — blocks elevated vol |
| B, C | 99 | Gate effectively always open |

**Fail-open:** missing data → treat as calm (allow entry).

## Limitation for calm-night research

Turbulence is **backward-looking** — it scores recent completed hours, not the **upcoming** hold window (16:00 NYC → 08:00 UTC).

Phase 0 tests whether **US morning extrusion** is a better *forward* signal. Phase 2 may combine:

- Morning session extrusion (new)
- Turbulence `decay_score` / calm streak (existing)
- IV-implied overnight move (from Deribit parquets)

## Using in this study

```python
# Study-local — adapt imports to CryoQuant data layer
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turbulence_reference import turbulence

# df_15m: UTC index, columns open/high/low/close from load_track 15m bars
result = turbulence(df_15m)
```

Prefer `load_track(Symbol("binance.spot", "BTCUSDT"), "15m", start, end)` in production code; resample if needed to match 15m schema.

## Promotion path

If validated, port to `cryoquant/features/turbulence.py` as a `FeatureBuilder` — do not keep a permanent dependency on this study copy.
