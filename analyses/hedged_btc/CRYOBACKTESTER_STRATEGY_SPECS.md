# Hedged BTC — CryoBacktester strategy specs

**Audience:** AI agents implementing strategies in `/Users/ulrikdeichsel/CryoBacktester`  
**Companion:** [`APPROACH.md`](APPROACH.md) (design intent) · [`RESULTS.md`](RESULTS.md) (Phase 1–2 findings)  
**Canonical code pattern:** `backtester/strategies/blueprint_howto.py`  
**Multi-leg roll pattern:** `backtester/strategies/pagoda.py` (`partial_close` + `add_legs`)  
**Perp hedge pattern:** `backtester/strategies/covered_call_put.py` (synthetic perp PnL outside `price_legs`)

**Status:** Spec only — no implementation files yet.  
**Goal:** Tick-level (5-min) fund NAV vs buy-and-hold BTCUSD on identical data, regime-fair evaluation.

---

## Shared conventions (all candidates)

### Product framing

Each strategy models a **1 BTC spot unit** fund book:

```
NAVₜ = (spotₜ + Σ option_leg_mtmₜ + cash_premiumsₜ) / spot₀
```

- **Spot** is implicit (not a traded leg) — same convention as Phase 2 `nav_sim.py`.
- **Cash premiums** = net option premium paid/received at open/close, minus Deribit fees.
- **Benchmark:** BTC buy-and-hold equity `spotₜ / spot₀` on every tick (engine can emit alongside strategy NAV).

### Engine integration

| Requirement | Notes |
|---|---|
| Class protocol | `configure` / `on_market_state` / `on_end` / `reset` per `strategy_base.py` |
| Positions | `self._positions: List[OpenPosition]` — engine reads for NAV |
| Leg dict fields | All mandatory open/close fields per `AGENTS.md` §Required leg fields |
| Fees | `deribit_fee_per_leg(spot, premium_usd)` on every leg event |
| Pricing | Entry: executable (long=ask, short=bid). MTM/SL: mark. Rolls: executable. |
| IV | `mark_iv` in parquet is **already percent** (e.g. `45.5` = 45.5%) — do not rescale |
| Expiry | Options settle 08:00 UTC; use `check_expiry`, `EXPIRY_HOUR_UTC`, `expiry_dt_utc` |
| Registration | Add to `backtester/run.py` `STRATEGIES` dict |

### Shared `PARAM_GRID` keys (all strategies)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `qty` | float | `1.0` | BTC-notional unit (always 1.0 for fund sim) |
| `entry_hour_utc` | int | `8` | First roll/entry tick at or after this UTC hour |
| `entry_minute_utc` | int | `0` | Minute component of entry gate |
| `skip_weekends` | int | `0` | `0`=none · `3`=skip Sat+Sun (optional; BTC trades 24/7) |
| `iv_ceiling_pct` | float | `55.0` | Defer discretionary protection rolls when ATM IV above |
| `critical_prot_dte` | int | `7` | Always roll protection at/below this DTE regardless of IV gate |
| `ratchet_pct` | float | `0.12` | Protection ratchet: roll up strikes after spot rally vs open (`0`=off) |

### Shared roll priority (`on_market_state`)

Check in this order every tick:

1. **Settle / expire** any leg whose `expiry_dt` has passed (`check_expiry`, intrinsic settlement).
2. **Roll income sleeve** if short-leg DTE ≤ `income_roll_min_dte` → `partial_close` income legs + `add_legs`.
3. **Roll protection sleeve** if protection DTE ≤ `prot_roll_min_dte` OR ratchet fired OR IV gate allows → close protection legs + open new protection.
4. **Initial open** if flat and past entry gate.

### Evaluation deliverables (Phase 3)

Do **not** rank on start→end return alone. Emit:

- Daily NAV series + BTC benchmark series
- Regime splits: `early_rally` (2025-04-11→2025-09-30), `oct_decline` (2025-10-01→end), `feb_2026_crash`
- Monthly excess vs BTC
- Layer attribution (C4 only): L1 / L2 / L3 / L4 PnL contribution
- Roll count + fee drag

Reuse regime logic from CryoQuant `analyses/hedged_btc/report.py`.

### Candidates to implement (priority order)

| Priority | ID | CryoBacktester `name` | Rationale |
|---|---|---|---|
| **1** | C4 | `hedged_btc_c4` | Primary product synthesis; best rally/bear balance in Phase 2 regime analysis |
| **2** | C3 | `hedged_btc_c3` | Best bear-leg; skew harvester; direct comparator for C4 |
| **3** | C5 | `hedged_btc_c5` | Upside-open income (no short calls on core); needs perp delta-hedge |
| **4** | C6 | `hedged_btc_c6` | Control benchmark (unhedged upside, tail insurance only) |

