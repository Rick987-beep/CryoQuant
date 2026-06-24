"""Analysis-local paths and config loading."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ANALYSIS_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def load_config() -> dict:
    with (ANALYSIS_ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def data_dir() -> Path:
    d = ANALYSIS_ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reports_dir() -> Path:
    d = ANALYSIS_ROOT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundles_dir() -> Path:
    d = reports_dir() / "bundles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cdx_clean_csv_path() -> Path:
    rel = load_config()["data"]["cdx_clean_csv"]
    return ANALYSIS_ROOT / rel
