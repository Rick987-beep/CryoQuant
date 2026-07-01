"""CDX.NA.IG overlay backtester with CDS economics."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from cryoquant.backtest.metrics import compute_metrics

from .cds_cost_model import CdsEconomicsConfig, daily_cds_pnl, nav_from_pnl


@dataclass
class CdsOverlayResult:
    name: str
    equity: pd.Series
    trades: pd.DataFrame
    daily_attribution: pd.DataFrame
    positions: pd.Series
    metrics: dict
    collateral_usd: float
    notional_usd: float


def _segments(position: pd.Series) -> list[tuple[int, int, float]]:
    arr = position.fillna(0.0).values
    out: list[tuple[int, int, float]] = []
    i = 0
    while i < len(arr):
        if arr[i] != 0:
            j = i + 1
            while j < len(arr) and arr[j] == arr[i]:
                j += 1
            out.append((i, j - 1, float(arr[i])))
            i = j
        else:
            i += 1
    return out


def _trades_from_pnl(
    pnl_df: pd.DataFrame,
    position: pd.Series,
    collateral_usd: float,
) -> pd.DataFrame:
    idx = position.index
    rows = []
    for start, end, side in _segments(position):
        if start + 1 > end:
            continue
        slc = pnl_df["total"].iloc[start + 1 : end + 1]
        pnl_usd = float(slc.sum())
        rows.append({
            "entry_ts": idx[start],
            "exit_ts": idx[end],
            "side": "long_protection" if side > 0 else "short_protection",
            "pnl_pct": pnl_usd / collateral_usd,
            "pnl_usd": pnl_usd,
            "duration_days": (idx[end] - idx[start]).days,
            "carry_usd": float(pnl_df["carry"].iloc[start + 1 : end + 1].sum()),
            "mtm_usd": float(pnl_df["mtm"].iloc[start + 1 : end + 1].sum()),
        })
    return pd.DataFrame(rows)


def run_overlay(
    spread_bps: pd.Series,
    position: pd.Series,
    *,
    name: str = "overlay",
    notional_usd: float,
    config: CdsEconomicsConfig | None = None,
    is_roll_day: pd.Series | None = None,
    collateral_usd: float | None = None,
) -> CdsOverlayResult:
    config = config or CdsEconomicsConfig.from_yaml()
    collateral = collateral_usd if collateral_usd is not None else config.collateral_usd

    pos = position.reindex(spread_bps.index).fillna(0.0)
    pnl_df = daily_cds_pnl(
        spread_bps, pos, notional_usd,
        config=config,
        is_roll_day=is_roll_day,
        collateral_usd=collateral,
    )
    nav = nav_from_pnl(pnl_df["total"], collateral)
    trades = _trades_from_pnl(pnl_df, pos, collateral)
    metrics = compute_metrics(trades, nav) if not trades.empty else compute_metrics(
        pd.DataFrame({"pnl_pct": [0.0]}), nav
    )
    metrics["carry_usd"] = float(pnl_df["carry"].sum())
    metrics["mtm_usd"] = float(pnl_df["mtm"].sum())
    metrics["pct_in_market"] = float((pos != 0).mean() * 100)
    metrics["nav_end"] = float(nav.iloc[-1])
    metrics["cagr"] = float(nav.iloc[-1] ** (252 / max(len(nav), 1)) - 1) if len(nav) > 1 else 0.0

    return CdsOverlayResult(
        name=name,
        equity=nav,
        trades=trades,
        daily_attribution=pnl_df,
        positions=pos,
        metrics=metrics,
        collateral_usd=collateral,
        notional_usd=notional_usd,
    )
