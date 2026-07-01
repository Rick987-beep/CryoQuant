"""Load Phase 7 hold-out register."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.paths import ANALYSIS_ROOT


def holdout_yaml_path() -> Path:
    return ANALYSIS_ROOT / "holdout.yaml"


def load_holdout_register(path: Path | None = None) -> dict[str, Any]:
    p = path or holdout_yaml_path()
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
