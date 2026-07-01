# CDX NA IG — Full Research Report
_Generated: 2026-05-21 | Audience: AI agents, systematic strategy developers_

---

## Repository Context

All work lives in `/Users/ulrikdeichsel/IndicatorBench/research/cdx/`.

| File | Purpose |
|---|---|
| `CDX NA IG_historie.xlsx` | Raw source data (Excel) |
| `cdx_na_ig_clean.csv` | Canonical working dataset (3,622 rows, 2011-09-09 → 2026-03-15) |
| `build_clean.py` | Reproducible xlsx → CSV conversion (`data_only=True` required for openpyxl) |
| `analyse.py` | Deep statistical analysis → `cdx_na_ig_deep.svg` + `cdx_na_ig_report.md` |
| `signals.py` | All 13 signal generator functions (pure, no side effects) |
| `backtest.py` | Vectorised daily backtester + `Result` dataclass + `grid_search()` |
| `run.py` | Grid search orchestration, leaderboard, charts |
| `charts_v3.py` | Supplementary summary charts |
| `results/best_per_family.csv` | Best config per family, all metrics |
| `results/spike_onset_trades.csv` | B strategy: all 20 individual trades |
| `results/tail_hold_trades.csv` | J strategy: all 11 individual trades |
| `results/crisis_ride_trades.csv` | K strategy: all 29 individual trades |
| `results/grid_results_v3.csv` | All configs scored across all families |

### Python environment
```
/Users/ulrikdeichsel/IndicatorBench/pineforge/.venv/bin/activate
```
Libraries used: `pandas`, `numpy`, `scipy`, `statsmodels`, `matplotlib`

### Run commands
```bash
cd /Users/ulrikdeichsel/IndicatorBench/research/cdx
source /Users/ulrikdeichsel/IndicatorBench/pineforge/.venv/bin/activate
python3 analyse.py        # regenerate statistics + cdx_na_ig_deep.svg
python3 run.py            # full grid search, leaderboard, charts
python3 charts_v3.py      # supplementary summary charts
```

---

## 1. Dataset

| Property | Value |
|---|---|
| Index | CDX North America Investment Grade (CDX NA IG) |
| Unit | Credit spread in basis points (bps) |
| Frequency | Daily (trading days only) |
| Date range | 2011-09-09 → 2026-03-15 |
| Observations | 3,622 |
| Current level (2026-03-15) | 70.0 bps |
| Current percentile (full history) | 60th pct |

**Column schema of `cdx_na_ig_clean.csv`:**
```
date        — YYYY-MM-DD (ascending)
cdx_na_ig   — spread in bps (float)
pct_chg     — daily % change
log_ret     — daily log return
gap_days    — calendar days since prior observation (Int64, nullable)
```

---

## 2. Statistical Properties of the Index

### 2.1 Level distribution

| Statistic | Value |
|---|---|
| Min | 43.75 bps (2020-02-13) |
| 5th percentile | 48.85 bps |
| 25th percentile | 54.60 bps |
| Median | 65.17 bps |
| Mean | 69.69 bps |
| 75th percentile | 79.14 bps |
| 95th percentile | 108.24 bps |
| Max | 151.80 bps (2020-03-20) |

The spread is right-skewed (skewness = 1.29), with the COVID-19 crisis forming the extreme right tail.

### 2.2 Regime breakdown

| Regime | Range | Days | % of History |
|---|---|---|---|
| Tight | < 50 bps | ~319 | 8.8% |
| Normal | 50–80 bps | ~2,436 | 67.3% |
| Elevated | 80–120 bps | ~761 | 21.0% |
| Stress | > 120 bps | ~105 | 2.9% |

The index spends two-thirds of its life in the 50–80 bps "Normal" band. Stress (>120 bps) is very rare — essentially only COVID-19 (Mar–Apr 2020) and brief episodes in 2012.

### 2.3 Return distribution

| Statistic | Log Returns |
|---|---|
| Skewness | 0.021 |
| Excess kurtosis | 13.057 |
| Student-t ν (best fit) | 3.69 |
| 95% daily VaR | 4.08% |
| 99% daily VaR | 6.55% |
| 99% CVaR (Expected Shortfall) | 10.68% |

