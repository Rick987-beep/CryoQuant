"""Merge Phase 4 OOS predictions with features for Phase 6 signals."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from cryoquant.features.labels import causal_forward_return_quantile
from cryoquant.models.validation import exceedance_prob_from_quantiles

from src.config_models import AssetId, StudyConfig
from src.dataset_build import load_features_frame
from src.label_build import _load_ohlcv
from src.paths import data_dir

log = logging.getLogger(__name__)

_HORIZON_SUFFIX = {
    "T+1d": "h1",
    "T+5d": "h5",
    "T+10-21d": "h14",
}

_QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
_QUANTILE_COLS = [f"quantile_q{int(q * 100):02d}" for q in _QUANTILE_LEVELS]


def _oos_run_id(head: str, asset: str, horizon_id: str) -> str:
    suffix = _HORIZON_SUFFIX[horizon_id]
    if head == "directional":
        return f"dir_{asset.lower()}_up_win_volscaled_{suffix}"
    if head == "realized_vol":
        return f"realized_vol_{asset.lower()}_{suffix}"
    if head == "distributional":
        return f"quantile_{asset.lower()}_{suffix}"
    raise ValueError(f"unsupported head {head}")


def _load_predictions(
    cfg: StudyConfig,
    *,
    holdout: bool = False,
) -> pd.DataFrame:
    path = data_dir() / ("holdout_predictions.parquet" if holdout else "oos_predictions.parquet")
    oos = pd.read_parquet(path)
    oos["timestamp"] = pd.to_datetime(oos["timestamp"], utc=True)
    boundary = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    if holdout:
        return oos[oos["timestamp"] >= boundary].copy()
    return oos[oos["timestamp"] < boundary].copy()


def _load_oos_dev(cfg: StudyConfig) -> pd.DataFrame:
    return _load_predictions(cfg, holdout=False)


def _feature_series_from_df(
    feat: pd.DataFrame,
    asset: str,
    col: str,
) -> pd.Series:
    sub = feat[feat["asset"] == asset].set_index("timestamp").sort_index()
    if col not in sub.columns:
        return pd.Series(dtype=float, name=col)
    return sub[col].astype(float)


def _feature_series(cfg: StudyConfig, asset: str, col: str, *, holdout: bool = False) -> pd.Series:
    if holdout:
        from src.dataset_build import load_features_all

        feat = load_features_all(cfg)
    else:
        feat = load_features_frame(cfg)
    return _feature_series_from_df(feat, asset, col)


def _exceedance_edge_row(
    row: pd.Series,
    strike_call: float,
    strike_put: float,
    *,
    delta: float,
) -> float:
    qvals = np.array([row.get(c, np.nan) for c in _QUANTILE_COLS], dtype=float)
    if not np.all(np.isfinite(qvals)):
        return float("nan")
    p_itm_call = exceedance_prob_from_quantiles(_QUANTILE_LEVELS, qvals, strike_call, "call")
    p_itm_put = exceedance_prob_from_quantiles(_QUANTILE_LEVELS, qvals, strike_put, "put")
    p_otm_call = 1.0 - p_itm_call
    p_otm_put = 1.0 - p_itm_put
    p_otm = 0.5 * (p_otm_call + p_otm_put)
    return float(p_otm - (1.0 - delta))


def _build_horizon_signals_core(
    cfg: StudyConfig,
    register: dict[str, Any],
    oos: pd.DataFrame,
    *,
    asset: str = "BTC",
    horizon_id: str = "T+1d",
    target_delta: float = 0.15,
    close: pd.Series,
    dvol: pd.Series,
    ivrv: pd.Series,
) -> pd.DataFrame:
    h_bars = next(h.horizon_bars for h in cfg.horizons if h.id.value == horizon_id)
    rv_id = _oos_run_id("realized_vol", asset, horizon_id)
    q_id = _oos_run_id("distributional", asset, horizon_id)
    dir_id = _oos_run_id("directional", asset, horizon_id)

    rv = oos[oos["run_id"] == rv_id][["timestamp", "y_pred"]].rename(columns={"y_pred": "pred_fwd_rv"})
    qsub = oos[oos["run_id"] == q_id].copy()
    direc = oos[oos["run_id"] == dir_id][["timestamp", "y_prob"]].rename(columns={"y_prob": "p_up"})

    idx = dvol.dropna().index
    for s in (rv.set_index("timestamp")["pred_fwd_rv"], ivrv):
        idx = idx.intersection(s.dropna().index)

    out = pd.DataFrame(index=idx.sort_values())
    out["dvol"] = dvol.reindex(out.index)
    out["pred_fwd_rv"] = rv.set_index("timestamp")["pred_fwd_rv"].reindex(out.index)
    out["iv_minus_rv"] = ivrv.reindex(out.index)
    out["vol_edge"] = out["dvol"] - out["pred_fwd_rv"]
    out["p_up"] = direc.set_index("timestamp")["p_up"].reindex(out.index)

    lookback = cfg.label.exceedance_quantile_lookback
    q_call = causal_forward_return_quantile(close, h_bars, 1.0 - target_delta, lookback)
    q_put = causal_forward_return_quantile(close, h_bars, target_delta, lookback)

    q_by_ts = qsub.set_index("timestamp")
    edges: list[float] = []
    ecfg = register.get("signal", {}).get("exceedance_gate", {})
    gate_horizons = ecfg.get("horizons", ["T+1d", "T+5d"])
    gate_enabled = ecfg.get("enabled", True) and horizon_id in gate_horizons

    for ts in out.index:
        if ts not in q_by_ts.index or ts not in q_call.index:
            edges.append(float("nan"))
            continue
        row = q_by_ts.loc[ts]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        edges.append(
            _exceedance_edge_row(
                row,
                float(q_call.loc[ts]),
                float(q_put.loc[ts]),
                delta=target_delta,
            )
        )
    out["exceedance_edge"] = edges
    out["exceedance_gate_active"] = gate_enabled
    out["asset"] = asset
    out["horizon_id"] = horizon_id
    out["target_delta"] = target_delta
    return out


def build_horizon_signals(
    cfg: StudyConfig,
    register: dict[str, Any],
    *,
    asset: str = "BTC",
    horizon_id: str = "T+1d",
    target_delta: float = 0.15,
) -> pd.DataFrame:
    """Per-bar vol_edge, exceedance_edge, p_up aligned on dev timestamps."""
    from datetime import datetime, timezone

    oos = _load_oos_dev(cfg)
    prefix = asset.lower()
    dvol = _feature_series(cfg, asset, f"{prefix}_dvol_30d").rename("dvol")
    ivrv = _feature_series(cfg, asset, f"{prefix}_iv_minus_rv").rename("iv_minus_rv")
    start = datetime.combine(cfg.splits.dev_start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(cfg.splits.holdout_start, datetime.min.time(), tzinfo=timezone.utc)
    close = _load_ohlcv(asset, start, end)["close"].sort_index()
    return _build_horizon_signals_core(
        cfg,
        register,
        oos,
        asset=asset,
        horizon_id=horizon_id,
        target_delta=target_delta,
        close=close,
        dvol=dvol,
        ivrv=ivrv,
    )


def build_horizon_signals_holdout(
    cfg: StudyConfig,
    register: dict[str, Any],
    *,
    asset: str = "BTC",
    horizon_id: str = "T+1d",
    target_delta: float = 0.15,
    slice_start: pd.Timestamp | None = None,
    slice_end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Per-bar signals on hold-out using holdout_predictions.parquet."""
    from datetime import date, datetime, timezone

    oos = _load_predictions(cfg, holdout=True)
    prefix = asset.lower()
    dvol = _feature_series(cfg, asset, f"{prefix}_dvol_30d", holdout=True).rename("dvol")
    ivrv = _feature_series(cfg, asset, f"{prefix}_iv_minus_rv", holdout=True).rename("iv_minus_rv")

    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    start = datetime.combine(cfg.splits.holdout_start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(date.today(), datetime.max.time(), tzinfo=timezone.utc)
    close = _load_ohlcv(asset, start, end)["close"].sort_index()

    out = _build_horizon_signals_core(
        cfg,
        register,
        oos,
        asset=asset,
        horizon_id=horizon_id,
        target_delta=target_delta,
        close=close,
        dvol=dvol,
        ivrv=ivrv,
    )
    if slice_start is not None:
        out = out[out.index >= slice_start]
    if slice_end is not None:
        out = out[out.index < slice_end]
    if len(out) and out.index.min() < holdout:
        raise ValueError("hold-out signals contain pre-holdout timestamps")
    return out


def build_all_horizon_signals(
    cfg: StudyConfig,
    register: dict[str, Any],
    *,
    asset: str = "BTC",
) -> dict[str, pd.DataFrame]:
    delta = float(register.get("signal", {}).get("exceedance_gate", {}).get("max_delta", 0.15))
    sweep = register.get("sweep", {})
    horizons = sweep.get("axes", {}).get("horizon_id", ["T+1d", "T+5d"])
    return {
        h: build_horizon_signals(cfg, register, asset=asset, horizon_id=h, target_delta=delta)
        for h in horizons
    }
