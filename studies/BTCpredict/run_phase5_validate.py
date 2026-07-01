#!/usr/bin/env python3
"""Phase 5 — statistical validation harness."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, load_study_config, reports_dir
from src.phase5_qa import format_report_text, run_phase5_qa, write_report
from src.phase5_report import write_validation_report
from src.phase5_validate import run_phase5_validation, write_validation_report as write_json

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 5 validation")
    parser.add_argument("--smoke", action="store_true", help="Smoke: permute smoke_btc_up_h1 only")
    parser.add_argument("--skip-permutation", action="store_true", help="Skip permutation battery")
    parser.add_argument("--run-id", type=str, default=None, help="Single run_id for permutation")
    parser.add_argument("--permutation-only", action="store_true", help="Re-run permutation only")
    parser.add_argument("--max-runs", type=int, default=None, help="Limit permutation runs")
    parser.add_argument("--qa-only", action="store_true", help="Re-run QA on existing report")
    args = parser.parse_args()

    cfg = load_study_config()
    if not cfg.phase4_5_complete:
        log.error("phase4_5_complete must be true before Phase 5")
        return 2

    json_out = data_dir() / "validation_report.json"
    txt_out = reports_dir() / "phase5_validation_report.txt"

    if not args.qa_only:
        log.info("Phase 5 validation starting")
        report = run_phase5_validation(
            cfg,
            smoke=args.smoke,
            skip_permutation=args.skip_permutation,
            max_runs=args.max_runs,
            run_id=args.run_id,
            permutation_only=args.permutation_only,
        )
        write_json(report, json_out)
        log.info("Wrote %s", json_out)
        write_validation_report(json_out, txt_out)
        log.info("Wrote %s", txt_out)

    qa = run_phase5_qa(json_out)
    qa_json = data_dir() / "phase5_qa_report.json"
    qa_txt = reports_dir() / "phase5_qa_report.txt"
    write_report(qa, qa_json, qa_txt)
    print(format_report_text(qa))
    log.info("Wrote %s and %s", qa_json, qa_txt)

    return 1 if qa.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
