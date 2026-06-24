"""Study index HTML renderer."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_index_html(
    path: Path | str,
    *,
    title: str,
    generated_at: str = "",
    sample_label: str = "",
    n_bars: int | None = None,
    highlights: list[dict[str, str]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    phases: list[dict[str, Any]] | None = None,
    walk_forward: dict[str, Any] | None = None,
) -> Path:
    """Render a study index page to *path*."""
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    template = _get_env().get_template("study_index.html")
    html = template.render(
        title=title,
        generated_at=generated_at,
        sample_label=sample_label,
        n_bars=n_bars,
        highlights=highlights or [],
        sections=sections or [],
        phases=phases or [],
        walk_forward=walk_forward,
    )
    out.write_text(html, encoding="utf-8")
    return out


def render_index_from_manifest(
    path: Path | str,
    manifest: dict[str, Any],
    *,
    title: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    highlights: list[dict[str, str]] | None = None,
    walk_forward: dict[str, Any] | None = None,
) -> Path:
    """Render index HTML using fields from a study manifest."""
    sample = manifest.get("sample", {})
    return render_index_html(
        path,
        title=title or f"{manifest.get('study', 'Study')} — Reports",
        generated_at=manifest.get("created_at", ""),
        sample_label=sample.get("label", ""),
        n_bars=sample.get("n_bars"),
        highlights=highlights,
        sections=sections,
        phases=manifest.get("phases"),
        walk_forward=walk_forward,
    )
