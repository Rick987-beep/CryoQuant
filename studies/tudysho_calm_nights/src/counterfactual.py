"""Counterfactual options grid on morning-quiet days."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from cryoquant import config as cq_config
from cryoquant.backtest.option_lookup import (
    _best_leg,
    _load_chain_df,
    _spot_price_on_date,
    _to_deribit_expiry,
)

from contingency import _apply_min_otm, _min_otm_distance_pct
from extrusion import path_extrusion, slice_bars
from sessions import hold_from_entry_bounds_utc

MIN_TICK_BTC = 0.0001


def _strangle_legs(
    chain: pd.DataFrame,
    entry_day: date,
    *,
    delta: float,
    min_otm_pct: float,
    spot: float,
) -> tuple[pd.Series, pd.Series] | None:
    expiry_day = entry_day + timedelta(days=1)
    call_leg = _best_leg(chain, expiry_day, delta, is_call=True)
    put_leg = _best_leg(chain, expiry_day, delta, is_call=False)
    if call_leg is None or put_leg is None:
        return None
    expiry_label = _to_deribit_expiry(expiry_day)
    call_leg = _apply_min_otm(call_leg, spot, min_otm_pct, True, chain, expiry_label)
    put_leg = _apply_min_otm(put_leg, spot, min_otm_pct, False, chain, expiry_label)
    return call_leg, put_leg


def _premium_usd_per_contract(
    call_leg: pd.Series, put_leg: pd.Series, spot: float
) -> tuple[float, float, float]:
    """Short strangle premium from bid prices (BTC fraction → USD)."""
    bid_call = float(call_leg.get("bid_price", 0) or 0)
    bid_put = float(put_leg.get("bid_price", 0) or 0)
    premium_btc = bid_call + bid_put
    premium_usd = premium_btc * spot
    return premium_usd, bid_call, bid_put


def _contracts_qty(
    premium_usd: float,
    nav_usd: float,
    nav_premium_pct: float,
    max_qty_per_1btc_equity: float = 12.0,
    equity_btc: float | None = None,
) -> float:
    if premium_usd <= 0:
        return 0.0
    target = nav_usd * (nav_premium_pct / 100.0)
    qty = target / premium_usd
    if equity_btc is not None and max_qty_per_1btc_equity > 0:
        qty = min(qty, equity_btc * max_qty_per_1btc_equity)
    return max(round(qty, 1), 0.1) if qty >= 0.1 else 0.0


def evaluate_cell(
    entry_day: date,
    bars: pd.DataFrame,
    *,
    entry_time_nyc: str,
    delta: float,
    min_otm_pct: float,
    nav_usd: float,
    nav_premium_pct: float,
    chains_dir: Any | None = None,
) -> dict[str, Any]:
    """Single counterfactual grid cell."""
    chains_dir = chains_dir or cq_config.CRYOBACKTESTER_DATA_DIR
    chain = _load_chain_df(chains_dir, entry_day)
    if chain is None:
        return {"status": "no_chain"}

    spot = _spot_price_on_date(chains_dir, entry_day)
    if spot is None:
        return {"status": "no_spot"}

    legs = _strangle_legs(
        chain, entry_day, delta=delta, min_otm_pct=min_otm_pct, spot=spot
    )
    if legs is None:
        return {"status": "no_legs"}

    call_leg, put_leg = legs
    premium_usd, bid_call, bid_put = _premium_usd_per_contract(call_leg, put_leg, spot)
    equity_btc = nav_usd / spot
    qty = _contracts_qty(
        premium_usd, nav_usd, nav_premium_pct, equity_btc=equity_btc
    )

    h0, h1 = hold_from_entry_bounds_utc(entry_day, entry_time_nyc)
    hold_bars = slice_bars(bars, pd.Timestamp(h0), pd.Timestamp(h1))
    hold_path = path_extrusion(hold_bars)
    min_dist = _min_otm_distance_pct(call_leg, put_leg, spot)
    extrusion_ratio = hold_path / min_dist if min_dist > 0 else float("inf")

    return {
        "status": "ok",
        "entry_date": entry_day.isoformat(),
        "entry_time_nyc": entry_time_nyc,
        "delta": delta,
        "min_otm_pct": min_otm_pct,
        "spot": spot,
        "premium_usd_per_contract": premium_usd,
        "contracts_per_leg": qty,
        "bid_call_btc": bid_call,
        "bid_put_btc": bid_put,
        "bid_at_min_tick": bid_call <= MIN_TICK_BTC + 1e-9 or bid_put <= MIN_TICK_BTC + 1e-9,
        "hold_path": hold_path,
        "min_otm_distance_pct": min_dist,
        "extrusion_ratio": extrusion_ratio,
        "extrusion_safe": extrusion_ratio < 1.0,
    }


def run_counterfactual_grid(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    cfg: dict,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Evaluate full grid on morning-quiet days."""
    cf = cfg["counterfactual"]
    obj = cfg["objective"]
    quiet = daily[daily["predictor_quiet"].fillna(False)]

    rows: list[dict] = []
    for _, day_row in quiet.iterrows():
        entry_day = date.fromisoformat(day_row["entry_date"])
        for et in cf["entry_times_nyc"]:
            for delta in cf["deltas"]:
                for motm in cf["min_otm_pct"]:
                    cell = evaluate_cell(
                        entry_day,
                        bars,
                        entry_time_nyc=et,
                        delta=delta,
                        min_otm_pct=motm,
                        nav_usd=cf["account_nav_usd"],
                        nav_premium_pct=obj["nav_premium_pct"],
                    )
                    if cell.get("status") == "ok":
                        rows.append(cell)

    grid = pd.DataFrame(rows)

    summary = _grid_summary(grid, cfg)
    return grid, summary


