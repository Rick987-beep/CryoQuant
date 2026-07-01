"""Load Phase 6 backtest register."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.paths import ANALYSIS_ROOT


def backtest_yaml_path() -> Path:
    return ANALYSIS_ROOT / "backtest.yaml"


def load_backtest_register(path: Path | None = None) -> dict[str, Any]:
    p = path or backtest_yaml_path()
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
