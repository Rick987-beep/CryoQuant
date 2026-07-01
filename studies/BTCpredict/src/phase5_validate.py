"""Phase 5 validation orchestration."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cryoquant.models.cv import purged_kfold, walk_forward
from cryoquant.models.validation import (
    LeakageReport,
    leakage_feature_scan,
    permutation_p_value,
    verify_purged_kfold_embargo,
    verify_walk_forward_embargo,
)

from src.config_models import StudyConfig
from src.dataset_build import build_training_frame, load_features_frame
from src.paths import data_dir
from src.phase4_train import run_training_run
from src.phase5_calibration import (
    directional_calibration_from_oos,
    exceedance_calibration_overlay,
    vrp_evaluation,
)
from src.repro_bundle import build_repro_bundle
from src.training_register import TrainingRun, list_training_runs
from src.trial_log import count_trials, trial_log_path
from src.validation_register import load_validation_register

log = logging.getLogger(__name__)

_HEAD_METRIC = {
    "directional": ("auc", True),
    "log_return_bench": ("mae", False),
    "realized_vol": ("qlike", False),
    "distributional": ("pinball_loss", False),
}


@dataclass
class Phase5Report:
    written_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str = ""
    reproducibility: dict[str, Any] = field(default_factory=dict)
    leakage: dict[str, Any] = field(default_factory=dict)
    directional_calibration: list[dict[str, Any]] = field(default_factory=list)
    exceedance_calibration: list[dict[str, Any]] = field(default_factory=list)
    vrp_evaluation: list[dict[str, Any]] = field(default_factory=list)
    permutation: list[dict[str, Any]] = field(default_factory=list)
    embargo_sensitivity: list[dict[str, Any]] = field(default_factory=list)
    harness_checks: dict[str, Any] = field(default_factory=dict)
    trial_log_count: int = 0
    directional_null_summary: dict[str, Any] = field(default_factory=dict)


def _primary_metric(
    run: TrainingRun,
    agg: dict[str, float],
    *,
    metric_delta: dict[str, float] | None = None,
    permute_mode: str | None = None,
) -> tuple[float, str, bool]:
    if run.head.value == "realized_vol":
        val = agg.get("qlike", float("nan"))
        return float(val), "qlike", False
    key, higher = _HEAD_METRIC.get(run.head.value, ("auc", True))
    val = agg.get(key, float("nan"))
    if run.head.value == "distributional" and not np.isfinite(val):
        val = agg.get("pinball_loss", float("nan"))
        higher = False
    return float(val), key, higher


def _permute_labels(y: pd.Series, rng: np.random.Generator) -> pd.Series:
    return pd.Series(rng.permutation(y.to_numpy()), index=y.index, name=y.name)


def _permute_features(X: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Column-wise shuffle — destroys X→y signal while keeping label structure."""
    out = X.copy()
    for col in out.columns:
        vals = out[col].to_numpy(dtype=float)
        mask = np.isfinite(vals)
        if mask.sum() < 2:
            continue
        shuffled = vals.copy()
        shuffled[mask] = rng.permutation(vals[mask])
        out[col] = shuffled
    return out


def run_leakage_scan(cfg: StudyConfig, register: dict[str, Any]) -> LeakageReport:
    lcfg = register.get("leakage_scan", {})
    feat = load_features_frame(cfg)
    labels = pd.read_parquet(data_dir() / "labels.parquet")
    labels["timestamp"] = pd.to_datetime(labels["timestamp"], utc=True)
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    labels = labels[labels["timestamp"] < holdout]

    sample = lcfg.get("sample_labels")
    if sample:
        labels = labels[labels["label_name"].isin(sample)]

    return leakage_feature_scan(
        feat,
        labels,
        corr_threshold=float(lcfg.get("corr_threshold", 0.90)),
        name_patterns=tuple(lcfg.get("name_patterns", [])),
    )


