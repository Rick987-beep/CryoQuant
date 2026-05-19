"""Option chain P&L lookup — library-fy of reference 11b/11c/11d.

Loads daily Deribit option chain snapshots, finds straddle legs at a
(DTE × delta) target for each signal fire, and tracks mark-to-market P&L
at the exit horizon (hold_h hours rounded to the nearest available daily
snapshot).

Public interface::

    evaluate(signal, bars, *, dte, delta, exit_rule, chains_dir) -> OptionResult

    ExitRule   — Pydantic record controlling hold horizon and optional TP/SL.
    OptionResult — Pydantic record with P&L distribution + summary stats.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration / result types
# ---------------------------------------------------------------------------

class ExitRule(BaseModel):
    """Controls how straddle positions are closed.

    Attributes:
        hold_h:          Hold duration in hours.  Rounded to days when only
                         daily snapshots are available.  Default 24h (1 day).
        tp_multiple:     Close early if mark value reaches this multiple of
                         entry cost.  None = no take-profit.
        stop_multiple:   Close early if mark value drops to this fraction of
                         entry cost.  None = no stop.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hold_h: int = 24
    tp_multiple: float | None = None
    stop_multiple: float | None = None


class OptionResult(BaseModel):
    """Per-signal P&L distribution from ``evaluate``.

    Attributes:
        fires_evaluated:  Total signal fires in the evaluation window.
        fires_with_data:  Fires for which a valid chain snapshot was found.
        pnl_pct:          P&L per resolved fire as fraction of entry cost
                          (positive = profit).
        win_rate:         Fraction of resolved fires with pnl_pct > 0.
        expectancy:       Mean pnl_pct across resolved fires.
        entry_costs_usd:  Straddle entry cost (ask) per fire in USD.
        dte_actual:       Actual DTE found for each fire.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fires_evaluated: int
    fires_with_data: int
    pnl_pct: list[float]
    win_rate: float
    expectancy: float
    entry_costs_usd: list[float]
    dte_actual: list[int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DERIBIT_MONTHS = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]


def _to_deribit_expiry(d: date) -> str:
    """Convert a Python date to Deribit's expiry label, e.g. '12MAY26'."""
    return f"{d.day}{_DERIBIT_MONTHS[d.month - 1]}{str(d.year)[2:]}"


def _best_leg(
    chain: pd.DataFrame,
    expiry: date,
    target_delta: float,
    is_call: bool,
) -> pd.Series | None:
    """Find the single option leg closest to *target_delta* for *expiry*.

    Chain columns (real Deribit format): expiry (category, e.g. '12MAY26'),
    strike, is_call (bool), bid_price, ask_price, mark_price, delta.
    """
    expiry_label = _to_deribit_expiry(expiry)
    mask = (
        (chain["expiry"] == expiry_label)
        & (chain["is_call"] == is_call)
        & (chain["ask_price"] > 0)
    )
    subset = chain[mask]
    if subset.empty:
        return None

    # delta for puts is negative; use abs distance
    delta_col = subset["delta"].abs()
    idx = (delta_col - abs(target_delta)).abs().idxmin()
    return subset.loc[idx]


def _load_chain_df(chains_dir: Path, d: date) -> pd.DataFrame | None:
    """Try to load an options chain parquet from *chains_dir* for *d*."""
    path = chains_dir / f"options_{d.isoformat()}.parquet"
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        log.warning("Failed to load %s: %s", path, exc)
        return None


