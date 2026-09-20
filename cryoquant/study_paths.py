"""Shared study directory layout helpers.

Studies keep a thin ``paths.py`` that constructs ``StudyPaths`` from their
``ANALYSIS_ROOT``; hypothesis-specific paths stay local.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class StudyPaths:
    """Standard layout under ``studies/<name>/``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def config_path(self) -> Path:
        return self.root / "config.yaml"

    def data_dir(self) -> Path:
        d = self.root / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def reports_dir(self) -> Path:
        d = self.root / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def bundles_dir(self, *, under_reports: bool = False) -> Path:
        """Default ``bundles/`` at study root; CDX-style uses ``reports/bundles/``."""
        base = self.reports_dir() if under_reports else self.root
        d = base / "bundles"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def input_dir(self) -> Path:
        return self.root / "input"

    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    def variant_data_dir(self, variant: str) -> Path:
        d = self.data_dir() / variant
        d.mkdir(parents=True, exist_ok=True)
        return d

    def variant_reports_dir(self, variant: str) -> Path:
        d = self.reports_dir() / variant
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_config(self, *, cache: dict[str, Any] | None = None) -> dict[str, Any]:
        """Load ``config.yaml``. Pass a one-element *cache* dict to memoize."""
        if cache is not None and "config" in cache:
            return cache["config"]
        with self.config_path().open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if cache is not None:
            cache["config"] = cfg
        return cfg
