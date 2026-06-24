"""Portfolio-level metrics for CDX.NA.IG multi-overlay backtests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from cryoquant.backtest.metrics import compute_metrics


def calm_mask(spread_bps: pd.Series, threshold: float = 80.0) -> pd.Series:
    return spread_bps < threshold


def stress_mask(spread_bps: pd.Series, threshold: float = 80.0) -> pd.Series:
    return spread_bps >= threshold


def episode_pnl_usd(attribution: pd.DataFrame, start: str, end: str) -> float:
    slc = attribution["total"].loc[start:end]
    return float(slc.sum()) if len(slc) else 0.0


def carry_funding_ratio(
    yield_pnl: pd.Series,
    tail_carry: pd.Series,
    *,
    calm: pd.Series | None = None,
) -> float:
    """Yield total PnL / |tail carry| over calm days."""
    if calm is not None:
        yield_pnl = yield_pnl.loc[calm]
        tail_carry = tail_carry.loc[calm]
    denom = abs(float(tail_carry.sum()))
    if denom == 0:
        return float("nan")
    return float(yield_pnl.sum()) / denom


def leg_correlation(
    tail_pnl: pd.Series,
    yield_pnl: pd.Series,
    *,
    mask: pd.Series | None = None,
) -> float:
    t = tail_pnl
    y = yield_pnl
    if mask is not None:
        t = t.loc[mask]
        y = y.loc[mask]
    if len(t) < 2:
        return float("nan")
    return float(t.corr(y))


def portfolio_metrics(
    equity: pd.Series,
    attribution: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    spread_bps: pd.Series,
    calm_threshold: float = 80.0,
) -> dict:
    """Scalar metrics for combined portfolio."""
    base = compute_metrics(trades, equity) if not trades.empty else compute_metrics(
        pd.DataFrame({"pnl_pct": [0.0]}), equity
    )
    calm = calm_mask(spread_bps, calm_threshold)
    stress = stress_mask(spread_bps, calm_threshold)

    base["nav_end"] = float(equity.iloc[-1]) if len(equity) else 1.0
    if len(equity) > 1 and equity.iloc[-1] > 0:
        base["cagr"] = float(equity.iloc[-1] ** (252 / len(equity)) - 1)
    base["calm_pnl_usd"] = float(attribution.loc[calm, "total"].sum())
    base["stress_pnl_usd"] = float(attribution.loc[stress, "total"].sum())
    base["carry_funding_ratio"] = carry_funding_ratio(
        attribution["pnl_yield"],
        attribution["carry_tail"],
        calm=calm,
    )
    base["tail_yield_corr_stress"] = leg_correlation(
        attribution["pnl_tail"],
        attribution["pnl_yield"],
        mask=stress,
    )
    base["tail_yield_corr_calm"] = leg_correlation(
        attribution["pnl_tail"],
        attribution["pnl_yield"],
        mask=calm,
    )
    for ep_name, (start, end) in EPISODES.items():
        base[f"pnl_{ep_name}"] = episode_pnl_usd(attribution, start, end)
    return base


EPISODES: dict[str, tuple[str, str]] = {
    "covid": ("2020-02-01", "2020-04-30"),
    "2022_rates": ("2022-01-01", "2022-12-31"),
}
