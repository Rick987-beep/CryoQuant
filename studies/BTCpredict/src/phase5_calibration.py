"""Goal 2 calibration overlays — exceedance + VRP (Phase 5)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from cryoquant.features.labels import causal_forward_return_quantile
from cryoquant.models.validation import calibration_summary, exceedance_prob_from_quantiles

from src.config_models import AssetId, StudyConfig
from src.paths import data_dir
from src.dataset_build import load_label_series
from src.label_build import _load_ohlcv

log = logging.getLogger(__name__)

_HORIZON_MAP = {
    "h1": ("T+1d", 1),
    "h5": ("T+5d", 5),
    "h14": ("T+10-21d", 14),
}

_QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
_QUANTILE_COLS = [f"quantile_q{int(q * 100):02d}" for q in _QUANTILE_LEVELS]


def _load_close_series(cfg: StudyConfig, asset: str, *, through_holdout: bool = True) -> pd.Series:
    start = datetime.combine(cfg.splits.dev_start, datetime.min.time(), tzinfo=timezone.utc)
    end_date = cfg.splits.holdout_start if through_holdout else date.today()
    end = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
    bars = _load_ohlcv(asset, start, end)
    if bars.empty:
        return pd.Series(dtype=float)
    return bars["close"].sort_index()


def directional_calibration_from_oos(oos: pd.DataFrame) -> list[dict[str, Any]]:
    """ECE/Brier/reliability for directional OOS predictions."""
    out: list[dict[str, Any]] = []
    sub = oos[(oos["head"] == "directional") & oos["y_prob"].notna()]
    for run_id, grp in sub.groupby("run_id"):
        cal = calibration_summary(grp["y_true"].to_numpy(), grp["y_prob"].to_numpy())
        out.append(
            {
                "run_id": run_id,
                "asset": str(grp["asset"].iloc[0]),
                "horizon_id": str(grp["horizon_id"].iloc[0]),
                **cal,
            }
        )
    return out


def exceedance_calibration_overlay(
    cfg: StudyConfig,
    oos: pd.DataFrame,
    register: dict[str, Any],
    *,
    dev_only_labels: bool = True,
    close_through_holdout: bool = True,
) -> list[dict[str, Any]]:
    """Compare quantile-implied P(exceedance) vs exceedance labels (BTC/ETH)."""
    ecfg = register.get("exceedance_calibration", {})
    assets = ecfg.get("assets", ["BTC", "ETH"])
    deltas = ecfg.get("deltas", [0.10, 0.15, 0.20])
    sides = ecfg.get("sides", ["call", "put"])
    lookback = cfg.label.exceedance_quantile_lookback
    levels = tuple(ecfg.get("quantile_levels", list(_QUANTILE_LEVELS)))

    close_by_asset = {
        a: _load_close_series(cfg, a, through_holdout=close_through_holdout) for a in assets
    }
    results: list[dict[str, Any]] = []

    q_oos = oos[oos["head"] == "distributional"].copy()
    if q_oos.empty:
        return results

    for asset in assets:
        close = close_by_asset.get(asset)
        if close is None or close.empty:
            continue
        aid = AssetId(asset)
        for h_suffix, (horizon_id, h_bars) in _HORIZON_MAP.items():
            run_id = f"quantile_{asset.lower()}_{h_suffix}"
            qsub = q_oos[q_oos["run_id"] == run_id]
            if qsub.empty:
                continue

            q_call_strike = causal_forward_return_quantile(close, h_bars, 1.0 - 0.10, lookback)
            # strikes computed per delta inside loop

            for delta in deltas:
                q_call = causal_forward_return_quantile(close, h_bars, 1.0 - delta, lookback)
                q_put = causal_forward_return_quantile(close, h_bars, delta, lookback)
                strike_by_side = {"call": q_call, "put": q_put}

                for side in sides:
                    label_name = f"exceedance_{side}_d0p{int(delta * 100):02d}_{h_suffix}"
                    y = load_label_series(
                        cfg,
                        asset=aid,
                        horizon_id=horizon_id,
                        label_name=label_name,
                        dev_only=dev_only_labels,
                    )
                    if y.empty:
                        continue

                    probs: list[float] = []
                    truths: list[float] = []
                    strikes = strike_by_side[side]

                    for _, row in qsub.iterrows():
                        ts = pd.Timestamp(row["timestamp"])
                        if ts not in y.index or ts not in strikes.index:
                            continue
                        strike = float(strikes.loc[ts])
                        if not np.isfinite(strike):
                            continue
                        qvals = np.array([row.get(c, np.nan) for c in _QUANTILE_COLS], dtype=float)
                        if not np.all(np.isfinite(qvals)):
                            continue
                        p = exceedance_prob_from_quantiles(levels, qvals, strike, side)
                        probs.append(p)
                        truths.append(float(y.loc[ts]))

                    if len(probs) < 20:
                        continue

                    cal = calibration_summary(np.array(truths), np.array(probs))
                    results.append(
                        {
                            "asset": asset,
                            "horizon_id": horizon_id,
                            "side": side,
                            "delta": delta,
                            "label_name": label_name,
                            "quantile_run_id": run_id,
                            **cal,
                        }
                    )
    return results


def vrp_evaluation(
    cfg: StudyConfig,
    oos: pd.DataFrame,
    register: dict[str, Any],
) -> list[dict[str, Any]]:
    """Score realized-vol OOS predictions vs vrp_realized labels (BTC/ETH)."""
    vcfg = register.get("vrp", {})
    assets = vcfg.get("assets", ["BTC", "ETH"])
    results: list[dict[str, Any]] = []

    rv_oos = oos[oos["head"] == "realized_vol"].copy()
    if rv_oos.empty:
        return results

    feat = pd.read_parquet(data_dir() / "features.parquet")
    feat["timestamp"] = pd.to_datetime(feat["timestamp"], utc=True)
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    feat = feat[feat["timestamp"] < holdout]

    for asset in assets:
        aid = AssetId(asset)
        prefix = asset.lower()
        dvol_col = f"{prefix}_dvol_30d"
        for h_suffix, (horizon_id, _) in _HORIZON_MAP.items():
            run_id = f"realized_vol_{asset.lower()}_{h_suffix}"
            rsub = rv_oos[rv_oos["run_id"] == run_id]
            if rsub.empty:
                continue

            label_name = f"vrp_realized_{h_suffix}"
            y_vrp = load_label_series(
                cfg, asset=aid, horizon_id=horizon_id, label_name=label_name
            )
            if y_vrp.empty:
                continue

            fsub = feat[(feat["asset"] == asset) & feat[dvol_col].notna()][
                ["timestamp", dvol_col]
            ].set_index("timestamp")

            preds: list[float] = []
            vrp_true: list[float] = []
            vrp_pred: list[float] = []

            for _, row in rsub.iterrows():
                ts = pd.Timestamp(row["timestamp"])
                if ts not in y_vrp.index or ts not in fsub.index:
                    continue
                dvol = float(fsub.loc[ts, dvol_col])
                pred_rv = float(row["y_pred"])
                if not np.isfinite(dvol) or not np.isfinite(pred_rv):
                    continue
                vrp_true.append(float(y_vrp.loc[ts]))
                vrp_pred.append(dvol - pred_rv)
                preds.append(pred_rv)

            if len(vrp_true) < 20:
                continue

            yt = np.array(vrp_true)
            yp = np.array(vrp_pred)
            rho, _ = spearmanr(yt, yp)
            sign_hit = float(np.mean(np.sign(yt) == np.sign(yp)))
            mae = float(np.mean(np.abs(yt - yp)))

            results.append(
                {
                    "asset": asset,
                    "horizon_id": horizon_id,
                    "run_id": run_id,
                    "n": len(yt),
                    "spearman": float(rho) if np.isfinite(rho) else float("nan"),
                    "sign_hit_rate": sign_hit,
                    "mae": mae,
                    "mean_vrp_true": float(np.mean(yt)),
                    "mean_vrp_pred": float(np.mean(yp)),
                }
            )
    return results