**Deprioritise for backtester:** C1 (rally drag), C2 (tail failure) — optional later as honesty checks.

---

## Spec 1 — `hedged_btc_c4` (Four-layer book) · **PRIMARY**

### Intent

Fund-style book: **participate in rallies**, **limit drawdowns**, **anti-fragile in crashes**.
Phase 2 regime read: +29.7% vs BTC +37.4% in rally; −33.7% vs BTC −46.8% in Oct decline.

### Structure (four independent sleeves)

```
Implicit long 1 BTC spot

L1 — Core protection (quarterly put spread)
  BUY  ATM put           (δ ≈ −0.45 to −0.50)
  SELL far OTM put       (strike ≈ spot × (1 − l1_lower_otm_pct))

L2 — Income (rolling short calls)
  SELL OTM call          (δ ≈ +l2_call_delta, biweekly tenor)

L3 — Conditional carry  [OPTIONAL v1 — default OFF]
  SELL BTC-PERPETUAL     (qty = l3_perp_frac × spot) when funding APR > l3_funding_trigger
  → Post-Mar2026 Deribit funding ~0; implement flag but default trigger high (e.g. 5% APR)

L4 — Convexity kicker (put back-ratio, SEPARATE expiry from L1)
  SELL near OTM put      (strike ≈ spot × (1 − l4_short_otm_pct))   # MUST be ≤ L1 lower strike
  BUY  2× far OTM puts   (strike = L1 lower strike or l4_long_otm_pct)
```

**Critical rule (from APPROACH):** `l4_short_otm_pct` ≤ `l1_lower_otm_pct` — avoids the −19%…−25% pain pocket.

### `PARAM_GRID` (discovery — do not narrow post-hoc)

```python
PARAM_GRID = {
    "qty":                  [1.0],
    "entry_hour_utc":       [8],
    # L1 protection
    "l1_dte_min":           [75],
    "l1_dte_max":           [120],
    "l1_long_delta":        [0.45],          # ATM put
    "l1_lower_otm_pct":     [0.19],          # short put strike as fraction below spot
    "prot_roll_min_dte":    [21],
    # L2 income
    "l2_dte_min":           [10],
    "l2_dte_max":           [18],
    "l2_call_delta":        [0.22, 0.25],     # covered call target
    "income_roll_min_dte":  [3],
    # L4 convexity (separate expiry band)
    "l4_dte_min":           [75],
    "l4_dte_max":           [120],
    "l4_short_otm_pct":     [0.06],          # must be <= l1_lower_otm_pct
    "l4_long_otm_pct":      [0.19],          # aligns with L1 lower
    "l4_roll_min_dte":      [21],
    # L3 carry (off by default)
    "l3_enabled":           [0],              # 0=off, 1=on
    "l3_funding_trigger":   [0.05],           # APR; only matters if l3_enabled=1
    "l3_perp_frac":         [0.10],           # fraction of 1 BTC notional
    # Shared rolls
    "ratchet_pct":          [0.12],
    "iv_ceiling_pct":       [55.0],
    "critical_prot_dte":    [7],
}
```

### Position model

**One `OpenPosition`** with tagged legs in `metadata`:

```python
metadata = {
    "book": "c4",
    "layers": {
        "L1": [leg_ids...],
        "L2": [leg_ids...],
        "L3": [],           # perp tracked separately like covered_call_put
        "L4": [leg_ids...],
    },
    "l1_expiry": "...", "l2_expiry": "...", "l4_expiry": "...",
    "spot_at_l1_open": float,
}
```

- L2 rolls via `partial_close` (income legs only) + `add_legs` — **pagoda pattern**.
- L1 and L4 roll independently when各自的 DTE thresholds hit; L4 need not roll with L1.
- L3 perp: synthetic leg; PnL at close like `covered_call_put._do_close`.

### Entry

- **Day 1** of `DATE_RANGE` at `entry_hour_utc`: open L1 + L2 + L4 (L3 if enabled and funding gate passes).
- If any leg fails selection (illiquid strike), skip entire open for that tick (log reason).

### Exit conditions

No SL/TP on the book. Exits are **rolls** and **expiry settlement** only.

| Event | Action |
|---|---|
| L2 DTE ≤ `income_roll_min_dte` | Roll short call only |
| L1 DTE ≤ `prot_roll_min_dte` (and IV gate / ratchet) | Close L1 legs; reopen L1 at new expiry/strikes |
| L4 DTE ≤ `l4_roll_min_dte` | Close L4 legs; reopen L4 (verify overlap rule) |
| L3 funding drops below trigger | Close perp slice |
| End of `DATE_RANGE` | Force-close all legs at executable prices |

