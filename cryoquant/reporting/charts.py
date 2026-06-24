"""Inline SVG chart helpers for self-contained HTML reports."""
from __future__ import annotations

from html import escape

import pandas as pd


def svg_line_chart(
    series: pd.Series,
    *,
    width: int = 720,
    height: int = 220,
    stroke: str = "#3fb950",
    fill: str = "rgba(63,185,80,0.12)",
    y_label: str = "",
    hline: float | None = None,
) -> str:
    """Minimal SVG line chart from a numeric series."""
    if series.empty:
        return "<p><em>No series data.</em></p>"
    y = series.astype(float).values
    step = max(len(y) // 400, 1)
    xs, ys = [], []
    for i in range(0, len(y), step):
        xs.append(i)
        ys.append(y[i])
    if xs[-1] != len(y) - 1:
        xs.append(len(y) - 1)
        ys.append(y[-1])

    ymin, ymax = float(min(ys)), float(max(ys))
    if hline is not None:
        ymin = min(ymin, hline)
        ymax = max(ymax, hline)
    pad = (ymax - ymin) * 0.08 or 0.05
    ymin -= pad
    ymax += pad
    rng = ymax - ymin or 1.0

    def _px(i: int, v: float) -> tuple[float, float]:
        px = 40 + (width - 60) * (i / max(len(y) - 1, 1))
        py = 20 + (height - 40) * (1 - (v - ymin) / rng)
        return px, py

    points = [_px(x, v) for x, v in zip(xs, ys, strict=True)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area_d = path_d + f" L {points[-1][0]:.1f},{height - 20:.1f} L {points[0][0]:.1f},{height - 20:.1f} Z"

    hline_el = ""
    if hline is not None:
        _, y0 = _px(0, hline)
        hline_el = (
            f'<line x1="40" y1="{y0:.1f}" x2="{width - 20}" y2="{y0:.1f}" '
            f'stroke="#8b949e" stroke-dasharray="4,4" stroke-width="1"/>'
            f'<text x="{width - 18}" y="{y0 - 4:.1f}" fill="#8b949e" font-size="10" '
            f'text-anchor="end">1.0×</text>'
        )

    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;background:#161b22;border:1px solid #30363d;border-radius:6px;">
  <text x="40" y="14" fill="#8b949e" font-size="11">{escape(y_label)}</text>
  <text x="40" y="{height - 6}" fill="#8b949e" font-size="10">{escape(str(series.index[0])[:10])}</text>
  <text x="{width - 20}" y="{height - 6}" fill="#8b949e" font-size="10" text-anchor="end">{escape(str(series.index[-1])[:10])}</text>
  <text x="36" y="24" fill="#8b949e" font-size="10" text-anchor="end">{ymax:.2f}×</text>
  <text x="36" y="{height - 22}" fill="#8b949e" font-size="10" text-anchor="end">{ymin:.2f}×</text>
  {hline_el}
  <path d="{area_d}" fill="{fill}"/>
  <path d="{path_d}" fill="none" stroke="{stroke}" stroke-width="2"/>
</svg>"""


def svg_bars(
    labels: list[str],
    values: list[float],
    *,
    width: int = 720,
    height: int = 260,
    colors: list[str] | None = None,
    fmt: str = "{:.2f}×",
) -> str:
    """Minimal SVG bar chart."""
    if not values:
        return ""
    n = len(values)
    colors = colors or ["#58a6ff"] * n
    vmax = max(values) * 1.12 or 1.0
    bar_w = (width - 80) / n * 0.65
    gap = (width - 80) / n
    bars = []
    for i, (lab, val, col) in enumerate(zip(labels, values, colors, strict=True)):
        x = 50 + i * gap + (gap - bar_w) / 2
        h = (val / vmax) * (height - 70)
        y = height - 40 - h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{col}" rx="3"/>'
            f'<text x="{x + bar_w/2:.1f}" y="{y - 6:.1f}" fill="#c9d1d9" font-size="11" text-anchor="middle">{fmt.format(val)}</text>'
            f'<text x="{x + bar_w/2:.1f}" y="{height - 22:.1f}" fill="#8b949e" font-size="10" text-anchor="middle">{escape(lab)}</text>'
        )
    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;background:#161b22;border:1px solid #30363d;border-radius:6px;">
  {''.join(bars)}
</svg>"""
