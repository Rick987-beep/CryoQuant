"""Load Phase 5 validation register."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.paths import ANALYSIS_ROOT


def validation_yaml_path() -> Path:
    return ANALYSIS_ROOT / "validation.yaml"


def load_validation_register(path: Path | None = None) -> dict[str, Any]:
    p = path or validation_yaml_path()
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
