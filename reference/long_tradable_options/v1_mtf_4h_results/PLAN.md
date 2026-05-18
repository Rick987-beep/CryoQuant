# Long-Tradeable Options — Research Plan

**Date:** May 2026  
**Approach:** Work backwards from outcome — identify options that *were actually
tradeable* as long positions, then characterise the spot / IV environment that
made them tradeable and develop anticipation signals.

---

## 1. Motivation

Previous intraday-options research (`/research/intraday_options/`) started from
the spot chart and asked "which entry hours produce the best bang-for-buck?".
That is a necessary first step, but it does not answer the operational question:

> Given a specific option contract at a specific moment, was it actually worth
> buying?  What would have had to happen in spot / IV for it to pay off?

This analysis inverts the question: enumerate every option that *did* produce
a profitable long trade over our date range, then reverse-engineer what
preceded it in spot and IV.

---

## 2. Profitability Definition

An option long trade is **"tradeable"** if and only if ALL of the following hold:

| Criterion | Value | Rationale |
|---|---|---|
| Entry price (ask) | ≥ $75 USD | Avoid deep-OTM penny options; too noisy |
| Exit price (bid) | > entry × 1.20 | Require ≥ 20% gain *before* fees |
| Net P&L after fees | > 0 | Must actually profit net of Deribit charges |

**Execution model:**
- **Buy** at `ask_price` (USD converted via spot index)
- **Sell** at `bid_price` (USD converted via spot index at exit)

**Deribit fee model** (per leg, per contract):

```
fee_btc = min(0.0003 × underlying_price_btc,  0.125 × mark_price_btc)
fee_usd = fee_btc × spot_index_usd
```

Round-trip cost = 2 × single-leg fee (entry + exit).  
*Note: verify exact constants against `cryotrader/backtester` fee model before
drawing final conclusions.*

Net P&L = `exit_bid_usd − entry_ask_usd − rt_fee_usd`

The 20% gross threshold is set deliberately above the typical RT fee load
(~1–4% of option premium depending on DTE/moneyness) so that "tradeable" means
robustly profitable, not marginal.

---

## 3. Universe Constraints

Scanning all options every minute is computationally impractical.  The
following filters narrow the search to a tractable, meaningful universe.

### 3.1 Date range
- **2026-01-01 → 2026-05-12**  (data confirmed available in `option_data/`)
- Weekdays only (Mon–Fri); weekends excluded from *entry* (can still hold over
  weekend if already entered)

### 3.2 Entry time cadence
- Snapshot every **4 hours**: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
- Rationale: data has 5-min resolution; 4h cadence gives 6 entry candidates per
  day without drowning in near-identical observations

### 3.3 DTE (time to expiry at entry)
- **1 to 7 calendar days**  (DTE 1–7)
- Longer-dated options will not move 20%+ from a multi-day spot impulse in the
  short hold windows we care about (too much time value dampening delta)

### 3.4 Delta
- `|delta|` ∈ **[0.10, 0.40]**  (roughly 10-delta to 40-delta OTM)
- Below 0.10: too cheap, too unlikely to reach 20% gain, very wide spreads
- Above 0.40: near-ATM; expensive, low leverage ratio, dominated by big moves
- Both calls and puts included

### 3.5 Maximum hold period
- **4 calendar days** (96 hours) from entry
- Hard constraint: must exit *before* expiry (exit at earliest of: target
  reached, 4d elapsed, or expiry − 1h)
- Holding through expiry is not modelled (settlement mechanics differ)

### 3.6 Strike granularity
- Deribit lists strikes in round increments (500 or 1000 depending on spot
  level); no further filtering needed — just iterate what exists in the data

---

## 4. Scan Methodology

### Step 1 — Build candidate trade records

For each (entry_date, entry_time, option) in the filtered universe:

1. Look up `ask_price` at entry → `entry_ask_usd`
2. Apply filters: `entry_ask_usd ≥ 75`, `|delta| ∈ [0.10, 0.40]`, `DTE ≤ 7`
3. Walk forward through subsequent 5-min snapshots (same parquet day, then next
   days) up to max 96h or expiry − 1h
4. At each future snapshot: look up `bid_price` → `exit_bid_usd`
5. Compute `gross_gain_pct = (exit_bid_usd / entry_ask_usd − 1) × 100`
6. If `gross_gain_pct ≥ 20%`: compute fees, check net P&L > 0 → mark as
   **tradeable**; record exit timestamp, exit price, hold_hours
7. Record the **first** exit that passes (earliest tradeable exit within max hold)
8. Also record the **peak** exit (highest bid in the hold window) for reference

Output: one row per (entry_ts, option) with columns:
`entry_ts, expiry, strike, is_call, dte_at_entry, delta_at_entry,
entry_ask_usd, entry_ask_btc, entry_iv, entry_spot,
tradeable (bool), exit_ts, exit_bid_usd, gross_gain_pct, net_pnl_usd,
hold_hours_to_exit, peak_bid_usd, peak_hold_hours`

