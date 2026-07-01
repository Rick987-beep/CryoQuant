"""Phase 4.5 strict QA — auditable training gates (mirrors Phase 1–3 finding pattern)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np

from src.repro_bundle import repro_bundle_complete

Level = Literal["error", "warning", "info"]


@dataclass
class QAFinding:
    code: str
    level: Level
    message: str
    run_id: str | None = None


@dataclass
class Phase4QAReport:
    run_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    findings: list[QAFinding] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    errors: int = 0
    warnings: int = 0

    def add(self, level: Level, code: str, message: str, run_id: str | None = None) -> None:
        self.findings.append(QAFinding(code=code, level=level, message=message, run_id=run_id))
        if level == "error":
            self.errors += 1
        elif level == "warning":
            self.warnings += 1


def _min_folds_for_asset(asset: str) -> int:
    return 3 if asset == "SOL" else 5


def run_phase4_qa(
    manifest_path: Path,
    oos_path: Path | None = None,
    *,
    holdout_start: str = "2024-06-01",
    manifest_version: int = 2,
) -> Phase4QAReport:
    report = Phase4QAReport()
    if not manifest_path.is_file():
        report.add("error", "P45-MISSING", f"Missing manifest: {manifest_path}")
        return report

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("version", 1)
    report.checks["manifest_version"] = version

    if version < manifest_version:
        report.add(
            "error",
            "P45-VERSION",
            f"Manifest version {version} < {manifest_version} — re-run training with Phase 4.5",
        )

    repro = manifest.get("reproducibility") or {}
    report.checks["session_id"] = manifest.get("session_id")
    if not repro_bundle_complete(repro):
        report.add("error", "P45-REPRO", "Reproducibility bundle incomplete (missing file hashes)")

    runs = manifest.get("runs", [])
    report.checks["run_count"] = len(runs)
    if len(runs) == 0:
        report.add("error", "P45-EMPTY", "Training manifest has zero runs")
        return report

    beats_count = 0
    for run in runs:
        rid = run.get("run_id")
        status = run.get("status")
        head = run.get("head", "")
        asset = run.get("asset", "")

        if status == "error":
            report.add("error", "P45-RUN-FAIL", f"Run failed: {run.get('error')}", rid)
            continue
        if status == "empty":
            report.add("error", "P45-RUN-EMPTY", "Run produced no completed folds", rid)
            continue

        base = run.get("baseline_metrics") or {}
        if not base:
            report.add("error", "P45-NO-BASELINE", "baseline_metrics empty", rid)

        ledger = run.get("fold_ledger") or []
        if not ledger and version >= 2:
            report.add("error", "P45-NO-LEDGER", "fold_ledger missing", rid)

        folds_used = run.get("folds_used", len(ledger))
        min_f = _min_folds_for_asset(asset)
        if folds_used < min_f:
            report.add(
                "error",
                "P45-FOLDS",
                f"Only {folds_used} folds used (min {min_f} for {asset})",
                rid,
            )

        skipped = run.get("folds_skipped", 0)
        scheduled = run.get("folds_scheduled", 0)
        if scheduled > 0 and skipped / scheduled > 0.35:
            report.add(
                "warning",
                "P45-SKIP-RATE",
                f"High skip rate: {skipped}/{scheduled} folds skipped",
                rid,
            )

        agg = run.get("aggregate_metrics") or {}
        gates = run.get("gates") or {}

        if head == "directional":
            auc = agg.get("auc")
            if auc is not None and np.isfinite(auc):
                if auc > 0.60:
                    report.add(
                        "error",
                        "P45-AUC-HIGH",
                        f"AUC={auc:.3f} > 0.60 — leakage alarm (SPEC §10.2)",
                        rid,
                    )
                elif auc < 0.52:
                    report.add(
                        "info",
                        "P45-AUC-LOW",
                        f"AUC={auc:.3f} below 0.52 floor (no directional edge)",
                        rid,
                    )

        if head == "log_return_bench":
            r2 = agg.get("r2")
            if r2 is not None and np.isfinite(r2) and r2 > 0.20:
                report.add(
                    "error",
                    "P45-R2-HIGH",
                    f"R²={r2:.3f} > 0.20 — leakage alarm (SPEC §10.2)",
                    rid,
                )

        if gates.get("beats_baseline") is True:
            beats_count += 1
        elif base and status == "ok":
            report.add(
                "warning",
                "P45-BEAT-BASE",
                "Did not beat baseline on primary metric",
                rid,
            )

        n_oos = run.get("n_oos", 0)
        if n_oos < 20 and asset != "SOL":
            report.add("warning", "P45-OOS-LOW", f"Only {n_oos} OOS rows", rid)

    report.checks["beats_baseline_count"] = beats_count
    report.checks["beats_baseline_pct"] = round(100.0 * beats_count / max(len(runs), 1), 1)

    if oos_path and oos_path.is_file():
        import pandas as pd

        oos = pd.read_parquet(oos_path)
        oos["timestamp"] = pd.to_datetime(oos["timestamp"], utc=True)
        holdout = pd.Timestamp(holdout_start, tz="UTC")
        leak = oos[oos["timestamp"] >= holdout]
        report.checks["oos_rows"] = len(oos)
        if len(leak) > 0:
            report.add(
                "error",
                "P45-HOLDOUT-LEAK",
                f"{len(leak)} OOS rows >= {holdout_start}",
            )
    elif oos_path:
        report.add("error", "P45-NO-OOS", f"Missing OOS parquet: {oos_path}")

    report.checks["ok_runs"] = sum(1 for r in runs if r.get("status") == "ok")
    return report


def format_report_text(report: Phase4QAReport) -> str:
    lines = [
        "BTCpredict Phase 4 QA (strict)",
        f"Run: {report.run_at}",
        f"Runs checked: {report.checks.get('run_count', '?')}  "
        f"ok={report.checks.get('ok_runs', '?')}  "
        f"beat baseline: {report.checks.get('beats_baseline_count', '?')} "
        f"({report.checks.get('beats_baseline_pct', '?')}%)",
        f"Errors: {report.errors}  Warnings: {report.warnings}",
        "",
    ]
    for f in report.findings:
        prefix = f"[{f.level.upper()}] {f.code}"
        rid = f" ({f.run_id})" if f.run_id else ""
        lines.append(f"  {prefix}{rid}: {f.message}")
    if not report.findings:
        lines.append("  (no findings)")
    lines.append("")
    lines.append(f"Overall: {'FAIL' if report.errors else 'PASS'}")
    return "\n".join(lines)


def write_report(report: Phase4QAReport, json_path: Path, txt_path: Path) -> None:
    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    txt_path.write_text(format_report_text(report) + "\n", encoding="utf-8")
