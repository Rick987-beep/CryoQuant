"""Generic multi-run sweep aggregator.

Keeps orchestration logic analysis-agnostic: analysis code injects the
simulator function, run-ID scheme, and parameter serialisation.

Public interface::

    RunRecord        — one completed run (id + params + result)
    SweepCollection  — all records; exposes leaderboard_rows / trades_df /
                       equity_daily_df helpers
    collect_runs(configs, runner, *, run_id_fn, params_fn, min_trades) -> SweepCollection
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from cryoquant.backtest.spot_pnl import SpotResult
from cryoquant.backtest.trades import TRADE_COLUMNS

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    """Result of a single parameterised backtest run."""

    run_id: str
    params: dict[str, Any]    # JSON-serialisable config snapshot
    result: SpotResult


@dataclass
class SweepCollection:
    """Container for all RunRecords produced by a sweep.

    Attributes
    ----------
    records:
        List of successful RunRecord objects (skipped / failed runs are
        not stored here).
    n_skipped:
        Number of configs skipped due to ``min_trades`` gate or errors.
    """

    records: list[RunRecord] = field(default_factory=list)
    n_skipped: int = 0

    # ── Aggregation helpers ──────────────────────────────────────────────────

    def leaderboard_rows(self) -> list[dict[str, Any]]:
        """Return one dict per run suitable for a leaderboard DataFrame.

        Each dict contains the run's params, its metrics (from
        ``result.metrics``), and the ``run_id``.
        """
        rows = []
        for rec in self.records:
            row: dict[str, Any] = {"run_id": rec.run_id}
            row.update(rec.params)
            row.update(rec.result.metrics)
            rows.append(row)
        return rows

    def trades_df(self) -> pd.DataFrame:
        """Return a stacked TradeLog DataFrame for all runs.

        Each trade's ``run_id`` column is set to the corresponding record's
        run_id.  Returns an empty DataFrame with ``TRADE_COLUMNS`` if no
        trades exist.
        """
        if not self.records:
            return pd.DataFrame(columns=TRADE_COLUMNS)

        parts = []
        for rec in self.records:
            t = rec.result.trades
            if t is None or t.empty:
                continue
            t = t.copy()
            t["run_id"] = rec.run_id
            parts.append(t)

        if not parts:
            return pd.DataFrame(columns=TRADE_COLUMNS)

        stacked = pd.concat(parts, ignore_index=True)

        # Ensure all TRADE_COLUMNS present
        for col in TRADE_COLUMNS:
            if col not in stacked.columns:
                stacked[col] = float("nan")

        return stacked[TRADE_COLUMNS].reset_index(drop=True)

    def equity_daily_df(self) -> pd.DataFrame:
        """Return a stacked equity DataFrame with columns run_id, date, equity."""
        if not self.records:
            return pd.DataFrame(columns=["run_id", "date", "equity"])

        parts = []
        for rec in self.records:
            eq = rec.result.equity
            if eq is None or eq.empty:
                continue
            eq_df = pd.DataFrame({
                "run_id": rec.run_id,
                "date":   eq.index,
                "equity": eq.to_numpy(dtype=float),
            })
            parts.append(eq_df)

        if not parts:
            return pd.DataFrame(columns=["run_id", "date", "equity"])

        return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_runs(
    configs: Iterable[Any],
    runner: Callable[[Any], SpotResult | None],
    *,
    run_id_fn: Callable[[Any], str],
    params_fn: Callable[[Any], dict[str, Any]],
    min_trades: int = 5,
    progress: bool = True,
) -> SweepCollection:
    """Run all configs through *runner* and aggregate results.

    Parameters
    ----------
    configs:
        Iterable of configuration objects (e.g. ``SweepConfig`` dataclasses).
    runner:
        Callable that takes one config and returns a ``SpotResult`` or
        ``None`` on failure.  Exceptions are caught and logged.
    run_id_fn:
        Extracts a unique string run identifier from a config.
    params_fn:
        Extracts a JSON-serialisable ``dict`` snapshot from a config.
    min_trades:
        Minimum number of completed trades for a run to be included.
        Runs below this threshold increment ``n_skipped``.
    progress:
        If True, log a progress line every 100 configs (useful for long
        sweeps).

    Returns
    -------
    SweepCollection with all qualifying runs.
    """
    configs_list = list(configs)
    total = len(configs_list)
    collection = SweepCollection()

    for i, cfg in enumerate(configs_list):
        if progress and (i % 100 == 0):
            log.info("sweep progress %d / %d", i, total)

        run_id = run_id_fn(cfg)
        try:
            result = runner(cfg)
        except Exception:
            log.warning("run %s raised an exception:\n%s", run_id, traceback.format_exc())
            collection.n_skipped += 1
            continue

        if result is None:
            collection.n_skipped += 1
            continue

        n_trades = result.metrics.get("n_trades", 0) if result.metrics else 0
        if n_trades < min_trades:
            collection.n_skipped += 1
            continue

        collection.records.append(RunRecord(
            run_id=run_id,
            params=params_fn(cfg),
            result=result,
        ))

    log.info(
        "collect_runs done: %d accepted, %d skipped (total %d)",
        len(collection.records), collection.n_skipped, total,
    )
    return collection
