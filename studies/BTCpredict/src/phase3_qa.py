"""Phase 3 label QA — schema, causality guards, distribution sanity."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

log = logging.getLogger(__name__)

Level = Literal["error", "warning", "info"]
EXPECTED_LABEL_NAMES = 36
OPTIONS_LABEL_PREFIXES = ("exceedance_", "vrp_realized_")
BINARY_PREFIXES = ("up_win_", "down_win_", "magnitude_win_", "exceedance_")
# KICKOFF §1.3: sustained directional accuracy ≥ 60% is a leakage alarm.
MAX_DIRECTIONAL_HIT_RATE = 0.65


@dataclass
class QAFinding:
    code: str
    level: Level
    message: str


@dataclass
class Phase3QAReport:
    run_at: str
    rows: int
    label_names: int
    errors: int = 0
    warnings: int = 0
    findings: list[QAFinding] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)

    def add(self, level: Level, code: str, message: str) -> None:
        self.findings.append(QAFinding(code=code, level=level, message=message))
        if level == "error":
            self.errors += 1
        elif level == "warning":
            self.warnings += 1


def check_duplicate_keys(df: pd.DataFrame, report: Phase3QAReport) -> None:
    dupes = df.duplicated(subset=["timestamp", "asset", "horizon_id", "label_name"], keep=False)
    if dupes.any():
        report.add("error", "DUP_KEYS", f"Duplicate label keys: {int(dupes.sum())} rows")


def check_label_name_count(df: pd.DataFrame, report: Phase3QAReport) -> None:
    n = df["label_name"].nunique()
    if n != EXPECTED_LABEL_NAMES:
        report.add("error", "LABEL_COUNT", f"Expected {EXPECTED_LABEL_NAMES} label names, got {n}")


def check_sol_excludes_options_labels(df: pd.DataFrame, report: Phase3QAReport) -> None:
    sol = df[df["asset"] == "SOL"]
    bad = sol[sol["label_name"].str.startswith(OPTIONS_LABEL_PREFIXES)]
    if not bad.empty:
        report.add("error", "SOL_OPTIONS", f"SOL has {len(bad)} exceedance/vrp rows (expected 0)")


def check_binary_values(df: pd.DataFrame, report: Phase3QAReport) -> None:
    mask = df["label_name"].str.startswith(BINARY_PREFIXES)
    bad = df[mask & ~df["value"].isin([0.0, 1.0])]
    if not bad.empty:
        report.add("error", "BINARY_VALUES", f"Non 0/1 values in binary labels: {len(bad)} rows")


def check_trailing_bars_absent(
    df: pd.DataFrame,
    report: Phase3QAReport,
    features_path: Path | None,
) -> None:
    """Last H calendar rows per asset should have no labels (incomplete forward window)."""
    if features_path is None or not features_path.is_file():
        report.add("warning", "TRAILING_SKIP", "No features.parquet — skipped trailing-bar check")
        return
    feat = pd.read_parquet(features_path, columns=["timestamp", "asset"])
    horizon_tail = {"T+1d": 1, "T+5d": 5, "T+10-21d": 14}
    for asset, grp in feat.groupby("asset"):
        max_ts = grp["timestamp"].max()
        on_last = df[(df["asset"] == asset) & (df["timestamp"] == max_ts)]
        if not on_last.empty:
            report.add(
                "error",
                "TRAILING_LEAK",
                f"{asset} has {len(on_last)} labels on last bar {max_ts}",
            )
        for hid, h in horizon_tail.items():
            asset_ts = sorted(grp["timestamp"].unique())
            if len(asset_ts) < h:
                continue
            tail_ts = set(asset_ts[-h:])
            leaked = df[(df["asset"] == asset) & (df["horizon_id"] == hid) & (df["timestamp"].isin(tail_ts))]
            if not leaked.empty:
                report.add(
                    "error",
                    "TRAILING_H",
                    f"{asset}/{hid}: {len(leaked)} labels in trailing {h} bars",
                )


def check_directional_hit_rates(df: pd.DataFrame, report: Phase3QAReport) -> None:
    for name in df["label_name"].unique():
        if not name.startswith(("up_win_", "down_win_", "magnitude_win_")):
            continue
        sub = df[df["label_name"] == name]
        rate = sub["value"].mean()
        if rate > MAX_DIRECTIONAL_HIT_RATE:
            report.add(
                "warning",
                "DIR_HIT_HIGH",
                f"{name}: hit rate {rate:.1%} > {MAX_DIRECTIONAL_HIT_RATE:.0%} (leakage alarm)",
            )


def check_exceedance_rates(df: pd.DataFrame, report: Phase3QAReport) -> None:
    for name in df["label_name"].unique():
        if not name.startswith("exceedance_"):
            continue
        # Parse delta from name like exceedance_call_d0p15_h5
        parts = name.split("_d")
        if len(parts) < 2:
            continue
        delta_str = parts[1].split("_h")[0].replace("p", ".")
        try:
            delta = float(delta_str)
        except ValueError:
            continue
        rate = df[df["label_name"] == name]["value"].mean()
        if not (0.5 * delta < rate < 2.5 * delta + 0.05):
            report.add(
                "warning",
                "EXCEEDANCE_CALIB",
                f"{name}: hit rate {rate:.1%} vs target δ≈{delta:.0%}",
            )


def run_phase3_qa(
    labels_path: Path,
    schema_path: Path | None = None,
    features_path: Path | None = None,
) -> Phase3QAReport:
    df = pd.read_parquet(labels_path)
    schema: dict[str, Any] = {}
    if schema_path and schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

    report = Phase3QAReport(
        run_at=datetime.now(timezone.utc).isoformat(),
        rows=len(df),
        label_names=int(df["label_name"].nunique()),
        schema=schema,
    )

    check_duplicate_keys(df, report)
    check_label_name_count(df, report)
    check_sol_excludes_options_labels(df, report)
    check_binary_values(df, report)
    check_trailing_bars_absent(df, report, features_path)
    check_directional_hit_rates(df, report)
    check_exceedance_rates(df, report)

    return report


def format_report_text(report: Phase3QAReport) -> str:
    lines = [
        f"Phase 3 QA — {report.run_at}",
        f"rows={report.rows} label_names={report.label_names}",
        f"errors={report.errors} warnings={report.warnings}",
        "",
    ]
    for f in report.findings:
        lines.append(f"[{f.level.upper()}] {f.code}: {f.message}")
    if not report.findings:
        lines.append("No findings.")
    return "\n".join(lines)


def write_report(report: Phase3QAReport, json_path: Path, txt_path: Path | None = None) -> None:
    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if txt_path is not None:
        txt_path.write_text(format_report_text(report) + "\n", encoding="utf-8")
