#!/usr/bin/env python3
"""Phase 3 label QA — run after run_phase3_labels.py."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, reports_dir
from src.phase3_qa import format_report_text, run_phase3_qa, write_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 3 label QA")
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    labels_path = data_dir() / "labels.parquet"
    schema_path = data_dir() / "labels_schema.json"
    features_path = data_dir() / "features.parquet"
    if not labels_path.is_file():
        log.error("Missing %s — run run_phase3_labels.py first", labels_path)
        return 2

    report = run_phase3_qa(labels_path, schema_path, features_path)
    json_out = data_dir() / "phase3_qa_report.json"
    txt_out = reports_dir() / "phase3_qa_report.txt"
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
