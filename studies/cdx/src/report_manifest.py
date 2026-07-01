"""Manifest and index HTML for CDX Phase 5 reporting."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from cryoquant.reporting import (
    build_manifest as _build_manifest,
)
from cryoquant.reporting import (
    bundle_status,
    render_index_from_manifest,
    write_manifest,
)

from .paths import ANALYSIS_ROOT

_REPORTS_ROOT = ANALYSIS_ROOT / "reports"


def _load_meta(bundle_dir: Path) -> dict[str, Any] | None:
    meta_path = bundle_dir / "meta.json"
    if not meta_path.exists():
        return None
    import json

    with open(meta_path, encoding="utf-8") as fh:
        return json.load(fh)


def primary_status(bundle_dir: Path) -> dict[str, Any]:
    """Summarise primary portfolio bundle with CDX-specific meta fields."""
    status = bundle_status(bundle_dir, reports_root=_REPORTS_ROOT)
    if status.get("status") != "ok":
        return status
    meta = _load_meta(bundle_dir) or {}
    status.update({
        "carry_funding_ratio": meta.get("carry_funding_ratio"),
        "pnl_covid": meta.get("pnl_covid"),
        "mutex_overlap_days": meta.get("mutex_overlap_days"),
    })
    return status


def build_manifest(
    *,
    data_start: str,
    data_end: str,
    n_bars: int,
    primary_name: str,
    phase3_dir: Path,
    phase4_dir: Path,
    primary_dir: Path,
    walk_forward: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble manifest.json content for CDX.NA.IG."""
    p3 = bundle_status(phase3_dir, reports_root=_REPORTS_ROOT)
    p4 = bundle_status(phase4_dir, reports_root=_REPORTS_ROOT)
    primary = primary_status(primary_dir)

    highlights: dict[str, Any] = {
        "primary": primary_name,
        "primary_nav_end": primary.get("nav_end"),
        "primary_carry_funding": primary.get("carry_funding_ratio"),
        "primary_covid_pnl_usd": primary.get("pnl_covid"),
    }
    if p3.get("status") == "ok":
        highlights["top_yield_run"] = p3.get("top_run_id")
        highlights["top_yield_nav_end"] = p3.get("top_nav_end")
    if p4.get("status") == "ok":
        highlights["top_portfolio_run"] = p4.get("top_run_id")
        highlights["top_portfolio_nav_end"] = p4.get("top_nav_end")

    return _build_manifest(
        study="CDX.NA.IG",
        sample={
            "start": data_start,
            "end": data_end,
            "n_bars": n_bars,
            "label": f"{data_start} → {data_end}",
        },
        bundles={
            "phase3_overlay_sweep": p3,
            "phase4_portfolio": p4,
            "primary": primary,
        },
        highlights=highlights,
        reports={
            "index": "report.html",
            "phase3": p3.get("report_html"),
            "phase4": p4.get("report_html"),
            "primary": primary.get("report_html"),
        },
        extra={
            "data_start": data_start,
            "data_end": data_end,
            "n_bars": n_bars,
            "primary": primary_name,
            "walk_forward": walk_forward,
            "backtest_windows": {
                "full_sample": {
                    "start": data_start,
                    "end": data_end,
                    "n_bars": n_bars,
                    "description": "Phases 3–4 and primary portfolio use the full aligned panel",
                },
                "walk_forward_oos": walk_forward,
            },
        },
    )


def render_index_html(
    path: Path | str,
    manifest: dict[str, Any],
) -> Path:
    """Render studies/cdx/reports/report.html index page."""
    highlights = []
    hl = manifest.get("highlights", {})
    highlight_specs = [
        ("primary_nav_end", "Primary NAV end"),
        ("primary_carry_funding", "Carry funding ratio"),
        ("primary_covid_pnl_usd", "COVID PnL (USD)"),
        ("top_yield_run", "Top yield run"),
        ("top_yield_nav_end", "Top yield NAV"),
        ("top_portfolio_run", "Top portfolio run"),
    ]
    for key, label in highlight_specs:
        val = hl.get(key)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        if isinstance(val, float):
            if key.endswith("_pnl_usd"):
                text = f"${val:,.0f}"
            elif key.endswith("_nav_end"):
                text = f"{val:.3f}×"
            else:
                text = f"{val:.3f}"
        else:
            text = str(val)
        highlights.append({"label": label, "value": text})

    bundles = manifest.get("bundles", {})
    sections = [
        {
            "name": "Phase 3 — Overlay sweep",
            "description": "Tail grid + Y1–Y14 yield strategies (isolated overlays)",
            "href": manifest.get("reports", {}).get("phase3"),
            "status": bundles.get("phase3_overlay_sweep", {}).get("status", "missing"),
        },
        {
            "name": "Phase 4 — Portfolio variants",
            "description": "Tail + yield composition, mutex on/off",
            "href": manifest.get("reports", {}).get("phase4"),
            "status": bundles.get("phase4_portfolio", {}).get("status", "missing"),
        },
        {
            "name": f"Primary — {manifest.get('primary', '')}",
            "description": "Full-sample primary portfolio deep dive + attribution",
            "href": manifest.get("reports", {}).get("primary"),
            "status": bundles.get("primary", {}).get("status", "missing"),
        },
    ]

    wf = manifest.get("walk_forward")
    walk_forward_ctx = None
    if wf:
        metrics = wf.get("metrics", {})
        walk_forward_ctx = {
            "spec": wf.get("spec", manifest.get("primary")),
            "n_blocks": metrics.get("n_blocks", len(wf.get("blocks", []))),
            "nav_end": f"{metrics.get('nav_end', float('nan')):.3f}×",
            "blocks": wf.get("blocks", []),
        }

    return render_index_from_manifest(
        path,
        manifest,
        title="CDX.NA.IG — Analysis Reports",
        highlights=highlights,
        sections=sections,
        walk_forward=walk_forward_ctx,
    )


__all__ = [
    "build_manifest",
    "bundle_status",
    "primary_status",
    "render_index_html",
    "write_manifest",
]
