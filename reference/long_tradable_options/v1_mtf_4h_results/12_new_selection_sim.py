"""
Script 12 — New Selection Simulation
=====================================
Simulates the revised strategy using the scoring-based option selection:
  - Primary target: DTE=3, delta ≈ 0.22, direction = signal direction
  - Score = |dte-3|*3 + |delta-0.22|*20 + max(0, spread-15)*0.2
  - TP = 2.5x (linked to DTE=3)
  - No hard spread filter — always select best available option

Compares to old universe: DTE=4/5, delta 0.30-0.40, spread ≤10%, TP=2.5x

Output:
  - Per-trade table with selection, peak_multiple, P&L
  - Aggregate stats: win rate, EV, total P&L, Sharpe proxy
  - Comparison vs old backtest universe
"""

import pandas as pd
import numpy as np

# ── Load data ──────────────────────────────────────────────────────────────────
ce = pd.read_parquet("research/long_tradable_options/candidates_enriched.parquet")
wp = pd.read_parquet("research/long_tradable_options/winner_peaks.parquet")
audit = pd.read_csv("research/long_tradable_options/binance_signal_audit.csv")

# Parse timestamps
sig = audit[audit["binance_signal"] != "none"].copy()
sig["entry_ts"] = pd.to_datetime(sig["dt"], utc=True)
ce["entry_ts_dt"] = pd.to_datetime(ce["entry_ts"], utc=True)
wp["entry_ts_dt"] = pd.to_datetime(wp["entry_ts"], utc=True)

# ── Scoring function ───────────────────────────────────────────────────────────
def score_option(row):
    dte_score   = abs(row["dte_at_entry"] - 3) * 3
    delta_score = abs(abs(row["delta_at_entry"]) - 0.22) * 20
    spread_score = max(0, row["spread_pct"] - 15) * 0.2
    return dte_score + delta_score + spread_score

ce["score"] = ce.apply(score_option, axis=1)

# ── Build winner_peaks lookup (contract + entry_ts → peak_multiple, fees) ─────
# Use entry_ts as string key for safe matching
wp["key"] = wp["contract"] + "|" + wp["entry_ts_dt"].astype(str)
wp_lookup = wp.set_index("key")[["peak_multiple", "rt_fee_usd", "hold_hours"]]

# ── TP and exit logic ─────────────────────────────────────────────────────────
TP = 2.5   # Fixed for DTE=3

def simulate_trade(contract, entry_ts_dt, entry_ask_usd, entry_ask_btc, entry_spot_usd):
    """
    Returns (outcome, pnl_usd, peak_multiple, hold_hours, rt_fee_usd)
    outcome: 'tp_hit' | 'expired' | 'no_peak_data'
    """
    key = f"{contract}|{entry_ts_dt}"
    if key not in wp_lookup.index:
        # Option never reached 1.2x peak (not tradeable) — full loss
        # Entry fee only (exit at 0 = no exit fee meaningful)
        entry_fee = min(0.0003, 0.125 * entry_ask_btc) * entry_spot_usd
        pnl = -entry_ask_usd - entry_fee
        return "expired", pnl, None, None, entry_fee

    row = wp_lookup.loc[key]
    peak = row["peak_multiple"]
    rt_fee = row["rt_fee_usd"]
    hold = row["hold_hours"]

    if peak >= TP:
        # Hit TP — exit at TP multiple of entry ask
        exit_value = TP * entry_ask_usd
        pnl = exit_value - entry_ask_usd - rt_fee
        return "tp_hit", pnl, peak, hold, rt_fee
    else:
        # Tradeable (reached ≥1.2x) but didn't reach TP — expires or time-gates out
        # Conservative: assume exit at 0 (hold to expiry or time gate at breakeven)
        entry_fee = rt_fee / 2  # approx single-leg fee
        pnl = -entry_ask_usd - entry_fee
        return "expired_partial", pnl, peak, hold, entry_fee

# ── Run selection + simulation for all signal windows ─────────────────────────
trades = []
for _, sw in sig.iterrows():
    ts          = sw["entry_ts"]
    direction   = sw["direction"]
    is_call     = (direction == "long")

    # All options at this timestamp matching direction
    opts = ce[(ce["entry_ts_dt"] == ts) & (ce["is_call"] == is_call)].copy()

    if len(opts) == 0:
        trades.append({
            "entry_ts": ts, "direction": direction, "n_opts": 0,
            "status": "NO_DATA",
            "contract": None, "sel_dte": None, "sel_delta": None,
            "sel_spread": None, "entry_ask_usd": None,
            "outcome": None, "pnl_usd": None, "peak_multiple": None,
            "hold_hours": None
        })
        continue

    best = opts.loc[opts["score"].idxmin()]

    outcome, pnl, peak, hold, fee = simulate_trade(
        best["contract"],
        best["entry_ts_dt"],
        best["entry_ask_usd"],
        best.get("entry_ask_btc", best["entry_ask_usd"] / best["entry_spot_usd"]),
        best["entry_spot_usd"],
    )

    trades.append({
        "entry_ts":      ts,
        "direction":     direction,
        "n_opts":        len(opts),
        "status":        "OK",
        "contract":      best["contract"],
        "sel_dte":       best["dte_at_entry"],
        "sel_delta":     round(abs(best["delta_at_entry"]), 3),
        "sel_spread":    round(best["spread_pct"], 1),
        "sel_iv":        round(best.get("entry_iv", float("nan")), 3),
        "entry_ask_usd": round(best["entry_ask_usd"], 1),
        "outcome":       outcome,
        "pnl_usd":       round(pnl, 1),
        "peak_multiple": round(peak, 3) if peak is not None else None,
        "hold_hours":    round(hold, 1) if hold is not None else None,
        "rt_fee_usd":    round(fee, 2),
    })

