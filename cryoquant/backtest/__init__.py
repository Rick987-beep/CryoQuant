"""CryoQuant backtest harness.

Phase 5 deliverables:
    spot_pnl       — vectorised spot simulation
    option_lookup  — Deribit option chain P&L evaluation
    robustness     — deflated Sharpe, bootstrap CI
    reports        — HTML report rendering
    cryobt_bridge  — CryoBacktester Strategy adapter
"""
from cryoquant.backtest.spot_pnl import SpotResult, simulate
from cryoquant.backtest.option_lookup import ExitRule, OptionResult, evaluate
from cryoquant.backtest.robustness import deflated_sharpe, bootstrap_ci
from cryoquant.backtest.reports import render, render_spot_result, render_option_result
from cryoquant.backtest.cryobt_bridge import CryoBTAdapter

__all__ = [
    # spot_pnl
    "simulate",
    "SpotResult",
    # option_lookup
    "evaluate",
    "ExitRule",
    "OptionResult",
    # robustness
    "deflated_sharpe",
    "bootstrap_ci",
    # reports
    "render",
    "render_spot_result",
    "render_option_result",
    # bridge
    "CryoBTAdapter",
]
