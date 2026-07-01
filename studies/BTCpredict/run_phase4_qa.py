#!/usr/bin/env python3
"""Phase 4 QA — run after run_phase4_train.py."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, load_study_config, reports_dir
from src.phase4_qa import format_report_text, run_phase4_qa, write_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 4 QA")
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    cfg = load_study_config()
    manifest = data_dir() / "phase4_training_manifest.json"
    oos = data_dir() / "oos_predictions.parquet"

    report = run_phase4_qa(
        manifest,
        oos,
        holdout_start=str(cfg.splits.holdout_start),
    )
    json_out = data_dir() / "phase4_qa_report.json"
    txt_out = reports_dir() / "phase4_qa_report.txt"
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
