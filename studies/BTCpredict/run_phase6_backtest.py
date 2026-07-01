#!/usr/bin/env python3
"""Phase 6 — dev VRP proxy backtest + chain infra smoke."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, load_study_config, reports_dir
from src.phase6_backtest import run_phase6_backtest, write_phase6_artifacts
from src.phase6_qa import format_report_text, run_phase6_qa, write_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 6 backtest")
    parser.add_argument("--smoke", action="store_true", help="Minimal proxy sweep")
    parser.add_argument("--qa-only", action="store_true", help="Re-run QA on existing report")
    parser.add_argument("--force", action="store_true", help="Overwrite outputs")
    args = parser.parse_args()

    cfg = load_study_config()
    if not cfg.phase5_complete:
        log.error("phase5_complete must be true before Phase 6")
        return 2

    json_out = data_dir() / "phase6_backtest_report.json"

    if not args.qa_only:
        log.info("Phase 6 backtest starting")
        report = run_phase6_backtest(cfg, smoke=args.smoke, data_dir=data_dir())
        write_phase6_artifacts(report, data_dir(), reports_dir())
        log.info("Wrote %s", json_out)

    qa = run_phase6_qa(json_out)
    qa_json = data_dir() / "phase6_qa_report.json"
    qa_txt = reports_dir() / "phase6_qa_report.txt"
    write_report(qa, qa_json, qa_txt)
    print(format_report_text(qa))

    if qa.errors == 0 and not args.qa_only:
        _mark_phase6_complete()

    return 1 if qa.errors else 0


def _mark_phase6_complete() -> None:
    """Set phase6_complete in config.yaml when gates pass."""
    import re
    from datetime import date

    path = ROOT / "config.yaml"
    text = path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    if "phase6_complete:" not in text:
        text = text.rstrip() + f"\nphase6_complete: true\nphase6_complete_date: \"{today}\"\n"
    else:
        text = re.sub(r"phase6_complete:\s*\w+", "phase6_complete: true", text)
        if "phase6_complete_date:" in text:
            text = re.sub(r'phase6_complete_date:\s*"[^"]*"', f'phase6_complete_date: "{today}"', text)
        else:
            text = text.rstrip() + f'\nphase6_complete_date: "{today}"\n'
    path.write_text(text, encoding="utf-8")
    load_study_config.cache_clear()


if __name__ == "__main__":
    raise SystemExit(main())