Normality tests (Jarque-Bera, KS, Shapiro-Wilk) all reject normality with p < 1×10⁻¹⁰. Return tails are Student-t with ν ≈ 3.7 — **extremely fat tails** for a major index. On the worst 1% of days, the average widening is 10.7%.

### 2.4 Mean reversion (Ornstein-Uhlenbeck)

| Metric | Value |
|---|---|
| OU regression slope β | -0.00912 |
| Half-life (trading days) | 76.0 (≈ 3.6 months) |
| R² | 0.005 |

The spread is stationary (ADF p = 0.0002) and mean-reverts, but slowly. A stress episode launched from normal levels (50–80 bps) takes approximately 3–4 months to fully revert. This implies:
- Short-duration mean-reversion trades will often be stopped out mid-episode
- Longer-hold or trailing-stop exits are structurally better for short-spread positions

### 2.5 Hurst exponent

R/S estimate: **H = 0.786**

H > 0.5 indicates trending/persistent behaviour — moves in one direction tend to continue before reversing. This is consistent with two observed features:
1. Stress episodes cluster (COVID: ~30 trading days of sequential widening)
2. Compression regimes also cluster (2013–2015, 2021 all show extended tight periods)

This creates both momentum opportunities (ride the spike) and fade opportunities (after the peak is confirmed).

### 2.6 Volatility structure

- ACF of |log returns| at lag 1: **0.208** (significant, band ±0.033)
- Volatility is strongly clustered: calm periods follow calm, stress follows stress
- 10-day rolling vol is a useful filter to distinguish "first-move" spikes from mid-crisis noise

### 2.7 Spike analysis

Using threshold |Δ%| ≥ 5%:

| Metric | Value |
|---|---|
| Total spike days (|Δ%| ≥ 5%) | 218 |
| Up spikes (widening) | 127 |
| Down spikes (compression) | 91 |
| Distinct clustered episodes | 60 |
| Standalone spikes | 47 |

**Top widening spikes:**
| Date | Δ% | Level (bps) | Event |
|---|---|---|---|
| 2020-03-09 | +33.4% | 110.9 | COVID-19 crash onset |
| 2026-03-15 | +19.8% | 70.0 | Tariff/macro shock (Q1 2026) |
| 2020-03-12 | +18.3% | 138.9 | COVID-19 (WHO pandemic declaration) |
| 2014-10-06 | +15.9% | 67.9 | EM/Russia contagion |
| 2019-09-20 | +15.3% | 59.7 | IMM roll date volatility |

> **Note on roll dates:** The CDX index is rolled every March/September 20th (IMM dates). Several large single-day moves correspond to roll-date liquidity dislocations, not macro credit events. The `vol_filter` parameter in spike signals (requiring 10d vol < 2× 63d vol) partially screens these out.

---

## 3. Signal Library — `signals.py`

All functions: `sig_xxx(s: pd.Series, **params) → pd.Series`
- `+1` = long spread (buy protection, profits on widening)
- `-1` = short spread (sell protection, profits on compression)
- `0`  = flat

Timing: position `pos[t]` set at close of bar `t` → P&L applied to return from `t → t+1`.

### Building blocks

| Function | Description |
|---|---|
| `zscore(s, window)` | Rolling z-score |
| `rsi(s, period)` | Wilder RSI |
| `bb(s, period, mult)` | Bollinger Bands → (upper, mid, lower) |

### Strategy families

| ID | Function | Core logic | Direction |
|---|---|---|---|
| A | `sig_zscore_fade` | Short when rolling z ≥ z_enter for `confirm` bars; exit at z_exit or z_stop | Short-spread |
| A2 | `sig_zscore_peak_fade` | Short when z peaked above z_enter and is now falling | Short-spread |
| B | `sig_spike_onset` | Long on large daily Δ% move; fixed hold_days; optional vol_filter | Long-spread |
| C | `sig_bb_fade` | Short above BB upper; optionally long below BB lower | Both |
| D | `sig_rsi_fade` | Short when RSI ≥ rsi_enter; exit at rsi_exit | Short-spread |
| E | `sig_ou_continuous` | Always positioned: short if z > thresh, long if z < –thresh | Both |
| G | `sig_zscore_fade_capped` | Like A, but max_hold bars caps the position | Short-spread |
| H | `sig_two_phase` | Phase 1: long on spike (onset_hold bars); Phase 2: short when z elevated (fade_hold bars) | Both |
| I | `sig_regime_fade` | Like A, but only fires when spread ≥ min_level (elevated regime) | Short-spread |
| J | `sig_tail_hold` | Long on spike; trailing stop trail_pct below rolling peak; max_level filter | Long-spread |
| K | `sig_crisis_ride` | Long on spike; hold until spread reverts to revert_mult × entry; max_level filter | Long-spread |

