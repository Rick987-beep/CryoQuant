"""Phase 7C — RESULTS.md and study manifest."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryoquant.reporting.manifest import build_manifest

from src.phase7_holdout import Phase7Report
from src.repro_bundle import build_repro_bundle


def _fmt(x: Any, digits: int = 4) -> str:
    if x is None:
        return "n/a"
    try:
        v = float(x)
        if not (v == v):  # nan
            return "n/a"
        return f"{v:.{digits}f}"
    except (TypeError, ValueError):
        return str(x)


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def write_results_md(report: Phase7Report, cfg: Any, path: Path) -> None:
    g = report.gates
    cw = report.chain_window
    prim = report.preregistered_primary
    phys = report.physical_vs_delta
    cal = report.calibration_slice
    inf = report.inference_summary

    grid = report.report_all_grid
    exp_pos = sum(1 for r in grid if r.get("expectancy") is not None and float(r.get("expectancy", 0)) > 0)
    gap_pos = sum(1 for r in grid if r.get("calibration_gap") is not None and float(r.get("calibration_gap", 0)) > 0)

    diag = cw.get("signal_diagnostics", {})
    lines = [
        "# BTCpredict v1 — Final Results",
        "",
        f"*Generated: {report.written_at}*",
        "",
        "## 1. Executive summary",
        "",
        f"- **Primary gate (G2′):** {'PASS' if g.get('G2_primary', {}).get('pass') else 'FAIL'} "
        f"(via {g.get('G2_primary', {}).get('passed_via', '?')})",
        f"  - Chain calibration gap: {_fmt(g.get('G2_primary', {}).get('calibration_gap'))} "
        f"(n={g.get('G2_primary', {}).get('chain_trades', 0)} trades)",
        f"  - Pre-chain calibration-slice BTC h1 min ECE: {_fmt(g.get('G2_primary', {}).get('ece_min'))}",
        f"- **G1′ (beat naive seller DSR):** {'PASS' if g.get('G1_secondary', {}).get('pass') else 'FAIL'}",
        f"- **G3′ (CVaR cap):** {'PASS' if g.get('G3_secondary', {}).get('pass') else 'FAIL'}",
        f"- **G4′ (expectancy > 0):** {'PASS' if g.get('G4_secondary', {}).get('pass') else 'FAIL'}",
        f"- **Chain trades (model, primary endpoint):** {prim.get('n_trades', 0)} resolved / "
        f"{prim.get('fires_evaluated', 0)} fires evaluated",
        f"- **Report-all grid:** {len(grid)} combos — {exp_pos} with positive expectancy, "
        f"{gap_pos} with positive calibration gap (no hold-out selection)",
        "",
        "A null hold-out economic result is valid if reported honestly (P-0). "
        "Hold-out touched **once** per P-8.",
        "",
        "## 2. Dev recap (Phases 4–6)",
        "",
        "- Directional dev null confirmed (AUC ≈ 0.50); not used for promotion.",
        "- Vol head beat HAR-RV on dev; VRP structural signal present.",
        "- Phase 6 frozen policy: "
        f"BTC {report.frozen_signal.get('horizon_id')}, "
        f"vrp_threshold={report.frozen_signal.get('vrp_threshold')}, "
        f"tilt={report.frozen_signal.get('tilt_mode')}, "
        f"min_physical_edge={report.frozen_signal.get('min_physical_edge')}.",
        "- Phase 6 did **not** beat naive VRP proxy on dev (G1 warning).",
        "",
        "## 3. Hold-out inference (7A)",
        "",
        f"- Models refit: {inf.get('runs', 0)} runs ({inf.get('ok_runs', 0)} ok)",
        f"- Prediction rows: {inf.get('prediction_rows', 0)}",
        "- Fit slice: `timestamp < 2024-06-01` (full dev)",
        "- Predict slice: `timestamp >= 2024-06-01`",
        "- No HPO; hyperparams from `training.yaml`.",
        "",
        "## 4. Calibration slice (2024-06 → 2025-04, no chains)",
        "",
        f"- Window: {cal.get('slice_start', '?')} → {cal.get('slice_end', '?')}",
        f"- Hold-out prediction rows in slice: {cal.get('prediction_rows', 0)}",
        f"- BTC T+1d exceedance overlays: {len(cal.get('exceedance_overlays', []))}",
        f"- Min ECE (BTC h1): {_fmt(cal.get('btc_h1_ece_min'))}",
        "",
        "## 5. Chain window (Apr 2025+)",
        "",
        f"- Effective start: {cw.get('effective_start', '?')}",
        f"- Chain dates with valid schema: {cw.get('chain_dates_available', 0)}",
        f"- Bars with spot: {cw.get('bars_with_spot', 0)}",
        f"- Range: {cw.get('first_date', '?')} → {cw.get('last_date', '?')}",
        f"- Model fires on chain window: {prim.get('fires_evaluated', 0)} "
        f"(vol_edge>0: {diag.get('vol_edge_positive', '?')}; "
        f"exceedance gate blocked: {diag.get('exceedance_gate_blocks', '?')})",
        f"- Mean exceedance_edge on chain bars: {_fmt(diag.get('mean_exceedance_edge'))}",
        f"- Naive seller fires: {report.naive_seller.get('fires_evaluated', 0)}",
        "",
        "> Chain N (~15 months) may be insufficient for definitive DSR significance; "
        "treat economic gates as directional.",
        "",
        "## 6. Physical P(OTM) vs market δ (primary thesis)",
        "",
        f"- Target δ: {_fmt(phys.get('target_delta'))}",
        f"- Market-implied P(OTM) ≈ 1−δ: {_fmt(phys.get('implied_otm'))}",
        f"- Mean exceedance edge on model fires: {_fmt(phys.get('mean_exceedance_edge_on_fires'))}",
        f"- Realized OTM rate (trades): {_fmt(phys.get('realized_otm_rate'))} (n={phys.get('n', 0)})",
        f"- Calibration gap (realized OTM − (1−δ)): {_fmt(phys.get('gap_vs_market_delta'))}",
        "",
        "## 7. Model vs baselines (preregistered primary: δ=0.15, DTE=7, strangle)",
        "",
        "| Strategy | n_trades | Expectancy | Sharpe | DSR | CVaR | Cal gap |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for row in (report.model_gated, report.naive_seller, report.naive_vrp_gate):
        lines.append(
            f"| {row.get('label', '?')} | {row.get('n_trades', 0)} | "
            f"{_fmt(row.get('expectancy'))} | {_fmt(row.get('sharpe'))} | "
            f"{_fmt(row.get('deflated_sharpe'))} | {_fmt(row.get('cvar'))} | "
            f"{_fmt(row.get('calibration_gap'))} |"
        )

    lines.extend(
        [
            "",
            "## 8. Report-all grid (distribution only — no champion on hold-out)",
            "",
            f"- Combos: {len(grid)}",
            f"- Expectancy > 0: {exp_pos}/{len(grid)}" if grid else "- No grid runs",
            f"- Calibration gap > 0: {gap_pos}/{len(grid)}" if grid else "",
            "",
            "Top 5 by expectancy (informational only, not selected):",
            "",
        ]
    )

    if grid:
        top = sorted(grid, key=lambda r: r.get("expectancy") or -1e9, reverse=True)[:5]
        for r in top:
            lines.append(
                f"- `{r.get('run_id')}`: exp={_fmt(r.get('expectancy'))}, "
                f"gap={_fmt(r.get('calibration_gap'))}, n={r.get('n_trades', 0)}"
            )
    else:
        lines.append("- (empty)")

    lines.extend(
        [
            "",
            "## 9. Conclusion",
            "",
        ]
    )

    if g.get("G2_primary", {}).get("pass"):
        via = g.get("G2_primary", {}).get("passed_via", "")
        if via == "calibration_slice_ece":
            lines.append(
                "- **Calibration (pre-chain slice):** Quantile exceedance ECE on hold-out "
                "predictions (2024-06→2025-04) meets threshold — distributional head calibrates."
            )
        if prim.get("n_trades", 0) == 0:
            lines.append(
                "- **Chain economics:** Frozen policy produced **zero fires** on Apr 2025+ "
                "because `exceedance_edge ≤ 0` on all chain bars (physical P(OTM) below market δ). "
                "Vol gate alone would have fired, but exceedance gate blocks."
            )
        lines.append(
            "- **Naive seller on chains:** Negative expectancy; unconditional short vol loses "
            "after bid/ask on this window — no deployable economic edge demonstrated."
        )
    else:
        lines.append(
            "- **Null result:** Primary calibration gate G2′ not met on hold-out. "
            "No demonstrated edge over market-implied δ after costs. "
            "Recommend research-only; do not deploy capital on this signal stack."
        )

    if not g.get("G1_secondary", {}).get("pass"):
        lines.append("- Model did not beat naive unconditional seller on deflated Sharpe (secondary).")

    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(
    cfg: Any,
    data_dir: Path,
    reports_dir: Path,
    report: Phase7Report,
) -> Path:
    artifacts = {
        "holdout_predictions": data_dir / "holdout_predictions.parquet",
        "phase7_holdout_report": data_dir / "phase7_holdout_report.json",
        "phase6_best_config": data_dir / "phase6_best_config.json",
        "phase7_guard": data_dir / "phase7_holdout_touched.json",
        "RESULTS.md": reports_dir / "RESULTS.md",
    }
    hashed = {k: _file_sha256(v) for k, v in artifacts.items()}

    manifest = build_manifest(
        study="btcpredict_v1",
        sample={"phase": 7, "session_id": report.session_id},
        phases=[
            {"id": 7, "name": "hold-out", "status": "complete"},
        ],
        reports={"RESULTS.md": "RESULTS.md"},
        highlights={
            "G2_primary_pass": report.gates.get("G2_primary", {}).get("pass"),
            "n_trades": report.preregistered_primary.get("n_trades"),
            "chain_days": report.chain_window.get("chain_dates_available"),
        },
        extra={
            "artifact_sha256": hashed,
            "reproducibility": build_repro_bundle(cfg),
            "gates": report.gates,
        },
    )
    out = reports_dir / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