### `DATE_RANGE`

```python
DATE_RANGE = ("2025-04-11", "2026-06-07")  # match chain coverage
```

### Phase 2 fixes required (do not repeat v1 shortcuts)

- L4 on **separate expiry** from L1
- L2 uses **delta selection** (`select_by_delta`), not fixed % OTM
- Enforce **L4 short ≤ L1 lower strike**
- Layer attribution in `on_end` or report bundle

### `DESCRIPTION`

```
Four-layer hedged BTC fund: L1 quarterly put spread + L2 rolling covered calls +
optional L3 funding carry + L4 put back-ratio convexity.  1 BTC notional.
Roll-driven; no SL/TP.  Primary product candidate.
```

---

## Spec 2 — `hedged_btc_c3` (Skew diagonal)

### Intent

Harvest **front/back skew spread**: long quarterly hard floor, financed by short front OTM calls.
Phase 2: best **Oct decline** excess (+28.4 pp) but **rally drag** (−15.8 pp vs BTC in Apr–Sep).

### Structure

```
Implicit long 1 BTC spot

Protection sleeve (quarterly)
  BUY  ATM put   (δ ≈ −prot_delta, DTE ∈ [prot_dte_min, prot_dte_max])

Income sleeve (front, rolls frequently)
  SELL OTM call  (strike ≈ spot × (1 + income_call_otm_pct) OR δ ≈ +income_call_delta)
                 (DTE ∈ [income_dte_min, income_dte_max])
```

### `PARAM_GRID`

```python
PARAM_GRID = {
    "qty":                  [1.0],
    "entry_hour_utc":       [8],
    # Protection
    "prot_dte_min":         [75],
    "prot_dte_max":         [105],
    "prot_delta":           [0.45],
    "prot_roll_min_dte":    [14],
    # Income
    "income_dte_min":       [7],
    "income_dte_max":       [14],
    "income_call_otm_pct":  [0.07],          # ~+7% OTM per APPROACH
    "income_roll_min_dte":  [2],
    # Shared
    "ratchet_pct":          [0.10],
    "iv_ceiling_pct":       [55.0],
    "critical_prot_dte":    [7],
}
```

### Position model

One `OpenPosition`; two sleeve groups in metadata (`protection`, `income`).  
Income rolls on short DTE — **pagoda `partial_close` + `add_legs`**.  
Protection rolls on calendar/ratchet/IV gate — close protection legs only, keep income if alive.

### Entry / exit

Same shared roll priority. No SL/TP. Initial open: both sleeves on first eligible tick.

### `DATE_RANGE`

```python
DATE_RANGE = ("2025-04-11", "2026-06-07")
```

### `DESCRIPTION`

```
Skew diagonal: long quarterly ATM put + rolling short front OTM calls against 1 BTC spot.
Hard floor at put strike; upside capped between income rolls.  Skew harvester.
```

### Backtest questions this spec must answer

- Does skew income **overpay** for protection net of fees across full path?
- Rally participation vs C4 in `early_rally` regime
- Mid-period MTM drawdown before quarterly put expiry (fast −18% 24h moves)

---

## Spec 3 — `hedged_btc_c5` (Protected core + VRP harvester)

### Intent

Keep **full upside** on the spot core (no short calls); finance hedge via **delta-hedged short vol**.
Cleanest VRP expression; operationally heaviest.

### Structure

```
Implicit long 1 BTC spot

Protection sleeve (quarterly put spread — same as C4 L1)
  BUY  ATM put
  SELL far OTM put   (strike ≈ spot × (1 − prot_lower_otm_pct))

Income sleeve (front short strangle/straddle, delta-hedged)
  SELL OTM put   (δ ≈ −income_put_delta)
  SELL OTM call  (δ ≈ +income_call_delta)
  BUY/SELL BTC-PERPETUAL  to keep net book delta ≈ income_sleeve_delta_target
```

### `PARAM_GRID`