### Key parameter interaction notes
- `vol_filter=True` + `calm_mult=2.0`: requires 10-day vol < 2× 63-day vol before firing — effectively rejects "already elevated vol" entries (mid-crisis noise)
- `max_level`: restricts entries to compressed spread environments; critical for J/K "insurance" trades
- `trail_pct` (J): trailing stop measured from rolling spread peak — allows monster trades to run
- `revert_mult` (K): exit threshold relative to entry level; 1.20 = exit when spread ≤ 20% above entry

---

## 4. Backtesting Framework — `backtest.py`

### `Result` dataclass
```python
@dataclass
class Result:
    name: str
    total_ret_pct: float
    cagr_pct: float
    ann_vol_pct: float
    sharpe: float
    max_dd_pct: float
    n_trades: int
    avg_hold_days: float
    win_rate_pct: float
    pct_in_market: float
    daily_pnl: pd.Series
    equity: pd.Series
    positions: pd.Series
```

### `run(s, positions, name) → Result`
```python
ret    = s.pct_change()
pnl    = positions.shift(1) * ret   # lag-1 position → return at t+1
equity = (1 + pnl).cumprod()
```
No transaction costs, no carry/funding.

### `grid_search(signal_fn, param_grid, s) → pd.DataFrame`
- Runs all param combos from `expand_grid(**kwargs)`
- Returns DataFrame sorted by Sharpe, with `params` column containing the dict

### Calmar ratio (computed in run.py)
```python
calmar = r.cagr_pct / abs(r.max_dd_pct)
```

---

## 5. Grid Search Configuration

Total configs evaluated across all families: **1,306**

| Family | Configs | Best Sharpe |
|---|---|---|
| A | 162 | 0.258 |
| A2 | 54 | 0.285 |
| B | 120 | 0.560 |
| C | 32 | 0.504 |
| D | 48 | 0.251 |
| E | 16 | 0.479 |
| G | 192 | 0.316 |
| H | 162 | 0.723 |
| I | 216 | 0.368 |
| J | 288 | 0.465 |
| K | 216 | 0.630 |

---

## 6. Backtesting Results — Full Leaderboard

No transaction costs. Single-instrument, daily bars. Position = ±1 or 0 (no sizing).

| Rank | Strategy | Sharpe | Calmar | CAGR% | AnnVol% | MaxDD% | N trades | Avg Hold | WR% | In-Mkt% |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | H_two_phase | 0.723 | 0.532 | 18.31 | 28.94 | -34.40 | 124 | 5.1d | 69.4 | 20.9 |
| 2 | K_crisis_ride | 0.630 | 0.572 | 7.33 | 12.28 | -12.82 | 29 | ~1d | 69.0 | 0.8 |
| 3 | B_spike_onset | 0.560 | 0.352 | 7.96 | 15.78 | -22.60 | 20 | 2.6d | 60.0 | 2.0 |
| 4 | C_bb_fade | 0.504 | 0.161 | 12.23 | 35.83 | -76.05 | 101 | 15.5d | 80.2 | 45.9 |
| 5 | E_ou_continuous | 0.479 | 0.152 | 11.02 | 34.28 | -72.70 | 199 | 7.7d | 83.9 | 48.1 |
| 6 | J_tail_hold | 0.465 | 0.308 | 8.47 | 22.96 | -27.50 | 11 | 52.1d | 54.5 | 16.1 |
| 7 | I_regime_fade | 0.368 | 0.098 | 5.59 | 20.44 | -57.13 | 21 | 14.2d | 76.2 | 8.8 |
| 8 | G_fade_capped | 0.316 | 0.072 | 4.84 | 24.82 | -67.43 | 56 | 9.3d | 69.6 | 16.0 |
| 9 | A2_peak_fade | 0.285 | 0.069 | 4.00 | 23.85 | -58.34 | 44 | 11.5d | 75.0 | 15.2 |
| 10 | A_zscore_fade | 0.258 | 0.049 | 3.33 | 25.39 | -67.43 | 48 | 11.8d | 68.8 | 17.0 |
| 11 | D_rsi_fade | 0.251 | 0.037 | 2.78 | 32.17 | -74.98 | 73 | 13.8d | 79.5 | 29.7 |

