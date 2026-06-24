"""Manifest and index HTML for CDX Phase 5 reporting."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .paths import ANALYSIS_ROOT

_TEMPLATES_DIR = ANALYSIS_ROOT / "templates"


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


def bundle_status(bundle_dir: Path) -> dict[str, Any]:
    """Summarise an on-disk sweep bundle for manifest/index."""
    if not bundle_dir.is_dir():
        return {"status": "missing", "path": str(bundle_dir)}
    meta = _load_meta(bundle_dir)
    if meta is None:
        return {"status": "incomplete", "path": str(bundle_dir)}
    top = _top_leaderboard_row(bundle_dir)
    report_rel = _relative_report_href(bundle_dir)
    return {
        "status": "ok",
        "path": str(bundle_dir),
        "study": meta.get("study"),
        "n_runs": meta.get("n_runs"),
        "data_end": meta.get("data_end"),
        "report_html": report_rel,
        "top_run_id": top.get("run_id") or top.get("name"),
        "top_nav_end": top.get("nav_end"),
        "top_composite_score": top.get("composite_score"),
    }


def primary_status(bundle_dir: Path) -> dict[str, Any]:
    """Summarise primary portfolio bundle."""
    if not bundle_dir.is_dir():
        return {"status": "missing", "path": str(bundle_dir)}
    meta = _load_meta(bundle_dir)
    if meta is None:
        return {"status": "incomplete", "path": str(bundle_dir)}
    return {
        "status": "ok",
        "path": str(bundle_dir),
        "study": meta.get("study"),
        "name": meta.get("name"),
        "nav_end": meta.get("nav_end"),
        "carry_funding_ratio": meta.get("carry_funding_ratio"),
        "pnl_covid": meta.get("pnl_covid"),
        "mutex_overlap_days": meta.get("mutex_overlap_days"),
        "report_html": _relative_report_href(bundle_dir),
    }


def _relative_report_href(bundle_dir: Path) -> str:
    """Path from analyses/cdx/reports/ to bundle report.html."""
    reports_root = ANALYSIS_ROOT / "reports"
    try:
        rel = bundle_dir.resolve().relative_to(reports_root.resolve())
        return f"{rel.as_posix()}/report.html"
    except ValueError:
        return f"{bundle_dir.name}/report.html"


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
    """Assemble manifest.json content."""
    p3 = bundle_status(phase3_dir)
    p4 = bundle_status(phase4_dir)
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

    return {
        "study": "CDX.NA.IG",
        "bundle_version": "1",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample": {
            "start": data_start,
            "end": data_end,
            "n_bars": n_bars,
            "label": f"{data_start} → {data_end}",
        },
        "data_start": data_start,
        "data_end": data_end,
        "n_bars": n_bars,
        "primary": primary_name,
        "highlights": highlights,
        "bundles": {
            "phase3_overlay_sweep": p3,
            "phase4_portfolio": p4,
            "primary": primary,
        },
        "reports": {
            "index": "report.html",
            "phase3": p3.get("report_html"),
            "phase4": p4.get("report_html"),
            "primary": primary.get("report_html"),
        },
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
    }


def write_manifest(path: Path | str, manifest: dict[str, Any]) -> Path:
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return out


def render_index_html(
    path: Path | str,
    manifest: dict[str, Any],
) -> Path:
    """Render analyses/cdx/reports/report.html index page."""
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("cdx_index.html")

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

    html = template.render(
        title="CDX.NA.IG — Analysis Reports",
        generated_at=manifest.get("created_at", ""),
        sample_label=manifest.get("sample", {}).get("label", manifest.get("data_end", "")),
        n_bars=manifest.get("n_bars"),
        data_end=manifest.get("data_end", ""),
        highlights=highlights,
        sections=sections,
        walk_forward=walk_forward_ctx,
    )
    out.write_text(html, encoding="utf-8")
    return out
