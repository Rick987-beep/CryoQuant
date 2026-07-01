#!/usr/bin/env python3
"""Phase 1 data QA — run after ingest, before Phase 2 feature engineering."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, reports_dir
from src.phase1_qa import format_report_text, run_phase1_qa, write_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 1 data QA")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to ingest_manifest.json (default: data/ingest_manifest.json)",
    )
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit 1 on warnings too")
    args = parser.parse_args()

    manifest_path = args.manifest or (data_dir() / "ingest_manifest.json")
    if not manifest_path.is_file():
        log.error("Missing manifest: %s", manifest_path)
        return 2

    log.info("Running Phase 1 QA on %s", manifest_path)
    report = run_phase1_qa(manifest_path)

    json_out = data_dir() / "phase1_qa_report.json"
    txt_out = reports_dir() / "phase1_qa_report.txt"
    write_report(report, json_out, txt_out)

    print(format_report_text(report))
    log.info("Wrote %s and %s", json_out, txt_out)

    if report.errors:
        log.error("QA failed with %d error(s)", report.errors)
        return 1
    if args.fail_on_warning and report.warnings:
        log.error("QA failed with %d warning(s)", report.warnings)
        return 1
    log.info("QA passed (%d warning(s))", report.warnings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