### Best parameters per family

**H_two_phase (winner):**
```python
move_thresh=6.0, onset_hold=3, z_window=42, z_enter=1.5,
fade_hold=20, z_exit=0.5, z_stop=4.5
```

**K_crisis_ride (best risk-adjusted):**
```python
move_thresh=10.0, vol_filter=False, calm_mult=2.0,
max_hold=180, revert_mult=1.20, max_level=9999.0
```

**B_spike_onset:**
```python
move_thresh=10.0, hold_days=3, vol_filter=True, calm_mult=2.0
```

**J_tail_hold:**
```python
move_thresh=8.0, trail_pct=0.20, max_hold=60,
vol_filter=True, calm_mult=2.0, max_level=70.0
```

---

## 7. Extreme-Spike / Insurance Strategies (J & K)

### 7.1 J — Tail Hold: all 11 trades

| Entry Date | Level (bps) | Hold Days | Return % | Win |
|---|---|---|---|---|
| 2014-10-07 | 69.8 | 60 | +4.90 | ✓ |
| 2018-02-06 | 53.0 | 60 | +19.83 | ✓ |
| 2018-09-21 | 61.5 | 60 | **+39.81** | ✓ |
| 2019-03-21 | 64.5 | 60 | -4.51 | ✗ |
| 2019-08-06 | 59.5 | 60 | -4.05 | ✗ |
| 2020-02-25 | 55.4 | 14 | **+94.55** | ✓ |
| 2021-02-26 | 55.9 | 60 | -4.48 | ✗ |
| 2021-09-21 | 53.2 | 60 | +0.32 | ✓ |
| 2024-09-23 | 53.0 | 60 | -2.22 | ✗ |
| 2025-03-21 | 59.5 | 30 | +10.82 | ✓ |
| 2025-09-23 | 52.2 | 60 | -1.45 | ✗ |

**Summary:** N=11, WR=55%, Avg=+13.96%, Median=+0.32%. The distribution is bimodal: 5 losses of ~4%, and 6 winners dominated by 2 outliers (+94.6% and +39.8%). Highly fat-tailed.

### 7.2 K — Crisis Ride: all 29 trades

| Entry Date | Level (bps) | Hold Days | Return % | Win |
|---|---|---|---|---|
| 2012-09-21 | 96.4 | 1 | +2.20 | ✓ |
| 2013-09-23 | 80.2 | 1 | -1.64 | ✗ |
| 2014-03-21 | 70.8 | 1 | +1.51 | ✓ |
| 2014-10-07 | 69.8 | 1 | -4.05 | ✗ |
| 2016-06-27 | 91.2 | 1 | -7.22 | ✗ |
| 2017-03-21 | 69.7 | 1 | -1.92 | ✗ |
| 2018-02-06 | 53.0 | 1 | +3.95 | ✓ |
| 2018-03-21 | 61.6 | 1 | +6.61 | ✓ |
| 2019-03-21 | 64.5 | 1 | +5.62 | ✓ |
| 2019-08-06 | 59.5 | 1 | +0.78 | ✓ |
| 2019-09-23 | 59.0 | 1 | +3.36 | ✓ |
| 2020-02-25 | 55.4 | 1 | +4.11 | ✓ |
| 2020-02-28 | 66.5 | 1 | -2.82 | ✗ |
| 2020-03-04 | 65.8 | 1 | +11.27 | ✓ |
| 2020-03-06 | 83.2 | 1 | **+33.41** | ✓ |
| 2020-03-10 | 106.8 | 1 | +9.99 | ✓ |
| 2020-03-13 | 107.5 | 1 | +15.57 | ✓ |
| 2020-03-17 | 123.2 | 1 | +14.39 | ✓ |
| 2020-03-19 | 141.8 | 1 | +7.02 | ✓ |
| 2020-03-30 | 107.9 | 1 | +4.80 | ✓ |
| 2020-04-02 | 123.3 | 1 | +3.44 | ✓ |
| 2021-03-23 | 58.0 | 1 | +0.21 | ✓ |
| 2021-09-21 | 53.2 | 1 | -3.25 | ✗ |
| 2022-03-22 | 69.7 | 1 | +3.16 | ✓ |
| 2022-09-21 | 100.6 | 1 | +1.83 | ✓ |
| 2023-09-21 | 72.8 | 1 | -0.34 | ✗ |
| 2025-03-21 | 59.5 | 1 | -4.00 | ✗ |
| 2025-04-04 | 72.2 | 1 | +5.98 | ✓ |
| 2025-04-11 | 73.0 | 1 | -2.72 | ✗ |

