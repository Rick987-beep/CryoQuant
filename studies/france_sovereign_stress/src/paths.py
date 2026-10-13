"""Study-local paths and config loading.

Two kinds of market-data snapshot live under ``input/``:

- ``v5_reference/`` — the frozen 9 Oct 2026 v5 inputs (``reference.stamp``).
- ``snapshots/<stamp>/`` — fresh pulls made by ``run_snapshot.py``.

The *active* stamp picks which one the loaders read. Order of precedence:
``FSS_SNAPSHOT`` environment variable (a stamp, or ``reference``), then
``snapshot.stamp`` in ``config.yaml``, then ``reference.stamp``.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

from cryoquant.study_paths import StudyPaths

ANALYSIS_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ENV = "FSS_SNAPSHOT"


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


def snapshots_dir() -> Path:
    return input_dir() / "snapshots"


def archive_dir(stamp: str) -> Path:
    return ANALYSIS_ROOT / "archive" / stamp


@lru_cache(maxsize=1)
def load_config() -> dict:
    return _sp().load_config()


def reference_stamp() -> str:
    return str(load_config()["reference"]["stamp"])


def active_stamp() -> str:
    env = os.environ.get(SNAPSHOT_ENV, "").strip()
    if env:
        return reference_stamp() if env == "reference" else env
    snap = (load_config().get("snapshot") or {}).get("stamp")
    return str(snap) if snap else reference_stamp()


def is_reference_run() -> bool:
    return active_stamp() == reference_stamp()


def stamp_date(stamp: str) -> date:
    """``"2026-10-12T0935"`` → ``date(2026, 10, 12)``."""
    return date.fromisoformat(stamp.split("T", 1)[0])


def snapshot_data_dir(stamp: str | None = None) -> Path:
    stamp = stamp or active_stamp()
    if stamp == reference_stamp():
        return v5_reference_dir() / "data"
    return snapshots_dir() / stamp / "data"
