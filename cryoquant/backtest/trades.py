"""Canonical trade log schema and enrichment for CryoQuant backtests.

Any simulator (spot_pnl, turtle_simulate, or future) outputs a minimal
DataFrame; ``enrich_trades()`` normalises it to the full TradeLog schema.

Public interface::

    enrich_trades(trades, equity, bars_index=None, *, run_id=None) -> pd.DataFrame
    TRADE_COLUMNS — ordered list of all TradeLog columns
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Column contract
# ---------------------------------------------------------------------------

# Minimal columns expected from any simulator (must be present before enrich)
_SIMULATOR_REQUIRED = frozenset({
    "entry_ts", "exit_ts", "entry_price", "exit_price", "pnl_pct", "fee_pct",
})

# Full canonical schema — order matters for parquet schema stability
TRADE_COLUMNS: list[str] = [
    # Identity
    "run_id",        # added by sweep_collector; empty string when single-run
    "trade_id",      # 0-based index within run
    # Timestamps
    "entry_ts",
    "exit_ts",
    # Prices
    "entry_price",
    "exit_price",
    # Direction & exit reason (may be absent on spot_pnl / fixed-hold trades)
    "side",          # "long" | "short"
    "exit_type",     # "trail" | "hard_stop" | "end_of_data" | "fixed_hold"
    # Position sizing (placeholder; full-equity compounding = 1.0)
    "qty",
    # P&L
    "gross_pnl_pct",   # (exit - entry)/entry before fee, sign-corrected for side
    "fee_pct",         # round-trip fee fraction
    "pnl_pct",         # net = gross - fee
    "pnl_abs",         # pnl_pct * equity_before
    # Equity context
    "equity_before",   # account equity at entry (NAV just before this trade)
    "equity_after",    # account equity after exit  (NAV after this trade)
    # Holding period
    "duration_bars",   # integer bars held
    "duration_days",   # calendar days held (float)
]


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_trades(
    trades: pd.DataFrame,
    equity: pd.Series,
    bars_index: pd.DatetimeIndex | None = None,
    *,
    run_id: str = "",
) -> pd.DataFrame:
    """Enrich a minimal simulator trade DataFrame to the full TradeLog schema.

    Parameters
    ----------
    trades:
        Simulator output — must contain ``entry_ts``, ``exit_ts``,
        ``entry_price``, ``exit_price``, ``pnl_pct``, ``fee_pct``.
        Optionally contains ``side`` and ``exit_type``.
    equity:
        Equity curve indexed by bar timestamp (starts at 1.0, jumps at
        exits).  Used to derive ``equity_before`` / ``equity_after``.
    bars_index:
        The full bar DatetimeIndex from the OHLCV DataFrame.  Used to
        compute ``duration_bars``.  If ``None``, ``duration_bars`` is set
        to ``NaN``.
    run_id:
        Optional run identifier string added to every row.  Typically set
        by ``sweep_collector`` when stacking multi-run results.

    Returns
    -------
    pd.DataFrame with columns matching ``TRADE_COLUMNS`` (in order).
    """
    if trades.empty:
        return _empty_enriched()

    missing = _SIMULATOR_REQUIRED - set(trades.columns)
    if missing:
        raise ValueError(f"enrich_trades: missing required columns: {missing}")

    df = trades.copy()

    # Identity
    df["run_id"] = run_id
    df["trade_id"] = np.arange(len(df), dtype=np.int32)

    # Direction defaults for fixed-hold simulators that don't emit side/exit_type
    if "side" not in df.columns:
        df["side"] = "long"
    if "exit_type" not in df.columns:
        df["exit_type"] = "fixed_hold"

    # Position sizing placeholder
    df["qty"] = 1.0

    # Gross P&L: reverse-engineer from net + fee, keep sign correct
    df["gross_pnl_pct"] = df["pnl_pct"] + df["fee_pct"]

    # Duration
    entry_ts = pd.to_datetime(df["entry_ts"], utc=True)
    exit_ts  = pd.to_datetime(df["exit_ts"],  utc=True)
    df["duration_days"] = (exit_ts - entry_ts).dt.total_seconds() / 86_400.0

    if bars_index is not None:
        entry_pos = _ts_to_pos(entry_ts, bars_index)
        exit_pos  = _ts_to_pos(exit_ts,  bars_index)
        df["duration_bars"] = (exit_pos - entry_pos).clip(lower=0)
    else:
        df["duration_bars"] = float("nan")

    # Equity context — reconstruct equity_before / equity_after from the
    # stepped equity curve (equity jumps at exit_ts bars)
    if equity is not None and not equity.empty:
        eq_before, eq_after = _equity_context(df, equity)
        df["equity_before"] = eq_before
        df["equity_after"]  = eq_after
        df["pnl_abs"]       = df["pnl_pct"] * df["equity_before"]
    else:
        df["equity_before"] = float("nan")
        df["equity_after"]  = float("nan")
        df["pnl_abs"]       = float("nan")

    # Enforce column order (add any missing with NaN)
    for col in TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")

    return df[TRADE_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_enriched() -> pd.DataFrame:
    """Return an empty DataFrame with the full TradeLog schema."""
    return pd.DataFrame(columns=TRADE_COLUMNS)


def _ts_to_pos(
    ts_series: pd.Series,
    bars_index: pd.DatetimeIndex,
) -> pd.Series:
    """Map a Series of timestamps to integer bar positions.

    Uses ``searchsorted`` on int64 nanosecond representation to avoid
    tz-aware / tz-naive comparison errors.
    """
    # Normalise to UTC int64 nanoseconds
    if bars_index.tz is None:
        bi_ns = bars_index.tz_localize("UTC").view("i8")
    else:
        bi_ns = bars_index.tz_convert("UTC").view("i8")

    ts_utc = pd.to_datetime(ts_series, utc=True)
    ts_ns  = ts_utc.values.astype("i8")

    positions = np.searchsorted(bi_ns, ts_ns, side="left")
    positions = np.clip(positions, 0, len(bars_index) - 1)
    return pd.Series(positions, index=ts_series.index, dtype=np.int32)


def _equity_context(
    df: pd.DataFrame,
    equity: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Derive equity_before and equity_after for each trade.

    equity_before: equity value at the bar *before* entry (last settled value)
    equity_after:  equity value at the exit bar (updated after the trade closes)
    """
    eq_index = equity.index
    eq_vals  = equity.to_numpy(dtype=float)

    eq_before_list = []
    eq_after_list  = []

    for _, row in df.iterrows():
        entry_ts = pd.Timestamp(row["entry_ts"]).tz_localize("UTC") \
            if not hasattr(pd.Timestamp(row["entry_ts"]), "tzinfo") or \
               pd.Timestamp(row["entry_ts"]).tzinfo is None \
            else pd.Timestamp(row["entry_ts"])
        exit_ts = pd.Timestamp(row["exit_ts"]).tz_localize("UTC") \
            if pd.Timestamp(row["exit_ts"]).tzinfo is None \
            else pd.Timestamp(row["exit_ts"])

        # equity_before: value just before entry — one bar back if possible
        entry_pos = eq_index.searchsorted(entry_ts, side="left")
        before_pos = max(entry_pos - 1, 0)
        eq_before_list.append(float(eq_vals[before_pos]))

        # equity_after: value at exit bar
        exit_pos = eq_index.searchsorted(exit_ts, side="left")
        exit_pos = min(exit_pos, len(eq_vals) - 1)
        eq_after_list.append(float(eq_vals[exit_pos]))

    return (
        pd.Series(eq_before_list, index=df.index, dtype=float),
        pd.Series(eq_after_list,  index=df.index, dtype=float),
    )
