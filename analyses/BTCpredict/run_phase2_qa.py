#!/usr/bin/env python3
"""Phase 2 feature QA — run after run_phase2_features.py."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, reports_dir
from src.phase2_qa import format_report_text, run_phase2_qa, write_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 2 feature QA")
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    features_path = data_dir() / "features.parquet"
    schema_path = data_dir() / "features_schema.json"
    if not features_path.is_file():
        log.error("Missing %s — run run_phase2_features.py first", features_path)
        return 2

    report = run_phase2_qa(features_path, schema_path)
    json_out = data_dir() / "phase2_qa_report.json"
    txt_out = reports_dir() / "phase2_qa_report.txt"
    write_report(report, json_out, txt_out)

    print(format_report_text(report))
    log.info("Wrote %s and %s", json_out, txt_out)

    if report.errors:
        return 1
    if args.fail_on_warning and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
