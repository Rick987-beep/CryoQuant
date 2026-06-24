"""CDS economics for CDX.NA.IG index protection positions."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .paths import load_config


@dataclass(frozen=True)
class CdsEconomicsConfig:
    duration: float = 5.0
    day_count: int = 360
    bid_ask_bps: float = 0.5
    roll_cost_bps: float = 1.0
    financing_rate: float = 0.05
    collateral_usd: float = 5_000_000

    @classmethod
    def from_yaml(cls) -> CdsEconomicsConfig:
        cfg = load_config()
        econ = cfg["cds_economics"]
        costs = cfg["costs"]
        return cls(
            duration=float(econ["duration"]),
            day_count=int(econ["day_count"]),
            bid_ask_bps=float(costs["bid_ask_bps"]),
            roll_cost_bps=float(costs["roll_cost_bps"]),
            financing_rate=float(costs["financing_rate"]),
            collateral_usd=float(econ["collateral_usd"]),
        )


def daily_cds_pnl(
    spread_bps: pd.Series,
    position: pd.Series,
    notional_usd: float,
    *,
    config: CdsEconomicsConfig | None = None,
    is_roll_day: pd.Series | None = None,
    collateral_usd: float | None = None,
) -> pd.DataFrame:
    """
    Daily PnL components for CDX.NA.IG protection book.

    position: +1 long protection, -1 short protection, 0 flat
    """
    config = config or CdsEconomicsConfig.from_yaml()
    collateral = collateral_usd if collateral_usd is not None else config.collateral_usd

    pos = position.reindex(spread_bps.index).fillna(0.0)
    spread = spread_bps.reindex(spread_bps.index)
    d_spread = spread.diff().fillna(0.0)

    exposure = pos * notional_usd
    prev_exposure = exposure.shift(1).fillna(0.0)

    carry = -pos * notional_usd * (spread / 10_000) / config.day_count
    mtm = pos * notional_usd * config.duration * (d_spread / 10_000)

    delta_exposure = (exposure - prev_exposure).abs()
    trade_cost = -delta_exposure * (config.bid_ask_bps / 10_000)

    roll_cost = pd.Series(0.0, index=spread.index)
    if is_roll_day is not None:
        held = (pos != 0) & (pos.shift(1).fillna(0) != 0)
        roll_cost = -held.astype(float) * is_roll_day.astype(float) * notional_usd * (config.roll_cost_bps / 10_000)

    financing = -pd.Series(collateral, index=spread.index) * (config.financing_rate / config.day_count)

    total = carry + mtm + trade_cost + roll_cost + financing
    return pd.DataFrame(
        {
            "carry": carry,
            "mtm": mtm,
            "trade_cost": trade_cost,
            "roll_cost": roll_cost,
            "financing": financing,
            "total": total,
        },
        index=spread.index,
    )


def nav_from_pnl(pnl: pd.Series, collateral_usd: float) -> pd.Series:
    """Cumulative NAV on collateral base (starts at 1.0)."""
    equity = collateral_usd + pnl.cumsum()
    return equity / collateral_usd


def replay_constant_position(
    spread_bps: pd.Series,
    *,
    entry_date: str,
    exit_date: str | None = None,
    notional_usd: float = 100_000_000,
    config: CdsEconomicsConfig | None = None,
) -> dict:
    """Hold long protection from entry_date through exit_date (inclusive)."""
    config = config or CdsEconomicsConfig.from_yaml()
    idx = spread_bps.index
    entry_ts = pd.Timestamp(entry_date, tz=idx.tz)
    exit_ts = pd.Timestamp(exit_date, tz=idx.tz) if exit_date else idx[-1]

    position = pd.Series(0.0, index=idx)
    mask = (idx >= entry_ts) & (idx <= exit_ts)
    position.loc[mask] = 1.0

    window_spread = spread_bps.loc[mask]
    window_pos = position.loc[mask]
    pnl_df = daily_cds_pnl(window_spread, window_pos, notional_usd, config=config)
    nav = nav_from_pnl(pnl_df["total"], config.collateral_usd)

    entry_spread = float(spread_bps.loc[entry_ts])
    exit_spread = float(spread_bps.loc[exit_ts])
    ds = (exit_spread - entry_spread) / 10_000
    theoretical = ds * config.duration * notional_usd

    return {
        "entry_date": str(entry_ts.date()),
        "exit_date": str(exit_ts.date()),
        "entry_spread_bps": entry_spread,
        "exit_spread_bps": exit_spread,
        "notional_usd": notional_usd,
        "carry_usd": float(pnl_df["carry"].sum()),
        "mtm_usd": float(pnl_df["mtm"].sum()),
        "costs_usd": float(pnl_df[["trade_cost", "roll_cost", "financing"]].sum().sum()),
        "total_pnl_usd": float(pnl_df["total"].sum()),
        "theoretical_pnl_usd": theoretical,
        "nav_end": float(nav.iloc[-1]),
        "nav_multiple": float(nav.iloc[-1]),
        "pnl_daily": pnl_df,
        "nav": nav,
    }
