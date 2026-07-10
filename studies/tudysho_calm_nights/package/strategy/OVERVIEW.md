# TuDySho — strategy overview

Short-DTE OTM premium on Deribit BTC options. Three scheduled **slots** on one account (max one concurrent position).

## Slots (live)

| Slot | NYC days | Entry (NYC) | DTE | Expiry | Turbulence |
|------|----------|-------------|-----|--------|------------|
| **A** `slot_a_mon_thu` | Mon–Thu | 16:00 | 1 | Next day 08:00 UTC | threshold **60** |
| **B** `slot_b_mon_early` | Mon | 01:00 | 0 | Same Mon 08:00 UTC | threshold **99** (open) |
| **C** `slot_c_fri_sat` | Fri | 12:00 | 1 | Sat 08:00 UTC | threshold **99** (open) |

Monday may have **two sequential trades** (B expires 08:00 UTC, then A at 16:00 NYC).

## Shared params (all slots)

| Param | Value | Notes |
|-------|-------|-------|
| `leg_type` | strangle | Sell OTM call + put |
| `delta` | 0.10 | Target before `min_otm_pct` push |
| `nav_premium_pct` | 0.8 | Target premium as % of NAV |
| `max_qty_per_1btc_equity` | 12 | Hard cap on contracts per BTC equity |
| `leg_min_price` | 0 | Positive bid only |

## Why params feel "extreme"

- **Late entry** (A at NYSE close) + **low delta** + **`min_otm_pct` 2.6%** → strikes far OTM
- Legs often bid at **0.0001 BTC** minimum tick
- Sizing needs **~10–19 contracts** per leg to hit 0.8% NAV premium
- Win rate ~99% but poor **contract efficiency**

## Isolated backtest stats (Jun 2025 – Jun 2026, $100k)

From [`backtest_stats.json`](backtest_stats.json):

| Slot | Trades | Return | Sharpe | Max DD | Win rate |
|------|--------|--------|--------|--------|----------|
| A | 143 | +92.5% | 9.0 | 10.7% | 99.3% |
| B | 30 | +13.6% | 5.2 | 3.1% | 100% |
| C | 51 | (see JSON) | — | — | — |

Combined marketing merge (0.5× size scale): 224 trades, ~+67% return, Sharpe ~11, max DD ~5.8% intraday-scaled.

**Known tail:** Slot A Oct-2025 expiry loss ~$1,095 (spot moved through put strike).

## Research goal

Keep `nav_premium_pct = 0.8%` but reduce contracts by entering **earlier on calm days** (higher premium per contract at higher delta).

## Code references (CryoBacktester)

- Strategy: `backtester/strategies/tudysho.py`
- Handover: `handover/tudysho_cryotrader/`
- Live target: CryoTrader fork of `short_str_turb_dyn.py`