def _grid_summary(grid: pd.DataFrame, cfg: dict) -> dict[str, Any]:
    """Summarize counterfactual pass criteria."""
    if grid.empty:
        return {
            "n_cells": 0,
            "passed": False,
            "note": "No counterfactual cells resolved (missing option chains?)",
        }

    profiles = cfg["profiles"]
    agg = profiles["aggressive"]
    base = profiles["base"]

    def _median_contracts(et: str, delta: float, motm: float) -> float:
        sub = grid[
            (grid["entry_time_nyc"] == et)
            & (grid["delta"] == delta)
            & (grid["min_otm_pct"] == motm)
        ]
        if sub.empty:
            return float("nan")
        return float(sub["contracts_per_leg"].median())

    med_agg = _median_contracts(
        agg["entry_time"], agg["delta"], agg["min_otm_pct"]
    )
    med_base = _median_contracts(
        base["entry_time"], base["delta"], base["min_otm_pct"]
    )
    reduction_pct = (
        (med_base - med_agg) / med_base * 100.0
        if med_base and med_base > 0 and not np.isnan(med_base)
        else float("nan")
    )

    agg_cells = grid[
        (grid["entry_time_nyc"] == agg["entry_time"])
        & (grid["delta"] == agg["delta"])
        & (grid["min_otm_pct"] == agg["min_otm_pct"])
    ]
    safe_pct = (
        float(agg_cells["extrusion_safe"].mean() * 100.0)
        if not agg_cells.empty
        else float("nan")
    )

    return {
        "n_cells": len(grid),
        "n_quiet_days": int(grid["entry_date"].nunique()),
        "median_contracts_aggressive": med_agg,
        "median_contracts_base": med_base,
        "contract_reduction_pct": reduction_pct,
        "contract_reduction_passed": reduction_pct >= 40.0 if not np.isnan(reduction_pct) else False,
        "extrusion_safe_pct_aggressive": safe_pct,
        "extrusion_safe_passed": safe_pct >= 97.0 if not np.isnan(safe_pct) else False,
        "chain_snapshot_note": (
            "Daily Deribit parquets used; 12:00 vs 16:00 entry bids are approximate."
        ),
    }
