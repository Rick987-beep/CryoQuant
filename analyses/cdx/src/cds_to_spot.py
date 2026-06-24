"""Adapt CDX overlay/portfolio results to framework SpotResult types."""
from __future__ import annotations

import pandas as pd

from cryoquant.backtest.spot_pnl import SpotResult
from cryoquant.backtest.trades import TRADE_COLUMNS, enrich_trades

from .backtest_cds import CdsOverlayResult
from .portfolio_backtest import PortfolioResult

_SIDE_MAP = {
    "long_protection": "long",
    "short_protection": "short",
    "long": "long",
    "short": "short",
}


def _spread_at(spread_bps: pd.Series, ts: pd.Timestamp) -> float:
    """Look up spread (bps) at timestamp; nearest prior bar if exact miss."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    if ts in spread_bps.index:
        return float(spread_bps.loc[ts])
    pos = spread_bps.index.searchsorted(ts, side="right") - 1
    pos = max(int(pos), 0)
    return float(spread_bps.iloc[pos])


def cds_trades_to_minimal(
    trades: pd.DataFrame,
    spread_bps: pd.Series,
    collateral_usd: float,
) -> pd.DataFrame:
    """Map CDX trade log columns to enrich_trades minimal schema."""
    if trades.empty:
        return pd.DataFrame(
            columns=["entry_ts", "exit_ts", "entry_price", "exit_price", "pnl_pct", "fee_pct"]
        )

    rows: list[dict] = []
    for _, row in trades.iterrows():
        entry_ts = row["entry_ts"]
        exit_ts = row["exit_ts"]
        pnl_usd = float(row.get("pnl_usd", row["pnl_pct"] * collateral_usd))
        carry = float(row.get("carry_usd", 0.0))
        mtm = float(row.get("mtm_usd", 0.0))
        costs_usd = pnl_usd - carry - mtm
        fee_pct = abs(costs_usd) / collateral_usd if collateral_usd else 0.0

        raw_side = str(row.get("side", "long"))
        side = _SIDE_MAP.get(raw_side, raw_side)

        rows.append({
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "entry_price": _spread_at(spread_bps, entry_ts),
            "exit_price": _spread_at(spread_bps, exit_ts),
            "pnl_pct": float(row["pnl_pct"]),
            "fee_pct": fee_pct,
            "side": side,
            "exit_type": "cds_overlay",
        })

    return pd.DataFrame(rows)


def overlay_to_spot(
    result: CdsOverlayResult,
    spread_bps: pd.Series,
    *,
    run_id: str | None = None,
    extra_metrics: dict | None = None,
) -> SpotResult:
    """Convert a single CDS overlay backtest to SpotResult."""
    minimal = cds_trades_to_minimal(result.trades, spread_bps, result.collateral_usd)
    enriched = enrich_trades(
        minimal,
        result.equity,
        bars_index=spread_bps.index,
        run_id=run_id or result.name,
    )
    metrics = dict(result.metrics)
    if extra_metrics:
        metrics.update(extra_metrics)
    metrics.setdefault("nav_end", float(result.equity.iloc[-1]) if len(result.equity) else 1.0)
    return SpotResult(equity=result.equity, trades=enriched, metrics=metrics)


def portfolio_to_spot(
    result: PortfolioResult,
    spread_bps: pd.Series,
    *,
    run_id: str | None = None,
) -> SpotResult:
    """Convert a portfolio backtest to SpotResult (combined NAV + stacked trades)."""
    minimal = cds_trades_to_minimal(result.trades, spread_bps, result.collateral_usd)
    enriched = enrich_trades(
        minimal,
        result.equity,
        bars_index=spread_bps.index,
        run_id=run_id or result.name,
    )
    metrics = dict(result.metrics)
    metrics.setdefault("nav_end", float(result.equity.iloc[-1]) if len(result.equity) else 1.0)
    # Normalise COVID key for scoring consistency with Phase 3 rows
    if "pnl_covid" in metrics and "covid_pnl_usd" not in metrics:
        metrics["covid_pnl_usd"] = metrics["pnl_covid"]
    return SpotResult(equity=result.equity, trades=enriched, metrics=metrics)


def spot_trades_schema(trades: pd.DataFrame) -> bool:
    """Return True if trades DataFrame has all TRADE_COLUMNS."""
    return trades.empty or set(TRADE_COLUMNS).issubset(set(trades.columns))
