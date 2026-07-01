"""Human-readable Phase 6 backtest report."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_report_text(report: dict[str, Any]) -> str:
    lines = [
        "BTCpredict Phase 6 — Backtest Report",
        "=" * 72,
        "",
        f"Session:     {report.get('session_id', '?')}",
        f"Written:     {report.get('written_at', '?')}",
        f"Trial log:   {report.get('trial_log_count', '?')} entries (pre-run)",
        "",
        "Best config (dev proxy)",
        "-" * 72,
    ]
    best = report.get("best_config") or {}
    for k in (
        "asset",
        "horizon_id",
        "vrp_threshold",
        "tilt_mode",
        "min_physical_edge",
        "deflated_sharpe",
        "expectancy",
        "cvar",
        "beats_naive",
    ):
        lines.append(f"  {k}: {best.get(k, '?')}")

    lines.extend(["", "Proxy sweep (top 8 by deflated Sharpe)", "-" * 72])
    rows = sorted(
        report.get("proxy_sweep") or [],
        key=lambda r: r.get("deflated_sharpe") or -1e9,
        reverse=True,
    )[:8]
    for row in rows:
        lines.append(
            f"  {row.get('run_id', '')[:40]:<40} "
            f"dsr={row.get('deflated_sharpe', float('nan')):.3f} "
            f"sh={row.get('sharpe', float('nan')):.3f} "
            f"n={row.get('n_trades', 0)} beat={row.get('beats_naive')}"
        )

    lines.extend(["", "Naive VRP baselines", "-" * 72])
    for row in report.get("naive_baselines") or []:
        lines.append(
            f"  {row.get('horizon_id')} sharpe={row.get('sharpe', float('nan')):.3f} "
            f"n={row.get('n_trades', 0)}"
        )

    lines.extend(["", "Chain smoke (BTC infra)", "-" * 72])
    smoke = report.get("chain_smoke") or {}
    for k in ("status", "fires_evaluated", "fires_with_data", "expectancy", "win_rate"):
        lines.append(f"  {k}: {smoke.get(k, '?')}")

    lines.append("")
    return "\n".join(lines)


def write_report_text(report: dict[str, Any], path: Path) -> str:
    text = build_report_text(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
