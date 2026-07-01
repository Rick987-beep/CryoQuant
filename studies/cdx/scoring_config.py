"""CDX analysis scoring weights for framework leaderboards."""
from __future__ import annotations

from cryoquant.backtest.scoring import ScoringConfig

# Yield overlay sweeps (Phase 3 yield leg + Y1 benchmark comparison)
CDX_YIELD_SCORING = ScoringConfig(
    weights={
        "carry_funding_ratio": 0.35,
        "nav_end": 0.25,
        "calm_pnl_usd": 0.20,
        "max_drawdown": 0.10,
        "covid_pnl_usd": 0.10,
    },
    higher_is_better=(
        "carry_funding_ratio",
        "nav_end",
        "calm_pnl_usd",
        "covid_pnl_usd",
    ),
    lower_is_better=("max_drawdown",),
    min_trades=1,
    rank_column="composite_score",
    tie_breaker="nav_end",
)

# Tail insurance grid (Phase 3 tail leg)
CDX_TAIL_SCORING = ScoringConfig(
    weights={
        "nav_end": 0.30,
        "covid_pnl_usd": 0.30,
        "calm_pnl_usd": 0.20,
        "max_drawdown": 0.20,
    },
    higher_is_better=("nav_end", "covid_pnl_usd", "calm_pnl_usd"),
    lower_is_better=("max_drawdown",),
    min_trades=1,
    rank_column="composite_score",
    tie_breaker="covid_pnl_usd",
)

# Combined Phase 3 overlay sweep (tail + yield in one bundle)
CDX_OVERLAY_SCORING = ScoringConfig(
    weights={
        "nav_end": 0.30,
        "carry_funding_ratio": 0.25,
        "calm_pnl_usd": 0.20,
        "max_drawdown": 0.15,
        "covid_pnl_usd": 0.10,
    },
    higher_is_better=(
        "nav_end",
        "carry_funding_ratio",
        "calm_pnl_usd",
        "covid_pnl_usd",
    ),
    lower_is_better=("max_drawdown",),
    min_trades=1,
    rank_column="composite_score",
    tie_breaker="nav_end",
)

# Crunch Fund — crisis-first scoring (10× target)
CRUNCH_FUND_SCORING = ScoringConfig(
    weights={
        "distance_to_10x_tier_bc": 0.50,
        "crisis_nav_peak_tier_bc": 0.30,
        "hit_10x_rate_tier_bc": 0.20,
    },
    higher_is_better=("crisis_nav_peak_tier_bc", "hit_10x_rate_tier_bc"),
    lower_is_better=("distance_to_10x_tier_bc",),
    min_trades=0,
    rank_column="composite_score",
    tie_breaker="crisis_nav_peak_tier_bc",
)

# Portfolio variants (Phase 4)
CDX_PORTFOLIO_SCORING = ScoringConfig(
    weights={
        "carry_funding_ratio": 0.30,
        "nav_end": 0.25,
        "calm_pnl_usd": 0.20,
        "pnl_covid": 0.15,
        "max_drawdown": 0.10,
    },
    higher_is_better=(
        "carry_funding_ratio",
        "nav_end",
        "calm_pnl_usd",
        "pnl_covid",
    ),
    lower_is_better=("max_drawdown",),
    min_trades=1,
    rank_column="composite_score",
    tie_breaker="nav_end",
)