**Summary:** N=29, WR=69%, Avg=+3.84%, Median=+3.16%. 11 trades from the COVID-19 episode (2020-02-25 → 2020-04-02) account for ~60% of total P&L. All 29 trades exit within 1 day due to `revert_mult=1.20` (strict near-entry exit).

---

## 8. B — Spike Onset: all 20 trades

| Entry Date | Level (bps) | Trigger% | Hold | Return % | Win |
|---|---|---|---|---|---|
| 2012-09-20 | 96.1 | +12.4% | 3d | +6.65 | ✓ |
| 2013-09-20 | 79.9 | +14.4% | 3d | -0.21 | ✗ |
| 2014-03-20 | 71.4 | +10.4% | 3d | -0.07 | ✗ |
| 2014-10-06 | 67.9 | +15.9% | 3d | +3.57 | ✓ |
| 2016-06-24 | 87.0 | +14.1% | 3d | -6.30 | ✗ (Brexit) |
| 2018-02-05 | 55.8 | +10.7% | 3d | +8.09 | ✓ |
| 2018-03-20 | 62.8 | +14.5% | 3d | +9.67 | ✓ |
| 2019-03-20 | 65.8 | +14.1% | 3d | +4.65 | ✓ |
| 2019-08-05 | 62.5 | +10.3% | 3d | -6.96 | ✗ |
| 2019-09-20 | 59.7 | +15.3% | 3d | +0.70 | ✓ |
| 2020-02-24 | 53.1 | +14.0% | 12d | **+87.71** | ✓ (COVID onset) |
| 2020-03-12 | 138.9 | +18.3% | 3d | -7.83 | ✗ (mid-crisis) |
| 2020-03-27 | 111.9 | +15.8% | 6d | +5.69 | ✓ |
| 2021-03-22 | 57.5 | +10.3% | 3d | +0.30 | ✓ |
| 2021-09-20 | 53.7 | +14.9% | 3d | -5.47 | ✗ |
| 2022-03-21 | 72.1 | +12.2% | 3d | -1.64 | ✗ |
| 2022-09-20 | 98.5 | +13.4% | 3d | +7.38 | ✓ |
| 2023-09-20 | 70.3 | +11.2% | 3d | +3.90 | ✓ |
| 2025-03-20 | 58.2 | +10.9% | 3d | -2.28 | ✗ |
| 2025-04-03 | 67.2 | +12.5% | 3d | **+19.42** | ✓ (Liberation Day) |

**Summary:** N=20, WR=60%, Avg=+6.35%. The 2020-02-24 trade alone contributes +87.71% and accounts for ~44% of cumulative strategy return.

> **Note on the 2020-02-24 hold_days discrepancy:** The trade log shows 12-day hold despite `hold_days=3`. This occurs because consecutive >10% daily moves during the COVID onset each independently triggered new 3-day hold counters, resulting in a continuous long position for 12 days.

---

## 9. Charts Generated

