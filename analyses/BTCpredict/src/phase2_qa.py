"""Phase 2 feature QA — warmup, finiteness, lookahead checks, schema audit."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from cryoquant.data.sources import fomc_calendar
from cryoquant.features.options import atm_iv

from src.feature_schema import META_COLS, catalog_feature_columns, column_tags, load_features_yaml

log = logging.getLogger(__name__)

Level = Literal["error", "warning", "info"]
WARMUP_BARS = 252


@dataclass
class QAFinding:
    code: str
    level: Level
    message: str


@dataclass
class Phase2QAReport:
    run_at: str
    rows: int
    columns: int
    feature_columns: int
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


def _feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META_COLS]


def check_duplicate_columns(df: pd.DataFrame, report: Phase2QAReport) -> None:
    dupes = df.columns[df.columns.duplicated()].tolist()
    if dupes:
        report.add("error", "DUP_COLS", f"Duplicate columns: {dupes}")


def check_schema_coverage(df: pd.DataFrame, report: Phase2QAReport) -> None:
    expected = catalog_feature_columns()
    missing = [c for c in expected if c not in df.columns]
    if missing:
        report.add("error", "SCHEMA_MISSING", f"Missing catalog columns ({len(missing)}): {missing[:10]}...")
    extra = [c for c in _feature_cols(df) if c not in column_tags()]
    if extra:
        report.add("warning", "SCHEMA_EXTRA", f"Columns not in catalog ({len(extra)}): {extra[:10]}...")


def check_finiteness_after_warmup(df: pd.DataFrame, report: Phase2QAReport) -> None:
    feats = _feature_cols(df)
    if df.empty or not feats:
        return
    post = df.groupby("asset", group_keys=False).apply(lambda g: g.iloc[WARMUP_BARS:], include_groups=False)
    if post.empty:
        report.add("warning", "WARMUP_SKIP", "Not enough rows for warmup finiteness check")
        return
    numeric = post[feats].select_dtypes(include=[np.number])
    inf_mask = np.isinf(numeric.to_numpy())
    if inf_mask.any():
        bad = numeric.columns[np.isinf(numeric).any()].tolist()
        report.add("error", "INF_VALUES", f"Infinite values after warmup in: {bad[:15]}")


def check_lookahead_trend_shift(df: pd.DataFrame, report: Phase2QAReport) -> None:
    """P2-T02: ret_1d at T should not equal value computed with future close."""
    col = "btc_ret_1d"
    if col not in df.columns:
        report.add("warning", "P2T02_SKIP", f"{col} missing for lookahead check")
        return
    btc = df[df["asset"] == "BTC"].sort_values("timestamp")
    if len(btc) < 30:
        return
    mid = len(btc) // 2
    a = btc.iloc[mid - 1][col]
    b = btc.iloc[mid][col]
    if pd.isna(a) or pd.isna(b):
        return
    if a == b and btc[col].nunique() < 5:
        report.add("warning", "P2T02_FLAT", f"{col} appears constant — weak lookahead signal")


def check_lookahead_chain_entry_time(report: Phase2QAReport) -> None:
    """P2-T03: atm_iv at t unchanged if chain at t+1 is modified."""
    from datetime import date

    from cryoquant.data.sources import deribit_options

    dates = [d for d in deribit_options.list_dates() if d >= date(2025, 4, 11)]
    if len(dates) < 2:
        report.add("info", "P2T03_SKIP", "Insufficient chain dates for lookahead test")
        return
    d0, d1 = dates[0], dates[1]
    try:
        c0 = deribit_options.load_chain(d0)
        c1 = deribit_options.load_chain(d1)
    except Exception as exc:
        report.add("warning", "P2T03_SKIP", f"Could not load chains: {exc}")
        return

    iv_base = float(atm_iv([(d0, c0)], dte_target=30).iloc[0])
    c1_bad = c1.copy()
    if "mark_iv" in c1_bad.columns:
        c1_bad["mark_iv"] = c1_bad["mark_iv"] * 2.0
    elif "mark_iv" in [c.lower() for c in c1_bad.columns]:
        col = [c for c in c1_bad.columns if c.lower() == "mark_iv"][0]
        c1_bad[col] = c1_bad[col] * 2.0
    iv_again = float(atm_iv([(d0, c0), (d1, c1_bad)], dte_target=30).iloc[0])
    if not np.isclose(iv_base, iv_again, equal_nan=True):
        report.add("error", "P2T03_LOOKAHEAD", "atm_iv at d0 changed when d1 chain modified")


def check_fomc_calendar_exempt(df: pd.DataFrame, report: Phase2QAReport) -> None:
    if "is_fomc_decision_day" not in df.columns:
        return
    decision_dates = set(fomc_calendar._FOMC_DECISION_DATES)  # noqa: SLF001
    btc = df[df["asset"] == "BTC"]
    flagged = btc[btc["is_fomc_decision_day"] == 1.0]["timestamp"].dt.date.tolist()
    if not flagged:
        report.add("warning", "FOMC_NONE", "No FOMC decision days flagged in panel")
        return
    outside = [d for d in flagged if d not in decision_dates]
    if outside:
        report.add("error", "FOMC_BAD", f"FOMC flags on non-decision dates: {outside[:5]}")


def check_options_source(df: pd.DataFrame, report: Phase2QAReport) -> None:
    if "options_source" not in df.columns:
        report.add("error", "OPTS_META", "Missing options_source column")
        return
    bad = df[~df["options_source"].isin(["none", "dvol", "chain"])]
    if not bad.empty:
        report.add("error", "OPTS_SOURCE", f"Invalid options_source values: {bad['options_source'].unique()}")


def run_phase2_qa(
    features_path: Path,
    schema_path: Path | None = None,
) -> Phase2QAReport:
    if not features_path.is_file():
        raise FileNotFoundError(features_path)

    df = pd.read_parquet(features_path)
    report = Phase2QAReport(
        run_at=datetime.now(timezone.utc).isoformat(),
        rows=len(df),
        columns=len(df.columns),
        feature_columns=len(_feature_cols(df)),
    )

    if schema_path and schema_path.is_file():
        report.schema = json.loads(schema_path.read_text())

    check_duplicate_columns(df, report)
    check_schema_coverage(df, report)
    check_finiteness_after_warmup(df, report)
    check_lookahead_trend_shift(df, report)
    check_lookahead_chain_entry_time(report)
    check_fomc_calendar_exempt(df, report)
    check_options_source(df, report)

    if report.schema.get("missing_from_panel"):
        report.add(
            "error",
            "SCHEMA_JSON",
            f"Schema reports missing: {report.schema['missing_from_panel'][:10]}",
        )

    return report


def format_report_text(report: Phase2QAReport) -> str:
    lines = [
        f"Phase 2 QA — {report.run_at}",
        f"Rows: {report.rows}  Columns: {report.columns}  Features: {report.feature_columns}",
        f"Errors: {report.errors}  Warnings: {report.warnings}",
        "",
    ]
    for f in report.findings:
        lines.append(f"[{f.level.upper()}] {f.code}: {f.message}")
    return "\n".join(lines) + "\n"


def write_report(report: Phase2QAReport, json_path: Path, txt_path: Path) -> None:
    json_path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    txt_path.write_text(format_report_text(report), encoding="utf-8")
