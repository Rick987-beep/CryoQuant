"""Export CDX sweep results to framework RunBundle artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from cryoquant.backtest.bundle import RunBundle, write_bundle
from cryoquant.backtest.reports import render_sweep_leaderboard
from cryoquant.backtest.scoring import ScoringConfig, score_leaderboard
from cryoquant.backtest.sweep_collector import RunRecord, SweepCollection

from .cds_to_spot import overlay_to_spot, portfolio_to_spot
from .backtest_cds import CdsOverlayResult
from .portfolio_backtest import PortfolioResult

CDX_DISPLAY_COLUMNS = [
    "run_id",
    "overlay",
    "name",
    "composite_score",
    "nav_end",
    "cagr",
    "max_drawdown",
    "carry_funding_ratio",
    "calm_pnl_usd",
    "covid_pnl_usd",
    "pnl_covid",
    "n_trades",
    "pct_in_market",
    "vs_y1_nav",
]

CDX_PORTFOLIO_DISPLAY_COLUMNS = [
    "run_id",
    "name",
    "yield_strategy",
    "apply_mutex",
    "composite_score",
    "nav_end",
    "cagr",
    "max_drawdown",
    "carry_funding_ratio",
    "calm_pnl_usd",
    "pnl_covid",
    "mutex_overlap_days",
    "pct_tail_in_market",
    "pct_yield_in_market",
]


def collection_from_records(records: list[RunRecord]) -> SweepCollection:
    """Build a SweepCollection from explicit RunRecord list."""
    return SweepCollection(records=list(records))


def overlay_record(
    run_id: str,
    params: dict[str, Any],
    result: CdsOverlayResult,
    spread_bps: pd.Series,
    *,
    extra_metrics: dict[str, Any] | None = None,
) -> RunRecord:
    """Build a RunRecord from a CDS overlay result."""
    spot = overlay_to_spot(
        result, spread_bps, run_id=run_id, extra_metrics=extra_metrics,
    )
    return RunRecord(run_id=run_id, params=params, result=spot)


def portfolio_record(
    run_id: str,
    params: dict[str, Any],
    result: PortfolioResult,
    spread_bps: pd.Series,
) -> RunRecord:
    """Build a RunRecord from a portfolio result."""
    spot = portfolio_to_spot(result, spread_bps, run_id=run_id)
    return RunRecord(run_id=run_id, params=params, result=spot)


def export_sweep_bundle(
    bundle_dir: Path | str,
    collection: SweepCollection,
    *,
    meta: dict[str, Any],
    scoring: ScoringConfig,
    breakdown_cols: tuple[str, ...] = ("overlay",),
    display_columns: list[str] | None = None,
    top_n: int = 30,
) -> Path:
    """Score leaderboard, write RunBundle, and render HTML report."""
    leaderboard = pd.DataFrame(collection.leaderboard_rows())
    if not leaderboard.empty:
        leaderboard = score_leaderboard(leaderboard, scoring)

    bundle = RunBundle(
        meta={
            **meta,
            "n_runs": len(collection.records),
            "n_skipped": collection.n_skipped,
            "scoring": {
                "weights": dict(scoring.weights),
                "min_trades": scoring.min_trades,
                "rank_column": scoring.rank_column,
            },
        },
        leaderboard=leaderboard,
        trades=collection.trades_df(),
        equity_daily=collection.equity_daily_df(),
    )

    out_dir = write_bundle(bundle_dir, bundle)
    cols = display_columns or _pick_display_columns(leaderboard, bundle.meta.get("study", ""))
    render_sweep_leaderboard(
        bundle,
        out_dir / "report.html",
        top_n=top_n,
        breakdown_cols=breakdown_cols,
        display_columns=cols,
    )
    return out_dir


def export_leaderboard_bundle(
    bundle_dir: Path | str,
    leaderboard: pd.DataFrame,
    collection: SweepCollection,
    *,
    meta: dict[str, Any],
    scoring: ScoringConfig,
    breakdown_cols: tuple[str, ...] = ("overlay",),
    display_columns: list[str] | None = None,
    top_n: int = 30,
) -> Path:
    """Write bundle using a pre-built leaderboard (e.g. crunch fund aggregates)."""
    lb = leaderboard.copy()
    if not lb.empty:
        if "run_id" not in lb.columns and "run_id" in lb.columns:
            pass
        if "n_trades" not in lb.columns:
            lb["n_trades"] = 1
        lb = score_leaderboard(lb, scoring)

    bundle = RunBundle(
        meta={
            **meta,
            "n_runs": len(lb),
            "n_skipped": 0,
            "scoring": {
                "weights": dict(scoring.weights),
                "min_trades": scoring.min_trades,
                "rank_column": scoring.rank_column,
            },
        },
        leaderboard=lb,
        trades=collection.trades_df(),
        equity_daily=collection.equity_daily_df(),
    )
    out_dir = write_bundle(bundle_dir, bundle)
    cols = display_columns or _pick_display_columns(lb, bundle.meta.get("study", ""))
    render_sweep_leaderboard(
        bundle, out_dir / "report.html",
        top_n=top_n, breakdown_cols=breakdown_cols, display_columns=cols,
    )
    return out_dir


def _pick_display_columns(leaderboard: pd.DataFrame, study: str) -> list[str]:
    if "portfolio" in study:
        template = CDX_PORTFOLIO_DISPLAY_COLUMNS
    elif "crunch" in study:
        template = [
            "run_id", "strategy", "notional_usd", "entry_max_bps", "exit_bps",
            "composite_score", "crisis_nav_peak_tier_bc", "distance_to_10x_tier_bc",
            "hit_10x_rate_tier_bc", "median_covid_peak", "notional_for_10x",
            "median_terminal_nav",
        ]
    else:
        template = CDX_DISPLAY_COLUMNS
    if leaderboard.empty:
        return template
    return [c for c in template if c in leaderboard.columns] or list(leaderboard.columns)