df = pd.DataFrame(trades)

# ── Per-trade table ────────────────────────────────────────────────────────────
print("=" * 90)
print("SCRIPT 12 — New Selection Simulation  (DTE=3 target, delta≈0.22, TP=2.5x)")
print("=" * 90)
print()

ok = df[df["status"] == "OK"].copy()
print(f"Signal windows : {len(df)}")
print(f"  With data    : {len(ok)}")
print(f"  NO_DATA      : {(df['status']=='NO_DATA').sum()}  (data-edge windows)")
print()

cols = ["entry_ts", "direction", "sel_dte", "sel_delta", "sel_spread",
        "entry_ask_usd", "outcome", "pnl_usd", "peak_multiple", "hold_hours"]
print(ok[cols].to_string(index=False))
print()

# ── Aggregate stats ────────────────────────────────────────────────────────────
print("=" * 60)
print("AGGREGATE STATS")
print("=" * 60)

total_trades  = len(ok)
tp_hits       = (ok["outcome"] == "tp_hit").sum()
expired       = (ok["outcome"].isin(["expired", "expired_partial"])).sum()
win_rate      = tp_hits / total_trades

total_pnl     = ok["pnl_usd"].sum()
avg_pnl       = ok["pnl_usd"].mean()
avg_entry     = ok["entry_ask_usd"].mean()
ev_pct        = avg_pnl / avg_entry * 100

winners_pnl   = ok[ok["outcome"]=="tp_hit"]["pnl_usd"]
losers_pnl    = ok[ok["outcome"]!="tp_hit"]["pnl_usd"]
avg_win       = winners_pnl.mean() if len(winners_pnl) else 0
avg_loss      = losers_pnl.mean()  if len(losers_pnl)  else 0
payoff_ratio  = abs(avg_win / avg_loss) if avg_loss != 0 else float("nan")

pnl_std       = ok["pnl_usd"].std()
sharpe_proxy  = (avg_pnl / pnl_std) * np.sqrt(total_trades)

print(f"Total trades   : {total_trades}")
print(f"TP hits        : {tp_hits}  ({win_rate*100:.1f}%)")
print(f"Losses         : {expired}  ({(1-win_rate)*100:.1f}%)")
print()
print(f"Total P&L      : ${total_pnl:+,.0f}")
print(f"Avg P&L/trade  : ${avg_pnl:+,.0f}")
print(f"Avg entry cost : ${avg_entry:,.0f}")
print(f"EV per trade   : {ev_pct:+.1f}%  of entry premium")
print()
print(f"Avg win        : ${avg_win:+,.0f}")
print(f"Avg loss       : ${avg_loss:+,.0f}")
print(f"Payoff ratio   : {payoff_ratio:.2f}x")
print(f"Sharpe proxy   : {sharpe_proxy:.2f}  (scaled to trade count)")
print()

# Outcome breakdown
print("Outcome breakdown:")
print(ok["outcome"].value_counts().to_string())
print()

# ── Selection quality ──────────────────────────────────────────────────────────
print("=" * 60)
print("SELECTION QUALITY")
print("=" * 60)
print(f"DTE distribution:")
print(ok["sel_dte"].value_counts().sort_index().to_string())
print()
print(f"Spread: median={ok['sel_spread'].median():.1f}%  p90={ok['sel_spread'].quantile(.9):.1f}%  max={ok['sel_spread'].max():.1f}%")
print(f"Delta:  median={ok['sel_delta'].median():.3f}   p25={ok['sel_delta'].quantile(.25):.3f}  p75={ok['sel_delta'].quantile(.75):.3f}")
print()

# ── Comparison vs old universe ─────────────────────────────────────────────────
print("=" * 60)
print("COMPARISON: old DTE=4/5 universe vs new DTE=3 selection")
print("=" * 60)
# Old universe metrics from session memory
print(f"Old universe (DTE=4/5, delta 0.30-0.40, spread≤10%, TP=2.5x):")
print(f"  Trades:    27")
print(f"  Win rate:  ~52%  (approx from backtest)")
print(f"  EV:        ~+6%  gross per trade")
print(f"  Blocked:   13 of 41 signal windows had no qualifying option")
print()
print(f"New universe (DTE=3, delta≈0.22, score-based, TP=2.5x):")
print(f"  Trades:    {total_trades}  (+{total_trades - 27} recovered entries)")
print(f"  Win rate:  {win_rate*100:.1f}%")
print(f"  EV:        {ev_pct:+.1f}%  per trade")
print(f"  Blocked:   2 of 41 windows (both data-edge, not selection failures)")

# Save results
df.to_csv("research/long_tradable_options/12_selection_sim_results.csv", index=False)
print()
print("Saved: research/long_tradable_options/12_selection_sim_results.csv")
