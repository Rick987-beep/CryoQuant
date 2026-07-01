"""Phase 7 QA — one-shot guard and leak checks."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from src.holdout_register import load_holdout_register
from src.paths import splits_path

Level = Literal["error", "warning", "info"]


@dataclass
class QAFinding:
    code: str
    level: Level
    message: str


@dataclass
class Phase7QAReport:
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


class HoldoutAlreadyTouchedError(RuntimeError):
    pass


def guard_path(data_dir: Path, register: dict[str, Any] | None = None) -> Path:
    reg = register or load_holdout_register()
    rel = reg.get("one_shot", {}).get("guard_file", "data/phase7_holdout_touched.json")
    name = Path(rel).name
    return data_dir / name


def check_one_shot(data_dir: Path, *, force: bool = False) -> None:
    reg = load_holdout_register()
    path = guard_path(data_dir, reg)
    if path.is_file() and not force:
        raise HoldoutAlreadyTouchedError(
            f"Hold-out already evaluated ({path}). Use --force with principal approval."
        )


def write_one_shot_guard(data_dir: Path, metadata: dict[str, Any]) -> Path:
    path = guard_path(data_dir)
    payload = {
        "touched_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run_phase7_qa(
    cfg: Any,
    data_dir: Path,
    reports_dir: Path,
    *,
    register: dict[str, Any] | None = None,
) -> Phase7QAReport:
    reg = register or load_holdout_register()
    qa = Phase7QAReport()

    if not splits_path().is_file():
        qa.add("error", "P7-NO-SPLITS", f"Missing {splits_path()}")

    ho_path = data_dir / "holdout_predictions.parquet"
    qa.checks["holdout_predictions_exists"] = ho_path.is_file()
    if not ho_path.is_file():
        qa.add("error", "P7-NO-PREDS", "holdout_predictions.parquet missing")
        return qa

    preds = pd.read_parquet(ho_path)
    preds["timestamp"] = pd.to_datetime(preds["timestamp"], utc=True)
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    leak = preds[preds["timestamp"] < holdout]
    qa.checks["holdout_rows"] = len(preds[preds["timestamp"] >= holdout])
    qa.checks["leak_rows"] = len(leak)
    if len(leak) > 0:
        qa.add("error", "P7-LEAK", f"{len(leak)} prediction rows before holdout_start")

    eff = pd.Timestamp(reg.get("chain_eval", {}).get("effective_start", "2025-04-11"), tz="UTC")
    report_path = data_dir / "phase7_holdout_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        cw = report.get("chain_window", {})
        qa.checks["chain_window"] = cw
        if cw.get("first_date") and pd.Timestamp(cw["first_date"], tz="UTC") < eff:
            qa.add("error", "P7-EARLY-CHAIN", "Chain eval includes dates before effective_start")
        if "best_config" in report:
            qa.add("error", "P7-CHERRY", "hold-out report must not contain best_config selection")
        gates = report.get("gates", {})
        qa.checks["gates"] = gates
        if not gates.get("G2_primary", {}).get("pass"):
            qa.add("warning", "P7-G2", "Primary gate G2 failed — valid null result")
        if not gates.get("G1_secondary", {}).get("pass"):
            qa.add("info", "P7-G1", "Secondary gate G1 (beat naive seller) not passed")

    results_md = reports_dir / "RESULTS.md"
    qa.checks["results_md_exists"] = results_md.is_file()
    if results_md.is_file():
        text = results_md.read_text(encoding="utf-8")
        for section in ("Dev recap", "Hold-out inference", "Chain window", "Physical P(OTM)"):
            if section not in text:
                qa.add("error", "P7-RESULTS", f"RESULTS.md missing section: {section}")
        if "n_trades" not in text.lower() and "trades" not in text.lower():
            qa.add("warning", "P7-N-TRADES", "RESULTS.md should report trade counts")

    qa.add("info", "P7-OK", f"Hold-out QA complete ({qa.checks.get('holdout_rows', 0)} prediction rows)")
    return qa


def format_report_text(report: Phase7QAReport) -> str:
    lines = [
        "BTCpredict Phase 7 QA",
        f"Run: {report.run_at}",
        f"Errors: {report.errors}  Warnings: {report.warnings}",
        "",
    ]
    for f in report.findings:
        lines.append(f"  [{f.level.upper()}] {f.code}: {f.message}")
    lines.append("")
    lines.append(f"Overall: {'FAIL' if report.errors else 'PASS'}")
    return "\n".join(lines)


def write_report(report: Phase7QAReport, json_path: Path, txt_path: Path) -> None:
    json_path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    txt_path.write_text(format_report_text(report) + "\n", encoding="utf-8")
