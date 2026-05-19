"""HTML report renderer using Jinja2 templates.

Templates live in ``cryoquant/backtest/reports/``.

Public interface::

    render(template_name, context, out_path) -> Path

Available templates:
    "spot_pnl"      -> spot_pnl.html
    "option_lookup" -> option_lookup.html
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent / "reports"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render(
    template_name: str,
    context: dict,
    out_path: Path | str,
) -> Path:
    """Render *template_name* with *context* and write to *out_path*.

    Parameters
    ----------
    template_name:  Base name without extension, e.g. ``"spot_pnl"``.
    context:        Template variables.
    out_path:       Destination file path.

    Returns
    -------
    Absolute Path to the rendered file.
    """
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = _get_env()
    template = env.get_template(f"{template_name}.html")

    ctx = dict(context)
    ctx.setdefault("generated_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    html = template.render(**ctx)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_spot_result(result: object, out_path: Path | str, signal_info: str = "") -> Path:
    """Convenience wrapper: render a SpotResult to spot_pnl.html.

    Parameters
    ----------
    result:      A SpotResult instance.
    out_path:    Destination path.
    signal_info: Optional free-text signal description.
    """
    trades_list = []
    if hasattr(result, "trades") and not result.trades.empty:
        for _, row in result.trades.iterrows():
            trades_list.append(
                {
                    "entry_ts": str(row["entry_ts"])[:19],
                    "exit_ts":  str(row["exit_ts"])[:19],
                    "entry_price": float(row["entry_price"]),
                    "exit_price":  float(row["exit_price"]),
                    "pnl_pct":     float(row["pnl_pct"]),
                }
            )

    context = {
        "title": "Spot P&L Report",
        "metrics": result.metrics,
        "trades": trades_list,
        "signal_info": signal_info,
    }
    return render("spot_pnl", context, out_path)


def render_option_result(
    result: object,
    out_path: Path | str,
    dte: int = 0,
    delta: float = 0.0,
) -> Path:
    """Convenience wrapper: render an OptionResult to option_lookup.html."""
    import numpy as np

    pnl_table = []
    if hasattr(result, "pnl_pct"):
        for i, (p, c, d) in enumerate(
            zip(result.pnl_pct, result.entry_costs_usd, result.dte_actual)
        ):
            pnl_table.append({"pnl": p, "entry_cost": c, "dte": d})

    entry_costs = getattr(result, "entry_costs_usd", [])
    median_cost = float(np.median(entry_costs)) if entry_costs else 0.0

    context = {
        "title": "Option Lookup Report",
        "fires_evaluated": result.fires_evaluated,
        "fires_with_data": result.fires_with_data,
        "win_rate": result.win_rate,
        "expectancy": result.expectancy,
        "median_entry_cost_usd": median_cost,
        "dte": dte,
        "delta": delta,
        "pnl_table": pnl_table,
    }
    return render("option_lookup", context, out_path)
