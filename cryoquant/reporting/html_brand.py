"""Branded matplotlib + agent_commons HTML helpers for study reports.

Uses the ``cryo-dark`` brand by default. Depends on optional ``agent_commons``.
"""
from __future__ import annotations

import base64
import html
import io
from typing import Any

import matplotlib.pyplot as plt

DEFAULT_BRAND = "cryo-dark"


def load_palette(brand: str = DEFAULT_BRAND) -> dict[str, Any]:
    from agent_commons.brand import load_brand

    return load_brand(brand).palette


def fig_to_b64(fig: plt.Figure, *, brand: str = DEFAULT_BRAND, dpi: int = 160) -> str:
    """Encode a matplotlib figure as a base64 PNG string (closes the figure)."""
    pal = load_palette(brand)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor=pal.get("bg", "#070d18"))
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def style_axes(
    ax: plt.Axes,
    title: str,
    ylabel: str = "",
    xlabel: str = "",
    *,
    brand: str = DEFAULT_BRAND,
) -> None:
    """Apply cryo-dark title/label/spine styling via agent_commons ax_clean."""
    from agent_commons.charts import ax_clean

    pal = load_palette(brand)
    ax.set_title(title, color=pal.get("text", "#edf2f9"), fontsize=12, loc="left", pad=10)
    if ylabel:
        ax.set_ylabel(ylabel, color=pal.get("muted", "#8fa3bc"), fontsize=10)
    if xlabel:
        ax.set_xlabel(xlabel, color=pal.get("muted", "#8fa3bc"), fontsize=10)
    ax.tick_params(colors=pal.get("muted", "#8fa3bc"), labelsize=9)
    ax_clean(ax, grid_axis="both")
    for spine in ax.spines.values():
        spine.set_color(pal.get("grid", "#1e2d45"))


def brand_css(brand: str = DEFAULT_BRAND) -> str:
    from agent_commons.brand import load_brand
    from agent_commons.brand.css import render as render_brand_css

    return render_brand_css(load_brand(brand))


def escape_html(v: Any) -> str:
    return html.escape(str(v))


def html_document(
    *,
    title: str,
    body: str,
    brand: str = DEFAULT_BRAND,
    extra_head: str = "",
) -> str:
    """Minimal self-contained HTML shell with brand CSS."""
    css = brand_css(brand)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
{css}
</style>
{extra_head}
</head>
<body>
{body}
</body>
</html>
"""