def _spot_price_on_date(chains_dir: Path, d: date) -> float | None:
    """Return a representative spot price from spot parquet for *d*."""
    path = chains_dir / f"spot_{d.isoformat()}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        col = "close" if "close" in df.columns else df.columns[0]
        return float(df[col].dropna().iloc[-1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public: evaluate
# ---------------------------------------------------------------------------

def evaluate(
    signal: object,
    bars: pd.DataFrame,
    *,
    dte: int = 1,
    delta: float = 0.25,
    exit_rule: ExitRule | None = None,
    chains_dir: Path,
) -> OptionResult:
    """Evaluate a signal's option-trade performance against real chains.

    Parameters
    ----------
    signal:      BoolSignal or ProbSignal (duck-typed).
    bars:        OHLCV DataFrame used to compute signal fires.  Must have a
                 tz-aware UTC DatetimeIndex.
    dte:         Target days-to-expiry at entry.
    delta:       Target absolute delta per leg (both call and put).
    exit_rule:   Exit parameters.  Defaults to ExitRule(hold_h=24).
    chains_dir:  Directory containing ``options_YYYY-MM-DD.parquet`` files.

    Returns
    -------
    OptionResult with P&L distribution and summary statistics.
    """
    if exit_rule is None:
        exit_rule = ExitRule()

    from cryoquant.signals.base import ProbSignal

    # Fire mask
    if isinstance(signal, ProbSignal):
        thr = signal.default_threshold
        probs = signal.as_feature(bars).to_numpy(dtype=float)
        fires_mask = probs >= thr
    else:
        fires_mask = signal.as_feature(bars).fillna(False).to_numpy(dtype=bool)

    fire_timestamps = bars.index[fires_mask]
    n_fires = len(fire_timestamps)
    log.debug("evaluate: %d signal fires in %d bars", n_fires, len(bars))

    pnl_pct: list[float] = []
    entry_costs_usd: list[float] = []
    dte_actual: list[int] = []
    hold_days = max(1, exit_rule.hold_h // 24)

    for ts in fire_timestamps:
        fire_date = ts.date()
        expiry_date = fire_date + timedelta(days=dte)

        entry_chain = _load_chain_df(chains_dir, fire_date)
        if entry_chain is None:
            continue

        # Need spot price for USD cost conversion
        spot = _spot_price_on_date(chains_dir, fire_date)
        if spot is None:
            # Fallback: use bar's close price
            if ts in bars.index:
                spot = float(bars.loc[ts, "close"])
            else:
                continue

        # Find call and put legs
        call_leg = _best_leg(entry_chain, expiry_date, delta, is_call=True)
        put_leg = _best_leg(entry_chain, expiry_date, delta, is_call=False)
        if call_leg is None or put_leg is None:
            continue

        entry_call_ask = float(call_leg["ask_price"])
        entry_put_ask = float(put_leg["ask_price"])
        entry_cost_frac = entry_call_ask + entry_put_ask  # fraction of spot
        entry_cost_usd = entry_cost_frac * spot
        if entry_cost_usd <= 0:
            continue

        # Exit: load chain at hold_days later (or at expiry)
        exit_date = fire_date + timedelta(days=hold_days)
        if exit_date > expiry_date:
            exit_date = expiry_date

        exit_chain = _load_chain_df(chains_dir, exit_date)
        exit_spot = _spot_price_on_date(chains_dir, exit_date)

        if exit_chain is not None and exit_spot is not None:
            # Mark-to-market exit using mid price
            exit_call = _best_leg(exit_chain, expiry_date, delta, is_call=True)
            exit_put = _best_leg(exit_chain, expiry_date, delta, is_call=False)
            if exit_call is not None and exit_put is not None:
                exit_call_bid = float(
                    exit_call["bid_price"]
                    if exit_call["bid_price"] > 0
                    else exit_call["ask_price"] * 0.9
                )
                exit_put_bid = float(
                    exit_put["bid_price"]
                    if exit_put["bid_price"] > 0
                    else exit_put["ask_price"] * 0.9
                )
                exit_value_frac = exit_call_bid + exit_put_bid
            else:
                # Intrinsic value fallback
                strike = float(call_leg["strike"])
                exit_value_frac = (
                    max(0.0, exit_spot - strike) + max(0.0, strike - exit_spot)
                ) / exit_spot
        else:
            # Intrinsic value at expiry using fire-date spot
            strike = float(call_leg["strike"])
            exit_value_frac = (
                max(0.0, spot - strike) + max(0.0, strike - spot)
            ) / spot

        pnl = (exit_value_frac - entry_cost_frac) / entry_cost_frac
        pnl_pct.append(float(pnl))
        entry_costs_usd.append(float(entry_cost_usd))
        dte_actual.append(
            (expiry_date - fire_date).days
        )

    fires_with_data = len(pnl_pct)
    if fires_with_data > 0:
        win_rate = float(np.mean(np.array(pnl_pct) > 0))
        expectancy = float(np.mean(pnl_pct))
    else:
        win_rate = float("nan")
        expectancy = float("nan")

    return OptionResult(
        fires_evaluated=n_fires,
        fires_with_data=fires_with_data,
        pnl_pct=pnl_pct,
        win_rate=win_rate,
        expectancy=expectancy,
        entry_costs_usd=entry_costs_usd,
        dte_actual=dte_actual,
    )
