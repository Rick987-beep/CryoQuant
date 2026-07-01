#!/usr/bin/env python3
"""Phase 7 — hold-out inference + chain backtest + RESULTS (one-shot)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.holdout_register import load_holdout_register
from src.paths import data_dir, load_study_config, reports_dir, splits_path
from src.phase7_holdout import run_phase7_holdout, write_phase7_artifacts
from src.phase7_inference import run_holdout_inference
from src.phase7_qa import (
    HoldoutAlreadyTouchedError,
    check_one_shot,
    format_report_text,
    run_phase7_qa,
    write_one_shot_guard,
    write_report,
)
from src.phase7_report import write_manifest, write_results_md

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 7 hold-out report")
    parser.add_argument("--force", action="store_true", help="Overwrite one-shot guard (principal only)")
    parser.add_argument("--smoke", action="store_true", help="3-model inference smoke + chain eval")
    parser.add_argument("--skip-inference", action="store_true", help="Reuse existing holdout_predictions.parquet")
    parser.add_argument("--qa-only", action="store_true", help="Re-run QA on existing artifacts")
    args = parser.parse_args()

    cfg = load_study_config()
    if not cfg.phase6_complete:
        log.error("phase6_complete must be true before Phase 7")
        return 2
    if not splits_path().is_file():
        log.error("Missing %s — run phase 0 first", splits_path())
        return 2

    ddir = data_dir()
    rdir = reports_dir()
    register = load_holdout_register()

    try:
        check_one_shot(ddir, force=args.force)
    except HoldoutAlreadyTouchedError as exc:
        log.error("%s", exc)
        return 2

    best_path = ddir / "phase6_best_config.json"
    if not best_path.is_file():
        log.error("Missing frozen signal: %s", best_path)
        return 2
    frozen_signal = json.loads(best_path.read_text(encoding="utf-8"))

    inference_meta: list[dict] = []
    holdout_preds = None

    if not args.qa_only:
        if not args.skip_inference:
            log.info("Phase 7A — hold-out inference")
            holdout_preds, inference_meta = run_holdout_inference(
                cfg, data_dir=ddir, smoke=args.smoke
            )
        else:
            import pandas as pd

            pred_path = ddir / "holdout_predictions.parquet"
            if not pred_path.is_file():
                log.error("--skip-inference but %s missing", pred_path)
                return 2
            holdout_preds = pd.read_parquet(pred_path)
            inference_meta = [{"status": "skipped", "note": "reused artifact"}]

        log.info("Phase 7B — chain backtest")
        report = run_phase7_holdout(
            cfg,
            data_dir=ddir,
            frozen_signal=frozen_signal,
            inference_meta=inference_meta,
            holdout_preds=holdout_preds,
        )
        write_phase7_artifacts(report, ddir, rdir)
        write_results_md(report, cfg, rdir / "RESULTS.md")
        write_manifest(cfg, ddir, rdir, report)
        write_one_shot_guard(
            ddir,
            {
                "session_id": report.session_id,
                "G2_primary_pass": report.gates.get("G2_primary", {}).get("pass"),
                "n_trades": report.preregistered_primary.get("n_trades"),
            },
        )
        log.info("Wrote RESULTS.md and manifest")

    qa = run_phase7_qa(cfg, ddir, rdir, register=register)
    qa_json = ddir / "phase7_qa_report.json"
    qa_txt = rdir / "phase7_qa_report.txt"
    write_report(qa, qa_json, qa_txt)
    print(format_report_text(qa))

    if qa.errors == 0 and not args.qa_only:
        _mark_phase7_complete()

    return 1 if qa.errors else 0


def _mark_phase7_complete() -> None:
    import re
    from datetime import date

    path = ROOT / "config.yaml"
    text = path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    if "phase7_complete:" not in text:
        text = text.rstrip() + f"\nphase7_complete: true\nphase7_complete_date: \"{today}\"\n"
    else:
        text = re.sub(r"phase7_complete:\s*\w+", "phase7_complete: true", text)
        if "phase7_complete_date:" in text:
            text = re.sub(r'phase7_complete_date:\s*"[^"]*"', f'phase7_complete_date: "{today}"', text)
        else:
            text = text.rstrip() + f'\nphase7_complete_date: "{today}"\n'
    path.write_text(text, encoding="utf-8")
    load_study_config.cache_clear()


if __name__ == "__main__":
    raise SystemExit(main())
