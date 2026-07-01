"""Phase 6 strict QA gates."""
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


@dataclass
class Phase6QAReport:
    run_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    findings: list[QAFinding] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    errors: int = 0
    warnings: int = 0

    def add(self, level: Level, code: str, message: str) -> None:
        self.findings.append(QAFinding(code=code, level=level, message=message))
        if level == "error":
            self.errors += 1
        elif level == "warning":
            self.warnings += 1


def run_phase6_qa(report_path: Path, register: dict[str, Any] | None = None) -> Phase6QAReport:
    from src.backtest_register import load_backtest_register

    reg = register or load_backtest_register()
    qa = Phase6QAReport()

    if not report_path.is_file():
        qa.add("error", "P6-MISSING", f"Missing backtest report: {report_path}")
        return qa

    report = json.loads(report_path.read_text(encoding="utf-8"))
    completion = reg.get("completion", {})
    gates = reg.get("gates", {}).get("phase6_dev", {})

    best = report.get("best_config") or {}
    qa.checks["best_config_present"] = bool(best)
    if completion.get("errors_on") and "missing_best_config" in completion["errors_on"]:
        if not best:
            qa.add("error", "P6-NO-BEST", "phase6_best_config missing from report")

    proxy = report.get("proxy_sweep") or []
    qa.checks["proxy_run_count"] = len(proxy)
    if len(proxy) == 0:
        qa.add("error", "P6-NO-PROXY", "Proxy sweep produced zero runs")

    smoke = report.get("chain_smoke") or {}
    qa.checks["chain_smoke"] = smoke
    if completion.get("chain_smoke_required"):
        fwd = int(smoke.get("fires_with_data", 0))
        if smoke.get("status") == "ok" and fwd <= 0:
            qa.add("error", "P6-SMOKE-ZERO", "Chain smoke had zero fires_with_data")
        elif smoke.get("status") == "skipped" and smoke.get("reason") == "no_chain_dates":
            qa.add("warning", "P6-SMOKE-SKIP", "No chain dates available for smoke")

    required = completion.get("proxy_gates_required", ["G1", "G3", "G4"])
    if best and proxy:
        best_row = next((r for r in proxy if r.get("run_id", "").startswith("proxy_") and
                         r.get("horizon_id") == best.get("horizon_id") and
                         r.get("vrp_threshold") == best.get("vrp_threshold") and
                         r.get("tilt_mode") == best.get("tilt_mode") and
                         r.get("min_physical_edge") == best.get("min_physical_edge")), best)

        naive_rows = report.get("naive_baselines") or []
        naive = next((n for n in naive_rows if n.get("horizon_id") == best.get("horizon_id")), None)

        if "G1" in required:
            beats = best_row.get("beats_naive") or best.get("beats_naive")
            qa.checks["G1_beats_naive"] = beats
            if not beats:
                qa.add("warning", "P6-G1", "Best config did not beat naive VRP baseline (G1)")

        max_cvar = 0.15
        cvar = best_row.get("cvar", best.get("cvar"))
        qa.checks["G3_cvar"] = cvar
        if "G3" in required and cvar is not None:
            try:
                cap = -float(max_cvar)
                if float(cvar) < cap:
                    qa.add("warning", "P6-G3", f"Proxy CVaR {cvar:.3f} below {cap:.3f} (vol-point proxy)")
            except (TypeError, ValueError):
                qa.add("warning", "P6-G3", "CVaR not computable for best config")

        exp = best_row.get("expectancy", best.get("expectancy"))
        qa.checks["G4_expectancy"] = exp
        if "G4" in required:
            try:
                if not (exp is not None and float(exp) > 0):
                    qa.add("warning", "P6-G4", f"Expectancy not positive: {exp}")
            except (TypeError, ValueError):
                qa.add("warning", "P6-G4", "Expectancy not computable")

    qa.add("info", "P6-PROXY", f"Proxy sweep completed with {len(proxy)} runs")
    return qa


def format_report_text(report: Phase6QAReport) -> str:
    lines = [
        "BTCpredict Phase 6 QA",
        f"Run: {report.run_at}",
        f"Errors: {report.errors}  Warnings: {report.warnings}",
        "",
    ]
    for f in report.findings:
        lines.append(f"  [{f.level.upper()}] {f.code}: {f.message}")
    lines.append("")
    lines.append(f"Overall: {'FAIL' if report.errors else 'PASS'}")
    return "\n".join(lines)


def write_report(report: Phase6QAReport, json_path: Path, txt_path: Path) -> None:
    json_path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    txt_path.write_text(format_report_text(report) + "\n", encoding="utf-8")
