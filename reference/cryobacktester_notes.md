# CryoBacktester — What CryoQuant Depends On

**Repo:** `/Users/ulrikdeichsel/CryoBacktester`
**Policy:** Per decision D3, we do not modify CryoBacktester until CryoQuant has produced its
first working signal. Read-only dependency until then.

## Data we read

### `backtester/data/options_YYYY-MM-DD.parquet`
5-minute Deribit option chain snapshots. BTC only (today). Schema (per CryoBacktester README):

| Column | Type | Notes |
|---|---|---|
| `timestamp` | int64 µs | UTC microseconds |
| `expiry` | string | e.g. `30MAY25` |
| `strike` | float | |
| `is_call` | bool | |
| `underlying_price` | float | spot at snapshot |
| `bid_price` | float | **BTC-denominated** (USD = `× spot`) |
| `ask_price` | float | BTC-denominated |
| `mark_price` | float | BTC-denominated |
| `mark_iv` | float | **percentage** (e.g. `39.8` = 39.8% annualised) — divide by 100 before pricing |
| `delta` | float | signed |

Coverage: 2025-04-11 → present, daily.

### `backtester/data/spot_YYYY-MM-DD.parquet`
1-minute BTC spot OHLC bars covering the same range. Used to anchor option snapshots and
compute realised vol / spot features.

### `backtester/data/spot_track_YYYY-MM-DD.parquet`
Higher-frequency spot tracking (tick-level mid) for the most recent ~2 months. Fallback only.

## Reading from CryoQuant

`cryoquant/config.py` exposes:

```python
CRYOBACKTESTER_DATA_DIR = Path("/Users/ulrikdeichsel/CryoBacktester/backtester/data")
```

`cryoquant.data.sources.deribit_options` reads from this path. No copying. No re-ingestion.

If you move CryoBacktester, change the one config line.

## What we DO NOT touch (yet)

- `backtester/strategies/` — strategies are CryoBacktester's, not ours.
- `backtester/engine.py`, `market_replay.py`, `pricing.py` — out of scope until Phase 5
  (`cryobt_bridge.py`).
- `indicators/` (supertrend, turbulence, hist_data) — left alone per D3. If we end up needing
  these shared, they migrate to `cryocore/` later.

## Future integration (Phase 5+)

- `cryoquant/backtest/cryobt_bridge.py` will adapt a CryoQuant `Signal` into a CryoBacktester
  `Strategy` so the full engine can run it.
- `cryocore/robustness.py` may absorb CryoBacktester's `backtester/robustness.py` (Deflated
  Sharpe) so both repos share one implementation.
