"""Study-local paths and config loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

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


def variant_data_dir(variant: str) -> Path:
    d = data_dir() / variant
    d.mkdir(parents=True, exist_ok=True)
    return d


def variant_reports_dir(variant: str) -> Path:
    d = reports_dir() / variant
    d.mkdir(parents=True, exist_ok=True)
    return d


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(config_path()) as f:
        return yaml.safe_load(f)
