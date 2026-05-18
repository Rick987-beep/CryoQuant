"""Pydantic schemas for agent-runnable artifacts.

Five contracts power the loop:

    RunSpec        \u2014 fully reproducible inputs to one candidate run.
    RunResult      \u2014 outputs of one run (metrics + complexity + paths).
    IdeaSpec       \u2014 a proposed candidate (agent- or human-authored).
    Comparison     \u2014 a ranked bake-off output.
    FeedSpec       \u2014 a non-OHLCV feed adapter's metadata (Phase 5+).
    FeedSnapshot   \u2014 a cached feed parquet's sidecar (Phase 5+).

All five JSON-serialize via `model_dump_json()` and round-trip via
`Model.model_validate_json(text)`. Run IDs are content-addressable:
same RunSpec ⇒ same id ⇒ idempotent re-runs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "2"  # bumped when RunResult gains episode_stats


# ---------------------------------------------------------------------------
# RunSpec
# ---------------------------------------------------------------------------

class RunSpec(BaseModel):
    """Inputs to a single candidate run. Hashed to produce the run id."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    candidate: str                       # e.g. "A_v2"
    symbol: str = "BTCUSDT"
    tf: str = "1h"
    start: str | None = None             # ISO date, inclusive; None = full history
    end: str | None = None               # ISO date, inclusive; None = full history
    params: dict[str, Any] = Field(default_factory=dict)
    feeds: list[str] = Field(default_factory=list)   # non-OHLCV feed names to attach
    hold_bars: int | None = None         # when set: use flip-only fixed-hold burst eval
    code_git_ref: str | None = None      # set by agent_api at run-time

    @field_validator("params")
    @classmethod
    def _params_are_jsonable(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Strict guard: params must be plain JSON-types so spec.json is
        # both human-readable and reproducible without surprise coercions.
        try:
            json.dumps(v, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"params not JSON-serializable: {exc}") from exc
        return v

    def fingerprint(self) -> str:
        """Stable 8-hex content hash over the spec (excluding code_git_ref).

        hold_bars=None is stripped from the payload so that adding this field
        does not invalidate pre-existing standard-eval cache entries.
        """
        payload = self.model_dump(exclude={"code_git_ref", "schema_version"})
        if payload.get("hold_bars") is None:
            payload.pop("hold_bars", None)
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:8]

    def run_id(self) -> str:
        span = "all"
        if self.start or self.end:
            span = f"{self.start or 'min'}_{self.end or 'max'}"
        return f"{self.symbol}_{self.tf}_{self.candidate}_{self.fingerprint()}_{span}"


# ---------------------------------------------------------------------------
# RunResult \u2014 metrics + complexity + paths
# ---------------------------------------------------------------------------

class StateBlock(BaseModel):
    """Per-state metrics for a single run."""
    model_config = ConfigDict(extra="forbid")

    state: int                           # -1 / 0 / +1
    n_bars: int
    share: float
    hit_rate_h1: float | None
    hit_rate_h4: float | None
    hit_rate_h24: float | None
    mean_fwd_ret_h24: float | None
    median_fwd_ret_h24: float | None
    mfe_atr: float | None
    mae_atr: float | None
    avg_dwell: float
    n_visits: int


class StrategyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sharpe: float | None
    cagr: float | None
    max_drawdown: float | None
    win_rate: float | None
    n_trades: int


class EpisodeStats(BaseModel):
    """Episode-level directional edge metrics."""
    model_config = ConfigDict(extra="forbid")

    n_ep: int
    win_rate: float | None
    payoff_ratio: float | None           # mean_win / mean_abs_loss
    expectancy: float | None             # p * mean_win - (1-p) * mean_abs_loss
    edge_tstat: float | None             # one-sample t on episode returns (H0: mean=0)
    sig: bool                            # True if t > 1.645 and n_ep >= 34


class RegimeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regime: int                          # -1 / 0 / +1 (bear/range/bull)
    n_bars: int
    sharpe: float | None
    cagr: float | None
    max_drawdown: float | None


class FlipStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flip_up: int
    flip_down: int
    flip_to_flat: int
    flips_per_day: float


class Complexity(BaseModel):
    """Inputs to the simplicity-tiebreaker. Phase 4 fills minimally."""
    model_config = ConfigDict(extra="forbid")

    n_primitives: int = 0
    n_feeds: int = 0
    n_params: int = 0


