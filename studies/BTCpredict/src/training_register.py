"""Load Phase 4 training register and enumerate training runs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

from src.config_models import AssetId, HorizonId, ModelHeadId
from src.paths import ANALYSIS_ROOT


@dataclass(frozen=True)
class TrainingRun:
    run_id: str
    head: ModelHeadId
    asset: AssetId
    horizon_id: HorizonId
    label_base: str
    label_name: str
    task: str  # classification | regression | quantile


_HORIZON_SUFFIX = {
    HorizonId.H1: "h1",
    HorizonId.H5: "h5",
    HorizonId.H21: "h14",
}


def training_yaml_path() -> Path:
    return ANALYSIS_ROOT / "training.yaml"


def load_training_register(path: Path | None = None) -> dict[str, Any]:
    p = path or training_yaml_path()
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _label_name(base: str, horizon_id: HorizonId) -> str:
    suffix = _HORIZON_SUFFIX[horizon_id]
    if base in ("log_return", "fwd_rv"):
        return f"{base}_{suffix}"
    return f"{base}_{suffix}"


def iter_training_runs(register: dict[str, Any] | None = None) -> Iterator[TrainingRun]:
    """Yield all 48 training runs in train_order."""
    reg = register or load_training_register()
    horizons = [HorizonId(h["id"]) for h in reg["horizons"]]

    # Smoke first
    for step in reg.get("train_order", []):
        if step.get("id") == "smoke_btc_up_h1":
            hid = HorizonId(step["horizon_id"])
            base = step["label"]
            yield TrainingRun(
                run_id=step["id"],
                head=ModelHeadId.DIRECTIONAL,
                asset=AssetId(step["asset"]),
                horizon_id=hid,
                label_base=base,
                label_name=_label_name(base, hid),
                task="classification",
            )

    # Directional (remaining)
    dir_cfg = reg["directional"]
    for asset_name, spec in dir_cfg.items():
        if asset_name == "rationale":
            continue
        if not isinstance(spec, dict) or "labels" not in spec:
            continue
        asset = AssetId(asset_name)
        for base in spec["labels"]:
            for hid in horizons:
                run_id = f"dir_{asset.value.lower()}_{base}_{_HORIZON_SUFFIX[hid]}"
                if run_id == "dir_btc_up_win_volscaled_h1":
                    continue  # smoke already
                yield TrainingRun(
                    run_id=run_id,
                    head=ModelHeadId.DIRECTIONAL,
                    asset=asset,
                    horizon_id=hid,
                    label_base=base,
                    label_name=_label_name(base, hid),
                    task="classification",
                )

    for head_key, model_head, base, task in (
        ("log_return_bench", ModelHeadId.LOG_RETURN_BENCH, "log_return", "regression"),
        ("realized_vol", ModelHeadId.REALIZED_VOL, "fwd_rv", "regression"),
        ("quantile", ModelHeadId.DISTRIBUTIONAL, "log_return", "quantile"),
    ):
        head_spec = reg["heads"][head_key]
        for asset_name in head_spec["assets"]:
            asset = AssetId(asset_name)
            for hid in horizons:
                suffix = _HORIZON_SUFFIX[hid]
                yield TrainingRun(
                    run_id=f"{head_key}_{asset.value.lower()}_{suffix}",
                    head=model_head,
                    asset=asset,
                    horizon_id=hid,
                    label_base=base,
                    label_name=_label_name(base, hid),
                    task=task,
                )


def list_training_runs(register: dict[str, Any] | None = None) -> list[TrainingRun]:
    return list(iter_training_runs(register))
