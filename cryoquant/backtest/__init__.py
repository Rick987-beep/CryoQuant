"""CryoQuant backtest harness.

Phase 5 deliverables (v1.0):
    spot_pnl       — vectorised fixed-hold spot simulation
    option_lookup  — Deribit option chain P&L evaluation
    robustness     — deflated Sharpe, bootstrap CI
    reports        — HTML report rendering
    cryobt_bridge  — CryoBacktester Strategy adapter

June 2026 additions:
    metrics        — shared performance metrics (CAGR, Sortino, Calmar, …)
    trades         — canonical TradeLog schema and enrich_trades
    scoring        — percentile-composite leaderboard scoring
    bundle         — sweep artifact I/O (RunBundle)
    sweep_collector — generic multi-run aggregator
    breakout_sim   — channel-breakout simulator with dynamic trailing exits
"""
from cryoquant.backtest.spot_pnl import SpotResult, simulate
from cryoquant.backtest.option_lookup import ExitRule, OptionResult, evaluate
from cryoquant.backtest.robustness import deflated_sharpe, bootstrap_ci
from cryoquant.backtest.reports import (
    render,
    render_spot_result,
    render_option_result,
    render_sweep_leaderboard,
)
from cryoquant.backtest.cryobt_bridge import CryoBTAdapter
from cryoquant.backtest.metrics import compute_metrics, empty_metrics
from cryoquant.backtest.trades import TRADE_COLUMNS, enrich_trades
from cryoquant.backtest.scoring import ScoringConfig, score_leaderboard
from cryoquant.backtest.bundle import RunBundle, write_bundle, load_bundle
from cryoquant.backtest.sweep_collector import RunRecord, SweepCollection, collect_runs
from cryoquant.backtest.breakout_sim import BreakoutConfig, simulate_breakout

__all__ = [
    # spot_pnl (v1.0)
    "simulate",
    "SpotResult",
    # option_lookup (v1.0)
    "evaluate",
    "ExitRule",
    "OptionResult",
    # robustness (v1.0)
    "deflated_sharpe",
    "bootstrap_ci",
    # reports (v1.0 + sweep_leaderboard added June 2026)
    "render",
    "render_spot_result",
    "render_option_result",
    "render_sweep_leaderboard",
    # bridge (v1.0)
    "CryoBTAdapter",
    # metrics (June 2026)
    "compute_metrics",
    "empty_metrics",
    # trades (June 2026)
    "TRADE_COLUMNS",
    "enrich_trades",
    # scoring (June 2026)
    "ScoringConfig",
    "score_leaderboard",
    # bundle (June 2026)
    "RunBundle",
    "write_bundle",
    "load_bundle",
    # sweep_collector (June 2026)
    "RunRecord",
    "SweepCollection",
    "collect_runs",
    # breakout_sim (June 2026)
    "BreakoutConfig",
    "simulate_breakout",
]