| File | Description |
|---|---|
| `cdx_na_ig_deep.svg` | 8-panel statistical analysis (distribution, ACF, tails, OU, etc.) |
| `cdx_signals.svg` | Top 6 strategy signal overlays on spread level |
| `cdx_equity.svg` | All 11 equity curves + drawdown panel |
| `cdx_scatter.svg` | Sharpe vs CAGR / Calmar scatter across all 1,306 grid configs |
| `cdx_strategy_bars.svg` | Horizontal bar chart: Sharpe, Calmar, CAGR per family |
| `cdx_trade_logs.svg` | Per-trade return dot plots for B, J, K |
| `cdx_regime_hist.svg` | Spread time series (regime bands) + frequency histogram |

---

## 10. Observations & Failure Modes

### Why fade strategies underperform (A/A2/D/G)

1. **Long drawdown episodes:** During COVID-19, the spread went from ~50 to ~151 bps — a 200% widening. Any short-spread position entered at 2.0σ (≈70 bps) was badly underwater by the time it reached 4.5σ (z_stop). The stop is protective, but the damage before it fires is severe.
2. **False z-score signals in tight markets:** When the spread is in the 50–65 bps band, small absolute moves generate inflated z-scores. Requiring `min_level ≥ 70bps` (strategy I) helps but only marginally.
3. **Hurst > 0.5 hurts faders:** The persistence coefficient means widening tends to continue — short-spread positions entered too early get punished.

### Why BB fade and OU continuous have high CAGR but poor Calmar (C/E)

- High in-market percentage (46–48%) means they were short during COVID-19 and experienced -70%+ drawdowns
- Good long-run mean: 80%+ win rate on individual trades
- Unsuitable for real trading without position sizing / VaR limits

### Why H_two_phase is the composite winner

- Captures the widening momentum (phase 1: long on spike, 3 bars)
- Captures the mean-reversion (phase 2: short after z-score elevates, up to 20 bars)
- The two phases are non-overlapping, so the model naturally stays flat during the chaotic mid-crisis period where fade signals get hurt
- 20-bar cap on fade phase limits maximum single-trade drawdown

### Caveat: roll-date artifacts

Multiple large moves correspond to CDX roll dates (March/September 20): 2013-09-20, 2014-03-20, 2019-03-20, 2021-03-22, etc. These are liquidity dislocations, not macro events. The `vol_filter` (`calm_mult=2.0`) partially screens them by requiring prior-period vol to be calm; however, roll dates that happen during genuine stress (e.g., 2020-03-12 near roll) still trigger.

---

## 11. Implementation Notes for Pine Script Port

If porting to TradingView Pine v5:
- `zscore` → `(close - ta.sma(close, z_window)) / ta.stdev(close, z_window)`
- `rsi` → `ta.rsi(close, period)`
- Bollinger Bands → `ta.bb(close, period, mult)`
- Two-phase state machine → use `var int phase = 0` with `var int bars_held = 0`
- No trailing stop primitive in Pine → must implement manually with `var float peak_val = na`
- Timing: Pine `strategy.entry()` on bar close fires at next bar open — effectively equivalent to the Python `pos[t] → pnl[t+1]` convention

Key gotcha: multi-line ternary expressions in Pine must be on a single line (see `pine-script-gotchas.md`).

---

## 12. Recommended Next Steps

1. **Transaction cost sensitivity:** Re-run grid search with a synthetic bid-ask spread cost. CDX NA IG typical bid-ask: 0.25–0.5 bps. For B/J/K (few trades), cost impact is negligible. For H (124 trades), cost impact at 0.5 bps round-trip = ~62 bps/year ≈ 0.9% CAGR drag.
2. **Walk-forward validation:** The grid search is in-sample. Run a 3-year rolling window (train first 8 years, test on remaining 6) to check parameter stability.
3. **Regime-conditional sizing:** Use the compressed-spread regime (< 60 bps) as a signal to increase J/K position size — insurance is cheapest when the probability-weighted loss is also high.
4. **Combination portfolio:** B + H are largely uncorrelated (B: 2% in-market, H: 21%); a weighted combination may produce better risk-adjusted returns.
5. **Pine indicator:** Port H_two_phase or B_spike_onset to Pine v5 for live signal alerts.
