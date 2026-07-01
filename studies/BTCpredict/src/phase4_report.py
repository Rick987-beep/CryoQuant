"""Human-readable Phase 4 training report (Phase 4.5)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def _fmt_metric(head: str, metrics: dict[str, float]) -> str:
    if not metrics:
        return "—"
    if head == "directional":
        v = metrics.get("auc")
        return f"AUC={v:.3f}" if v is not None and np.isfinite(v) else "—"
    if head == "log_return_bench":
        v = metrics.get("mae")
        r2 = metrics.get("r2")
        parts = []
        if v is not None and np.isfinite(v):
            parts.append(f"MAE={v:.4f}")
        if r2 is not None and np.isfinite(r2):
            parts.append(f"R²={r2:.3f}")
        return " ".join(parts) if parts else "—"
    if head == "realized_vol":
        v = metrics.get("qlike", metrics.get("mae"))
        return f"QLIKE={v:.3f}" if v is not None and np.isfinite(v) else "—"
    if head == "distributional":
        v = metrics.get("pinball_loss")
        return f"pinball={v:.4f}" if v is not None and np.isfinite(v) else "—"
    return str(metrics)[:40]


def _fmt_delta(head: str, delta: dict[str, float]) -> str:
    if not delta:
        return "—"
    if head == "directional":
        v = delta.get("auc_delta")
        return f"ΔAUC={v:+.3f}" if v is not None and np.isfinite(v) else "—"
    if head == "log_return_bench":
        v = delta.get("mae_improvement")
        return f"ΔMAE={v:+.4f}" if v is not None and np.isfinite(v) else "—"
    if head == "realized_vol":
        v = delta.get("qlike_improvement")
        return f"ΔQLIKE={v:+.3f}" if v is not None and np.isfinite(v) else "—"
    return "—"


def build_report_text(manifest: dict[str, Any]) -> str:
    lines = [
        "BTCpredict Phase 4 — Training Report",
        "=" * 72,
        "",
    ]
    repro = manifest.get("reproducibility") or {}
    lines.extend(
        [
            f"Session:     {manifest.get('session_id', '?')}",
            f"Written:     {manifest.get('written_at', '?')}",
            f"Git commit:  {repro.get('git_commit', '?')}",
            f"Runs:        {manifest.get('run_count', '?')}",
            f"Hold-out ≥:  {repro.get('holdout_start', '?')} (must not appear in OOS)",
            "",
            "File hashes (prefix):",
        ]
    )
    for name, h in (repro.get("file_hashes") or {}).items():
        lines.append(f"  {name}: {h or 'MISSING'}")
    lines.extend(["", "Run summary", "-" * 72])
    lines.append(
        f"{'run_id':<36} {'model':<22} {'baseline':<22} {'delta':<12} "
        f"{'folds':>5} {'oos':>5} {'beat':>4}"
    )
    lines.append("-" * 72)

    for run in manifest.get("runs", []):
        head = run.get("head", "")
        beat = run.get("gates", {}).get("beats_baseline", False)
        folds = f"{run.get('folds_used', '?')}/{run.get('folds_scheduled', '?')}"
        lines.append(
            f"{run.get('run_id', '')[:36]:<36} "
            f"{_fmt_metric(head, run.get('aggregate_metrics', {})):<22} "
            f"{_fmt_metric(head, run.get('baseline_metrics', {})):<22} "
            f"{_fmt_delta(head, run.get('metric_delta', {})):<12} "
            f"{folds:>5} "
            f"{run.get('n_oos', 0):>5} "
            f"{'Y' if beat else 'N':>4}"
        )

    lines.extend(["", "Skipped-fold reasons (aggregate)", "-" * 72])
    reason_counts: dict[str, int] = {}
    for run in manifest.get("runs", []):
        for sk in run.get("skipped_folds") or []:
            reason = sk.get("reason", "?").split("=")[0]
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {reason}: {count}")

    lines.extend(
        [
            "",
            "Notes",
            "-" * 72,
            "  • 'beat' = model beats baseline on primary metric (AUC / MAE / QLIKE).",
            "  • Folds skipped when train rows too sparse (early-era NaN features) or single-class.",
            "  • ETF columns activate only in folds where etf_active=true in fold_ledger.",
            "",
        ]
    )
    return "\n".join(lines)


def write_training_report(manifest_path: Path, txt_path: Path, json_path: Path | None = None) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text = build_report_text(manifest)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(text, encoding="utf-8")
    if json_path:
        summary = {
            "session_id": manifest.get("session_id"),
            "run_count": manifest.get("run_count"),
            "runs": [
                {
                    "run_id": r.get("run_id"),
                    "head": r.get("head"),
                    "aggregate_metrics": r.get("aggregate_metrics"),
                    "baseline_metrics": r.get("baseline_metrics"),
                    "metric_delta": r.get("metric_delta"),
                    "folds_used": r.get("folds_used"),
                    "gates": r.get("gates"),
                }
                for r in manifest.get("runs", [])
            ],
        }
        json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return text