```python
PARAM_GRID = {
    "qty":                  [1.0],
    "entry_hour_utc":       [8],
    # Protection (same as C4 L1)
    "prot_dte_min":         [75],
    "prot_dte_max":         [105],
    "prot_delta":           [0.45],
    "prot_lower_otm_pct":   [0.10],
    "prot_roll_min_dte":    [14],
    # Income strangle
    "income_dte_min":       [7],
    "income_dte_max":       [12],
    "income_put_delta":     [0.20],
    "income_call_delta":    [0.20],
    "income_roll_min_dte":  [2],
    # Delta hedge (perp)
    "hedge_interval_min":   [5],             # re-hedge every N minutes (match data cadence)
    "income_sleeve_delta_target": [0.0],     # net delta target for income sleeve
    "max_perp_notional":    [1.0],           # cap perp size vs 1 BTC
    # Shared
    "ratchet_pct":          [0.12],
    "iv_ceiling_pct":       [55.0],
    "critical_prot_dte":    [7],
}
```

### Position model

One `OpenPosition` for options; perp hedge tracked like `covered_call_put`:

- Option legs in `pos.legs`
- Perp qty in `metadata["perp_qty"]`; rebalanced on `hedge_interval_min`
- At income roll: close strangle + flatten perp + open new strangle + re-hedge

### Entry / exit

- Protection: roll on DTE/ratchet (same as C3/C4 L1)
- Income: roll on DTE; **re-hedge perp every `hedge_interval_min`** while income sleeve open
- Crash correlation test: log income sleeve loss vs protection gain in `feb_2026_crash`

### Approximation flag

Document in `DESCRIPTION` and report bundle: delta-hedge uses 5-min snapshots only (no tick-level fill simulation). Slippage = Deribit perp taker fee only unless extended.

### `DATE_RANGE`

```python
DATE_RANGE = ("2025-04-11", "2026-06-07")
```

### `DESCRIPTION`

```
Protected put spread + delta-hedged short front strangle against 1 BTC spot.  No short calls
on core — full upside retained.  Perp re-hedge on income sleeve.  VRP-financed hedge.
```

---

## Spec 4 — `hedged_btc_c6` (Tail-risk overlay) · **CONTROL**

### Intent

Minimalist **benchmark**: maximal upside, catastrophe insurance only. Every fancier design must beat this on risk-adjusted path, not just endpoint.

### Structure

```
Implicit long 1 BTC spot

Protection only
  BUY  far OTM put   (strike ≈ spot × (1 − tail_otm_pct), DTE ∈ [tail_dte_min, tail_dte_max])
```

### `PARAM_GRID`

```python
PARAM_GRID = {
    "qty":              [1.0],
    "entry_hour_utc":   [8],
    "tail_dte_min":     [75],
    "tail_dte_max":     [105],
    "tail_otm_pct":     [0.16, 0.20],       # −16% / −20% OTM
    "prot_roll_min_dte":[14],
    "ratchet_pct":      [0.0],              # no ratchet on tail overlay
    "iv_ceiling_pct":   [65.0],
    "critical_prot_dte":[7],
}
```

### Position model

Single-leg (or multi if grid expands); simplest blueprint-like book.

### `DATE_RANGE`

```python
DATE_RANGE = ("2025-04-11", "2026-06-07")
```

### `DESCRIPTION`

```
Tail-risk overlay: long 1 BTC spot + rolling far OTM long puts only.  Control candidate.
No income engine.  Maximal upside; crash-only hedge.
```

---

## Implementation checklist (agent)

```
[ ] Create backtester/strategies/hedged_btc_c4.py  (first)
[ ] Create backtester/strategies/hedged_btc_c3.py
[ ] Create backtester/strategies/hedged_btc_c5.py  (after perp pattern validated)
[ ] Create backtester/strategies/hedged_btc_c6.py  (control)
[ ] Register all four in backtester/run.py STRATEGIES
[ ] DATE_RANGE = ("2025-04-11", "2026-06-07") for all
[ ] Emit BTC benchmark series in report bundle (or post-process from spot parquets)
[ ] Port regime report from CryoQuant report.py into backtester report step
[ ] experiments/hedged_btc_phase3.toml — narrow grid only after wide discovery run
[ ] Do NOT copy CryoBacktester data into CryoQuant repo
```

## Experiment TOML stub (post-discovery)

Save as `backtester/experiments/hedged_btc_phase3.toml` once wide grids have run:

```toml
# Hedged BTC Phase 3 — comparative run (identical window, identical fees)
# Strategies: hedged_btc_c4, hedged_btc_c3, hedged_btc_c5, hedged_btc_c6
date_range = ["2025-04-11", "2026-06-07"]

[strategies.hedged_btc_c4]
# paste winning combo from discovery grid

[strategies.hedged_btc_c3]
# paste winning combo

# Evaluation: regime splits + monthly excess (not endpoint rank)
```

---

## Revision log

| Date | Change |
|---|---|
| 2026-06-10 | Initial specs — C4 primary, C3/C5/C6 comparators; blueprint/pagoda/covered_call_put patterns |
