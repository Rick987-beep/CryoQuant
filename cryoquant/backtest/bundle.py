"""Machine-readable run bundle I/O for CryoQuant sweeps.

A bundle is a directory with a fixed layout::

    <bundle_dir>/
    ├── meta.json              # caller-supplied metadata dict
    ├── leaderboard.parquet    # scored and ranked leaderboard
    ├── leaderboard.csv        # same, for spreadsheet consumption
    ├── trades.parquet         # stacked TradeLog across all runs
    ├── equity_daily.parquet   # stacked daily equity indexed by (run_id, date)
    └── report.html            # rendered HTML (written by reports module)

Public interface::

    RunBundle      — dataclass holding all bundle components in memory
    write_bundle(path, bundle) -> Path
    load_bundle(path) -> RunBundle
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RunBundle:
    """All components of a sweep bundle, held in memory.

    Attributes
    ----------
    meta:
        Dict of metadata describing the bundle.  Must contain at minimum
        the keys documented in the plan: ``study``, ``n_runs``, ``scoring``.
        ``bundle_version`` and ``created_at`` are added automatically by
        ``write_bundle`` if absent.
    leaderboard:
        Scored and ranked leaderboard DataFrame; one row per run.
    trades:
        Stacked TradeLog DataFrame for all runs.  Contains a ``run_id``
        column identifying each run.  May be empty if no trades were
        collected.
    equity_daily:
        Stacked daily equity DataFrame with columns ``run_id``, ``date``,
        ``equity``.  May be empty.
    """

    meta: dict[str, Any] = field(default_factory=dict)
    leaderboard: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity_daily: pd.DataFrame = field(default_factory=pd.DataFrame)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_bundle(path: Path | str, bundle: RunBundle) -> Path:
    """Persist a RunBundle to disk.

    Parameters
    ----------
    path:
        Directory to write into.  Created (including parents) if absent.
    bundle:
        In-memory bundle to persist.

    Returns
    -------
    Absolute path to the bundle directory.
    """
    bundle_dir = Path(path).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Ensure required meta keys
    meta = dict(bundle.meta)
    meta.setdefault("bundle_version", "1")
    meta.setdefault(
        "created_at",
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # meta.json
    with open(bundle_dir / "meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, default=str)

    # leaderboard
    if not bundle.leaderboard.empty:
        bundle.leaderboard.to_parquet(
            bundle_dir / "leaderboard.parquet", index=False
        )
        bundle.leaderboard.to_csv(
            bundle_dir / "leaderboard.csv", index=False
        )

    # trades
    if not bundle.trades.empty:
        bundle.trades.to_parquet(bundle_dir / "trades.parquet", index=False)

    # equity_daily
    if not bundle.equity_daily.empty:
        bundle.equity_daily.to_parquet(
            bundle_dir / "equity_daily.parquet", index=False
        )

    return bundle_dir


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_bundle(path: Path | str) -> RunBundle:
    """Load a RunBundle from a directory written by ``write_bundle``.

    Parameters
    ----------
    path:
        Bundle directory.

    Returns
    -------
    RunBundle.  Components not found on disk are returned as empty
    DataFrames / empty dicts.
    """
    bundle_dir = Path(path).resolve()
    if not bundle_dir.is_dir():
        raise FileNotFoundError(f"Bundle directory not found: {bundle_dir}")

    meta: dict[str, Any] = {}
    meta_path = bundle_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)

    leaderboard = _load_parquet(bundle_dir / "leaderboard.parquet")
    trades      = _load_parquet(bundle_dir / "trades.parquet")
    eq_daily    = _load_parquet(bundle_dir / "equity_daily.parquet")

    return RunBundle(
        meta=meta,
        leaderboard=leaderboard,
        trades=trades,
        equity_daily=eq_daily,
    )


def _load_parquet(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()
