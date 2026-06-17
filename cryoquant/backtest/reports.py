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


def render_sweep_leaderboard(
    bundle: object,
    out_path: Path | str,
    *,
    top_n: int = 30,
    breakdown_cols: tuple[str, ...] = ("direction", "ticker"),
    display_columns: list[str] | None = None,
) -> Path:
    """Render a sweep bundle to a human-readable HTML leaderboard.

    Parameters
    ----------
    bundle:
        A ``RunBundle`` instance (``cryoquant.backtest.bundle.RunBundle``).
    out_path:
        Destination HTML file path.
    top_n:
        Number of top runs to include in the drill-down section.
    breakdown_cols:
        Leaderboard columns to use for group-breakdown tables.
    display_columns:
        Ordered list of leaderboard columns to show in the main table.
        Defaults to a standard set if None.

    Returns
    -------
    Absolute Path to the rendered HTML file.
    """
    _PCT_COLS = frozenset({
        "total_return", "max_drawdown", "win_rate",
        "pct_long", "pct_short", "cagr",
    })
    _FLOAT_COLS = frozenset({
        "sharpe", "sharpe_trade", "sharpe_equity", "sortino_equity", "calmar",
        "profit_factor", "omega", "expectancy", "avg_hold_days",
        "dsr", "composite_score",
    })
    _COLUMN_LABELS = {
        "sharpe":        "Trade Sharpe",
        "sharpe_trade":  "Trade Sharpe",
        "sharpe_equity": "Daily Sharpe",
        "cagr":          "CAGR",
        "composite_score": "Score",
        "total_return":  "Return",
        "max_drawdown":  "Max DD",
        "profit_factor": "PF",
        "win_rate":      "Win%",
        "n_trades":      "Trades",
        "avg_hold_days": "Avg Hold",
        "entry_n":       "Entry N",
        "exit_n":        "Exit N",
        "filter":        "Filter",
        "timeframe":     "TF",
        "direction":     "Dir",
    }

    leaderboard = bundle.leaderboard if hasattr(bundle, "leaderboard") else None
    meta = bundle.meta if hasattr(bundle, "meta") else {}
    trades_df = bundle.trades if hasattr(bundle, "trades") else None

    rows_data: list[dict] = []
    all_cols: list[str] = []

    if leaderboard is not None and not leaderboard.empty:
        if display_columns:
            show_cols = [c for c in display_columns if c in leaderboard.columns]
        else:
            _DEFAULT = [
                "run_id", "ticker", "timeframe", "direction",
                "entry_n", "filter",
                "composite_score", "cagr", "total_return", "max_drawdown",
                "sharpe_trade", "sharpe_equity",
                "calmar", "profit_factor", "n_trades", "win_rate", "dsr",
            ]
            show_cols = [c for c in _DEFAULT if c in leaderboard.columns]

        all_cols = show_cols
        for _, row in leaderboard.head(top_n).iterrows():
            rows_data.append({c: row.get(c) for c in show_cols})

    # Build top-N drill-down trade lists
    top_runs_ctx: list[dict] = []
    if leaderboard is not None and not leaderboard.empty and trades_df is not None and not trades_df.empty:
        for _, lb_row in leaderboard.head(min(top_n, 5)).iterrows():
            run_id = lb_row.get("run_id", "")
            run_trades = trades_df[trades_df["run_id"] == run_id]
            trades_list = [r.to_dict() for _, r in run_trades.iterrows()]
            top_runs_ctx.append({
                "run_id":        run_id,
                "total_return":  lb_row.get("total_return",  float("nan")),
                "cagr":          lb_row.get("cagr",          float("nan")),
                "sharpe_trade":  lb_row.get("sharpe_trade",  float("nan")),
                "sharpe_equity": lb_row.get("sharpe_equity", float("nan")),
                "max_drawdown":  lb_row.get("max_drawdown",  float("nan")),
                "calmar":        lb_row.get("calmar",        float("nan")),
                "profit_factor": lb_row.get("profit_factor", float("nan")),
                "n_trades":      lb_row.get("n_trades", 0),
                "trades":        trades_list,
            })

    # Build breakdown tables
    breakdowns_ctx: list[dict] = []
    if leaderboard is not None and not leaderboard.empty:
        for col in breakdown_cols:
            if col not in leaderboard.columns:
                continue
            groups = []
            for val, grp in leaderboard.groupby(col, dropna=False):
                groups.append({
                    "value":         str(val),
                    "count":         len(grp),
                    "cagr":          float(grp["cagr"].mean())          if "cagr"          in grp else float("nan"),
                    "sharpe_trade":  float(grp["sharpe_trade"].mean())  if "sharpe_trade"  in grp else float("nan"),
                    "sharpe_equity": float(grp["sharpe_equity"].mean()) if "sharpe_equity" in grp else float("nan"),
                    "total_return":  float(grp["total_return"].mean())  if "total_return"  in grp else float("nan"),
                    "max_drawdown":  float(grp["max_drawdown"].mean())  if "max_drawdown"  in grp else float("nan"),
                    "n_trades":      float(grp["n_trades"].mean())      if "n_trades"      in grp else float("nan"),
                })
            breakdowns_ctx.append({"col": col, "groups": groups})

    context = {
        "title":        f"Sweep Leaderboard — {meta.get('study', '')}",
        "meta":         meta,
        "rows":         rows_data,
        "columns":      all_cols,
        "column_labels": _COLUMN_LABELS,
        "pct_cols":     list(_PCT_COLS),
        "float_cols":   list(_FLOAT_COLS),
        "top_runs":     top_runs_ctx,
        "breakdowns":   breakdowns_ctx,
    }
    return render("sweep_leaderboard", context, out_path)


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
