# BTC Straddle Strategy — Configuration v2.0

*Derived from V2 analysis (Jan–May 2026 Deribit options data), lookahead-corrected 18 May 2026.*  
*Audience: CryoBacktester implementation agent. For research trail see `V2_PLAN.md`.*

---

## ⚠ Signal status

| Signal | Status | Reason |
|---|---|---|
| `pullback` | ✅ **ACTIVE** | Survives lookahead fix: E[$] = +$53/fire |
| `vol_burst` | ❌ **DISABLED** | Lookahead illusion: E[$] collapsed from +$211 to +$6 after fix |

**Do not implement or enable `vol_burst`.** The edge was entirely an artefact of
signal features using the current bar's close, which is only known 1 hour later.

---

## 1. Entry signal — `pullback`

### 1.1 Indicator definitions

All computed on **1h BTCUSDT OHLCV**. Bar timestamps are bar-open (Binance convention).
Every feature must use only data available at the bar's open — i.e. from closed bars ≤ T-1.

#### `ret_1h`
```
ret_1h[T] = (close[T-1] / close[T-2] - 1) × 100   (%)
```
*(1h close-to-close return of the **previous** closed bar — shifted by 1 vs naive pct_change)*

#### `ret_4h`
```
df4h       = resample(df1h, "4h")
ret_4h_htf = df4h["close"].pct_change() × 100
ret_4h[T]  = last completed 4h bar's return at or before T   (htf_align / merge_asof)
```
Never use a 4h bar that has not yet closed.

#### `rv_rank`
```
log_ret[T] = ln(close[T-1] / close[T-2])            # closed bar only
rv_24h[T]  = std(log_ret[T-23..T], ddof=1) × sqrt(8760) × 100
rv_rank[T] = percentile_rank(rv_24h[T]  within  rv_24h[T-719..T])
```
Window: 720 bars (30 days). `min_periods=360`. Range: 0.0 → 1.0.

### 1.2 Signal condition

```
bull_pullback = (ret_4h[T] >= +1.0%)  AND  (ret_1h[T] <= -0.5%)
bear_pullback = (ret_4h[T] <= -1.0%)  AND  (ret_1h[T] >= +0.5%)

pullback = (bull_pullback OR bear_pullback)
           AND  rv_rank[T] >= 0.60
           AND  day_of_week[T] != Saturday
```

**Signal timestamp** = T (the bar whose open is the entry time).  
Minimum warmup before any signal is valid: **720 bars** (30 days of 1h data).

### 1.3 Cooldown

After a pullback signal fires and a trade is taken, suppress the next pullback signal
for **4 hours**. This reduces clustering without sacrificing much frequency (keeps ~72%
of raw fires; see 11a results).

### 1.4 Stand-aside rule

```
stand_aside = rv_rank[T] < 0.35  for ≥ 12 consecutive bars
```
Do not enter any trade during extended low-vol regimes. Re-enable once rv_rank rises
back above 0.35. In calm periods (e.g. late April 2026 uptrend) this correctly
suppresses all entries.

---

## 2. Option selection

### 2.1 Target expiry

```
target_expiry_date = floor(fire_date) + 2          # DTE = 2 calendar days
target_expiry_dt   = target_expiry_date at 08:00 UTC
```

Find the nearest Deribit expiry at or after `target_expiry_dt` satisfying:
```
hours_to_expiry = (expiry_dt - fire_ts) / 3600  >=  4.0
```
If none found: skip the trade (do not fall back to DTE=3 or beyond).

### 2.2 Strike selection

Independent OTM strikes per leg. **Target delta: 0.35** for both call and put.

```
call_strike = argmin |call_delta - 0.35|   over call options for this expiry
put_strike  = argmin |put_delta  - 0.35|   over put  options for this expiry
```

Delta tolerance: ±0.04. If no leg within tolerance exists, skip the trade.
Normal case: `call_strike > spot > put_strike` (OTM strangle).

### 2.3 Availability filter

Accept only if **both** legs pass:
```
ask_price_usd      >= $75.00      (per leg — liquidity floor)
spread_pct         <= 30%         (= (ask - bid) / ask per leg)
hours_to_expiry    >=  4.0 hours
```

Availability at pullback fires (from 11b, options window Jan–May 2026):
- DTE=2, δ=0.35: **100% available** across all 54 fires
- DTE=1, δ=0.35: 98% available (not used, but noted)

### 2.4 Entry fill

```
entry_cost_usd = call_ask_usd + put_ask_usd      # pay the ask — conservative
```

Median entry cost at pullback fires, DTE=2, δ=0.35: **~$1,394**

---

## 3. Exit rules

| Rule | Condition | Action |
|---|---|---|
| Take-profit | `strangle_bid >= 2.0 × entry_cost` | Exit at `strangle_bid` immediately |
| Time-stop | `hours_since_entry >= 20` | Exit at `strangle_bid` |
| Expiry stop | `hours_to_expiry <= 1` | Exit at `strangle_bid` — mandatory safety |
| Stop-loss | — | **Not used.** SL reduces EV; dips recover before time-stop. |

Priority: take-profit checked first. TP takes priority if both TP and time-stop would
fire on the same 5-min bar.