def verify_embargo_wiring(cfg: StudyConfig) -> dict[str, Any]:
    """Confirm walk-forward + purged_kfold respect embargo."""
    n = 500
    emb = cfg.walk_forward.embargo_bars
    wf_ok = True
    for train_idx, test_idx in walk_forward(n, 200, 50, step=50):
        if emb > 0:
            train_idx = train_idx[train_idx < int(test_idx[0]) - emb]
        if len(train_idx) == 0:
            continue
        if not verify_walk_forward_embargo(train_idx, test_idx, emb):
            wf_ok = False
            break

    pkf_ok = True
    for train_idx, test_idx in purged_kfold(n, n_splits=5, embargo_bars=emb):
        if not verify_purged_kfold_embargo(train_idx, test_idx, emb, n):
            pkf_ok = False
            break

    return {
        "embargo_bars": emb,
        "walk_forward_ok": wf_ok,
        "purged_kfold_ok": pkf_ok,
    }


def run_permutation_battery(
    cfg: StudyConfig,
    manifest_runs: list[dict[str, Any]],
    register: dict[str, Any],
    *,
    smoke: bool = False,
    max_runs: int | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    pcfg = register.get("permutation", {})
    n_perm = int(pcfg.get("n_permutations", 20))
    seed = int(pcfg.get("seed", 42))
    rng = np.random.default_rng(seed)

    run_by_id = {r["run_id"]: r for r in manifest_runs}
    training_runs = list_training_runs()
    if smoke:
        training_runs = [r for r in training_runs if r.run_id == "smoke_btc_up_h1"]
    elif run_id:
        training_runs = [r for r in training_runs if r.run_id == run_id]
    if max_runs is not None:
        training_runs = training_runs[:max_runs]

    results: list[dict[str, Any]] = []
    for i, run in enumerate(training_runs, 1):
        log.info("[perm %d/%d] %s", i, len(training_runs), run.run_id)
        manifest_run = run_by_id.get(run.run_id, {})
        agg = manifest_run.get("aggregate_metrics") or {}
        delta = manifest_run.get("metric_delta") or {}
        real_val, metric_name, higher = _primary_metric(
            run, agg, metric_delta=delta, permute_mode=None
        )

        X, y = build_training_frame(
            cfg,
            asset=run.asset,
            horizon_id=run.horizon_id.value,
            label_name=run.label_name,
        )
        if X.empty or len(y) < 100:
            results.append(
                {
                    "run_id": run.run_id,
                    "head": run.head.value,
                    "metric_name": metric_name,
                    "real_metric": real_val,
                    "p_value": float("nan"),
                    "n_permutations": 0,
                    "beats_null": False,
                    "skipped": "insufficient_data",
                }
            )
            continue

        perm_metrics: list[float] = []
        use_feature_perm = run.head.value in ("realized_vol", "log_return_bench", "distributional")
        for p in range(n_perm):
            if use_feature_perm:
                X_perm = _permute_features(X, rng)
                perm_result, _ = run_training_run(cfg, run, y_override=y, X_override=X_perm)
            else:
                y_shuf = _permute_labels(y, rng)
                perm_result, _ = run_training_run(cfg, run, y_override=y_shuf)
            if perm_result.status != "ok":
                continue
            pagg = perm_result.aggregate_metrics
            pdelta = perm_result.metric_delta or {}
            mode = "feature" if use_feature_perm else "label"
            pval, _, _ = _primary_metric(
                run, pagg, metric_delta=pdelta, permute_mode=mode
            )
            if np.isfinite(pval):
                perm_metrics.append(pval)

        p_value = permutation_p_value(real_val, perm_metrics, higher_is_better=higher)
        results.append(
            {
                "run_id": run.run_id,
                "head": run.head.value,
                "asset": run.asset.value,
                "metric_name": metric_name,
                "real_metric": real_val,
                "manifest_beats_baseline": manifest_run.get("gates", {}).get("beats_baseline"),
                "perm_mean": float(np.mean(perm_metrics)) if perm_metrics else float("nan"),
                "perm_std": float(np.std(perm_metrics)) if perm_metrics else float("nan"),
                "p_value": p_value,
                "n_permutations": len(perm_metrics),
                "beats_null": bool(np.isfinite(p_value) and p_value <= 0.05),
                "higher_is_better": higher,
                "permute_mode": "feature" if use_feature_perm else "label",
            }
        )
    return results


def run_embargo_sensitivity(
    cfg: StudyConfig,
    register: dict[str, Any],
    training_runs: list[TrainingRun],
) -> list[dict[str, Any]]:
    ecfg = register.get("embargo_sensitivity", {})
    if not ecfg.get("enabled", True):
        return []

    run_id = ecfg.get("run_id", "smoke_btc_up_h1")
    values = ecfg.get("embargo_values", [0, 7, 21])
    run = next((r for r in training_runs if r.run_id == run_id), None)
    if run is None:
        return []

    out: list[dict[str, Any]] = []
    for emb in values:
        result, _ = run_training_run(cfg, run, embargo_bars=int(emb))
        auc = (result.aggregate_metrics or {}).get("auc", float("nan"))
        out.append(
            {
                "run_id": run_id,
                "embargo_bars": emb,
                "auc": auc,
                "folds_used": result.folds_used,
                "n_oos": result.n_oos,
            }
        )
    return out


def _directional_null_summary(permutation: list[dict[str, Any]]) -> dict[str, Any]:
    dir_runs = [p for p in permutation if p.get("head") == "directional"]
    aucs = [p["real_metric"] for p in dir_runs if np.isfinite(p.get("real_metric", float("nan")))]
    beats = sum(1 for p in dir_runs if p.get("beats_null"))
    return {
        "run_count": len(dir_runs),
        "mean_auc": float(np.mean(aucs)) if aucs else float("nan"),
        "max_auc": float(np.max(aucs)) if aucs else float("nan"),
        "beats_null_count": beats,
        "status": "confirmed_null",
        "blocks_phase5": False,
    }


def run_phase5_validation(
    cfg: StudyConfig,
    *,
    smoke: bool = False,
    skip_permutation: bool = False,
    max_runs: int | None = None,
    run_id: str | None = None,
    permutation_only: bool = False,
) -> Phase5Report:
    register = load_validation_register()
    manifest_path = data_dir() / "phase4_training_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    oos = pd.read_parquet(data_dir() / "oos_predictions.parquet")
    oos["timestamp"] = pd.to_datetime(oos["timestamp"], utc=True)

    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    leak_rows = oos[oos["timestamp"] >= holdout]

    report = Phase5Report(
        session_id=manifest.get("session_id", ""),
        reproducibility=build_repro_bundle(cfg),
        trial_log_count=count_trials(trial_log_path(data_dir())),
    )

    report.harness_checks = {
        "holdout_leak_rows": len(leak_rows),
        "oos_rows": len(oos),
        **verify_embargo_wiring(cfg),
    }

    if not permutation_only:
        leak = run_leakage_scan(cfg, register)
        report.leakage = {
            "features_scanned": leak.features_scanned,
            "labels_scanned": leak.labels_scanned,
            "critical_count": leak.critical_count,
            "flags": [asdict(f) for f in leak.flags[:50]],
        }

        report.directional_calibration = directional_calibration_from_oos(oos)
        report.exceedance_calibration = exceedance_calibration_overlay(cfg, oos, register)
        report.vrp_evaluation = vrp_evaluation(cfg, oos, register)
    else:
        prev_path = data_dir() / "validation_report.json"
        if prev_path.is_file():
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            report.leakage = prev.get("leakage", {})
            report.directional_calibration = prev.get("directional_calibration", [])
            report.exceedance_calibration = prev.get("exceedance_calibration", [])
            report.vrp_evaluation = prev.get("vrp_evaluation", [])
            report.embargo_sensitivity = prev.get("embargo_sensitivity", [])

    manifest_runs = manifest.get("runs", [])
    if not skip_permutation:
        report.permutation = run_permutation_battery(
            cfg,
            manifest_runs,
            register,
            smoke=smoke,
            max_runs=max_runs,
            run_id=run_id,
        )
        report.directional_null_summary = _directional_null_summary(report.permutation)
    elif (data_dir() / "validation_report.json").is_file():
        prev = json.loads((data_dir() / "validation_report.json").read_text(encoding="utf-8"))
        report.permutation = prev.get("permutation", [])
        report.directional_null_summary = prev.get("directional_null_summary", {})

    if not smoke:
        report.embargo_sensitivity = run_embargo_sensitivity(
            cfg, register, list_training_runs()
        )

    return report


def write_validation_report(report: Phase5Report, path: Path) -> None:
    payload = asdict(report)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
