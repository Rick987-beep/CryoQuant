# Lookahead Bug — Investigation Notes (2026-05-17)

## Status
**Bug confirmed. Not yet fixed. Resume here tomorrow.**

---

## The Bug

`build_features()` in `06_v2_spot_signals.py` computes all features using
**bar-open timestamps** (Binance convention: bar at T opens at T, closes at T+1h).
Features like `ret_1h[T]`, `rv_24h[T]`, `vol_z[T]` all use `close[T]` and
`volume[T]`, which span the period **T → T+1h** and are only known at **T+1h**.

This means every feature at timestamp T contains **1h of future data** relative
to when the bar opens.

### Concrete proof — Jan 21 16:00 crash bar

| Feature | At bar 15:00 (known at 16:00) | At bar 16:00 (only known at 17:00) |
|---|---|---|
| `log_ret` | +0.54% (calm) | **−3.02% (the crash itself!)** |
| `rv_rank` | 0.907 | **1.000** |
| `vol_z` | 0.49 (no signal) | **2.29 (signal fires!)** |

The `vol_burst` signal at 16:00 fires **because of** the crash that happens
inside the 16:00 bar. At 16:00 open, `vol_z = 0.49` — no signal would fire
on available data. The signal is only visible at 17:00 when bar 16:00 closes.

---

## Impact by script layer

### 06–09 (signal discovery, AUC analysis)
- Conceptually valid question: "after a big-vol bar, does vol continue?"
- AUC / win-rate numbers are **inflated** because features include bar T's own
  move. The signal is partly measuring "this bar was big" → "next 24h is big."
- Signal conditions (e.g. `vol_z >= 2.0`) were selected on lookahead data, so
  thresholds may be tighter than achievable in practice.
- **Not completely wrong**, but numbers should be re-verified after the fix.

### 11b → 11d (option universe + P&L backtesting)
- `11b_option_universe.py` enters options at `fire_ts = T` using the T-snapshot.
- But the signal at T is only known at T+1h. Entry should be at **T+1h**.
- This is what creates the entire discrepancy vs CryoBacktester:
  - IndicatorBench 11d: vol_burst DTE=1 δ=0.35 ts_h=4 → **+$211/trade (fake)**
  - CryoBacktester same combo                          → **−$187/trade (real)**
- For Jan 21 the 16:00 "fire" gave a perfect pre-crash strangle entry at spot
  ~90k. That entry is impossible in practice — you only see the crash at 17:00.

---

## The fix (one line in `build_features`)

Shift all features by 1 bar so that feature at timestamp T uses only data
available at T (i.e. bar T−1's close):

```python
# Before (broken):
ret_1h   = close.pct_change() * 100
rv_24h   = log_ret.rolling(24).std() * np.sqrt(8760) * 100
vol_z    = (volume - vol_mean) / vol_std

# After (correct):
ret_1h   = close.pct_change() * 100             # compute as before…
ret_1h   = ret_1h.shift(1)                      # …then shift by 1 bar
rv_24h   = (log_ret.rolling(24).std() * np.sqrt(8760) * 100).shift(1)
vol_z    = ((volume - vol_mean) / vol_std).shift(1)
# same for: accel_1h, rv_rank, rv_trend, bb_width, range_ratio, ret_4h, ret_1d
```

After shifting, `build_features` will be **identical in convention** to
CryoBacktester's `build_indicators` (which also reads the previous closed bar
via `bar_ts = state.dt - timedelta(hours=1)`).

---

## Re-run chain after fix

1. Fix `build_features` in `06_v2_spot_signals.py`
2. Re-run `06_v2_spot_signals.py` → new AUC / conditions CSV
3. Re-run `07_v2_spot_charts.py` (if needed)
4. Re-run `11a_signal_combinations.py` → new signal fire list
5. Re-run `11b_option_universe.py` → new option universe CSV  
6. Re-run `11c_pnl_lookup.py` → new P&L curves parquet
7. Re-run `11d_optimise.py` → new grid results

CryoBacktester does **not** need changes — its convention is already correct.

---

## CryoBacktester status (for context)

- Last bundle: `Str_VolBurst_Pullback_20260517_191143.bundle`
- All 150 combos negative (best: −$3,686 total over 30 trades)
- Entry/exit pricing verified correct (ASK entry, BID exit, fees correct)
- Main drag: theta decay on short-dated OTM strangles + expiry_stop killing
  DTE=1 positions with ts_h ≥ 12h (exits at near-zero value)
- The negative results are likely **real** — they are what IndicatorBench will
  also show once the lookahead is fixed

---

## Key parameter finding (IndicatorBench, pre-fix — not trustworthy)

Best combo before fix: `vol_burst, DTE=1, δ=0.40, ts_h=4, no TP, no SL`
→ +$236/trade, 52% win rate, mean entry $1090.

After fix these numbers will likely shift significantly. **Do not use
11d_grid_results.csv for any decisions until the chain is re-run.**
