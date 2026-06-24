"""Study manifest builders for CryoQuant reporting."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


def _load_meta(bundle_dir: Path) -> dict[str, Any] | None:
    meta_path = bundle_dir / "meta.json"
    if not meta_path.exists():
        return None
    with open(meta_path, encoding="utf-8") as fh:
        return json.load(fh)


def _top_leaderboard_row(bundle_dir: Path) -> dict[str, Any]:
    lb_path = bundle_dir / "leaderboard.parquet"
    if not lb_path.exists():
        return {}
    lb = pd.read_parquet(lb_path)
    if lb.empty:
        return {}
    return lb.iloc[0].to_dict()


def relative_report_href(bundle_dir: Path, reports_root: Path) -> str:
    """Path from *reports_root* to a bundle's ``report.html``."""
    try:
        rel = bundle_dir.resolve().relative_to(reports_root.resolve())
        return f"{rel.as_posix()}/report.html"
    except ValueError:
        return f"{bundle_dir.name}/report.html"


def bundle_status(
    bundle_dir: Path,
    *,
    reports_root: Path | None = None,
) -> dict[str, Any]:
    """Summarise an on-disk RunBundle directory for manifest/index pages."""
    if not bundle_dir.is_dir():
        return {"status": "missing", "path": str(bundle_dir)}
    meta = _load_meta(bundle_dir)
    if meta is None:
        return {"status": "incomplete", "path": str(bundle_dir)}

    top = _top_leaderboard_row(bundle_dir)
    status: dict[str, Any] = {
        "status": "ok",
        "path": str(bundle_dir),
        "study": meta.get("study"),
        "n_runs": meta.get("n_runs"),
        "name": meta.get("name"),
        "data_end": meta.get("data_end"),
        "nav_end": meta.get("nav_end"),
        "top_run_id": top.get("run_id") or top.get("name"),
        "top_nav_end": top.get("nav_end"),
        "top_composite_score": top.get("composite_score"),
    }
    if reports_root is not None:
        status["report_html"] = relative_report_href(bundle_dir, reports_root)
    return status


def build_manifest(
    *,
    study: str,
    sample: dict[str, Any],
    bundles: dict[str, dict[str, Any]] | None = None,
    highlights: dict[str, Any] | None = None,
    phases: list[dict[str, Any]] | None = None,
    reports: dict[str, str | None] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a study ``manifest.json`` document."""
    manifest: dict[str, Any] = {
        "study": study,
        "bundle_version": "1",
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample": sample,
        "highlights": highlights or {},
        "phases": phases or [],
        "bundles": bundles or {},
        "reports": reports or {"index": "index.html"},
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest(path: Path | str, manifest: dict[str, Any]) -> Path:
    """Write *manifest* to disk as indented JSON."""
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return out
