"""Export primary CDX portfolio deep-dive bundle (equity + attribution + trades)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from cryoquant.backtest.reports import render_spot_result

from .cds_to_spot import portfolio_to_spot
from .portfolio_backtest import PortfolioResult


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return str(value)


def export_primary_bundle(
    result: PortfolioResult,
    spread_bps: pd.Series,
    bundle_dir: Path | str,
    *,
    meta_extra: dict[str, Any] | None = None,
) -> Path:
    """Write primary portfolio artifacts beside the standard RunBundle layout."""
    out = Path(bundle_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    scalar_metrics = {
        k: _json_safe(v)
        for k, v in result.metrics.items()
        if isinstance(v, (int, float, str, bool)) or v is None
    }
    meta: dict[str, Any] = {
        "study": "cdx_primary_portfolio",
        "name": result.name,
        "bundle_version": "1",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collateral_usd": result.collateral_usd,
        **scalar_metrics,
    }
    if meta_extra:
        meta.update(meta_extra)

    with open(out / "meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, default=str)

    equity_df = pd.DataFrame({
        "date": result.equity.index,
        "equity": result.equity.to_numpy(dtype=float),
        "nav_usd": result.equity.to_numpy(dtype=float) * result.collateral_usd,
    })
    equity_df.to_parquet(out / "equity_daily.parquet", index=False)

    attr = result.attribution.copy()
    attr.index.name = "date"
    attr.reset_index().to_parquet(out / "attribution_daily.parquet", index=False)

    spot = portfolio_to_spot(result, spread_bps, run_id=result.name)
    if not spot.trades.empty:
        spot.trades.to_parquet(out / "trades.parquet", index=False)

    signal_lines = [
        f"Portfolio: {result.name}",
        f"Yield strategy: {result.metrics.get('yield_strategy', 'n/a')}",
        f"Mutex: {result.metrics.get('apply_mutex', 'n/a')}",
        f"NAV end: {result.metrics.get('nav_end', float('nan')):.3f}",
        f"Carry funding ratio: {result.metrics.get('carry_funding_ratio', float('nan')):.2f}",
        f"COVID PnL (USD): {result.metrics.get('pnl_covid', float('nan')):,.0f}",
        f"Mutex overlap days: {result.metrics.get('mutex_overlap_days', 0)}",
    ]
    render_spot_result(
        spot,
        out / "report.html",
        signal_info="\n".join(signal_lines),
    )
    return out
