"""Dev-period VRP proxy backtest (no option chains)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cryoquant.backtest.robustness import deflated_sharpe
from cryoquant.backtest.short_vol_metrics import cvar_loss, trade_sharpe

# Map annualized vol points (DVOL − RV) to fractional proxy P&L for gates.
VRP_PNL_SCALE = 1.0 / 1000.0

from src.config_models import AssetId, StudyConfig
from src.dataset_build import load_label_series

log = logging.getLogger(__name__)

_HORIZON_SUFFIX = {
    "T+1d": ("T+1d", "h1"),
    "T+5d": ("T+5d", "h5"),
    "T+10-21d": ("T+10-21d", "h14"),
}


@dataclass
class ProxyBacktestResult:
    run_id: str
    asset: str
    horizon_id: str
    vrp_threshold: float
    tilt_mode: str
    min_physical_edge: float
    n_trades: int = 0
    expectancy: float = float("nan")
    sharpe: float = float("nan")
    deflated_sharpe: float = float("nan")
    cvar: float = float("nan")
    sign_hit_rate: float = float("nan")
    pnl_pct: list[float] = field(default_factory=list)
    beats_naive: bool = False


def _apply_spread_cost(pnl: np.ndarray, spread_bps: float) -> np.ndarray:
    cost = spread_bps / 10_000.0
    return pnl * VRP_PNL_SCALE - cost


def run_vrp_proxy(
    policy: pd.DataFrame,
    cfg: StudyConfig,
    *,
    asset: str,
    horizon_id: str,
    spread_bps: float = 10.0,
    run_id: str = "",
) -> ProxyBacktestResult:
    """P&L proxy = vrp_realized label on fire bars; baseline uses iv_minus_rv > 0."""
    _, suffix = _HORIZON_SUFFIX[horizon_id]
    label_name = f"vrp_realized_{suffix}"
    vrp = load_label_series(
        cfg,
        asset=AssetId(asset),
        horizon_id=horizon_id,
        label_name=label_name,
    )
    if vrp.empty:
        return ProxyBacktestResult(
            run_id=run_id,
            asset=asset,
            horizon_id=horizon_id,
            vrp_threshold=float(policy["vrp_threshold"].iloc[0]) if len(policy) else 0.0,
            tilt_mode=str(policy["tilt_mode"].iloc[0]) if len(policy) else "symmetric",
            min_physical_edge=float(policy["min_physical_edge"].iloc[0]) if len(policy) else 0.0,
        )

    aligned = policy.join(vrp.rename("vrp_realized"), how="inner")
    fired = aligned[aligned["fire"].astype(bool)]
    pnls = _apply_spread_cost(fired["vrp_realized"].to_numpy(dtype=float), spread_bps)
    pnls = pnls[np.isfinite(pnls)]

    sharpe = trade_sharpe(pnls)
    cvar = cvar_loss(pnls, alpha=cfg.risk.cvar_alpha)
    exp = float(np.mean(pnls)) if len(pnls) else float("nan")
    sign_hit = float(np.mean(np.sign(pnls) > 0)) if len(pnls) else float("nan")

    return ProxyBacktestResult(
        run_id=run_id,
        asset=asset,
        horizon_id=horizon_id,
        vrp_threshold=float(policy["vrp_threshold"].iloc[0]),
        tilt_mode=str(policy["tilt_mode"].iloc[0]),
        min_physical_edge=float(policy["min_physical_edge"].iloc[0]),
        n_trades=int(len(pnls)),
        expectancy=exp,
        sharpe=sharpe,
        cvar=cvar,
        sign_hit_rate=sign_hit,
        pnl_pct=[float(x) for x in pnls],
    )


def run_naive_vrp_baseline(
    signals: pd.DataFrame,
    cfg: StudyConfig,
    *,
    asset: str,
    horizon_id: str,
    spread_bps: float = 10.0,
) -> ProxyBacktestResult:
    _, suffix = _HORIZON_SUFFIX[horizon_id]
    label_name = f"vrp_realized_{suffix}"
    vrp = load_label_series(cfg, asset=AssetId(asset), horizon_id=horizon_id, label_name=label_name)
    aligned = signals.join(vrp.rename("vrp_realized"), how="inner")
    fired = aligned[aligned["iv_minus_rv"] > 0]
    pnls = _apply_spread_cost(fired["vrp_realized"].to_numpy(dtype=float), spread_bps)
    pnls = pnls[np.isfinite(pnls)]
    return ProxyBacktestResult(
        run_id="naive_vrp_positive",
        asset=asset,
        horizon_id=horizon_id,
        vrp_threshold=0.0,
        tilt_mode="symmetric",
        min_physical_edge=0.0,
        n_trades=int(len(pnls)),
        expectancy=float(np.mean(pnls)) if len(pnls) else float("nan"),
        sharpe=trade_sharpe(pnls),
        cvar=cvar_loss(pnls, alpha=cfg.risk.cvar_alpha),
        sign_hit_rate=float(np.mean(pnls > 0)) if len(pnls) else float("nan"),
        pnl_pct=[float(x) for x in pnls],
    )


def attach_deflated_sharpe(
    result: ProxyBacktestResult,
    *,
    n_trials: int,
) -> ProxyBacktestResult:
    pnls = np.asarray(result.pnl_pct, dtype=float)
    n = len(pnls)
    if n < 2 or not np.isfinite(result.sharpe):
        result.deflated_sharpe = float("nan")
        return result
    skew = float(pd.Series(pnls).skew()) if n > 2 else 0.0
    kurt = float(pd.Series(pnls).kurtosis() + 3) if n > 3 else 3.0
    result.deflated_sharpe = deflated_sharpe(
        result.sharpe, n_trials=max(1, n_trials), n_obs=n, skew=skew, kurt=kurt
    )
    return result


def compare_to_naive(model: ProxyBacktestResult, naive: ProxyBacktestResult) -> bool:
    if not np.isfinite(model.deflated_sharpe) or not np.isfinite(naive.deflated_sharpe):
        return bool(model.sharpe > naive.sharpe) if np.isfinite(model.sharpe) and np.isfinite(naive.sharpe) else False
    return model.deflated_sharpe > naive.deflated_sharpe


def proxy_to_dict(r: ProxyBacktestResult) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "asset": r.asset,
        "horizon_id": r.horizon_id,
        "vrp_threshold": r.vrp_threshold,
        "tilt_mode": r.tilt_mode,
        "min_physical_edge": r.min_physical_edge,
        "n_trades": r.n_trades,
        "expectancy": r.expectancy,
        "sharpe": r.sharpe,
        "deflated_sharpe": r.deflated_sharpe,
        "cvar": r.cvar,
        "sign_hit_rate": r.sign_hit_rate,
        "beats_naive": r.beats_naive,
    }