### Step 2 — Enrich with spot / IV context

Join the tradeable subset back to spot data at entry:
- `spot_price_at_entry`
- `spot_1h_change_pct` (1h prior move)
- `spot_4h_change_pct`, `spot_24h_change_pct`
- `iv_at_entry` (mark_iv of the option itself)
- `iv_atm_1dte` (1DTE ATM call IV at entry hour, from iv_intraday_summary.parquet
  if available, else computed fresh)
- `iv_vs_seasonal_median` (is IV above or below typical for this hour/DTE?)

For each tradeable trade: compute the spot move that *actually occurred*
between entry_ts and exit_ts:
- `spot_move_pct` (signed: positive = up)
- `spot_max_up_pct` (max high from entry to exit window)
- `spot_max_down_pct` (max low from entry to exit window)

---

## 5. Analysis Dimensions

Once the raw scan is complete, analyse the tradeable trades along these axes:

### 5.1 Frequency / base rate
- How many tradeable long options were there per day / per week?
- Breakdown: calls vs puts, DTE bucket (1, 2–3, 4–7), delta bucket

### 5.2 Timing patterns
- Entry hour distribution of tradeable trades
- Holding period distribution (how fast did they pay off?)
- Day-of-week pattern

### 5.3 Spot environment at entry
- What was the spot doing when tradeable options were entered?
  (trend, recent move size, time since last big candle)
- Distribution of `spot_4h_change_pct` at entry for tradeable vs non-tradeable

### 5.4 IV environment at entry
- Was IV elevated or suppressed relative to the hourly seasonal?
- Calls vs puts: does skew level predict which leg becomes tradeable?

### 5.5 Spot move required
- What minimum spot move was needed to hit the 20% profit threshold?
- Distribution by DTE, delta, IV at entry
- Does a higher IV at entry require a *smaller* spot move? (yes, via higher
  delta / vega convexity — quantify this)

### 5.6 Speed of gain
- Histogram: how many hours from entry to first 20% gain?
- Segmented by DTE: do 1DTE options pay faster than 3DTE?

---

## 6. Anticipated Outputs / Scripts

| Script | Purpose |
|---|---|
| `option_utils.py` | **Symlinked or copied from intraday_options/** — shared library |
| `01_scan_tradeable_longs.py` | Main scan; produces `tradeable_longs_raw.parquet` |
| `02_enrich_context.py` | Joins spot/IV context; produces `tradeable_longs_enriched.parquet` |
| `03_frequency_stats.py` | Base rates, breakdowns; `frequency_stats.csv` + charts |
| `04_timing_analysis.py` | Entry hour, hold period, DoW distributions |
| `05_spot_iv_at_entry.py` | Spot trend + IV level at entry; heatmaps |
| `06_move_required.py` | Required spot move vs (DTE, delta, IV) |
| `07_signal_hunt.py` | Regression / feature importance: what predicts tradeable? |
| `build_docs.py` | Render HTML research report |

All outputs (CSVs, SVGs, parquets) written to this folder.

---

## 7. Data Dependencies

| File | Source | Notes |
|---|---|---|
| `option_data/options_YYYY-MM-DD.parquet` | Shared with intraday_options | Symlink or copy path |
| `option_data/spot_YYYY-MM-DD.parquet` | Shared | Same |
| `iv_intraday_summary.parquet` | From intraday_options/ | Reuse if applicable |

The scan covers 133 calendar days (2026-01-01 → 2026-05-12).  At 6 entry
snapshots/day × ~200 options per snapshot in the delta/DTE window, that is
approximately **160,000 candidate rows** before hold-period expansion.  With
parquet caching this should complete in a few minutes.

---

## 8. Open Questions / Decisions Needed

1. **Strike stepping at entry** — do we include *all* strikes in delta range,
   or pick the single nearest strike per 0.05-delta bucket to avoid redundant
   observations?
2. **Weekends** — allow entries Saturday/Sunday or exclude?  (Lower liquidity,
   wider spreads — probably exclude from entry but allow holding through.)
3. **Fee constant verification** — confirm exact Deribit option taker fee from
   `cryotrader/backtester` before finalising the profitability filter.
4. **IV context source** — recompute IV seasonal from scratch (using 2026 data
   only) or reuse the `iv_intraday_summary.parquet` from `intraday_options/`
   (which uses a 90-day trailing window ending May 2026)?
5. **Delta bucket resolution** — 0.10 to 0.40 in steps of 0.05, or broader
   buckets (0.10–0.20 "low delta", 0.20–0.40 "mid delta")?

---

## 9. Next Steps

1. Confirm fee model constants (question 3 above)
2. Confirm delta / DTE filters (questions 1, 5)
3. Build `01_scan_tradeable_longs.py` — scan and produce raw parquet
4. Spot-check a handful of tradeable trades manually to verify correctness
5. Proceed with enrichment and analysis scripts
