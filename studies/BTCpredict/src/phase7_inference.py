"""Phase 7A — refit models on full dev, predict hold-out once."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config_models import StudyConfig
from src.dataset_build import FoldScaler, META_COLS, build_training_frame, load_features_holdout, select_features_for_run, valid_columns_for_train
from src.phase4_train import _make_model
from src.training_register import TrainingRun, list_training_runs, load_training_register

log = logging.getLogger(__name__)


def _predict_rows_classification(
    run: TrainingRun,
    model: Any,
    X_te: pd.DataFrame,
    y_te: pd.Series | None,
) -> list[dict[str, Any]]:
    probs = np.asarray(model.predict_proba(X_te), dtype=float)
    rows: list[dict[str, Any]] = []
    for ts, prob in zip(X_te.index, probs):
        yt = float(y_te.loc[ts]) if y_te is not None and ts in y_te.index else float("nan")
        rows.append(
            {
                "timestamp": ts,
                "asset": run.asset.value,
                "horizon_id": run.horizon_id.value,
                "head": run.head.value,
                "label_name": run.label_name,
                "run_id": run.run_id,
                "fold_id": -1,
                "y_true": yt,
                "y_prob": float(prob),
                "y_pred": np.nan,
            }
        )
    return rows


def _predict_rows_regression(
    run: TrainingRun,
    model: Any,
    X_te: pd.DataFrame,
    y_te: pd.Series | None,
    *,
    quantile: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if quantile:
        qdf = model.predict_quantiles(X_te)
        preds = model.predict(X_te)
        for i, ts in enumerate(X_te.index):
            yt = float(y_te.loc[ts]) if y_te is not None and ts in y_te.index else float("nan")
            row = {
                "timestamp": ts,
                "asset": run.asset.value,
                "horizon_id": run.horizon_id.value,
                "head": run.head.value,
                "label_name": run.label_name,
                "run_id": run.run_id,
                "fold_id": -1,
                "y_true": yt,
                "y_prob": np.nan,
                "y_pred": float(preds[i]),
            }
            for col in qdf.columns:
                row[f"quantile_{col}"] = float(qdf.iloc[i][col])
            rows.append(row)
        return rows

    preds = np.asarray(model.predict(X_te), dtype=float)
    for ts, pred in zip(X_te.index, preds):
        yt = float(y_te.loc[ts]) if y_te is not None and ts in y_te.index else float("nan")
        rows.append(
            {
                "timestamp": ts,
                "asset": run.asset.value,
                "horizon_id": run.horizon_id.value,
                "head": run.head.value,
                "label_name": run.label_name,
                "run_id": run.run_id,
                "fold_id": -1,
                "y_true": yt,
                "y_prob": np.nan,
                "y_pred": float(pred),
            }
        )
    return rows


def fit_predict_holdout_run(
    cfg: StudyConfig,
    run: TrainingRun,
    *,
    register: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Single final fit on dev; predict hold-out slice. No hold-out rows in fit."""
    reg = register or load_training_register()
    fp = reg.get("feature_policy", {})
    winsor = tuple(fp.get("winsor_percentiles", [1, 99]))
    never_drop = fp.get("never_drop", [])

    X_dev, y_dev = build_training_frame(
        cfg,
        asset=run.asset,
        horizon_id=run.horizon_id.value,
        label_name=run.label_name,
    )
    meta = {
        "run_id": run.run_id,
        "n_train": 0,
        "n_predict": 0,
        "n_features": 0,
        "status": "empty",
    }
    if X_dev.empty or y_dev.empty:
        meta["status"] = "empty"
        meta["error"] = "no dev aligned rows"
        return [], meta

    if run.task == "classification":
        y_dev = y_dev.astype(bool)
        vc = y_dev.value_counts()
        if len(vc) < 2 or vc.min() < 2:
            meta["status"] = "error"
            meta["error"] = "single_class_dev"
            return [], meta
    else:
        y_dev = y_dev.astype(float)

    feature_cols = select_features_for_run(
        cfg, X_dev, asset=run.asset, head=run.head, register=reg
    )
    fold_cols = valid_columns_for_train(
        X_dev, feature_cols, min_valid_frac=0.5, protected=never_drop
    )
    if len(fold_cols) < 3:
        meta["status"] = "error"
        meta["error"] = f"insufficient_features={len(fold_cols)}"
        return [], meta

    scaler = FoldScaler(fold_cols, winsor_percentiles=winsor)
    X_tr, y_tr = scaler.fit_transform(X_dev, y_dev)
    if X_tr.empty or len(X_tr) < 10:
        meta["status"] = "error"
        meta["error"] = "train_too_small"
        return [], meta

    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    feat_ho = load_features_holdout(cfg)
    feat_ho = feat_ho[feat_ho["asset"] == run.asset.value].set_index("timestamp").sort_index()
    X_ho_raw = feat_ho.drop(
        columns=[c for c in feat_ho.columns if c in META_COLS or c == "asset"],
        errors="ignore",
    )
    X_te = scaler.transform(X_ho_raw)
    if X_te.empty:
        meta["status"] = "error"
        meta["error"] = "empty_holdout_after_nan"
        meta["n_train"] = len(X_tr)
        return [], meta

    # No train leakage: dev fit ends before hold-out; predict starts at hold-out.
    assert X_tr.index.max() < holdout
    assert X_te.index.min() >= holdout

    try:
        model = _make_model(cfg, run)
        model.fit(X_tr, y_tr)
    except Exception as exc:
        meta["status"] = "error"
        meta["error"] = str(exc)
        meta["n_train"] = len(X_tr)
        return [], meta

    if run.task == "classification":
        rows = _predict_rows_classification(run, model, X_te, y_te=None)
    elif run.task == "quantile":
        rows = _predict_rows_regression(run, model, X_te, y_te=None, quantile=True)
    else:
        rows = _predict_rows_regression(run, model, X_te, y_te=None, quantile=False)

    meta.update(
        {
            "n_train": len(X_tr),
            "n_predict": len(rows),
            "n_features": len(fold_cols),
            "status": "ok" if rows else "empty",
            "train_end": pd.Timestamp(X_tr.index[-1]).isoformat(),
            "predict_start": pd.Timestamp(X_te.index[0]).isoformat(),
            "predict_end": pd.Timestamp(X_te.index[-1]).isoformat(),
        }
    )
    return rows, meta


def run_holdout_inference(
    cfg: StudyConfig,
    *,
    data_dir: Path,
    smoke: bool = False,
    max_runs: int | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    runs = list_training_runs()
    if smoke:
        runs = [r for r in runs if r.run_id in ("smoke_btc_up_h1", "realized_vol_btc_h1", "quantile_btc_h1")]
    elif max_runs is not None:
        runs = runs[:max_runs]

    all_rows: list[dict[str, Any]] = []
    run_meta: list[dict[str, Any]] = []
    for i, run in enumerate(runs, 1):
        log.info("Hold-out inference %d/%d: %s", i, len(runs), run.run_id)
        rows, meta = fit_predict_holdout_run(cfg, run)
        run_meta.append(meta)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for col in [f"quantile_q{int(q * 100):02d}" for q in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)]:
            if col not in df.columns:
                df[col] = np.nan

    out_path = data_dir / "holdout_predictions.parquet"
    if not df.empty:
        df.to_parquet(out_path, index=False)
    log.info("Wrote %s (%d rows, %d runs)", out_path, len(df), len(runs))
    return df, run_meta


def holdout_predictions_path(data_dir: Path) -> Path:
    return data_dir / "holdout_predictions.parquet"
