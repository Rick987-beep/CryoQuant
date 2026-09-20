"""Study reporting — manifests, index HTML, phase summaries, optional exports.

See ``docs/how_to_report.md`` for the format menu and artifact layout.
"""
from __future__ import annotations

from cryoquant.reporting.charts import svg_bars, svg_line_chart
from cryoquant.reporting.html_brand import (
    brand_css,
    escape_html,
    fig_to_b64,
    html_document,
    style_axes,
)
from cryoquant.reporting.index_html import render_index_from_manifest, render_index_html
from cryoquant.reporting.manifest import (
    build_manifest,
    bundle_status,
    relative_report_href,
    write_manifest,
)
from cryoquant.reporting.notebook_export import export_notebook
from cryoquant.reporting.phase_summary import write_phase_summary
from cryoquant.reporting.publish import publish_study
from cryoquant.reporting.tearsheet import render_tearsheet

__all__ = [
    "brand_css",
    "build_manifest",
    "bundle_status",
    "escape_html",
    "export_notebook",
    "fig_to_b64",
    "html_document",
    "publish_study",
    "relative_report_href",
    "render_index_from_manifest",
    "render_index_html",
    "render_tearsheet",
    "style_axes",
    "svg_bars",
    "svg_line_chart",
    "write_manifest",
    "write_phase_summary",
]
