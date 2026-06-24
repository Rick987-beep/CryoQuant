"""Multi-overlay CDX.NA.IG portfolio backtester."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .backtest_cds import CdsOverlayResult, run_overlay
from .cds_cost_model import CdsEconomicsConfig, nav_from_pnl
from .metrics_portfolio import portfolio_metrics
from .paths import load_config
from .signals_tail import standing_tail_insurance
from .signals_yield import run_yield_strategy
from .yield_gates import apply_tail_mutex


@dataclass(frozen=True)
class PortfolioSpec:
    name: str
    tail_entry_max_bps: float = 60.0
    tail_exit_bps: float = 100.0
    yield_strategy: str = "Y8_velocity_filter"
    apply_mutex: bool = True
    yield_scale: float = 1.0


@dataclass
class PortfolioResult:
    name: str
    equity: pd.Series
    attribution: pd.DataFrame
    tail: CdsOverlayResult
    yield_: CdsOverlayResult
    positions: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict
    collateral_usd: float


def _validate_index(spread: pd.Series, features: pd.DataFrame | None) -> None:
    if spread.empty:
        raise ValueError("spread_bps is empty")
    if spread.index.has_duplicates:
        raise ValueError("spread_bps index has duplicate timestamps")
    if features is not None and not features.index.equals(spread.index):
        features = features.reindex(spread.index)
    if spread.isna().all():
        raise ValueError("spread_bps is all NaN")


def build_positions(
    spread_bps: pd.Series,
    features: pd.DataFrame,
    panel: pd.DataFrame | None,
    spec: PortfolioSpec,
) -> tuple[pd.Series, pd.Series]:
    """Build tail and yield position series (causal at each bar)."""
    roll = features["is_roll_window"] if "is_roll_window" in features.columns else None
    tail_pos = standing_tail_insurance(
        spread_bps,
        entry_max_bps=spec.tail_entry_max_bps,
        exit_bps=spec.tail_exit_bps,
        skip_roll=roll,
    )
    # Raw yield signal — mutex applied at portfolio layer unless strategy needs tail (Y14)
    tail_for_yield = tail_pos if spec.yield_strategy == "Y14_handoff" else None
    yield_pos = run_yield_strategy(
        spec.yield_strategy,
        spread_bps,
        features=features,
        panel=panel,
        tail_position=tail_for_yield,
    )
    if spec.apply_mutex and spec.yield_strategy != "Y14_handoff":
        yield_pos = apply_tail_mutex(yield_pos, tail_pos)
    if spec.yield_scale != 1.0:
        yield_pos = yield_pos * spec.yield_scale
    return tail_pos, yield_pos.fillna(0.0)


def run_portfolio(
    spread_bps: pd.Series,
    features: pd.DataFrame,
    *,
    spec: PortfolioSpec,
    panel: pd.DataFrame | None = None,
    config: CdsEconomicsConfig | None = None,
) -> PortfolioResult:
    """
    Run tail + yield overlays on shared calendar; sum USD PnL on total collateral.

    Each leg uses its collateral slice for leg-level financing; portfolio NAV
    is computed on full cds_economics.collateral_usd.
    """
    _validate_index(spread_bps, features)
    cfg = load_config()
    config = config or CdsEconomicsConfig.from_yaml()
    overlay_cfg = cfg["overlays"]

    tail_notional = float(overlay_cfg["tail"]["notional_usd"])
    yield_notional = float(overlay_cfg["yield"]["notional_usd"])
    tail_collateral = config.collateral_usd * float(overlay_cfg["tail"]["collateral_slice_pct"])
    yield_collateral = config.collateral_usd * float(overlay_cfg["yield"]["collateral_slice_pct"])
    total_collateral = config.collateral_usd

    roll = features["is_roll_window"] if "is_roll_window" in features.columns else None
    tail_pos, yield_pos = build_positions(spread_bps, features, panel, spec)

    tail_result = run_overlay(
        spread_bps, tail_pos, name=f"{spec.name}_tail",
        notional_usd=tail_notional, config=config,
        is_roll_day=roll, collateral_usd=tail_collateral,
    )
    yield_result = run_overlay(
        spread_bps, yield_pos, name=f"{spec.name}_yield",
        notional_usd=yield_notional, config=config,
        is_roll_day=roll, collateral_usd=yield_collateral,
    )

    attribution = pd.DataFrame(index=spread_bps.index)
    for col, leg in [
        ("pnl_tail", tail_result.daily_attribution["total"]),
        ("pnl_yield", yield_result.daily_attribution["total"]),
        ("carry_tail", tail_result.daily_attribution["carry"]),
        ("carry_yield", yield_result.daily_attribution["carry"]),
        ("mtm_tail", tail_result.daily_attribution["mtm"]),
        ("mtm_yield", yield_result.daily_attribution["mtm"]),
    ]:
        attribution[col] = leg
    attribution["costs_tail"] = tail_result.daily_attribution[
        ["trade_cost", "roll_cost", "financing"]
    ].sum(axis=1)
    attribution["costs_yield"] = yield_result.daily_attribution[
        ["trade_cost", "roll_cost", "financing"]
    ].sum(axis=1)
    attribution["total"] = attribution["pnl_tail"] + attribution["pnl_yield"]
    attribution["costs_total"] = attribution["costs_tail"] + attribution["costs_yield"]

    equity = nav_from_pnl(attribution["total"], total_collateral)

    positions = pd.DataFrame({
        "tail": tail_result.positions,
        "yield": yield_result.positions,
    })
    # Combined trade log for portfolio-level metrics
    tail_trades = tail_result.trades.copy()
    if not tail_trades.empty:
        tail_trades["overlay"] = "tail"
    yield_trades = yield_result.trades.copy()
    if not yield_trades.empty:
        yield_trades["overlay"] = "yield"
    trades = pd.concat([tail_trades, yield_trades], ignore_index=True)
    if not trades.empty:
        trades["pnl_pct"] = trades["pnl_usd"] / total_collateral

    calm_threshold = float(cfg.get("yield_strategies", {}).get("stress_bps", 80))
    metrics = portfolio_metrics(
        equity, attribution, trades,
        spread_bps=spread_bps,
        calm_threshold=calm_threshold,
    )
    metrics["apply_mutex"] = spec.apply_mutex
    metrics["yield_strategy"] = spec.yield_strategy
    metrics["pct_tail_in_market"] = tail_result.metrics["pct_in_market"]
    metrics["pct_yield_in_market"] = yield_result.metrics["pct_in_market"]
    metrics["mutex_overlap_days"] = int(
        ((positions["tail"] != 0) & (positions["yield"] != 0)).sum()
    )

    return PortfolioResult(
        name=spec.name,
        equity=equity,
        attribution=attribution,
        tail=tail_result,
        yield_=yield_result,
        positions=positions,
        trades=trades,
        metrics=metrics,
        collateral_usd=total_collateral,
    )


def walk_forward_blocks(
    index: pd.DatetimeIndex,
    *,
    train_years: int = 8,
    test_years: int = 3,
) -> list[dict]:
    """
    Expanding-origin walk-forward: first test window starts after train_years.

    Strategy params are fixed; train window only sets when OOS evaluation begins.
    """
    if len(index) == 0:
        return []
    blocks: list[dict] = []
    origin = index[0]
    k = 0
    while True:
        train_end = origin + pd.DateOffset(years=train_years + k * test_years)
        test_end = origin + pd.DateOffset(years=train_years + (k + 1) * test_years)
        if train_end >= index[-1]:
            break
        test_mask = (index > train_end) & (index <= test_end)
        if not test_mask.any():
            break
        train_mask = index <= train_end
        blocks.append({
            "block_id": k,
            "train_end": train_end,
            "test_start": index[test_mask][0],
            "test_end": index[test_mask][-1],
            "train_mask": train_mask,
            "test_mask": test_mask,
        })
        k += 1
        if test_end >= index[-1]:
            break
    return blocks


def run_walk_forward_oos(
    spread_bps: pd.Series,
    features: pd.DataFrame,
    *,
    spec: PortfolioSpec,
    panel: pd.DataFrame | None = None,
    train_years: int = 8,
    test_years: int = 3,
    config: CdsEconomicsConfig | None = None,
) -> dict:
    """
    Run fixed-strategy portfolio on each OOS test window; stitch test PnL.

    No parameter fitting on train — train window exists only to enforce
    minimum history before first OOS block.
    """
    blocks = walk_forward_blocks(
        spread_bps.index, train_years=train_years, test_years=test_years,
    )
    if not blocks:
        return {"blocks": [], "oos_equity": pd.Series(dtype=float), "metrics": {}}

    oos_pnl_parts: list[pd.Series] = []
    block_results: list[dict] = []

    for block in blocks:
        test_idx = spread_bps.index[block["test_mask"]]
        slc_spread = spread_bps.loc[test_idx]
        slc_feat = features.loc[test_idx]
        slc_panel = panel.loc[test_idx] if panel is not None else None
        result = run_portfolio(
            slc_spread, slc_feat, spec=spec, panel=slc_panel, config=config,
        )
        oos_pnl_parts.append(result.attribution["total"])
        block_results.append({
            "block_id": block["block_id"],
            "test_start": str(block["test_start"].date()),
            "test_end": str(block["test_end"].date()),
            "nav_end": result.metrics["nav_end"],
            "calm_pnl_usd": result.metrics["calm_pnl_usd"],
            "carry_funding_ratio": result.metrics["carry_funding_ratio"],
            "max_drawdown": result.metrics["max_drawdown"],
        })

    oos_pnl = pd.concat(oos_pnl_parts)
    config = config or CdsEconomicsConfig.from_yaml()
    oos_equity = nav_from_pnl(oos_pnl, config.collateral_usd)

    oos_metrics = {
        "nav_end": float(oos_equity.iloc[-1]) if len(oos_equity) else 1.0,
        "n_blocks": len(blocks),
        "block_results": block_results,
    }
    if len(oos_equity) > 1 and oos_equity.iloc[-1] > 0:
        oos_metrics["cagr"] = float(oos_equity.iloc[-1] ** (252 / len(oos_equity)) - 1)

    return {
        "blocks": block_results,
        "oos_pnl": oos_pnl,
        "oos_equity": oos_equity,
        "metrics": oos_metrics,
    }
