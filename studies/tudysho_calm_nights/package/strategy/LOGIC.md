# TuDySho — strategy logic (condensed)

Condensed from CryoBacktester `handover/tudysho_cryotrader/STRATEGY_LOGIC.md`.

## Entry

1. **`entry_time` is NYC wall-clock** (DST-aware), converted to UTC each tick.
2. After entry time: open when **turbulence composite < `turbulence_threshold`**.
3. **Fail-open:** missing/NaN turbulence → allow entry.
4. **Weekday:** resolve slot from NYC weekday + time (not grid `trade_*` flags at live).
5. **Leg selection:** `select_by_delta` → optional `min_otm_pct` push further OTM → require positive bid.

## Sizing

```
target_premium_usd = nav_usd × (nav_premium_pct / 100)
qty = target_premium_usd / premium_usd_per_contract
qty = min(qty, equity_btc × max_qty_per_1btc_equity)   # if cap > 0
qty = max(round(qty, 1), 0.1)
```

Skip if `premium_usd_per_contract <= 0` or cap < 0.1.

## Exits (first match)

1. **Expiry** — 08:00 UTC settlement
2. **Strike proximity** — final N hours, spot vs strike ± buffer (quote-free)
3. **Equity drawdown** — disabled in live sets (0)
4. **Premium stop-loss** — mark-based multiplier; suppressed in final `premium_sl_except_final_hours`

Quote-based exits suppressed when option rows missing (except proximity).

## Slot A live params (primary research slot)

```json
{
  "entry_time": "16:00",
  "dte": 1,
  "delta": 0.10,
  "min_otm_pct": 2.6,
  "turbulence_threshold": 60,
  "nav_premium_pct": 0.8,
  "max_qty_per_1btc_equity": 12,
  "stop_loss_pct": 6.0,
  "proximity_stop_hours": 8,
  "proximity_buffer_usd": 1000,
  "premium_sl_except_final_hours": 8
}
```

## Turbulence gate

- Input: BTCUSDT 15m → hourly `composite` (0–100)
- Entry when `composite < threshold`
- CryoTrader uses **T−1h UTC bucket** for lookup (do not switch to NYC hours)

## Concurrency (live)

- Max **1** open position account-wide
- Max **1** entry per slot per NYC calendar day

## Proposed research change (if H1 confirmed)

**Morning quiet** (09:30–12:00 NYC extrusion) observed by 12:00:

| Profile | entry_time | delta | min_otm_pct |
|---------|------------|-------|-------------|
| aggressive | 12:00 | 0.20 | 1.0–1.5 |
| base | 16:00 | 0.10 | 2.6 |

Turbulence gate remains at actual entry tick. Store profile on position metadata for exit rules.
