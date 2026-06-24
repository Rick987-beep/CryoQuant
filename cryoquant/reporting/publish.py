"""Study reporting orchestrator."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .index_html import render_index_from_manifest
from .manifest import build_manifest, bundle_status, write_manifest


def _load_study_config(study_dir: Path) -> dict[str, Any]:
    config_path = study_dir / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def publish_study(
    study_dir: Path | str,
    *,
    config: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    title: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    highlights: list[dict[str, str]] | None = None,
    walk_forward: dict[str, Any] | None = None,
    index_filename: str = "index.html",
) -> dict[str, Path]:
    """Publish study-level report artifacts per ``reporting`` config.

    When *manifest* is provided it is written to ``reports/manifest.json``.
    When ``reporting.index`` is true (default), an index HTML page is rendered.

    Returns a dict of artifact paths written. Empty when no ``reporting`` section
    and no *manifest* is supplied.
    """
    root = Path(study_dir).resolve()
    cfg = config if config is not None else _load_study_config(root)
    reporting = cfg.get("reporting") or {}

    if manifest is None and not reporting:
        return {}

    reports_root = root / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    if manifest is None and reporting:
        bundle_specs: dict[str, str] = reporting.get("bundles", {})
        bundles: dict[str, dict[str, Any]] = {}
        report_links: dict[str, str | None] = {"index": index_filename}
        for name, rel_path in bundle_specs.items():
            bundle_dir = (root / rel_path).resolve()
            status = bundle_status(bundle_dir, reports_root=reports_root)
            bundles[name] = status
            report_links[name] = status.get("report_html")

        sample = reporting.get("sample", {})
        manifest = build_manifest(
            study=reporting.get("study", root.name),
            sample=sample,
            bundles=bundles,
            highlights=reporting.get("highlights", {}),
            phases=reporting.get("phases", []),
            reports=report_links,
        )

    if manifest is not None:
        manifest_path = write_manifest(reports_root / "manifest.json", manifest)
        written["manifest"] = manifest_path

        if reporting.get("index", True):
            index_path = render_index_from_manifest(
                reports_root / index_filename,
                manifest,
                title=title,
                sections=sections,
                highlights=highlights,
                walk_forward=walk_forward,
            )
            written["index"] = index_path

    return written
