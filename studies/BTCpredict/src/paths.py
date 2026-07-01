"""Analysis-local paths and config loading entrypoint."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ANALYSIS_ROOT = Path(__file__).resolve().parents[1]


def config_path() -> Path:
    return ANALYSIS_ROOT / "config.yaml"


def data_dir() -> Path:
    d = ANALYSIS_ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reports_dir() -> Path:
    d = ANALYSIS_ROOT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def splits_path() -> Path:
    return data_dir() / "splits.json"


@lru_cache(maxsize=1)
def load_study_config():
    """Load and validate study config from config.yaml."""
    from src.config_models import load_study_config as _load

    return _load(config_path())