class Headline(BaseModel):
    """Ranking-ready scalars surfaced for quick agent decisions."""
    model_config = ConfigDict(extra="forbid")

    sharpe: float | None
    worst_regime_sharpe: float | None    # min Sharpe across regimes (the headline)
    max_drawdown: float | None
    cagr: float | None


class RunResult(BaseModel):
    """Output of one candidate run.

    Paths are workspace-relative strings so the JSON is portable.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str
    spec: RunSpec
    created_at: datetime
    n_bars: int
    bar_span: tuple[str, str]            # (first_ts_iso, last_ts_iso)

    headline: Headline
    state_distribution: dict[str, int]   # {"-1": n, "0": n, "1": n}
    flip_stats: FlipStats
    state_metrics: list[StateBlock]
    strategy: StrategyBlock
    episode_stats: EpisodeStats | None = None
    per_regime: list[RegimeBlock]

    complexity: Complexity
    warnings: list[str] = Field(default_factory=list)
    coverage: CoverageReport | None = None   # None when coverage gate was not run

    # Artifact paths (relative to workspace root)
    state_parquet: str
    report_html: str | None = None       # may be skipped in headless runs

    @staticmethod
    def now_iso() -> datetime:
        return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# IdeaSpec \u2014 LLM- or human-authored proposal
# ---------------------------------------------------------------------------

class IdeaModification(BaseModel):
    """One atomic modification on top of a base candidate.

    Phase 4 only models param overrides. Phases 5+ will add veto/confirm
    composition modifiers.
    """
    model_config = ConfigDict(extra="forbid")

    kind: Literal["override_params"]
    params: dict[str, Any]


class IdeaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    name: str
    based_on: str                        # candidate id in the registry
    hypothesis: str
    symbol: str = "BTCUSDT"
    tf: str = "1h"
    start: str | None = None
    end: str | None = None
    modifications: list[IdeaModification] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Comparison \u2014 bake-off output (Phase 7)
# ---------------------------------------------------------------------------

class RankedRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    run_id: str
    candidate: str
    headline: Headline
    complexity: Complexity
    episode_stats: EpisodeStats | None = None
    coverage: CoverageReport | None = None


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    comparison_id: str
    created_at: datetime
    baseline_run_id: str | None
    ranking_metric: str = "worst_regime_sharpe"
    tiebreaker: str = "complexity"
    ranked: list[RankedRun]
    winner_run_id: str | None
    decision_log: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# FeedSpec / FeedSnapshot (Phase 5+)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TrendTest / CoverageResult / CoverageReport (coverage gate)
# ---------------------------------------------------------------------------

class TrendTest(BaseModel):
    """One labelled trend episode from trend_tests.yaml."""
    model_config = ConfigDict(extra="forbid")

    id: str
    direction: Literal["up", "down"]
    entry_bar: str                       # ISO timestamp string, UTC
    entry_price: float
    exit_bar: str                        # ISO timestamp string, UTC
    exit_price: float
    move_pct: float
    notes: str = ""
    # Optional per-test gate overrides (fall back to CoverageConfig defaults)
    min_coverage_pct: float | None = None
    max_lag_pct: float | None = None


class CoverageResult(BaseModel):
    """Coverage check result for one trend test."""
    model_config = ConfigDict(extra="forbid")

    test_id: str
    direction: Literal["up", "down"]
    expected_dir: int                    # +1 or -1
    n_bars: int
    correct_bars: int
    coverage_pct: float                  # correct_bars / n_bars * 100
    lag_bars: int | None                 # bars into window before first agreement
    lag_pct: float | None                # lag_bars / n_bars * 100
    min_coverage_pct: float              # threshold applied
    max_lag_pct: float                   # threshold applied
    passed: bool


class CoverageReport(BaseModel):
    """Aggregated coverage gate result for a full candidate run."""
    model_config = ConfigDict(extra="forbid")

    tests: list[CoverageResult]
    n_passed: int
    n_total: int
    passed: bool                         # True only if ALL tests pass
    summary: str                         # human-readable one-liner


# ---------------------------------------------------------------------------
# FeedSpec / FeedSnapshot (Phase 5+)
# ---------------------------------------------------------------------------

class FeedSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    name: str                            # e.g. "binance.funding"
    source_url: str
    columns: dict[str, str]              # column -> dtype
    cadence: str                         # e.g. "8h", "1d"
    release_lag_seconds: int             # how late after bar_ts the value is published
    history_start: str
    history_end: str | None              # None = ongoing


class FeedSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    spec: FeedSpec
    parquet_path: str                    # workspace-relative
    rows: int
    last_refreshed: datetime
