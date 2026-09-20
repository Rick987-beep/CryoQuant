"""CryoQuant backtest harness.

Deliverables:
    spot_pnl       — vectorised fixed-hold spot simulation
    replay         — linear weight / touch-fill market replay + BarLog
    option_lookup  — Deribit option chain P&L evaluation
    short_vol      — sell-side option economics
    robustness     — deflated Sharpe, bootstrap CI, trial log
    reports        — HTML report rendering
    bundle         — sweep artifact I/O (RunBundle)
"""
from cryoquant.backtest.account import (
    VXM,
    VX,
    AccountConfig,
    ExecutionModel,
    InstrumentSpec,
    apply_fill_price,
    build_futures_equity,
    futures_pnl_dollars,
)
from cryoquant.backtest.replay import ReplayConfig, ReplayResult, replay_weights, long_touch_fill, short_touch_fill
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
from cryoquant.backtest.short_vol import ShortVolConfig, ShortVolResult, evaluate_short_vol
from cryoquant.backtest.short_vol_metrics import (
    calibration_gap,
    cvar_loss,
    otm_rate_vs_delta,
    trade_sharpe,
)
from cryoquant.backtest.trial_log import append_trial, append_training_session, count_trials, trial_log_path

__all__ = [
    # spot_pnl
    "simulate",
    "SpotResult",
    # replay + account
    "ReplayConfig",
    "ReplayResult",
    "replay_weights",
    "long_touch_fill",
    "short_touch_fill",
    "AccountConfig",
    "ExecutionModel",
    "InstrumentSpec",
    "VXM",
    "VX",
    "apply_fill_price",
    "build_futures_equity",
    "futures_pnl_dollars",
    # option_lookup
    "evaluate",
    "ExitRule",
    "OptionResult",
    # robustness + trial log
    "deflated_sharpe",
    "bootstrap_ci",
    "trial_log_path",
    "count_trials",
    "append_trial",
    "append_training_session",
    # reports
    "render",
    "render_spot_result",
    "render_option_result",
    "render_sweep_leaderboard",
    # bridge
    "CryoBTAdapter",
    # metrics
    "compute_metrics",
    "empty_metrics",
    # trades
    "TRADE_COLUMNS",
    "enrich_trades",
    # scoring
    "ScoringConfig",
    "score_leaderboard",
    # bundle
    "RunBundle",
    "write_bundle",
    "load_bundle",
    # sweep_collector
    "RunRecord",
    "SweepCollection",
    "collect_runs",
    # breakout_sim
    "BreakoutConfig",
    "simulate_breakout",
    # short_vol
    "ShortVolConfig",
    "ShortVolResult",
    "evaluate_short_vol",
    "cvar_loss",
    "trade_sharpe",
    "otm_rate_vs_delta",
    "calibration_gap",
]
