"""Human-readable Phase 5 validation report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_report_text(report: dict[str, Any]) -> str:
    lines = [
        "BTCpredict Phase 5 — Validation Report",
        "=" * 72,
        "",
        f"Session (Phase 4): {report.get('session_id', '?')}",
        f"Written:           {report.get('written_at', '?')}",
        f"Trial log entries:   {report.get('trial_log_count', '?')}",
        "",
        "Harness",
        "-" * 72,
    ]
    h = report.get("harness_checks") or {}
    lines.extend(
        [
            f"  OOS rows:              {h.get('oos_rows', '?')}",
            f"  Hold-out leak rows:    {h.get('holdout_leak_rows', '?')}",
            f"  Embargo bars:          {h.get('embargo_bars', '?')}",
            f"  walk_forward OK:       {h.get('walk_forward_ok', '?')}",
            f"  purged_kfold OK:       {h.get('purged_kfold_ok', '?')}",
            "",
        ]
    )

    leak = report.get("leakage") or {}
    lines.extend(
        [
            "Leakage scan",
            "-" * 72,
            f"  Features scanned: {leak.get('features_scanned', '?')}",
            f"  Flags:            {leak.get('critical_count', '?')}",
            "",
        ]
    )

    dn = report.get("directional_null_summary") or {}
    lines.extend(
        [
            "Directional (dev null)",
            "-" * 72,
            f"  Runs:     {dn.get('run_count', '?')}",
            f"  Mean AUC: {dn.get('mean_auc', float('nan')):.3f}" if dn.get("mean_auc") is not None else "  Mean AUC: ?",
            f"  Max AUC:  {dn.get('max_auc', float('nan')):.3f}" if dn.get("max_auc") is not None else "  Max AUC:  ?",
            f"  Status:   {dn.get('status', '?')} (does not block Phase 5)",
            "",
        ]
    )

    lines.extend(["Vol permutation (realized_vol)", "-" * 72])
    for p in report.get("permutation", []):
        if p.get("head") != "realized_vol":
            continue
        beat = "Y" if p.get("beats_null") else "N"
        lines.append(
            f"  {p.get('run_id', ''):<32} {p.get('metric_name')}={p.get('real_metric', 0):.4f} "
            f"p={p.get('p_value', float('nan')):.3f} beat_null={beat}"
        )

    lines.extend(["", "Exceedance calibration (sample)", "-" * 72])
    for row in (report.get("exceedance_calibration") or [])[:12]:
        lines.append(
            f"  {row.get('asset')} {row.get('horizon_id')} {row.get('side')} δ={row.get('delta')} "
            f"n={row.get('n')} ECE={row.get('ece', float('nan')):.3f}"
        )

    lines.extend(["", "VRP evaluation", "-" * 72])
    for row in report.get("vrp_evaluation") or []:
        lines.append(
            f"  {row.get('asset')} {row.get('horizon_id')} "
            f"ρ={row.get('spearman', float('nan')):.3f} sign_hit={row.get('sign_hit_rate', float('nan')):.3f}"
        )

    lines.extend(["", "Embargo sensitivity", "-" * 72])
    for row in report.get("embargo_sensitivity") or []:
        lines.append(
            f"  embargo={row.get('embargo_bars')} AUC={row.get('auc', float('nan')):.3f} "
            f"folds={row.get('folds_used')}"
        )
    lines.append("")
    return "\n".join(lines)


def write_validation_report(json_path: Path, txt_path: Path) -> str:
    report = json.loads(json_path.read_text(encoding="utf-8"))
    text = build_report_text(report)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(text, encoding="utf-8")
    return text
