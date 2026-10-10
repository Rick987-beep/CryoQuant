"""Study-local paths and config loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from cryoquant.study_paths import StudyPaths

ANALYSIS_ROOT = Path(__file__).resolve().parents[1]


def _sp() -> StudyPaths:
    return StudyPaths(ANALYSIS_ROOT)


def config_path() -> Path:
    return _sp().config_path()


def data_dir() -> Path:
    return _sp().data_dir()


def reports_dir() -> Path:
    return _sp().reports_dir()


def input_dir() -> Path:
    return _sp().input_dir()


def v5_reference_dir() -> Path:
    return input_dir() / "v5_reference"


@lru_cache(maxsize=1)
def load_config() -> dict:
    return _sp().load_config()
