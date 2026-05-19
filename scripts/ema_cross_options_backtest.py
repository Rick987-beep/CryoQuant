"""EMA 7/21 crossover — directional options backtest — BTCUSDT daily.

Strategy:
  EMA-7 crosses above EMA-21 → buy call
  EMA-7 crosses below EMA-21 → buy put

At entry: select the nearest expiry at DTE days out, closest-delta strike.
At exit:  mark-to-market after HOLD_DAYS days (bid price). If hold extends
          past expiry, use intrinsic value at expiry instead.

Edit the PARAMETERS section below to explore different setups.

Usage:
    python scripts/ema_cross_options_backtest.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from cryocore.instruments import Symbol
from cryoquant import config
from cryoquant.data.loader import load
from cryoquant.features.builders import DatasetRef, DailyEmaCrossFeatures
from cryoquant.backtest.option_lookup import (
    OptionResult,
    _best_leg,
    _load_chain_df,
    _spot_price_on_date,
)
from cryoquant.backtest.reports import render_option_result

# ── PARAMETERS ────────────────────────────────────────────────────────────────
DTE        = 3      # days-to-expiry at entry          (try: 1, 2, 3, 4, 7)
DELTA      = 0.30   # target absolute delta per leg     (try: 0.20, 0.25, 0.30, 0.40)
HOLD_DAYS  = 3      # hold duration in calendar days    (try: 1, 2, 3, 5, 7)
#                     Note: capped at DTE if hold > DTE (held to expiry → intrinsic)

CHAINS_DIR = config.CRYOBACKTESTER_DATA_DIR

# Load bars from a month before the earliest chain date to give EMA warmup.
# Chain data covers 2025-04-11 → 2026-05-12.
START = datetime(2025, 3, 1, tzinfo=timezone.utc)
END   = datetime.now(timezone.utc)

REPORTS = Path("reports")
REPORTS.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────


def _eval_leg(
    fire_timestamps,
    *,
    is_call: bool,
    bars,
    dte: int,
    delta: float,
    hold_days: int,
    chains_dir: Path,
) -> tuple[list[float], list[float], list[int]]:
    """Evaluate single-leg directional trades for all fire timestamps.

    Returns (pnl_pct, entry_costs_usd, dte_actual) — one entry per resolved fire.
    P&L is expressed as a fraction of entry cost (positive = profit).
    """
    pnl_pct: list[float] = []
    entry_costs_usd: list[float] = []
    dte_actual: list[int] = []

    for ts in fire_timestamps:
        fire_date   = ts.date()
        expiry_date = fire_date + timedelta(days=dte)

        entry_chain = _load_chain_df(chains_dir, fire_date)
        if entry_chain is None:
            continue

        spot = _spot_price_on_date(chains_dir, fire_date)
        if spot is None:
            if ts in bars.index:
                spot = float(bars.loc[ts, "close"])
            else:
                continue

        leg = _best_leg(entry_chain, expiry_date, delta, is_call=is_call)
        if leg is None:
            continue

        entry_ask = float(leg["ask_price"])
        entry_cost_usd = entry_ask * spot
        if entry_cost_usd <= 0:
            continue

        strike = float(leg["strike"])

        # Cap hold at expiry date
        exit_date = fire_date + timedelta(days=hold_days)
        at_expiry = exit_date >= expiry_date
        if at_expiry:
            exit_date = expiry_date

        if not at_expiry:
            # Mark-to-market exit: bid on the same leg at exit date
            exit_chain = _load_chain_df(chains_dir, exit_date)
            exit_spot  = _spot_price_on_date(chains_dir, exit_date)

            if exit_chain is None or exit_spot is None:
                # No chain file for that date — skip this fire
                continue

            exit_leg = _best_leg(exit_chain, expiry_date, delta, is_call=is_call)
            if exit_leg is not None:
                exit_bid = float(exit_leg["bid_price"])
                if exit_bid <= 0:
                    exit_bid = float(exit_leg["ask_price"]) * 0.9
                exit_value = exit_bid
            else:
                # Leg disappeared (illiquid near expiry) — intrinsic fallback
                if is_call:
                    exit_value = max(0.0, exit_spot - strike) / exit_spot
                else:
                    exit_value = max(0.0, strike - exit_spot) / exit_spot
        else:
            # Held to expiry — use intrinsic value
            exp_spot = _spot_price_on_date(chains_dir, expiry_date)
            if exp_spot is None:
                exp_spot = spot  # last resort fallback
            if is_call:
                exit_value = max(0.0, exp_spot - strike) / exp_spot
            else:
                exit_value = max(0.0, strike - exp_spot) / exp_spot

        pnl = (exit_value - entry_ask) / entry_ask
        pnl_pct.append(float(pnl))
        entry_costs_usd.append(float(entry_cost_usd))
        dte_actual.append((expiry_date - fire_date).days)

    return pnl_pct, entry_costs_usd, dte_actual


def _make_result(n_fires: int, pnl_pct, entry_costs_usd, dte_actual) -> OptionResult:
    n = len(pnl_pct)
    if n > 0:
        win_rate   = float(np.mean(np.array(pnl_pct) > 0))
        expectancy = float(np.mean(pnl_pct))
    else:
        win_rate   = float("nan")
        expectancy = float("nan")
    return OptionResult(
        fires_evaluated=n_fires,
        fires_with_data=n,
        pnl_pct=pnl_pct,
        win_rate=win_rate,
        expectancy=expectancy,
        entry_costs_usd=entry_costs_usd,
        dte_actual=dte_actual,
    )


def _print_result(label: str, result: OptionResult) -> None:
    print(f"\n── {label}")
    print(f"   Fires evaluated : {result.fires_evaluated}")
    print(f"   Fires with data : {result.fires_with_data}")
    if result.fires_with_data > 0:
        arr = np.array(result.pnl_pct)
        print(f"   Win rate        : {result.win_rate:.1%}")
        print(f"   Expectancy      : {result.expectancy:+.2%}")
        print(f"   Median P&L      : {float(np.median(arr)):+.2%}")
        print(f"   Best / Worst    : {arr.max():+.2%} / {arr.min():+.2%}")
        print(f"   Median cost USD : ${float(np.median(result.entry_costs_usd)):,.0f}")
    else:
        print("   No chain data found for these fire dates.")


# ── 1. Load bars ──────────────────────────────────────────────────────────────
print("── 1. Loading daily bars ───────────────────────────────────────────────")
sym    = Symbol("binance.spot", "BTCUSDT")
df_raw = load(sym, "1d", START, END)
print(f"   {len(df_raw)} bars  ({df_raw.index[0].date()} → {df_raw.index[-1].date()})")

# ── 2. Build EMA cross features ───────────────────────────────────────────────
print("\n── 2. Building EMA cross features ──────────────────────────────────────")
ref  = DatasetRef(sym, "1d")
X    = DailyEmaCrossFeatures().build({ref: df_raw})
new_cols = [c for c in X.columns if c not in df_raw.columns]
bars = df_raw.join(X[new_cols])

cross_up_times   = bars.index[X["cross_up"].fillna(False).astype(bool)]
cross_down_times = bars.index[X["cross_down"].fillna(False).astype(bool)]
print(f"   up-crosses  : {len(cross_up_times)}")
print(f"   down-crosses: {len(cross_down_times)}")

# ── 3. Parameters summary ─────────────────────────────────────────────────────
print(f"\n── Parameters: DTE={DTE}d  delta={DELTA}  hold={HOLD_DAYS}d ──────────")
print(f"   Chains dir: {CHAINS_DIR}")

# ── 4. Evaluate calls (cross up → buy call) ───────────────────────────────────
print("\n── 3. Evaluating calls (cross up → buy call) ───────────────────────────")
call_pnl, call_costs, call_dte = _eval_leg(
    cross_up_times,
    is_call=True,
    bars=bars,
    dte=DTE,
    delta=DELTA,
    hold_days=HOLD_DAYS,
    chains_dir=CHAINS_DIR,
)

# ── 5. Evaluate puts (cross down → buy put) ───────────────────────────────────
print("── 4. Evaluating puts  (cross down → buy put) ──────────────────────────")
put_pnl, put_costs, put_dte = _eval_leg(
    cross_down_times,
    is_call=False,
    bars=bars,
    dte=DTE,
    delta=DELTA,
    hold_days=HOLD_DAYS,
    chains_dir=CHAINS_DIR,
)

# ── 6. Results ────────────────────────────────────────────────────────────────
result_calls = _make_result(len(cross_up_times),   call_pnl, call_costs, call_dte)
result_puts  = _make_result(len(cross_down_times),  put_pnl,  put_costs,  put_dte)

_print_result(f"CALLS — EMA cross up   (DTE={DTE}  delta={DELTA}  hold={HOLD_DAYS}d)", result_calls)
_print_result(f"PUTS  — EMA cross down (DTE={DTE}  delta={DELTA}  hold={HOLD_DAYS}d)", result_puts)

# ── 7. HTML reports ───────────────────────────────────────────────────────────
print("\n── 5. Writing reports ───────────────────────────────────────────────────")
tag = f"dte{DTE}_d{int(DELTA * 100)}_h{HOLD_DAYS * 24}"
calls_report = REPORTS / f"ema_cross_calls_{tag}.html"
puts_report  = REPORTS / f"ema_cross_puts_{tag}.html"
render_option_result(result_calls, str(calls_report), dte=DTE, delta=DELTA)
render_option_result(result_puts,  str(puts_report),  dte=DTE, delta=DELTA)
print(f"   {calls_report}")
print(f"   {puts_report}")
print("\nDone.")
