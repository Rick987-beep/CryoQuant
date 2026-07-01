"""Reproducibility metadata for training runs — study wrapper."""
from __future__ import annotations

from typing import Any

from cryoquant.reporting.repro import build_repro_bundle as _build_repro_bundle
from cryoquant.reporting.repro import repro_bundle_complete as _repro_bundle_complete

from src.config_models import StudyConfig
from src.paths import ANALYSIS_ROOT, config_path, data_dir
from src.training_register import training_yaml_path


def build_repro_bundle(cfg: StudyConfig) -> dict[str, Any]:
    """Hashes + git commit for BTCpredict replay audit."""
    dd = data_dir()
    files = {
        "config.yaml": config_path(),
        "training.yaml": training_yaml_path(),
        "features_schema.json": dd / "features_schema.json",
        "labels_schema.json": dd / "labels_schema.json",
        "features.parquet": dd / "features.parquet",
        "labels.parquet": dd / "labels.parquet",
    }
    return _build_repro_bundle(
        files=files,
        metadata={
            "study_id": cfg.study_id,
            "random_seed": cfg.random_seed,
            "holdout_start": str(cfg.splits.holdout_start),
            "dev_end": str(cfg.splits.dev_end),
        },
        repo_root=ANALYSIS_ROOT.parent.parent,
    )


def repro_bundle_complete(bundle: dict[str, Any]) -> bool:
    return _repro_bundle_complete(
        bundle,
        required_files=("config.yaml", "training.yaml", "features_schema.json", "labels_schema.json"),
    )