```
exit_proceeds_usd = call_bid_usd + put_bid_usd   # hit the bid — conservative
```

---

## 4. Fees

Deribit taker fee schedule per leg per event (entry and exit counted separately):
```
fee_per_leg_usd = min(
    0.0003 × btc_index_price_usd,       # 0.03% of underlying
    0.125  × mark_price_usd             # 12.5% of option premium cap
)
round_trip_fee_usd = sum of 4 fee events: call_entry, put_entry, call_exit, put_exit
```

---

## 5. P&L

```
net_pnl_usd = exit_proceeds_usd - entry_cost_usd - round_trip_fee_usd
net_multiple = exit_proceeds_usd / entry_cost_usd    (ignoring fees, for comparison)
```

---

## 6. Backtesting results

*Source: scripts 11b–11d, options window 2026-01-01 → 2026-05-12 (18.7 weeks).*  
*All prices from real Deribit bid/ask 5-min bars. Entry at ASK, exit at BID. No B-S approximations.*

### 6.1 Best configuration (DTE=2, δ=0.35, TP=2.0×, TS=20h, no SL)

| Metric | Value |
|---|---|
| N fires (options window) | 54 |
| E[exit multiple] | 0.973× |
| **E[$] per fire (net of fees)** | **+$53** |
| Win rate (exit proceeds > entry cost) | 31% |
| TP hit rate | 15% |
| Time-stop exit rate | 85% |
| SL hit rate | 0% |
| Median entry cost (DTE=2, δ=0.35) | ~$1,394 |
| Fires/week (raw) | 2.9 |
| Fires/week (after 4h cooldown) | ~2.2 |
| **Gross EV/week** | **~$154** |

### 6.2 Top-5 pullback configurations (from 11d grid search)

| Rank | DTE | δ | TP | TS | SL | E[×] | E[$]/fire | Win% |
|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 0.35 | 2.0× | 20h | none | 0.973 | **+$53** | 31% |
| 2 | 2 | 0.30 | 2.0× | 20h | none | 0.952 | +$42 | 33% |
| 3 | 2 | 0.25 | 2.5× | 20h | none | 0.940 | +$22 | 33% |
| 4 | 3 | 0.25 | 2.0× | 20h | 0.3× | 0.960 | +$25 | 28% |
| 5 | 2 | 0.20 | 2.0× | 20h | none | 0.940 | +$8 | 28% |

All positive configurations share: **DTE=2, TS=20h**. Time-stop shorter than 16h
turns all configurations sharply negative (DTE=2, δ=0.35 at TS=4h: −$180/fire).

### 6.3 Why vol_burst is disabled

| | Bugged (pre-fix) | Corrected (post-fix) |
|---|---|---|
| vol_burst best E[$]/fire | +$211 | **+$6** |
| vol_burst best config | DTE=1, δ=0.35, no TP, TS=4h | DTE=1, δ=0.25, TP=2.5×, TS=20h, SL=0.5× |
| SL hit rate (best config) | 0% | **73%** |

The 73% SL hit rate in the corrected best config reveals the signal has no real edge —
the 0.5× SL is doing most of the work capping losses on a neutral position. The
original +$211 was generated by entries timed perfectly *after* the vol event (inside
the current bar), not before it.

### 6.4 Full E[$] heatmap — pullback (best SL per cell)

DTE=2 cells only (DTE=1 is uniformly negative for pullback):

| | TS=4h | TS=8h | TS=12h | TS=16h | TS=20h |
|---|---|---|---|---|---|
| δ=0.20, TP=1.3× | −$123 | −$148 | −$96 | −$64 | −$22 |
| δ=0.20, TP=2.0× | −$138 | −$177 | −$114 | −$76 | **+$8** |
| δ=0.25, TP=2.0× | — | — | — | −$54 | **+$13** |
| δ=0.25, TP=2.5× | — | — | — | −$111 | **+$22** |
| δ=0.30, TP=2.0× | −$177 | −$209 | −$139 | −$65 | **+$42** |
| δ=0.35, TP=2.0× | — | — | — | — | **+$53** |

**Pattern is unambiguous: TS=20h is the only time-stop that works. Do not shorten it.**

---

## 7. Known limitations and open questions for backtester

1. **Sample size**: N=54 pullback fires over 18.7 weeks. 95% CI on TP rate (15%):
   roughly [5%–28%]. Removing 2 TP hits flips E[$] negative. Treat these numbers as
   directional, not precise — paper-trade before committing capital.

2. **Position sizing**: spec assumes 1 strangle per fire. Recommend: fixed $-amount
   per trade (e.g. 1% of capital), not fixed contract count.

3. **Max 1 open position** per signal at a time. If a new pullback fires while a
   previous pullback strangle is still open, skip.

4. **Delta drift**: no rebalancing after entry. Consistent with the analysis.

5. **Both signals simultaneously**: irrelevant since vol_burst is disabled.

6. **Regime sensitivity**: all results measured in high-vol regime (rv_rank ≥ 0.60).
   The stand-aside rule (§1.4) is non-negotiable — without it, the strategy is
   untested in the full distribution of market conditions.
