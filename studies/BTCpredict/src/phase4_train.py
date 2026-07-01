"""Phase 4 training — walk-forward fit with fold ledger and baseline parity (Phase 4.5)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor

from cryoquant.models.baselines import NaiveDirectional, NaiveRandomWalk
from cryoquant.models.cv import walk_forward
from cryoquant.models.metrics import compute_metrics, compute_regression_metrics, qlike
from cryoquant.models.tabular import QuantileModel, TabularModel, TabularRegressor
from cryoquant.models.vol_baselines import HAR_RVPredictor

from src.config_models import ModelHeadId, StudyConfig
from src.dataset_build import (
    FoldScaler,
    build_training_frame,
    select_features_for_run,
    valid_columns_for_train,
)
from src.training_register import TrainingRun, load_training_register

log = logging.getLogger(__name__)

ETF_COLS = frozenset({"etf_flow_1d_usd", "etf_flow_5d_usd", "etf_flow_z21"})


@dataclass
class SkippedFold:
    fold_id: int
    reason: str


@dataclass
class FoldLedgerEntry:
    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train: int
    n_test: int
    pos_rate: float | None
    n_features: int
    features: list[str]
    etf_active: bool
    model_metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    metric_delta: dict[str, float]


@dataclass
class RunResult:
    run_id: str
    head: str
    asset: str
    horizon_id: str
    label_name: str
    task: str
    n_oos: int
    feature_count: int
    features: list[str]
    fold_metrics: list[dict[str, float]]
    aggregate_metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    metric_delta: dict[str, float]
    model_id: str
    status: str = "ok"
    error: str | None = None
    fold_ledger: list[FoldLedgerEntry] = field(default_factory=list)
    skipped_folds: list[SkippedFold] = field(default_factory=list)
    folds_scheduled: int = 0
    folds_used: int = 0
    folds_skipped: int = 0
    gates: dict[str, bool] = field(default_factory=dict)


def _lgbm_kwargs(params) -> dict[str, Any]:
    return {
        "n_estimators": params.n_estimators,
        "max_depth": params.max_depth,
        "num_leaves": params.num_leaves,
        "min_child_samples": params.min_child_samples,
        "learning_rate": params.learning_rate,
        "subsample": params.subsample,
        "colsample_bytree": params.colsample_bytree,
        "reg_alpha": params.reg_alpha,
        "reg_lambda": params.reg_lambda,
        "verbose": -1,
    }


def _make_model(cfg: StudyConfig, run: TrainingRun):
    if cfg.phase4 is None:
        raise ValueError("phase4 section missing from config.yaml")
    seed = cfg.random_seed
    p4 = cfg.phase4

    if run.head == ModelHeadId.DIRECTIONAL:
        est = LGBMClassifier(**_lgbm_kwargs(p4.lgbm_classifier), random_state=seed)
        return TabularModel(estimator=est, calibration_cv=3)
    if run.head == ModelHeadId.LOG_RETURN_BENCH or run.head == ModelHeadId.REALIZED_VOL:
        est = LGBMRegressor(**_lgbm_kwargs(p4.lgbm_regressor), random_state=seed)
        return TabularRegressor(estimator=est, random_state=seed)
    if run.head == ModelHeadId.DISTRIBUTIONAL:
        q = load_training_register()["heads"]["quantile"]["quantiles"]
        return QuantileModel(
            quantiles=tuple(q),
            lgbm_params=_lgbm_kwargs(p4.lgbm_quantile),
            random_state=seed,
        )
    raise ValueError(f"Unknown head {run.head}")


def _baseline_model(run: TrainingRun, rv_col: str | None, train_y: pd.Series | None = None):
    if run.head == ModelHeadId.DIRECTIONAL:
        return NaiveDirectional()
    if run.head == ModelHeadId.LOG_RETURN_BENCH:
        return NaiveRandomWalk()
    if run.head == ModelHeadId.REALIZED_VOL:
        return HAR_RVPredictor(rv_col=rv_col)
    return NaiveRandomWalk()


def _historical_quantile_baseline(
    y_train: pd.Series, y_test: pd.Series, quantiles: tuple[float, ...]
) -> pd.DataFrame:
    """Naive baseline: train-set quantiles as constant predictions."""
    cols = {}
    for q in quantiles:
        cols[f"q{int(round(q * 100)):02d}"] = np.full(
            len(y_test), float(y_train.quantile(q)), dtype=float
        )
    return pd.DataFrame(cols, index=y_test.index)


def _aggregate_metrics(folds: list[dict[str, float]]) -> dict[str, float]:
    if not folds:
        return {}
    keys = folds[0].keys()
    out: dict[str, float] = {}
    for k in keys:
        vals = [f[k] for f in folds if k in f and np.isfinite(f[k])]
        out[k] = float(np.mean(vals)) if vals else float("nan")
    return out


def _primary_delta(
    head: str, model: dict[str, float], base: dict[str, float]
) -> dict[str, float]:
    if head == "directional":
        m, b = model.get("auc", float("nan")), base.get("auc", float("nan"))
        return {"auc_delta": float(m - b) if np.isfinite(m) and np.isfinite(b) else float("nan")}
    if head == "log_return_bench":
        m, b = model.get("mae", float("nan")), base.get("mae", float("nan"))
        return {"mae_improvement": float(b - m) if np.isfinite(m) and np.isfinite(b) else float("nan")}
    if head == "realized_vol":
        m = model.get("qlike", model.get("mae", float("nan")))
        b = base.get("qlike", base.get("mae", float("nan")))
        return {"qlike_improvement": float(b - m) if np.isfinite(m) and np.isfinite(b) else float("nan")}
    if head == "distributional":
        m = model.get("pinball_loss", float("nan"))
        return {"pinball_loss": m}
    return {}


def _compute_gates(head: str, agg: dict[str, float], base: dict[str, float]) -> dict[str, bool]:
    gates: dict[str, bool] = {"has_baseline": bool(base)}
    if head == "directional":
        auc = agg.get("auc", float("nan"))
        gates["auc_above_floor"] = bool(np.isfinite(auc) and auc > 0.52)
        gates["auc_below_ceiling"] = bool(np.isfinite(auc) and auc <= 0.60)
        b_auc = base.get("auc", float("nan"))
        gates["beats_baseline"] = bool(
            np.isfinite(auc) and np.isfinite(b_auc) and auc >= b_auc
        )
    elif head == "log_return_bench":
        m_mae, b_mae = agg.get("mae"), base.get("mae")
        gates["beats_baseline"] = bool(
            np.isfinite(m_mae) and np.isfinite(b_mae) and m_mae < b_mae
        )
        r2 = agg.get("r2", float("nan"))
        gates["r2_sane"] = bool(not np.isfinite(r2) or r2 <= 0.20)
    elif head == "realized_vol":
        m = agg.get("qlike", agg.get("mae"))
        b = base.get("qlike", base.get("mae"))
        gates["beats_baseline"] = bool(np.isfinite(m) and np.isfinite(b) and m < b)
    elif head == "distributional":
        gates["beats_baseline"] = bool(np.isfinite(agg.get("pinball_loss", float("nan"))))
    return gates


def _etf_active(cols: list[str], X_slice: pd.DataFrame) -> bool:
    present = [c for c in cols if c in ETF_COLS and c in X_slice.columns]
    if not present:
        return False
    return bool(X_slice[present].notna().any().any())


def _baseline_metrics_fold(
    run: TrainingRun,
    X_tr: pd.DataFrame,
    y_tr: pd.Series,
    X_te: pd.DataFrame,
    y_te: pd.Series,
    rv_col: str | None,
    quantiles: tuple[float, ...] | None = None,
) -> dict[str, float]:
    if run.task == "quantile" and quantiles:
        qdf = _historical_quantile_baseline(y_tr, y_te, quantiles)
        preds = qdf[f"q{50:02d}"] if f"q{50:02d}" in qdf.columns else qdf.iloc[:, len(qdf.columns) // 2]
        return compute_regression_metrics(y_te, preds.to_numpy(), quantile_preds=qdf)

    base = _baseline_model(run, rv_col)
    base.fit(X_tr, y_tr)
    if run.task == "classification":
        probs = base.predict_proba(X_te)
        return compute_metrics(y_te.astype(bool), probs)
    preds = base.predict(X_te)
    m = compute_regression_metrics(y_te, preds)
    if run.head == ModelHeadId.REALIZED_VOL:
        m["qlike"] = qlike(y_te, preds)
    return m


def _walk_forward_with_ledger(
    cfg: StudyConfig,
    run: TrainingRun,
    X: pd.DataFrame,
    y: pd.Series,
    feature_cols: list[str],
    register: dict,
    *,
    embargo_bars: int | None = None,
) -> tuple[list[FoldLedgerEntry], list[SkippedFold], pd.DataFrame, int]:
    fp = register.get("feature_policy", {})
    winsor = tuple(fp.get("winsor_percentiles", [1, 99]))
    never_drop = fp.get("never_drop", [])

    if run.task == "classification":
        y = y.astype(bool)
    else:
        y = y.astype(float)

    aligned = pd.concat([X, y.rename("_y")], axis=1).dropna(subset=["_y"])
    X_all = aligned.drop(columns=["_y"])
    y_all = aligned["_y"]

    wf = cfg.walk_forward
    emb = wf.embargo_bars if embargo_bars is None else embargo_bars
    n = len(aligned)
    splits = list(walk_forward(n, wf.train_window_bars, wf.test_window_bars, step=wf.step_bars))
    scheduled = len(splits)

    ledger: list[FoldLedgerEntry] = []
    skipped: list[SkippedFold] = []
    oos_rows: list[dict] = []

    prefix = run.asset.value.lower()
    rv_col = f"{prefix}_rv_24"
    quantiles = None
    if run.head == ModelHeadId.DISTRIBUTIONAL:
        quantiles = tuple(load_training_register()["heads"]["quantile"]["quantiles"])

    for fold_id, (train_idx, test_idx) in enumerate(splits):
        if emb > 0:
            train_idx = train_idx[train_idx < int(test_idx[0]) - emb]
            if len(train_idx) == 0:
                skipped.append(SkippedFold(fold_id, "embargo_empty_train"))
                continue

        fold_cols = valid_columns_for_train(
            X_all.iloc[train_idx],
            feature_cols,
            min_valid_frac=0.5,
            protected=never_drop,
        )
        if len(fold_cols) < 3:
            skipped.append(SkippedFold(fold_id, f"insufficient_features={len(fold_cols)}"))
            continue

        scaler = FoldScaler(fold_cols, winsor_percentiles=winsor)
        X_tr, y_tr = scaler.fit_transform(X_all.iloc[train_idx], y_all.iloc[train_idx])
        if X_tr.empty or len(X_tr) < 10:
            skipped.append(SkippedFold(fold_id, "train_too_small_after_nan"))
            continue

        if run.task == "classification":
            vc = y_tr.value_counts()
            if len(vc) < 2 or vc.min() < 2:
                skipped.append(SkippedFold(fold_id, "single_class_train"))
                continue

        X_te_raw = X_all.iloc[test_idx]
        y_te_raw = y_all.iloc[test_idx]
        X_te = scaler.transform(X_te_raw)
        if X_te.empty:
            skipped.append(SkippedFold(fold_id, "empty_test_after_nan"))
            continue
        y_te = y_te_raw.loc[X_te.index]
        if len(X_te) < 1:
            skipped.append(SkippedFold(fold_id, "no_test_rows"))
            continue

        # Baseline on same raw feature rows (unscaled) as model fold
        X_tr_raw = X_all.loc[X_tr.index, fold_cols].astype(float)
        X_te_raw_aligned = X_all.loc[X_te.index, fold_cols].astype(float)

        try:
            base_m = _baseline_metrics_fold(
                run, X_tr_raw, y_tr, X_te_raw_aligned, y_te, rv_col, quantiles
            )
            model = _make_model(cfg, run)
            model.fit(X_tr, y_tr)
        except Exception as exc:
            skipped.append(SkippedFold(fold_id, f"fit_error={exc!s}"))
            continue

        pos_rate = float(y_tr.mean()) if run.task == "classification" else None
        etf_on = _etf_active(fold_cols, X_tr_raw)

        if run.task == "classification":
            probs = np.asarray(model.predict_proba(X_te), dtype=float)
            model_m = compute_metrics(y_te, probs)
            for ts, prob, yt in zip(X_te.index, probs, y_te):
                oos_rows.append(
                    {
                        "timestamp": ts,
                        "asset": run.asset.value,
                        "horizon_id": run.horizon_id.value,
                        "head": run.head.value,
                        "label_name": run.label_name,
                        "run_id": run.run_id,
                        "fold_id": fold_id,
                        "y_true": float(yt),
                        "y_prob": float(prob),
                        "y_pred": np.nan,
                    }
                )
        elif run.task == "quantile":
            qdf = model.predict_quantiles(X_te)
            preds = model.predict(X_te)
            model_m = compute_regression_metrics(y_te, preds, quantile_preds=qdf)
            for i, ts in enumerate(X_te.index):
                row = {
                    "timestamp": ts,
                    "asset": run.asset.value,
                    "horizon_id": run.horizon_id.value,
                    "head": run.head.value,
                    "label_name": run.label_name,
                    "run_id": run.run_id,
                    "fold_id": fold_id,
                    "y_true": float(y_te.loc[ts]),
                    "y_prob": np.nan,
                    "y_pred": float(preds[i]),
                }
                for col in qdf.columns:
                    row[f"quantile_{col}"] = float(qdf.iloc[i][col])
                oos_rows.append(row)
        else:
            preds = np.asarray(model.predict(X_te), dtype=float)
            model_m = compute_regression_metrics(y_te, preds)
            if run.head == ModelHeadId.REALIZED_VOL:
                model_m["qlike"] = qlike(y_te, preds)
            for ts, pred, yt in zip(X_te.index, preds, y_te):
                oos_rows.append(
                    {
                        "timestamp": ts,
                        "asset": run.asset.value,
                        "horizon_id": run.horizon_id.value,
                        "head": run.head.value,
                        "label_name": run.label_name,
                        "run_id": run.run_id,
                        "fold_id": fold_id,
                        "y_true": float(yt),
                        "y_prob": np.nan,
                        "y_pred": float(pred),
                    }
                )

        delta = _primary_delta(run.head.value, model_m, base_m)
        ledger.append(
            FoldLedgerEntry(
                fold_id=fold_id,
                train_start=pd.Timestamp(X_tr.index[0]).isoformat(),
                train_end=pd.Timestamp(X_tr.index[-1]).isoformat(),
                test_start=pd.Timestamp(X_te.index[0]).isoformat(),
                test_end=pd.Timestamp(X_te.index[-1]).isoformat(),
                n_train=len(X_tr),
                n_test=len(X_te),
                pos_rate=pos_rate,
                n_features=len(fold_cols),
                features=fold_cols,
                etf_active=etf_on,
                model_metrics=model_m,
                baseline_metrics=base_m,
                metric_delta=delta,
            )
        )

    return ledger, skipped, pd.DataFrame(oos_rows), scheduled


def run_training_run(
    cfg: StudyConfig,
    run: TrainingRun,
    *,
    y_override: pd.Series | None = None,
    X_override: pd.DataFrame | None = None,
    embargo_bars: int | None = None,
) -> tuple[RunResult, pd.DataFrame]:
    register = load_training_register()
    X, y = build_training_frame(
        cfg,
        asset=run.asset,
        horizon_id=run.horizon_id.value,
        label_name=run.label_name,
    )
    empty_result = RunResult(
        run_id=run.run_id,
        head=run.head.value,
        asset=run.asset.value,
        horizon_id=run.horizon_id.value,
        label_name=run.label_name,
        task=run.task,
        n_oos=0,
        feature_count=0,
        features=[],
        fold_metrics=[],
        aggregate_metrics={},
        baseline_metrics={},
        metric_delta={},
        model_id="",
        status="empty",
    )

    if X.empty or y.empty:
        empty_result.error = "no aligned rows"
        return empty_result, pd.DataFrame()

    y_fit = y_override if y_override is not None else y
    X_fit = X_override if X_override is not None else X
    if y_override is not None or X_override is not None:
        aligned_idx = X_fit.index.intersection(y_fit.dropna().index)
        X_fit = X_fit.loc[aligned_idx]
        y_fit = y_fit.loc[aligned_idx]

    wf = cfg.walk_forward
    emb = wf.embargo_bars if embargo_bars is None else embargo_bars
    n = len(y_fit)
    first_splits = list(
        walk_forward(n, wf.train_window_bars, wf.test_window_bars, step=wf.step_bars)
    )
    if not first_splits:
        empty_result.error = "insufficient data for walk-forward"
        return empty_result, pd.DataFrame()

    train_idx = first_splits[0][0]
    if emb > 0:
        test_idx = first_splits[0][1]
        train_idx = train_idx[train_idx < int(test_idx[0]) - emb]

    feature_cols = select_features_for_run(
        cfg, X_fit.iloc[train_idx], asset=run.asset, head=run.head, register=register
    )

    try:
        ledger, skipped, oos_df, scheduled = _walk_forward_with_ledger(
            cfg,
            run,
            X_fit,
            y_fit,
            feature_cols,
            register,
            embargo_bars=embargo_bars,
        )
        fold_metrics = [e.model_metrics for e in ledger]
        base_folds = [e.baseline_metrics for e in ledger]
        agg = _aggregate_metrics(fold_metrics)
        base_agg = _aggregate_metrics(base_folds)
        delta = _primary_delta(run.head.value, agg, base_agg)
        model = _make_model(cfg, run)

        return (
            RunResult(
                run_id=run.run_id,
                head=run.head.value,
                asset=run.asset.value,
                horizon_id=run.horizon_id.value,
                label_name=run.label_name,
                task=run.task,
                n_oos=len(oos_df),
                feature_count=len(feature_cols),
                features=feature_cols,
                fold_metrics=fold_metrics,
                aggregate_metrics=agg,
                baseline_metrics=base_agg,
                metric_delta=delta,
                model_id=model.model_id,
                status="ok" if ledger else "empty",
                error=None if ledger else "no folds completed",
                fold_ledger=ledger,
                skipped_folds=skipped,
                folds_scheduled=scheduled,
                folds_used=len(ledger),
                folds_skipped=len(skipped),
                gates=_compute_gates(run.head.value, agg, base_agg),
            ),
            oos_df,
        )
    except Exception as exc:
        log.exception("Run %s failed", run.run_id)
        return (
            RunResult(
                run_id=run.run_id,
                head=run.head.value,
                asset=run.asset.value,
                horizon_id=run.horizon_id.value,
                label_name=run.label_name,
                task=run.task,
                n_oos=0,
                feature_count=len(feature_cols),
                features=feature_cols,
                fold_metrics=[],
                aggregate_metrics={},
                baseline_metrics={},
                metric_delta={},
                model_id="",
                status="error",
                error=str(exc),
            ),
            pd.DataFrame(),
        )


def run_result_to_dict(r: RunResult) -> dict[str, Any]:
    d = asdict(r)
    d["fold_ledger"] = [asdict(e) for e in r.fold_ledger]
    d["skipped_folds"] = [asdict(s) for s in r.skipped_folds]
    return d


def write_training_manifest(
    results: list[RunResult],
    path: Path,
    *,
    reproducibility: dict[str, Any],
    session_id: str,
) -> None:
    payload = {
        "version": 2,
        "session_id": session_id,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "run_count": len(results),
        "reproducibility": reproducibility,
        "runs": [run_result_to_dict(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
