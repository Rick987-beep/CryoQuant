"""Phase 5 strict QA gates."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Level = Literal["error", "warning", "info"]


@dataclass
class QAFinding:
    code: str
    level: Level
    message: str
    run_id: str | None = None


@dataclass
class Phase5QAReport:
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


def run_phase5_qa(report_path: Path, register: dict[str, Any] | None = None) -> Phase5QAReport:
    from src.validation_register import load_validation_register

    reg = register or load_validation_register()
    qa = Phase5QAReport()

    if not report_path.is_file():
        qa.add("error", "P5-MISSING", f"Missing validation report: {report_path}")
        return qa

    report = json.loads(report_path.read_text(encoding="utf-8"))
    completion = reg.get("completion", {})

    harness = report.get("harness_checks") or {}
    qa.checks["trial_log_count"] = report.get("trial_log_count")
    qa.checks["directional_null"] = report.get("directional_null_summary")

    if harness.get("holdout_leak_rows", 0) > 0:
        qa.add(
            "error",
            "P5-HOLDOUT-LEAK",
            f"{harness['holdout_leak_rows']} OOS rows in hold-out",
        )

    if not harness.get("walk_forward_ok", False):
        qa.add("error", "P5-EMBARGO-WF", "walk_forward embargo wiring failed")
    if not harness.get("purged_kfold_ok", False):
        qa.add("error", "P5-EMBARGO-PKF", "purged_kfold embargo wiring failed")

    leak = report.get("leakage") or {}
    name_flags = [f for f in leak.get("flags", []) if f.get("reason") == "name_pattern"]
    if name_flags:
        qa.add(
            "error",
            "P5-LEAK-NAME",
            f"{len(name_flags)} feature(s) with suspicious names",
        )
    corr_flags = [f for f in leak.get("flags", []) if f.get("reason") == "high_correlation"]
    if corr_flags:
        qa.add(
            "warning",
            "P5-LEAK-CORR",
            f"{len(corr_flags)} feature-label pairs with |ρ|>threshold",
        )

    exc = report.get("exceedance_calibration") or []
    qa.checks["exceedance_overlay_count"] = len(exc)
    if completion.get("exceedance_overlay_required") and len(exc) == 0:
        qa.add("error", "P5-NO-EXCEEDANCE", "Exceedance calibration overlay empty")

    vol_perms = [p for p in report.get("permutation", []) if p.get("head") == "realized_vol"]
    vol_beats = sum(1 for p in vol_perms if p.get("beats_null"))
    vol_manifest = sum(1 for p in vol_perms if p.get("manifest_beats_baseline"))
    qa.checks["vol_permutation_beats"] = vol_beats
    qa.checks["vol_manifest_beats"] = vol_manifest
    qa.checks["vol_permutation_total"] = len(vol_perms)
    p_max = float(reg.get("permutation", {}).get("vol_gate_p_max", 0.05))
    if completion.get("vol_permutation_required") and vol_perms:
        if vol_manifest < len(vol_perms):
            qa.add(
                "error",
                "P5-VOL-BASE",
                f"Only {vol_manifest}/{len(vol_perms)} vol runs beat HAR in Phase 4 manifest",
            )
        perm_fail = [p["run_id"] for p in vol_perms if not p.get("beats_null")]
        if len(perm_fail) > len(vol_perms) // 2:
            qa.add(
                "warning",
                "P5-VOL-PERM",
                f"Feature-permutation null not rejected for {len(perm_fail)} vol run(s) (p>{p_max})",
            )

    dir_sum = report.get("directional_null_summary") or {}
    if dir_sum.get("status") == "confirmed_null":
        qa.add(
            "info",
            "P5-DIR-NULL",
            f"Directional dev null confirmed (mean AUC={dir_sum.get('mean_auc', '?'):.3f})",
        )

    perm = report.get("permutation") or []
    qa.checks["permutation_run_count"] = len(perm)
    if len(perm) < 48 and not any(p.get("skipped") for p in perm):
        qa.add("warning", "P5-PERM-COUNT", f"Only {len(perm)} permutation results (expected 48)")

    return qa


def format_report_text(report: Phase5QAReport) -> str:
    lines = [
        "BTCpredict Phase 5 QA",
        f"Run: {report.run_at}",
        f"Errors: {report.errors}  Warnings: {report.warnings}",
        "",
    ]
    for f in report.findings:
        rid = f" ({f.run_id})" if f.run_id else ""
        lines.append(f"  [{f.level.upper()}] {f.code}{rid}: {f.message}")
    if not report.findings:
        lines.append("  (no findings)")
    lines.append("")
    lines.append(f"Overall: {'FAIL' if report.errors else 'PASS'}")
    return "\n".join(lines)


def write_report(report: Phase5QAReport, json_path: Path, txt_path: Path) -> None:
    json_path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    txt_path.write_text(format_report_text(report) + "\n", encoding="utf-8")
